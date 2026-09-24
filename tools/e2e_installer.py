# e2e_installer.py
# Teste ponta a ponta do INSTALADOR e do AUTO-UPDATE em Windows de verdade,
# usando os binarios REAIS: o MBChat_Setup.exe / MBChat_WebInstaller.exe
# oficiais de uma release publicada (ex. v1.8.38, o que esta nas maquinas) e
# um build novo do codigo atual. Roda no GitHub Actions
# (.github/workflows/installer-e2e.yml) em windows-2022 (familia do Windows 10,
# build 20348) e windows-2025 (familia do Windows 11, build 26100).
#
# O que o auto-update executa e o codigo CONGELADO dentro do MBChat.exe
# instalado -- por isso o teste instala a release oficial e deixa o proprio
# exe dela baixar, conferir o SHA256, extrair e aplicar o update. Nada do
# caminho do update e chamado "por fora".
#
# NAO RODAR NO PC DE TRABALHO: instala em Program Files, mexe no arquivo hosts,
# mata qualquer MBChat.exe e grava mensagens de teste no banco do usuario.
# Exige MBCHAT_E2E=1 (so o workflow define).
#
# Subcomandos:
#   install-release TAG            baixa o setup oficial da release e instala silencioso
#   seed VER                       1a abertura do app (cria o banco) + 300 mensagens de teste
#   install-setup SETUP VER        instala um setup local (build de teste) silencioso
#   update-flow ZIP VER [--8dot3] [--limited] [--api-calls N] [--expect-unelevated] [--via-startup]
#                                  api.github.com falso servindo ZIP como versao VER;
#                                  o app instalado baixa sozinho e aplica no "boot".
#                                  --limited: app aberto SEM privilegio de admin (como
#                                  no escritorio): o script do update pede o UAC.
#   make-user                      cria um 2o usuario ADMIN local (com UAC ele recebe o
#                                  token filtrado, como num PC do escritorio); os
#                                  comandos com --limited abrem o app como esse usuario
#   update-blocked ZIP VER [--expect-reopen]
#                                  o update NAO consegue trocar os arquivos (mesmo efeito
#                                  de clicar "Nao" no UAC): nada pode quebrar, e o app
#                                  tem que voltar a abrir e atualizar depois
#   setup-over SETUP VER           instalador novo por cima, com o app ABERTO
#   webinstaller EXE [--8dot3]     instalador web baixa o setup da ultima release e o abre
#   wizard EXE VER [--fresh]       roda o instalador web (ou o setup) e CLICA o assistente ate
#                                  "Concluir" com "Abrir MB Chat" marcado; confere que o app
#                                  abriu de verdade (sem "Failed to load Python DLL")

import os
import re
import sys
import ssl
import json
import time
import shutil
import sqlite3
import hashlib
import datetime
import tempfile
import threading
import subprocess
import urllib.request
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

try:
    sys.stdout.reconfigure(errors='backslashreplace', line_buffering=True)
except Exception:
    pass

REPO = 'pedropaivaf/MBchat'
APP_DIR = os.path.join(os.environ.get('ProgramFiles', r'C:\Program Files'), 'MBChat')
APP_EXE = os.path.join(APP_DIR, 'MBChat.exe')
APPDATA = os.environ.get('APPDATA', '')
DATA_DIR = os.path.join(APPDATA, '.mbchat')
DB_PATH = os.path.join(DATA_DIR, 'mbchat.db')
UPD_DIR = os.path.join(APPDATA, 'MBChat')


def use_appdata(path):
    # Pastas de dados do usuario que roda o app (o de teste, com --limited)
    global APPDATA, DATA_DIR, DB_PATH, UPD_DIR
    APPDATA = path
    DATA_DIR = os.path.join(APPDATA, '.mbchat')
    DB_PATH = os.path.join(DATA_DIR, 'mbchat.db')
    UPD_DIR = os.path.join(APPDATA, 'MBChat')
WORK = os.environ.get('RUNNER_TEMP') or tempfile.gettempdir()
STATE_FILE = os.path.join(WORK, 'e2e_state.json')
HOSTS = os.path.join(os.environ.get('SystemRoot', r'C:\Windows'),
                     'System32', 'drivers', 'etc', 'hosts')
UNINSTALL_KEY = r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{MB-CHAT-APP}_is1'
PEER_UID = 'e2e_peer_uid'

PASS, FAIL, SKIP = [], [], []


def ok(msg):
    PASS.append(msg)
    print(f'  PASS  {msg}')


def fail(msg, detail=''):
    FAIL.append(msg)
    print(f'  FAIL  {msg}' + (f': {detail}' if detail else ''))


def check(cond, msg, detail=''):
    ok(msg) if cond else fail(msg, detail)
    return bool(cond)


def info(msg):
    print(f'  ....  {msg}')


def skip(msg):
    SKIP.append(msg)
    print(f'  SKIP  {msg}')


def read_text(path):
    # update.log e gravado pelo Out-File do Windows PowerShell 5.1, que usa
    # UTF-16 LE por padrao; o log do app e UTF-8.
    try:
        with open(path, 'rb') as f:
            raw = f.read()
    except Exception:
        return ''
    if raw.startswith(b'\xff\xfe') or raw.startswith(b'\xfe\xff'):
        return raw.decode('utf-16', errors='replace')
    if raw[1:2] == b'\x00':
        return raw.decode('utf-16-le', errors='replace')
    return raw.decode('utf-8', errors='replace')


def wait_for(pred, timeout, step=1.0):
    end = time.time() + timeout
    while time.time() < end:
        try:
            if pred():
                return True
        except Exception:
            pass
        time.sleep(step)
    try:
        return bool(pred())
    except Exception:
        return False


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def download(url, dst):
    req = urllib.request.Request(url, headers={'User-Agent': 'MBChat-E2E'})
    with urllib.request.urlopen(req, timeout=120) as r, open(dst, 'wb') as f:
        shutil.copyfileobj(r, f)
    return dst


def load_state():
    try:
        with open(STATE_FILE, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(**kw):
    st = load_state()
    st.update(kw)
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(st, f, indent=1)


# ───────────────────────── Windows helpers ─────────────────────────

def file_version(path):
    # "1.8.38" (3 primeiras partes do FileVersion do recurso VERSIONINFO)
    import win32api
    try:
        vi = win32api.GetFileVersionInfo(path, '\\')
    except Exception:
        return ''
    ms, ls = vi['FileVersionMS'], vi['FileVersionLS']
    return f'{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}'


def short_path(path):
    import win32api
    try:
        return win32api.GetShortPathName(path)
    except Exception:
        return path


def ps(cmd, timeout=60):
    r = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive',
                        '-ExecutionPolicy', 'Bypass', '-Command', cmd],
                       capture_output=True, text=True, timeout=timeout)
    return r.stdout.strip()


