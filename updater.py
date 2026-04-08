# Auto-update via GitHub Releases (primario) ou pasta compartilhada (fallback).
# Verifica latest release no GitHub, compara com versao local,
# baixa o exe novo e aplica via batch script com restart.
import os
import sys
import shutil
import subprocess
import logging
import threading
import json
from urllib import request, error

from version import APP_VERSION

log = logging.getLogger('mbchat')


def _get_long_path(path):
    # Resolve caminho 8.3 (ex: PEDRO~1.PAI) para long path via Win32 API.
    # Retorna path original se falhar.
    if os.name != 'nt':
        return path
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(32768)
        result = ctypes.windll.kernel32.GetLongPathNameW(path, buf, len(buf))
        if result > 0:
            return buf.value
    except Exception:
        pass
    return path


# GitHub repo para checar releases
GITHUB_REPO = 'pedropaivaf/MBchat'
GITHUB_API_URL = f'https://api.github.com/repos/{GITHUB_REPO}/releases/latest'

# Caminho padrao do share de atualizacao (fallback)
DEFAULT_SHARE_PATH = r'\\192.168.0.9\Works2026\Publico\mbchat-update'

# Pasta local para arquivos temporarios de update
_UPDATE_DIR = _get_long_path(os.path.join(
    os.environ.get('APPDATA', os.path.expanduser('~')),
    'MBChat'))


def _parse_version(v):
    # "1.2.3" ou "v1.2.3" -> (1, 2, 3)
    try:
        v = v.strip().lstrip('v')
        return tuple(int(x) for x in v.split('.'))
    except Exception:
        return (0, 0, 0)


def check_update_github():
    # Checa GitHub Releases. Retorna (has_update, version_str, download_url).
    try:
        req = request.Request(GITHUB_API_URL, headers={
            'Accept': 'application/vnd.github.v3+json',
            'User-Agent': 'MBChat-Updater'
        })
        with request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        tag = data.get('tag_name', '')
        remote_ver = tag.lstrip('v')
        if _parse_version(remote_ver) > _parse_version(APP_VERSION):
            # Procura MBChat.exe nos assets
            download_url = ''
            for asset in data.get('assets', []):
                if asset['name'] == 'MBChat.exe':
                    download_url = asset['browser_download_url']
                    break
            return True, remote_ver, download_url
        return False, remote_ver, ''
    except Exception as e:
        log.warning(f'GitHub update check falhou: {e}')
        return False, '', ''


def check_update(share_path):
    # Retorna (has_update, remote_version_str) ou (False, '') se falhar.
    # Tenta GitHub primeiro, depois share como fallback.
    has_update, ver, url = check_update_github()
    if has_update:
        return True, ver
    if ver:
        return False, ver
    # Fallback: share de rede
    try:
        ver_file = os.path.join(share_path, 'version.txt')
        with open(ver_file, 'r', encoding='utf-8') as f:
            remote_ver = f.read().strip()
        if _parse_version(remote_ver) > _parse_version(APP_VERSION):
            return True, remote_ver
        return False, remote_ver
    except Exception as e:
        log.warning(f'Share update check falhou: {e}')
        return False, ''


def download_update(share_path, progress_cb=None):
    # Tenta baixar do GitHub primeiro, depois do share.
    # Retorna caminho do exe baixado ou None se falhar.
    os.makedirs(_UPDATE_DIR, exist_ok=True)
    dst = os.path.join(_UPDATE_DIR, 'MBChat_new.exe')

    # Tenta GitHub
    path = _download_from_github(dst, progress_cb)
    if path:
        return path

    # Fallback: share
    return _download_from_share(share_path, dst, progress_cb)


