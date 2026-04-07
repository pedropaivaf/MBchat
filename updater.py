# Auto-update via pasta compartilhada na rede (SMB/UNC).
# Verifica version.txt no share, compara com versao local,
# baixa o exe novo e aplica via batch script com restart.
import os
import sys
import shutil
import subprocess
import logging
import threading

from version import APP_VERSION

log = logging.getLogger('mbchat')

# Caminho padrao do share de atualizacao
DEFAULT_SHARE_PATH = r'\\192.168.0.9\Works2026\Publico\mbchat-update'

# Pasta local para arquivos temporarios de update
_UPDATE_DIR = os.path.join(
    os.environ.get('APPDATA', os.path.expanduser('~')),
    'MBChat')


def _parse_version(v):
    # "1.2.3" -> (1, 2, 3)
    try:
        return tuple(int(x) for x in v.strip().split('.'))
    except Exception:
        return (0, 0, 0)


def check_update(share_path):
    # Retorna (has_update, remote_version_str) ou (False, '') se falhar.
    # share_path: caminho UNC tipo \\servidor\apps\MBChat
    try:
        ver_file = os.path.join(share_path, 'version.txt')
        with open(ver_file, 'r', encoding='utf-8') as f:
            remote_ver = f.read().strip()
        if _parse_version(remote_ver) > _parse_version(APP_VERSION):
            return True, remote_ver
        return False, remote_ver
    except Exception as e:
        log.warning(f'Update check falhou: {e}')
        return False, ''


def download_update(share_path, progress_cb=None):
    # Copia MBChat.exe do share para local temp.
    # progress_cb(bytes_copiados, total) opcional.
    # Retorna caminho do exe baixado ou None se falhar.
    try:
        src = os.path.join(share_path, 'MBChat.exe')
        if not os.path.isfile(src):
            log.error(f'Exe nao encontrado no share: {src}')
            return None

        os.makedirs(_UPDATE_DIR, exist_ok=True)
        dst = os.path.join(_UPDATE_DIR, 'MBChat_new.exe')

        total = os.path.getsize(src)
        copied = 0
        chunk = 256 * 1024  # 256KB

        with open(src, 'rb') as fin, open(dst, 'wb') as fout:
            while True:
                buf = fin.read(chunk)
                if not buf:
                    break
                fout.write(buf)
                copied += len(buf)
                if progress_cb:
                    progress_cb(copied, total)

        log.info(f'Update baixado: {dst} ({total} bytes)')
        return dst
    except Exception as e:
        log.error(f'Download de update falhou: {e}')
        return None


def apply_update(new_exe_path):
    # Escreve batch script que troca o exe e reinicia o app.
    # Chamador deve fechar o app logo depois (os._exit ou sys.exit).
    target = sys.executable  # caminho do exe em execucao
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
powershell -Command "Start-Process -FilePath '{target}'"
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