def processes(name):
    # [(pid, commandline)] dos processos com esse nome de imagem
    out = ps(f"Get-CimInstance Win32_Process -Filter \"Name='{name}'\" | "
             "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress")
    if not out:
        return []
    data = json.loads(out)
    if isinstance(data, dict):
        data = [data]
    return [(d.get('ProcessId'), d.get('CommandLine') or '') for d in data]


def app_processes():
    return processes('MBChat.exe')


def kill_app():
    subprocess.run(['taskkill', '/f', '/im', 'MBChat.exe'],
                   capture_output=True)
    wait_for(lambda: not app_processes(), 30)


LIMITED = False


def launch_app(args=('--silent',), env=None):
    # Como o atalho de inicializacao do Windows abre o app: exe --silent.
    if LIMITED:
        # Abre como o usuario de teste (admin local, UAC ligado): o Windows da
        # a ele o token FILTRADO, sem admin -- igual a um duplo clique num PC
        # do escritorio. Assim o script do update precisa pedir o UAC de verdade.
        u = load_state()['as_user']
        _logon_run(u['user'], u['password'], f'"{APP_EXE}" ' + ' '.join(args), APP_DIR)
        return None
    DETACHED = 0x00000008
    NEW_GROUP = 0x00000200
    return subprocess.Popen([APP_EXE, *args], cwd=APP_DIR, env=env,
                            creationflags=DETACHED | NEW_GROUP,
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, close_fds=True)