def _download_from_github(dst, progress_cb=None):
    try:
        has_update, ver, url = check_update_github()
        if not url:
            return None
        log.info(f'Baixando update v{ver} do GitHub...')
        req = request.Request(url, headers={'User-Agent': 'MBChat-Updater'})
        with request.urlopen(req, timeout=60) as resp:
            total = int(resp.headers.get('Content-Length', 0))
            copied = 0
            chunk = 256 * 1024
            with open(dst, 'wb') as fout:
                while True:
                    buf = resp.read(chunk)
                    if not buf:
                        break
                    fout.write(buf)
                    copied += len(buf)
                    if progress_cb and total:
                        progress_cb(copied, total)
        log.info(f'Update baixado do GitHub: {dst} ({copied} bytes)')
        return dst
    except Exception as e:
        log.warning(f'Download GitHub falhou: {e}')
        return None


def _download_from_share(share_path, dst, progress_cb=None):
    try:
        src = os.path.join(share_path, 'MBChat.exe')
        if not os.path.isfile(src):
            log.error(f'Exe nao encontrado no share: {src}')
            return None
        total = os.path.getsize(src)
        copied = 0
        chunk = 256 * 1024
        with open(src, 'rb') as fin, open(dst, 'wb') as fout:
            while True:
                buf = fin.read(chunk)
                if not buf:
                    break
                fout.write(buf)
                copied += len(buf)
                if progress_cb:
                    progress_cb(copied, total)
        log.info(f'Update baixado do share: {dst} ({total} bytes)')
        return dst
    except Exception as e:
        log.error(f'Download share falhou: {e}')
        return None


def apply_update(new_exe_path):
    # Escreve batch script que troca o exe e reinicia o app.
    # Chamador deve fechar o app logo depois (os._exit ou sys.exit).
    target = _get_long_path(sys.executable)
    new_exe_path = _get_long_path(new_exe_path)
    bat_path = os.path.join(_UPDATE_DIR, 'update.bat')
    log_path = os.path.join(_UPDATE_DIR, 'update.log')

    bat_content = f'''@echo off
set LOG="{log_path}"
echo [%date% %time%] Update iniciado >> %LOG%
echo Target: "{target}" >> %LOG%
echo Source: "{new_exe_path}" >> %LOG%

taskkill /f /im MBChat.exe >nul 2>&1
timeout /t 3 /noretry >nul

set RETRIES=10
:retry
echo [%date% %time%] Tentando move (retry %RETRIES%) >> %LOG%
move /Y "{new_exe_path}" "{target}"
if not errorlevel 1 goto done
echo [%date% %time%] Move falhou, aguardando... >> %LOG%
timeout /t 2 /noretry >nul
set /a RETRIES-=1
if %RETRIES% gtr 0 goto retry
echo [%date% %time%] ERRO: todas as tentativas falharam >> %LOG%
exit /b 1
:done
echo [%date% %time%] Move OK >> %LOG%
timeout /t 1 /noretry >nul
echo [%date% %time%] Iniciando app... >> %LOG%
echo [%date% %time%] TEMP antes: %TEMP% >> %LOG%
REM Resolve TEMP/TMP para caminho longo (evita 8.3 como PEDRO~1.PAI)
for /f "delims=" %%i in ('powershell -NoProfile -Command "(Get-Item $env:TEMP).FullName"') do set "TEMP=%%i"
set "TMP=%TEMP%"
echo [%date% %time%] TEMP depois: %TEMP% >> %LOG%
powershell -NoProfile -Command "$t=(Get-Item $env:TEMP).FullName; $env:TEMP=$t; $env:TMP=$t; Start-Process -FilePath '{target}'"
echo [%date% %time%] Start-Process executado >> %LOG%
del "%~f0"
'''
    with open(bat_path, 'w', encoding='ascii') as f:
        f.write(bat_content)

    # Lanca o bat como processo desacoplado (sobrevive ao app fechar)
    CREATE_NO_WINDOW = 0x08000000
    DETACHED_PROCESS = 0x00000008
    subprocess.Popen(
        ['cmd.exe', '/c', bat_path],
        creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW,
        close_fds=True)

    log.info('Update batch lancado, encerrando app...')


def check_update_async(share_path, callback):
    # Roda check_update em thread background.
    # callback(has_update, remote_version) sera chamado na thread (usar root.after para GUI).
    def _run():
        has_update, ver = check_update(share_path)
        callback(has_update, ver)
    t = threading.Thread(target=_run, daemon=True)
    t.start()
