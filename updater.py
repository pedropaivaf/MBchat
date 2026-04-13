# Auto-update via GitHub Releases.
# Verifica latest release no GitHub, compara com versao local,
# baixa o zip com o app novo e aplica via PowerShell script com restart.
import os
import sys
import shutil
import subprocess
import logging
import threading
import json
import zipfile
from urllib import request, error

from version import APP_VERSION

log = logging.getLogger('mbchat')


def _get_long_path(path):
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


GITHUB_REPO = 'pedropaivaf/MBchat'
GITHUB_API_URL = f'https://api.github.com/repos/{GITHUB_REPO}/releases/latest'

_UPDATE_DIR = _get_long_path(os.path.join(
    os.environ.get('APPDATA', os.path.expanduser('~')),
    'MBChat'))


def _parse_version(v):
    try:
        v = v.strip().lstrip('v')
        return tuple(int(x) for x in v.split('.'))
    except Exception:
        return (0, 0, 0)


def check_update_github():
    # Retorna (has_update, version_str, download_url).
    # Procura MBChat_update.zip nos assets.
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
            download_url = ''
            for asset in data.get('assets', []):
                if asset['name'] == 'MBChat_update.zip':
                    download_url = asset['browser_download_url']
                    break
            return True, remote_ver, download_url
        return False, remote_ver, ''
    except Exception as e:
        log.warning(f'GitHub update check falhou: {e}')
        return False, '', ''


def check_update():
    has_update, ver, url = check_update_github()
    return has_update, ver


def download_update(progress_cb=None):
    # Baixa o zip do update. Retorna pasta extraida ou None.
    os.makedirs(_UPDATE_DIR, exist_ok=True)
    zip_dst = os.path.join(_UPDATE_DIR, 'MBChat_update.zip')
    extract_dir = os.path.join(_UPDATE_DIR, 'update_staging')

    path = _download_from_github(zip_dst, progress_cb)
    if not path:
        return None

    # Extrai o zip
    try:
        if os.path.isdir(extract_dir):
            shutil.rmtree(extract_dir)
        os.makedirs(extract_dir, exist_ok=True)
        with zipfile.ZipFile(path, 'r') as zf:
            zf.extractall(extract_dir)
        log.info(f'Update extraido em: {extract_dir}')
        return extract_dir
    except Exception as e:
        log.error(f'Erro ao extrair update: {e}')
        return None


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


def apply_update(staging_dir):
    # staging_dir contem os arquivos extraidos do zip (MBChat.exe + _internal/).
    # Script PowerShell mata o processo, substitui a pasta inteira e relanca.
    target_exe = _get_long_path(sys.executable)
    target_dir = _get_long_path(os.path.dirname(target_exe))
    staging_dir = _get_long_path(staging_dir)
    long_temp = _get_long_path(os.environ.get('TEMP', os.environ.get('TMP', '')))
    log_path = os.path.join(_UPDATE_DIR, 'update.log')

    ps_path = os.path.join(_UPDATE_DIR, 'update.ps1')

    ps_content = f'''
$LogFile = "{log_path}"
function Log($msg) {{ "{{0:yyyy-MM-dd HH:mm:ss}}" -f (Get-Date) + " $msg" | Out-File -Append -FilePath $LogFile }}

Log "Update iniciado"
Log "Target dir: {target_dir}"
Log "Staging dir: {staging_dir}"

# Mata o processo
Stop-Process -Name "MBChat" -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 3

# Remove _internal/ antiga com retry
$ok = $false
for ($i = 0; $i -lt 10; $i++) {{
    try {{
        $internalDir = Join-Path "{target_dir}" "_internal"
        if (Test-Path $internalDir) {{
            Remove-Item -Path $internalDir -Recurse -Force -ErrorAction Stop
        }}
        $ok = $true
        Log "Remove _internal OK"
        break
    }} catch {{
        Log "Remove falhou (tentativa $i): $_"
        Start-Sleep -Seconds 2
    }}
}}

if (-not $ok) {{
    Log "ERRO: nao conseguiu remover _internal"
    exit 1
}}

# Copia novos arquivos
try {{
    Copy-Item -Path "{staging_dir}\\*" -Destination "{target_dir}" -Recurse -Force -ErrorAction Stop
    Log "Copy OK"
}} catch {{
    Log "ERRO ao copiar: $_"
    exit 1
}}

Start-Sleep -Seconds 1

# Limpa staging
Remove-Item -Path "{staging_dir}" -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -Path "{os.path.join(_UPDATE_DIR, 'MBChat_update.zip')}" -Force -ErrorAction SilentlyContinue
Log "Cleanup OK"

# Lanca o app via CreateProcess (herda env do pai)
Log "Lancando app..."
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = "{target_exe}"
$psi.UseShellExecute = $false
[System.Diagnostics.Process]::Start($psi) | Out-Null
Log "App lancado via CreateProcess"

# Remove este script
Start-Sleep -Seconds 2
Remove-Item -Path $MyInvocation.MyCommand.Path -Force -ErrorAction SilentlyContinue
'''
    with open(ps_path, 'w', encoding='utf-8') as f:
        f.write(ps_content)

    CREATE_NO_WINDOW = 0x08000000
    subprocess.Popen(
        ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ps_path],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=CREATE_NO_WINDOW)

    log.info('Update script lancado, encerrando app...')


def check_update_async(callback):
    def _run():
        has_update, ver = check_update()
        callback(has_update, ver)
    t = threading.Thread(target=_run, daemon=True)
    t.start()