def _logon_run(user, password, cmdline, cwd=None, wait=False):
    # CreateProcessWithLogonW com o perfil do usuario (ambiente e %APPDATA%
    # dele). O Windows libera a area de trabalho atual para o processo.
    import ctypes
    from ctypes import wintypes

    class STARTUPINFOW(ctypes.Structure):
        _fields_ = [('cb', wintypes.DWORD), ('lpReserved', wintypes.LPWSTR),
                    ('lpDesktop', wintypes.LPWSTR), ('lpTitle', wintypes.LPWSTR),
                    ('dwX', wintypes.DWORD), ('dwY', wintypes.DWORD),
                    ('dwXSize', wintypes.DWORD), ('dwYSize', wintypes.DWORD),
                    ('dwXCountChars', wintypes.DWORD), ('dwYCountChars', wintypes.DWORD),
                    ('dwFillAttribute', wintypes.DWORD), ('dwFlags', wintypes.DWORD),
                    ('wShowWindow', wintypes.WORD), ('cbReserved2', wintypes.WORD),
                    ('lpReserved2', ctypes.c_void_p), ('hStdInput', wintypes.HANDLE),
                    ('hStdOutput', wintypes.HANDLE), ('hStdError', wintypes.HANDLE)]

    class PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [('hProcess', wintypes.HANDLE), ('hThread', wintypes.HANDLE),
                    ('dwProcessId', wintypes.DWORD), ('dwThreadId', wintypes.DWORD)]

    advapi32 = ctypes.WinDLL('advapi32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    si = STARTUPINFOW()
    si.cb = ctypes.sizeof(si)
    pi = PROCESS_INFORMATION()
    buf = ctypes.create_unicode_buffer(cmdline)
    LOGON_WITH_PROFILE = 1
    okc = advapi32.CreateProcessWithLogonW(user, '.', password, LOGON_WITH_PROFILE, None, buf,
                                           0, None, cwd, ctypes.byref(si), ctypes.byref(pi))
    if not okc:
        raise ctypes.WinError(ctypes.get_last_error())
    if wait:
        kernel32.WaitForSingleObject(pi.hProcess, 60000)
    kernel32.CloseHandle(pi.hThread)
    kernel32.CloseHandle(pi.hProcess)
    return pi.dwProcessId


def cmd_make_user():
    import secrets
    print('\n[make-user] usuario admin local de teste (UAC -> token filtrado)')
    user = 'mbteste'
    # ate 14 caracteres: acima disso o "net user" para e pergunta S/N
    pwd = 'Mb#' + secrets.token_hex(4) + 'x9'
    r = subprocess.run(['net', 'user', user, pwd, '/add'], capture_output=True, text=True,
                       stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        r = subprocess.run(['net', 'user', user, pwd], capture_output=True, text=True,
                           stdin=subprocess.DEVNULL)
    check(r.returncode == 0, 'usuario de teste criado', (r.stdout + r.stderr).strip())
    r = subprocess.run(['net', 'localgroup', 'Administrators', user, '/add'],
                       capture_output=True, text=True)
    info(f'grupo Administrators: rc={r.returncode} {(r.stdout + r.stderr).strip()[:80]}')
    out = r'C:\Users\Public\e2e_appdata.txt'
    if os.path.exists(out):
        os.remove(out)
    _logon_run(user, pwd, f'cmd.exe /c echo %APPDATA%> "{out}"', r'C:\Users\Public', wait=True)
    appdata = read_text(out).strip() if os.path.isfile(out) else ''
    check(appdata and os.path.isdir(appdata), f'perfil do usuario de teste criado ({appdata})')
    save_state(as_user={'user': user, 'password': pwd, 'appdata': appdata})


def process_elevated(pid):
    # True se o processo roda como administrador (token elevado)
    import win32api
    import win32security
    try:
        h = win32api.OpenProcess(0x1000, False, int(pid))  # QUERY_LIMITED_INFORMATION
        tok = win32security.OpenProcessToken(h, 0x0008)    # TOKEN_QUERY
        return bool(win32security.GetTokenInformation(tok, win32security.TokenElevation))
    except Exception as e:
        return f'? ({e})'


def firewall_rule(name):
    r = subprocess.run(['netsh', 'advfirewall', 'firewall', 'show', 'rule',
                        f'name={name}'], capture_output=True, text=True)
    return r.returncode == 0


def uninstall_display_version():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, UNINSTALL_KEY, 0,
                            winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
            return winreg.QueryValueEx(k, 'DisplayVersion')[0]
    except Exception:
        return ''


def make_8dot3_temp():
    # Pasta de TEMP com nome longo que ganha nome curto 8.3, como nas contas
    # "nome.sobrenome" do escritorio (C:\Users\PEDRO~1.PAI\...). Devolve o
    # caminho CURTO (e assim que o Windows entrega o %TEMP% nessas contas).
    subprocess.run(['fsutil', '8dot3name', 'set', '0'], capture_output=True)
    subprocess.run(['fsutil', '8dot3name', 'set', 'C:', '0'], capture_output=True)
    for n in range(20):
        longp = os.path.join('C:\\', 'e2e83', f'pedro.paiva{n}', 'AppData', 'Local', 'Temp')
        os.makedirs(longp, exist_ok=True)
        sp = short_path(longp)
        if sp.lower() != longp.lower() and '~' in sp:
            return sp
    return None


def dump_logs(extra=()):
    files = [os.path.join(UPD_DIR, 'update.log'),
             os.path.join(UPD_DIR, 'mbchat.log'),
             os.path.join(DATA_DIR, 'network.log'), *extra]
    for p in files:
        if not p or not os.path.isfile(p):
            continue
        lines = read_text(p).splitlines()
        print(f'\n----- {p} (ultimas 60 linhas) -----')
        for ln in lines[-60:]:
            print('  | ' + ln)


# ───────────────────────── banco ─────────────────────────

def db_get(sql, args=()):
    con = sqlite3.connect(DB_PATH, timeout=15)
    try:
        return con.execute(sql, args).fetchall()
    finally:
        con.close()


def db_exec(sql, args=()):
    con = sqlite3.connect(DB_PATH, timeout=15)
    try:
        con.execute(sql, args)
        con.commit()
    finally:
        con.close()


def setting(key):
    try:
        r = db_get('SELECT value FROM settings WHERE key=?', (key,))
        return r[0][0] if r else None
    except Exception:
        return None


def db_fingerprint():
    rows = db_get("SELECT msg_id, from_user, to_user, content, timestamp, is_sent "
                  "FROM messages WHERE msg_id LIKE 'e2e-%' ORDER BY msg_id")
    return len(rows), hashlib.sha256(repr(rows).encode('utf-8')).hexdigest()


def check_data_preserved(label):
    st = load_state()
    if not st.get('fingerprint'):
        fail(f'{label}: estado do seed ausente')
        return
    try:
        n, h = db_fingerprint()
    except Exception as e:
        fail(f'{label}: banco legivel', str(e))
        return
    check(n == st['fingerprint'][0] and h == st['fingerprint'][1],
          f'{label}: as {st["fingerprint"][0]} mensagens de teste intactas (byte a byte)',
          f'{n} msgs, hash {h[:12]} vs {st["fingerprint"][1][:12]}')
    check(setting('e2e_marker') == st.get('marker'),
          f'{label}: configuracoes do usuario preservadas')
    mk = os.path.join(DATA_DIR, 'e2e_marker.txt')
    check(os.path.isfile(mk) and read_text(mk) == st.get('marker'),
          f'{label}: arquivos da pasta de dados (.mbchat) preservados')


# ───────────────────────── subcomandos ─────────────────────────

def cmd_install_release(tag):
    ver = tag.lstrip('v')
    print(f'\n[install-release] instala a release oficial {tag} (silencioso, como o deploy)')
    setup = os.path.join(WORK, f'MBChat_Setup_{ver}.exe')
    download(f'https://github.com/{REPO}/releases/download/{tag}/MBChat_Setup.exe', setup)
    info(f'baixado {os.path.getsize(setup)} bytes, sha256 {sha256_file(setup)[:16]}')
    _install(setup, ver)


def cmd_install_setup(setup, ver):
    print(f'\n[install-setup] instala o build de teste {ver} (silencioso)')
    _install(os.path.abspath(setup), ver)


def _install(setup, ver):
    tag = f'v{ver}'
    log = os.path.join(WORK, f'setup_{ver}.log')
    r = subprocess.run([setup, '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART',
                        '/TASKS=desktopicon,autostart', f'/LOG={log}'], timeout=900)
    check(r.returncode == 0, f'setup {tag} terminou com codigo 0', str(r.returncode))
    check(file_version(APP_EXE) == ver, f'MBChat.exe instalado e {ver}', file_version(APP_EXE))
    check(os.path.isfile(os.path.join(APP_DIR, '_internal', 'python314.dll')),
          '_internal com python314.dll')
    check(uninstall_display_version() == ver, 'registro de desinstalacao com a versao certa',
          uninstall_display_version())
    for rule in ('MBChat TCP In', 'MBChat TCP In Dynamic', 'MBChat UDP In'):
        check(firewall_rule(rule), f'regra de firewall "{rule}" criada')
    save_state(installed_tag=tag)


def cmd_seed(ver):
    print(f'\n[seed] 1a abertura do app {ver} + historico de teste')
    kill_app()
    launch_app()
    up = wait_for(lambda: setting('last_version') == ver, 120)
    check(up, f'app {ver} abriu e iniciou o banco (last_version={setting("last_version")})')
    time.sleep(8)  # deixa o _deferred_init terminar (checagem de update, firewall...)
    check(len(app_processes()) == 1, 'app segue aberto depois do boot',
          str(app_processes()))
    kill_app()
    if not up:
        dump_logs()
        return
    import uuid
    marker = uuid.uuid4().hex
    con = sqlite3.connect(DB_PATH, timeout=15)
    me = con.execute('SELECT user_id FROM local_user WHERE id=1').fetchone()[0]
    now = time.time()
    con.execute('INSERT OR REPLACE INTO contacts (user_id, display_name, ip_address, '
                'hostname, status, last_seen, first_seen) VALUES (?,?,?,?,?,?,?)',
                (PEER_UID, 'Colega Teste E2E', '192.168.0.250', 'E2E-PC', 'offline',
                 now, now - 86400 * 30))
    samples = ['Bom dia! Tudo certo com a DCTF?', 'ATENÇÃO: prazo é sexta 🤌',
               'linha 1\nlinha 2\nlinha 3', 'desconto de 50% no arquivo_final.xlsx',
               'aspas "duplas" e \'simples\'', 'emoji 😀👍❤️ e acento ção ã é',
               'x' * 1500]
    for i in range(300):
        sent = i % 2 == 0
        con.execute('INSERT INTO messages (msg_id, from_user, to_user, content, msg_type, '
                    'timestamp, is_sent, is_read, is_delivered) VALUES (?,?,?,?,?,?,?,?,?)',
                    (f'e2e-{i:04d}', me if sent else PEER_UID, PEER_UID if sent else me,
                     f'{samples[i % len(samples)]} #{i}', 'text',
                     now - 86400 * 30 + i * 600, 1 if sent else 0, 1, 1))
    for i in range(20):
        con.execute('INSERT INTO messages (msg_id, from_user, to_user, content, msg_type, '
                    'timestamp, is_sent, is_read, is_delivered) VALUES (?,?,?,?,?,?,?,?,?)',
                    (f'e2e-g{i:03d}', 'outro_uid' if i % 2 else me, 'group:e2e_grupo',
                     f'mensagem de grupo {i}', 'text', now - 3600 + i, 0 if i % 2 else 1, 1, 1))
    con.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)',
                ('e2e_marker', marker))
    con.commit()
    con.close()
    with open(os.path.join(DATA_DIR, 'e2e_marker.txt'), 'w', encoding='utf-8') as f:
        f.write(marker)
    # O boot seguinte roda cleanup_unknown_contacts: reabre e fecha uma vez
    # para o fingerprint ja refletir o banco "assentado".
    launch_app()
    wait_for(lambda: len(app_processes()) == 1, 30)
    time.sleep(12)
    kill_app()
    n, h = db_fingerprint()
    check(n == 320, 'historico de teste gravado (300 individuais + 20 de grupo)', str(n))
    save_state(fingerprint=[n, h], marker=marker, me=me)


