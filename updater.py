# Auto-update via GitHub Releases.
# Verifica latest release no GitHub, compara com versao local,
# baixa o zip com o app novo e aplica via PowerShell script com restart.
import os
import re
import sys
import shutil
import hashlib
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
        v = v.strip().lstrip('v').split('-')[0]
        return tuple(int(x) for x in v.split('.'))
    except Exception:
        return (0, 0, 0)


def _extract_sha256(body):
    if not body:
        return None
    m = re.search(r'SHA256:\s*([a-f0-9]{64})', body, re.IGNORECASE)
    return m.group(1).lower() if m else None


def _verify_sha256(zip_path, expected):
    if not expected:
        return True  # releases sem hash: aceita (backward compat)
    h = hashlib.sha256()
    with open(zip_path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest().lower() == expected.lower()


def check_update_github():
    # Retorna (has_update, version_str, download_url, notes, sha256).
    # Procura MBChat_update.zip nos assets. notes = primeiras linhas do body.
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
            body = data.get('body', '') or ''
            sha256 = _extract_sha256(body)
            lines = [l.strip().lstrip('#').lstrip('*').lstrip('-').strip()
                     for l in body.splitlines()
                     if l.strip() and not l.strip().startswith('http')
                     and not l.strip().upper().startswith('SHA256')]
            notes = '\n'.join(('• ' + l) for l in lines[:5])
            return True, remote_ver, download_url, notes, sha256
        return False, remote_ver, '', '', None
    except Exception as e:
        log.warning(f'GitHub update check falhou: {e}')
        return False, '', '', '', None


def check_update():
    has_update, ver, url, notes, _sha = check_update_github()
    return has_update, ver, notes


def download_update(arg1=None, progress_cb=None):
    if callable(arg1):
        progress_cb = arg1
    # Baixa o zip do update. Retorna pasta extraida ou None.
    os.makedirs(_UPDATE_DIR, exist_ok=True)
    zip_dst = os.path.join(_UPDATE_DIR, 'MBChat_update.zip')
    extract_dir = os.path.join(_UPDATE_DIR, 'update_staging')

    path, expected_sha256 = _download_from_github(zip_dst, progress_cb)
    if not path:
        return None

    # Verifica integridade antes de extrair
    if not _verify_sha256(path, expected_sha256):
        log.error('SHA256 do zip nao confere — update corrompido ou adulterado, abortando.')
        try:
            os.remove(path)
        except Exception:
            pass
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
        has_update, ver, url, _notes, sha256 = check_update_github()
        if not url:
            return None, None
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
        return dst, sha256
    except Exception as e:
        log.warning(f'Download GitHub falhou: {e}')
        return None, None


def apply_update(staging_dir, **kwargs):
    # staging_dir contem os arquivos extraidos do zip (MBChat.exe + _internal/).
    # Script PowerShell mata o processo, substitui a pasta inteira e relanca.
    # kwargs aceita show_ui para compat com chamadas antigas (ignorado).
    if not staging_dir or not os.path.isdir(staging_dir):
        log.error(f'apply_update: staging_dir invalido: {staging_dir!r}')
        return
    target_exe = _get_long_path(sys.executable)
    target_dir = _get_long_path(os.path.dirname(target_exe))
    staging_dir = _get_long_path(staging_dir)
    log_path = os.path.join(_UPDATE_DIR, 'update.log')

    ps_path = os.path.join(_UPDATE_DIR, 'update.ps1')

    ps_content = f'''
# Auto-elevacao: se nao tem admin, relanca como admin via UAC.
# Necessario porque C:\Program Files\MBChat precisa de permissao elevada
# para deletar/copiar arquivos. O installer roda como admin (Inno Setup),
# mas o updater roda como usuario normal.
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {{
    try {{
        Start-Process powershell.exe -Verb RunAs -WindowStyle Hidden -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
        exit 0
    }} catch {{
        # Se UAC for negado, tenta sem admin mesmo (funciona se app esta em pasta de usuario)
    }}
}}

$LogFile = "{log_path}"
function Log($msg) {{ "{{0:yyyy-MM-dd HH:mm:ss}}" -f (Get-Date) + " $msg" | Out-File -Append -FilePath $LogFile }}

Log "Update iniciado (admin=$isAdmin)"
Log "Target dir: {target_dir}"
Log "Staging dir: {staging_dir}"

# Mata o processo
Stop-Process -Name "MBChat" -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 5

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

# Sanity check: _internal deve existir com pelo menos 50 arquivos
$internalNew = Join-Path "{target_dir}" "_internal"
$fileCount = (Get-ChildItem -Path $internalNew -Recurse -File -ErrorAction SilentlyContinue | Measure-Object).Count
if ($fileCount -lt 50) {{
    Log "ERRO: _internal incompleto ($fileCount arquivos). Abortando lancamento."
    exit 1
}}
Log "Sanity OK: $fileCount arquivos em _internal"

# Limpa staging e arquivo de pending
Remove-Item -Path "{staging_dir}" -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -Path "{os.path.join(_UPDATE_DIR, 'MBChat_update.zip')}" -Force -ErrorAction SilentlyContinue
Remove-Item -Path "{os.path.join(_UPDATE_DIR, 'update_pending.txt')}" -Force -ErrorAction SilentlyContinue
Log "Cleanup OK"

# Remove executaveis antigos soltos para evitar conflito de atalhos e versoes
$userDesktop = [Environment]::GetFolderPath("Desktop")
$userAppData = [Environment]::GetFolderPath("LocalApplicationData")
$roamingAppData = [Environment]::GetFolderPath("ApplicationData")

$oldExes = @(
    Join-Path $userDesktop "MBChat.exe",
    Join-Path $userAppData "Programs\MBChat.exe",
    Join-Path $roamingAppData "MBChat\MBChat.exe",
    Join-Path $roamingAppData "MBChat_new.exe"
)

foreach ($oldExe in $oldExes) {{
    if ((Test-Path $oldExe) -and ($oldExe -ne "{target_exe}")) {{
        try {{
            Remove-Item -Path $oldExe -Force -ErrorAction Stop
            Log "Removido executavel antigo: ${{oldExe}}"
        }} catch {{
            Log "Nao foi possivel remover ${{oldExe}} - $_"
        }}
    }}
}}

# Lanca o app via CreateProcess (UseShellExecute=$false herda env vars do pai).
# CRITICO: NUNCA usar Start-Process / start "" / explorer.exe — usam ShellExecute
# que ignora env vars do pai e causa "Failed to load Python DLL" em maquinas
# com caminho 8.3 no %TEMP% (ex: PEDRO~1.PAI). Veja CLAUDE.md.
# Passa --show pro novo MBChat abrir a janela principal direto (em vez de iniciar
# em tray). Sem isso o usuario clica OK no dialog mas o app fica "escondido" na
# bandeja e ele pensa que nao reabriu.
Log "Lancando app via CreateProcess..."
$launched = $false
try {{
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = "{target_exe}"
    $psi.Arguments = "--show"
    $psi.WorkingDirectory = "{target_dir}"
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $false
    [System.Diagnostics.Process]::Start($psi) | Out-Null
    $launched = $true
    Log "App lancado via CreateProcess OK (--show)"
}} catch {{
    Log "ERRO no CreateProcess: $_"
}}

# Fallback: se CreateProcess falhou por algum motivo, tenta Start-Process
if (-not $launched) {{
    try {{
        Start-Process -FilePath "{target_exe}" -ArgumentList "--show" -ErrorAction Stop
        Log "App lancado via Start-Process (fallback, --show)"
    }} catch {{
        Log "ERRO no fallback Start-Process: $_"
    }}
}}

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
        has_update, ver, notes = check_update()
        callback(has_update, ver, notes)
    t = threading.Thread(target=_run, daemon=True)
    t.start()


def mark_update_ready(staging_dir):
    # Salva o caminho do update para ser aplicado no proximo boot
    pending_file = os.path.join(_UPDATE_DIR, 'update_pending.txt')
    try:
        with open(pending_file, 'w', encoding='utf-8') as f:
            f.write(staging_dir)
        log.info(f'Update marcado como pronto: {pending_file}')
        return True
    except Exception as e:
        log.error(f'Falha ao marcar update: {e}')
        return False

def is_update_pending():
    # Verifica se ha um update aguardando aplicacao
    pending_file = os.path.join(_UPDATE_DIR, 'update_pending.txt')
    if os.path.exists(pending_file):
        try:
            with open(pending_file, 'r', encoding='utf-8') as f:
                return f.read().strip()
        except Exception:
            return None
    return None