class _MockGitHub(BaseHTTPRequestHandler):
    zip_path = ''
    version = ''
    sha = ''
    hits = []
    # depois de servir o zip, passa a anunciar uma versao velha: o app ja
    # atualizado nao baixa de novo (usado quando o conteudo do zip e de uma
    # versao menor que a anunciada, ex. o zip REAL da release)
    stop_after_zip = False
    served_zip = False

    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        _MockGitHub.hits.append(self.path)
        if self.path.startswith(f'/repos/{REPO}/releases/latest'):
            base = 'https://api.github.com/e2e-assets'
            ver = '0.0.1' if (_MockGitHub.stop_after_zip and _MockGitHub.served_zip) else self.version
            body = json.dumps({
                'tag_name': f'v{ver}',
                'name': f'MB Chat v{ver}',
                'body': ('Teste ponta a ponta do auto-update\n'
                         'Segunda linha das notas\n\n'
                         f'SHA256: {self.sha}'),
                'assets': [
                    {'name': 'MBChat_Setup.exe', 'browser_download_url': f'{base}/MBChat_Setup.exe'},
                    {'name': 'MBChat_update.zip', 'browser_download_url': f'{base}/MBChat_update.zip'},
                ],
            }).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == '/e2e-assets/MBChat_update.zip':
            size = os.path.getsize(self.zip_path)
            self.send_response(200)
            self.send_header('Content-Type', 'application/octet-stream')
            self.send_header('Content-Length', str(size))
            self.end_headers()
            with open(self.zip_path, 'rb') as f:
                shutil.copyfileobj(f, self.wfile, 1 << 20)
            _MockGitHub.served_zip = True
            return
        self.send_response(404)
        self.end_headers()


def _start_mock_github(zip_path, version):
    # api.github.com -> 127.0.0.1 com certificado autoassinado. O updater
    # congelado tenta com verificacao, falha e cai no fallback sem
    # verificacao (_urlopen_with_fallback) -- o mesmo caminho que socorre
    # redes corporativas com inspecao de SSL.
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'api.github.com')])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=7))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName('api.github.com')]), False)
            .sign(key, hashes.SHA256()))
    cert_pem = os.path.join(WORK, 'mock_cert.pem')
    key_pem = os.path.join(WORK, 'mock_key.pem')
    with open(cert_pem, 'wb') as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    with open(key_pem, 'wb') as f:
        f.write(key.private_bytes(serialization.Encoding.PEM,
                                  serialization.PrivateFormat.TraditionalOpenSSL,
                                  serialization.NoEncryption()))
    _MockGitHub.zip_path = zip_path
    _MockGitHub.version = version
    _MockGitHub.served_zip = False
    _MockGitHub.sha = sha256_file(zip_path)
    srv = ThreadingHTTPServer(('127.0.0.1', 443), _MockGitHub)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert_pem, key_pem)
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    with open(HOSTS, 'a', encoding='ascii') as f:
        f.write('\n127.0.0.1 api.github.com  # mbchat-e2e\n')
    subprocess.run(['ipconfig', '/flushdns'], capture_output=True)
    return srv


def startup_lnk():
    # Atalho "Iniciar com o Windows" criado pelo instalador ({userstartup}) --
    # do usuario que INSTALOU (o do runner), nao o de teste.
    return os.path.join(os.environ.get('APPDATA', ''), 'Microsoft', 'Windows', 'Start Menu',
                        'Programs', 'Startup', 'MB Chat.lnk')


def launch_boot():
    # Como o Windows abre o app no logon: pelo atalho de Inicializacao
    # (ShellExecute, igual ao Explorer), sem clique de ninguem.
    lnk = startup_lnk()
    if LIMITED:
        pub = r'C:\Users\Public\MBChat_boot.lnk'
        shutil.copy(lnk, pub)
        u = load_state()['as_user']
        _logon_run(u['user'], u['password'], f'cmd.exe /c start "" "{pub}"', r'C:\Users\Public')
    else:
        os.startfile(lnk)


def check_startup_shortcut():
    lnk = startup_lnk()
    if not check(os.path.isfile(lnk), 'atalho "Iniciar com o Windows" existe', lnk):
        return False
    out = ps("$s=(New-Object -ComObject WScript.Shell).CreateShortcut('" + lnk.replace("'", "''")
             + "'); $s.TargetPath + '|' + $s.Arguments")
    target, _, argl = out.partition('|')
    check(target.lower() == APP_EXE.lower() and argl.strip() == '--silent',
          'atalho abre o MBChat.exe instalado com --silent (inicia na bandeja)', out)
    return True


def process_owner(pid):
    return ps(f"(Get-CimInstance Win32_Process -Filter 'ProcessId={int(pid)}' | "
              "Invoke-CimMethod -MethodName GetOwner).User")


def cmd_update_flow(zip_path, ver, use_8dot3=False, api_calls=None, expect_unelevated=False,
                    via_startup=False, content_ver=None):
    # ver = versao anunciada pelo GitHub falso; content_ver = versao que o zip
    # realmente contem (difere so no teste com o zip REAL da release)
    announced = ver
    ver = content_ver or ver
    _MockGitHub.stop_after_zip = bool(content_ver)
    st = load_state()
    old = (st.get('installed_tag') or '').lstrip('v')
    print(f'\n[update-flow] app {old} instalado recebe a {ver} pelo proprio auto-update'
          + (' (TEMP em caminho 8.3)' if use_8dot3 else '')
          + (' (app SEM admin: script pede UAC)' if LIMITED else ''))
    check(file_version(APP_EXE) == old, f'ponto de partida: {old} instalado', file_version(APP_EXE))
    zip_path = os.path.abspath(zip_path)
    env = dict(os.environ)
    if use_8dot3:
        sp = make_8dot3_temp()
        if sp:
            info(f'TEMP/TMP do app = {sp}')
            env['TEMP'] = env['TMP'] = sp
        else:
            skip('runner sem nomes 8.3: cenario TEMP 8.3 NAO testado nesta rodada')
    srv = _start_mock_github(zip_path, announced)
    try:
        # ── 1. download silencioso (o que acontece com o app aberto) ──
        print('\n  -- 1. download silencioso em segundo plano --')
        kill_app()
        if via_startup:
            print('  (app aberto pelo atalho de Inicializacao do Windows, sem nenhum clique)')
            if not check_startup_shortcut():
                return
            launch_boot()
        else:
            launch_app(env=env)
        pend = os.path.join(UPD_DIR, 'update_pending.txt')
        got = wait_for(lambda: os.path.isfile(pend), 300, 2)
        check(got, 'app baixou e marcou o update sozinho (update_pending.txt)')
        api_hits = [h for h in _MockGitHub.hits if 'releases/latest' in h]
        zip_hits = [h for h in _MockGitHub.hits if h.endswith('.zip')]
        check(api_hits and len(zip_hits) == 1,
              'consultou a API (via fallback SSL) e baixou o zip 1 vez', repr(_MockGitHub.hits))
        info(f'chamadas a API do GitHub ate o download: {len(api_hits)}')
        if api_calls is not None:
            check(len(api_hits) == api_calls,
                  f'gastou {api_calls} chamada(s) da API (limite de 60/h do IP do escritorio)',
                  str(len(api_hits)))
        procs = app_processes()
        if LIMITED and procs:
            check(process_elevated(procs[0][0]) is False,
                  'app aberto SEM admin (token filtrado, como no escritorio)',
                  str(process_elevated(procs[0][0])))
        staging = os.path.join(UPD_DIR, 'update_staging')
        if got:
            check(read_text(pend).strip().lower() == staging.lower(),
                  'marcador aponta para a pasta de staging')
        check(file_version(os.path.join(staging, 'MBChat.exe')) == ver,
              f'staging tem o MBChat.exe {ver} (SHA256 conferido pelo app antes de extrair)')
        check(len(app_processes()) == 1, 'app segue aberto e funcionando depois do download')
        if not got:
            dump_logs()
            return

        # ── 2. "reinicia o PC": o app abre pelo atalho de inicializacao ──
        print('\n  -- 2. proxima abertura aplica o update (boot do Windows) --')
        kill_app()
        # apaga o last_version: so o app novo, rodando Python de verdade (sem
        # "Failed to load Python DLL"), grava de novo
        db_exec("DELETE FROM settings WHERE key='last_version'")
        ulog = os.path.join(UPD_DIR, 'update.log')
        if os.path.isfile(ulog):
            os.remove(ulog)
        t0 = time.time()
        if via_startup:
            launch_boot()
        else:
            launch_app(env=env)
        launched = wait_for(lambda: 'App lancado' in read_text(ulog), 240, 2)
        check(launched, 'script de update terminou e relancou o app')
        new_up = wait_for(lambda: file_version(APP_EXE) == ver and setting('last_version') == ver
                          and len(app_processes()) == 1, 180, 2)
        check(new_up, f'versao {ver} instalada E abriu de verdade (gravou last_version no banco)',
              f'exe={file_version(APP_EXE)} last_version={setting("last_version")} '
              f'procs={app_processes()}')
        info(f'update aplicado em {time.time() - t0:.0f}s')
        check('Aplicando update pendente no boot' in read_text(os.path.join(UPD_DIR, 'mbchat.log')),
              'instalado sozinho na abertura do app (sem clicar em "Reiniciar para Atualizar")')
        ulog_txt = read_text(ulog)
        for step in ('Backup _internal OK', 'Copy OK', 'Sanity _internal OK',
                     'Sanity exe OK', 'Cleanup OK', 'App lancado via CreateProcess OK (--show)'):
            check(step in ulog_txt, f'update.log: "{step}"')
        check('ROLLBACK' not in ulog_txt and 'ERRO' not in ulog_txt,
              'update.log sem ERRO/ROLLBACK')
        m = re.search(r'admin=(\w+)', ulog_txt)
        info(f'script rodou com admin={m.group(1) if m else "?"}')
        procs = app_processes()
        check(len(procs) == 1 and '--show' in procs[0][1],
              'um unico MBChat aberto, relancado com --show', repr(procs))
        if procs:
            elev = process_elevated(procs[0][0])
            owner = process_owner(procs[0][0])
            info(f'app relancado roda como admin: {elev} (usuario {owner})')
            if expect_unelevated:
                u = load_state().get('as_user', {}).get('user', '')
                check(elev is False and owner.lower() == u.lower(),
                      f'app reaberto SEM admin e como o usuario original ({u})',
                      f'admin={elev} usuario={owner}')
        if LIMITED:
            check('admin=True' in ulog_txt, 'script pediu o UAC e rodou elevado (admin=True)')
        time.sleep(20)
        check(len(app_processes()) == 1, 'app novo continua aberto 20s depois (sem crash de DLL)')
        check(os.path.isfile(os.path.join(APP_DIR, '_internal', 'python314.dll')),
              '_internal novo com python314.dll')
        check(not os.path.exists(os.path.join(APP_DIR, '_internal.bak'))
              and not os.path.exists(APP_EXE + '.bak'), 'backups (.bak) descartados')
        for leftover in ('update_pending.txt', 'update_attempts.txt', 'update_staging',
                         'MBChat_update.zip'):
            check(not os.path.exists(os.path.join(UPD_DIR, leftover)), f'{leftover} limpo')
        check(wait_for(lambda: not os.path.exists(os.path.join(UPD_DIR, 'update.ps1')), 20),
              'update.ps1 se autoremoveu')
        check_data_preserved('apos auto-update')
        info(f'registro de desinstalacao continua com DisplayVersion='
             f'{uninstall_display_version()} (o auto-update nao passa pelo Inno)')
        if FAIL:
            dump_logs()
    finally:
        srv.shutdown()
        _unhosts()


def _unhosts():
    try:
        with open(HOSTS, encoding='ascii', errors='replace') as f:
            lines = [l for l in f.read().splitlines() if 'mbchat-e2e' not in l]
        with open(HOSTS, 'w', encoding='ascii') as f:
            f.write('\n'.join(lines) + '\n')
        subprocess.run(['ipconfig', '/flushdns'], capture_output=True)
    except Exception:
        pass


def cmd_update_blocked(zip_path, ver, expect_reopen=False):
    st = load_state()
    old = (st.get('installed_tag') or '').lstrip('v')
    print(f'\n[update-blocked] update {old} -> {ver} com a pasta do app TRAVADA '
          '(mesmo efeito de clicar "Nao" no UAC)')
    import win32file
    srv = _start_mock_github(os.path.abspath(zip_path), ver)
    pend = os.path.join(UPD_DIR, 'update_pending.txt')
    ulog = os.path.join(UPD_DIR, 'update.log')
    lock = None
    try:
        kill_app()
        launch_app()
        check(wait_for(lambda: os.path.isfile(pend), 300, 2), 'download silencioso concluido')
        kill_app()
        # Arquivo aberto dentro de _internal: o Rename-Item da pasta falha,
        # exatamente como quando o script roda sem permissao em Program Files.
        target = os.path.join(APP_DIR, '_internal', 'base_library.zip')
        if not os.path.isfile(target):
            target = os.path.join(APP_DIR, '_internal', 'python314.dll')
        lock = win32file.CreateFile(target, win32file.GENERIC_READ, win32file.FILE_SHARE_READ,
                                    None, win32file.OPEN_EXISTING, 0, None)
        for n in (1, 2, 3):
            if os.path.exists(ulog):
                os.remove(ulog)
            launch_app()
            done = wait_for(lambda: 'Nada foi alterado' in read_text(ulog), 120, 2)
            check(done, f'tentativa {n}: script desistiu sem mexer em nada ("Nada foi alterado")')
            time.sleep(5)
            procs = app_processes()
            opened = bool(procs)
            info(f'tentativa {n}: app {"ABRIU" if opened else "ficou FECHADO (usuario precisa clicar no icone de novo)"}')
            if expect_reopen:
                check(len(procs) == 1 and '--skip-update' in procs[0][1],
                      f'tentativa {n}: script reabriu a versao atual sozinho (--skip-update)', repr(procs))
                time.sleep(15)
                tries = read_text(ulog).count('Update iniciado')
                check(tries == 1 and len(app_processes()) == 1,
                      f'tentativa {n}: app reaberto NAO tenta de novo (sem loop de UAC)',
                      f'{tries} execucoes do script')
            check(file_version(APP_EXE) == old
                  and os.path.isfile(os.path.join(APP_DIR, '_internal', 'python314.dll'))
                  and not os.path.exists(os.path.join(APP_DIR, '_internal.bak')),
                  f'tentativa {n}: versao {old} continua inteira (sem "Failed to load Python DLL")')
            kill_app()
        launch_app()
        applog = os.path.join(UPD_DIR, 'mbchat.log')
        up = wait_for(lambda: len(app_processes()) == 1 and 'desistindo' in read_text(applog), 60)
        check(up, 'tentativa 4: app desiste do update e ABRE normal (sem loop)')
        check(setting('last_version') == old, f'continua na {old} funcionando')
        check_data_preserved('apos 3 falhas')
        # destrava: o proprio app baixa de novo e o proximo boot aplica
        win32file.CloseHandle(lock)
        lock = None
        check(wait_for(lambda: os.path.isfile(pend), 300, 2),
              'com o app aberto, o update e baixado de novo sozinho')
        kill_app()
        if os.path.exists(ulog):
            os.remove(ulog)
        launch_app()
        ok_ = wait_for(lambda: file_version(APP_EXE) == ver and setting('last_version') == ver
                       and len(app_processes()) == 1, 240, 2)
        check(ok_, f'destravado: proxima abertura atualiza para {ver} e abre')
        check('ROLLBACK' not in read_text(ulog), 'sem rollback na tentativa final')
        check_data_preserved('apos atualizar')
        if FAIL:
            dump_logs()
    finally:
        if lock is not None:
            win32file.CloseHandle(lock)
        srv.shutdown()
        _unhosts()


def cmd_update_impatient(zip_path, ver, strict=False):
    # Update aplicado no boot enquanto o app e aberto de novo 3 vezes durante a
    # troca -- a 2a entrada de inicio automatico (HKCU Run + atalho de
    # Inicializacao) ou alguem clicando no icone porque "nao abriu". Registra
    # qualquer janela de erro de QUALQUER MBChat.exe (ex. "Failed to load
    # Python DLL") e confere o estado final.
    st = load_state()
    old = (st.get('installed_tag') or '').lstrip('v')
    print(f'\n[update-impatient] update {old} -> {ver} com o app sendo aberto 3x durante a troca')
    srv = _start_mock_github(os.path.abspath(zip_path), ver)
    pend = os.path.join(UPD_DIR, 'update_pending.txt')
    ulog = os.path.join(UPD_DIR, 'update.log')
    try:
        kill_app()
        launch_app()
        check(wait_for(lambda: os.path.isfile(pend), 300, 2), 'download silencioso concluido')
        kill_app()
        db_exec("DELETE FROM settings WHERE key='last_version'")
        if os.path.exists(ulog):
            os.remove(ulog)
        launch_app()
        check(wait_for(lambda: 'Update iniciado' in read_text(ulog), 120, 0.3), 'script de update comecou')
        dialogos, extras, t_end = [], 0, time.time() + 90
        prox = time.time() + 1.0
        while time.time() < t_end:
            if extras < 3 and time.time() >= prox:
                launch_app()
                extras += 1
                prox = time.time() + 2.0
            for txt in _dialogs_of(_pids('MBChat.exe')):
                if txt not in dialogos:
                    dialogos.append(txt)
            if extras >= 3 and 'App lancado' in read_text(ulog) and time.time() > prox + 10:
                break
            time.sleep(0.3)
        info(f'app aberto {extras}x a mais durante o update')
        for d in dialogos:
            info(f'JANELA DE ERRO: {d}')
        if strict:
            check(not dialogos, 'nenhuma janela de erro (ex. "Failed to load Python DLL")', ' || '.join(dialogos))
        ok_ = wait_for(lambda: file_version(APP_EXE) == ver and setting('last_version') == ver
                       and len(app_processes()) == 1, 240, 2)
        check(ok_, f'no fim: versao {ver} instalada e aberta (uma instancia so)',
              f'exe={file_version(APP_EXE)} last={setting("last_version")} procs={app_processes()}')
        time.sleep(15)
        procs = app_processes()
        erros = _dialogs_of({p for p, _ in procs})
        check(len(procs) == 1 and not erros, 'app continua aberto 15s depois, sem janela de erro',
              f'{procs} {erros}')
        check(os.path.isfile(os.path.join(APP_DIR, '_internal', 'python314.dll'))
              and not os.path.exists(os.path.join(APP_DIR, '_internal.bak'))
              and not os.path.exists(os.path.join(APP_DIR, '_internal.new')),
              'pasta do app consistente (python314.dll, sem .bak/.new)')
        ulog_txt = read_text(ulog)
        info(f'scripts de update que rodaram: {ulog_txt.count("Update iniciado")}')
        check_data_preserved('apos o update com cliques')
        if FAIL:
            dump_logs()
    finally:
        srv.shutdown()
        _unhosts()


def cmd_setup_over(setup, ver):
    st = load_state()
    old = (st.get('installed_tag') or '').lstrip('v')
    print(f'\n[setup-over] instalador {ver} por cima da {old}, com o app ABERTO')
    launch_app()
    check(wait_for(lambda: len(app_processes()) == 1, 30), f'app {old} aberto antes do setup')
    time.sleep(5)
    orphan = os.path.join(APP_DIR, '_internal', 'e2e_orfao_de_versao_velha.pyd')
    with open(orphan, 'wb') as f:
        f.write(b'x')
    os.makedirs(os.path.join(UPD_DIR, 'update_staging'), exist_ok=True)
    with open(os.path.join(UPD_DIR, 'update_pending.txt'), 'w', encoding='utf-8') as f:
        f.write(os.path.join(UPD_DIR, 'update_staging'))
    log = os.path.join(WORK, f'setup_over_{ver}.log')
    r = subprocess.run([os.path.abspath(setup), '/VERYSILENT', '/SUPPRESSMSGBOXES',
                        '/NORESTART', f'/LOG={log}'], timeout=900)
    check(r.returncode == 0, 'setup novo terminou com codigo 0', str(r.returncode))
    check(not app_processes(), 'setup fechou o app que estava aberto')
    check(file_version(APP_EXE) == ver, f'MBChat.exe agora e {ver}', file_version(APP_EXE))
    check(not os.path.exists(orphan), 'arquivo orfao de versao velha em _internal removido')
    check(os.path.isfile(os.path.join(APP_DIR, '_internal', 'python314.dll')),
          '_internal com python314.dll')
    check(uninstall_display_version() == ver, 'registro de desinstalacao atualizado',
          uninstall_display_version())
    for rule in ('MBChat TCP In', 'MBChat TCP In Dynamic', 'MBChat UDP In'):
        check(firewall_rule(rule), f'regra de firewall "{rule}" presente')
    startup = os.path.join(APPDATA, r'Microsoft\Windows\Start Menu\Programs\Startup\MB Chat.lnk')
    check(os.path.isfile(startup), 'atalho de inicializacao com o Windows mantido')
    check(not os.path.exists(os.path.join(UPD_DIR, 'update_pending.txt'))
          and not os.path.exists(os.path.join(UPD_DIR, 'update_staging')),
          'resto de update velho (pending/staging) limpo pelo setup')
    check_data_preserved('apos setup por cima')
    launch_app()
    up = wait_for(lambda: setting('last_version') == ver and len(app_processes()) == 1, 120)
    check(up, f'app {ver} abre depois do setup (last_version={setting("last_version")})')
    time.sleep(15)
    check(len(app_processes()) == 1, 'app segue aberto 15s depois')
    check_data_preserved('apos abrir a versao nova')
    kill_app()
    if FAIL:
        dump_logs([log])


def cmd_webinstaller(stub, use_8dot3=False):
    print('\n[webinstaller] instalador web baixa o setup da ULTIMA release e o executa'
          + (' (TEMP em caminho 8.3)' if use_8dot3 else ''))
    expected = os.path.join(WORK, 'latest_setup_direto.exe')
    download(f'https://github.com/{REPO}/releases/latest/download/MBChat_Setup.exe', expected)
    exp_sha = sha256_file(expected)
    env = dict(os.environ)
    temp = tempfile.gettempdir()
    if use_8dot3:
        sp = make_8dot3_temp()
        if sp:
            info(f'TEMP/TMP do instalador web = {sp}')
            env['TEMP'] = env['TMP'] = temp = sp
        else:
            skip('runner sem nomes 8.3: cenario TEMP 8.3 NAO testado nesta rodada')
    dst = os.path.join(temp, 'MBChat_Setup.exe')

    def _gone():
        # o setup de uma rodada anterior pode segurar o arquivo por alguns segundos
        if os.path.exists(dst):
            os.remove(dst)
        return True
    wait_for(_gone, 30)
    t0 = time.time()
    r = subprocess.run([os.path.abspath(stub)], env=env, timeout=600,
                       stdin=subprocess.DEVNULL)
    check(r.returncode == 0, 'instalador web terminou com codigo 0', str(r.returncode))
    info(f'download + abertura em {time.time() - t0:.0f}s')
    check(os.path.isfile(dst) and sha256_file(dst) == exp_sha,
          'baixou exatamente o MBChat_Setup.exe da ultima release',
          dst if not os.path.isfile(dst) else sha256_file(dst)[:16])
    started = wait_for(lambda: processes('MBChat_Setup.tmp') or processes('MBChat_Setup.exe'), 60)
    check(started, 'setup foi aberto pelo instalador web (sem erro de elevacao)')
    for name in ('MBChat_Setup.tmp', 'MBChat_Setup.exe'):
        subprocess.run(['taskkill', '/f', '/t', '/im', name], capture_output=True)
    wait_for(lambda: not processes('MBChat_Setup.tmp') and not processes('MBChat_Setup.exe'), 30)


# ───────────────────────── assistente (wizard) do Inno Setup ─────────────────────────

def _pids(name):
    return {pid for pid, _ in processes(name)}


def _dialogs_of(pids):
    # textos de caixas de mensagem (#32770) abertas por esses processos
    from pywinauto import Desktop
    out = []
    for d in Desktop(backend='win32').windows(class_name='#32770'):
        try:
            if d.process_id() in pids and d.is_visible():
                txt = ' | '.join(t for t in [d.window_text()] + [c.window_text() for c in d.descendants()] if t)
                out.append(txt)
        except Exception:
            pass
    return out


def drive_wizard(timeout=600):
    # Clica o botao principal (Avancar / Instalar / Concluir) de cada pagina,
    # como o funcionario faria, e devolve (paginas, erro). BM_CLICK por
    # PostMessage: nao depende de foco nem de mouse.
    import win32api
    from pywinauto import Desktop
    pages, started, last, ultimo_clique = [], False, None, 0.0
    end = time.time() + timeout
    while time.time() < end:
        setup_pids = _pids('MBChat_Setup.tmp') | _pids('MBChat_Setup.exe')
        erros = _dialogs_of(setup_pids)
        if erros:
            return pages, 'caixa de dialogo do instalador: ' + ' || '.join(erros)
        wiz = [w for w in Desktop(backend='win32').windows(class_name='TWizardForm') if w.is_visible()]
        if not wiz:
            if started and not setup_pids:
                return pages, None
            time.sleep(1)
            continue
        started = True
        w = wiz[0]
        alvo, rotulo = None, ''
        for c in w.descendants(class_name='TNewButton'):
            try:
                t = c.window_text().replace('&', '').strip()
                if c.is_visible() and c.is_enabled() and t.startswith(
                        ('Avan', 'Instalar', 'Concluir', 'Next', 'Install', 'Finish')):
                    alvo, rotulo = c, t
                    break
            except Exception:
                pass
        if alvo is None:
            time.sleep(1)
            continue
        # O Inno usa o MESMO botao "Avancar" em todas as paginas: a pagina e
        # identificada pelos textos dela; parada 6s sem mudar = clica de novo.
        textos = []
        for c in w.descendants(class_name='TNewStaticText'):
            try:
                if c.is_visible() and c.window_text():
                    textos.append(c.window_text())
            except Exception:
                pass
        assinatura = (rotulo, tuple(textos[:4]))
        agora = time.time()
        if assinatura != last or agora - ultimo_clique > 6:
            titulo = textos[0] if textos else '?'
            pages.append(f'{titulo} -> {rotulo}')
            last, ultimo_clique = assinatura, agora
            win32api.PostMessage(alvo.handle, 0x00F5, 0, 0)  # BM_CLICK
        time.sleep(1.5)
    return pages, 'o assistente nao terminou em %ds' % timeout


def check_app_booted(ver, label):
    # O app aberto pelo "Abrir MB Chat" do assistente rodou Python de verdade?
    # Grava last_version no banco (o teste apagou antes) e nao tem caixa de
    # erro do carregador ("Failed to load Python DLL").
    up = wait_for(lambda: setting('last_version') == ver and len(app_processes()) == 1, 120, 2)
    procs = app_processes()
    erros = _dialogs_of({p for p, _ in procs})
    check(up and not erros, f'{label}: MB Chat {ver} abriu de verdade (Python carregou, sem erro de DLL)',
          f'last_version={setting("last_version")} procs={procs} dialogos={erros}')
    time.sleep(15)
    procs = app_processes()
    erros = _dialogs_of({p for p, _ in procs})
    check(len(procs) == 1 and not erros, f'{label}: app continua aberto 15s depois, sem janela de erro',
          f'procs={procs} dialogos={erros}')
    if procs:
        info(f'{label}: app aberto pelo assistente roda como admin: {process_elevated(procs[0][0])}')


def cmd_wizard(exe, ver, fresh=False):
    # exe = instalador web (baixa o setup da ultima release) ou o proprio setup
    nome = os.path.basename(exe)
    print(f'\n[wizard] {nome}: assistente clicado ate "Concluir" com "Abrir MB Chat" marcado'
          + (' (PC sem MB Chat)' if fresh else ' (por cima, com o app ABERTO)'))
    if fresh:
        check(not os.path.exists(APP_EXE), 'ponto de partida: MB Chat nao instalado')
    else:
        launch_app()
        check(wait_for(lambda: len(app_processes()) == 1, 60), 'app aberto antes de instalar')
        time.sleep(8)
        db_exec("DELETE FROM settings WHERE key='last_version'")
    t0 = time.time()
    subprocess.Popen([os.path.abspath(exe)], stdin=subprocess.DEVNULL)
    pages, erro = drive_wizard()
    info(f'paginas clicadas: {" > ".join(pages)} ({time.time() - t0:.0f}s)')
    check(erro is None, 'assistente foi do inicio ao fim sem erro', str(erro))
    check(any(p.endswith(('Concluir', 'Finish')) for p in pages), 'chegou na pagina final (Concluir)')
    check(file_version(APP_EXE) == ver, f'MBChat.exe instalado e {ver}', file_version(APP_EXE))
    check(os.path.isfile(os.path.join(APP_DIR, '_internal', 'python314.dll')), '_internal com python314.dll')
    for rule in ('MBChat TCP In', 'MBChat TCP In Dynamic', 'MBChat UDP In'):
        check(firewall_rule(rule), f'regra de firewall "{rule}"')
    check_app_booted(ver, 'apos o assistente')
    if not fresh:
        check_data_preserved('apos reinstalar pelo assistente')
    if FAIL:
        dump_logs()
    save_state(installed_tag=f'v{ver}')


def main():
    if os.environ.get('MBCHAT_E2E') != '1':
        print('Recusado: este teste instala em Program Files e mexe no arquivo hosts.')
        print('So roda no CI (MBCHAT_E2E=1).')
        sys.exit(2)
    global LIMITED
    args = sys.argv[1:]
    flag83 = '--8dot3' in args
    LIMITED = '--limited' in args
    if LIMITED:
        use_appdata(load_state()['as_user']['appdata'])
    api_calls = None
    if '--api-calls' in args:
        i = args.index('--api-calls')
        api_calls = int(args[i + 1])
        del args[i:i + 2]
    content_ver = None
    if '--content-ver' in args:
        i = args.index('--content-ver')
        content_ver = args[i + 1]
        del args[i:i + 2]
    args = [a for a in args if a not in ('--8dot3', '--limited')]
    for flag in ('--expect-unelevated', '--via-startup', '--fresh', '--strict'):
        if flag in args:
            args = [a for a in args if a != flag] + [flag]
    cmd = args[0] if args else ''
    if cmd == 'install-release':
        cmd_install_release(args[1])
    elif cmd == 'make-user':
        cmd_make_user()
    elif cmd == 'install-setup':
        cmd_install_setup(args[1], args[2])
    elif cmd == 'seed':
        cmd_seed(args[1])
    elif cmd == 'update-flow':
        cmd_update_flow(args[1], args[2], flag83, api_calls, '--expect-unelevated' in args,
                        '--via-startup' in args, content_ver)
    elif cmd == 'update-blocked':
        cmd_update_blocked(args[1], args[2], '--expect-reopen' in args)
    elif cmd == 'setup-over':
        cmd_setup_over(args[1], args[2])
    elif cmd == 'webinstaller':
        cmd_webinstaller(args[1], flag83)
    elif cmd == 'update-impatient':
        cmd_update_impatient(args[1], args[2], '--strict' in args)
    elif cmd == 'wizard':
        cmd_wizard(args[1], args[2], '--fresh' in args)
    else:
        print(__doc__ or 'uso: ver cabecalho do arquivo')
        sys.exit(2)
    print(f'\n{len(PASS)} PASS, {len(FAIL)} FAIL, {len(SKIP)} SKIP')
    for s_ in SKIP:
        print(f'  (nao testado: {s_})')
    print(f'{len(PASS)} passou {len(FAIL)} falhou')
    sys.exit(0 if not FAIL else 1)


if __name__ == '__main__':
    main()
