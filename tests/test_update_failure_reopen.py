# test_update_failure_reopen.py
# Update que nao consegue trocar os arquivos (UAC negado, pasta travada,
# antivirus): a versao atual fica intacta, mas o script terminava sem reabrir
# o app -- o usuario ficava sem o MB Chat ate clicar no icone de novo (ate 3
# vezes, quando o contador de tentativas desiste). Agora:
#   1. toda saida de erro do script reabre a versao atual com --skip-update
#      (so quando o update partiu do boot ou do "Reiniciar para Atualizar";
#      no "Sair" da bandeja o app fica fechado, como o usuario pediu);
#   2. a abertura com --skip-update NAO tenta o update de novo (sem loop de
#      prompts do UAC) e nao zera o contador de tentativas.
# No Windows roda o script gerado de verdade (PowerShell) com _internal travado.
# Rodar: python tests/test_update_failure_reopen.py

import os
import re
import ast
import sys
import shutil
import tempfile
import subprocess

here = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(here) if os.path.basename(here) == 'tests' else here
sys.path.insert(0, root_dir)

try:
    sys.stdout.reconfigure(errors='backslashreplace')
except Exception:
    pass

import updater

PASS, FAIL = [], []


def ok(msg):
    PASS.append(msg)
    print(f'  PASS  {msg}')


def fail(msg, detail=''):
    FAIL.append(msg)
    print(f'  FAIL  {msg}' + (f': {detail}' if detail else ''))


def check(cond, msg, detail=''):
    ok(msg) if cond else fail(msg, detail)


def gen_script(base, inst, stg, **kw):
    updater._UPDATE_DIR = base
    real_exe, real_popen = updater.sys.executable, updater.subprocess.Popen
    updater.sys.executable = os.path.join(inst, 'MBChat.exe')
    updater.subprocess.Popen = lambda *a, **k: None
    try:
        updater.apply_update(stg, **kw)
    finally:
        updater.sys.executable = real_exe
        updater.subprocess.Popen = real_popen
    with open(os.path.join(base, 'update.ps1'), encoding='utf-8') as f:
        return f.read()


def sandbox():
    base = tempfile.mkdtemp(prefix='mbchat_reopen_')
    inst = os.path.join(base, 'inst')
    stg = os.path.join(base, 'stg')
    os.makedirs(os.path.join(inst, '_internal'))
    os.makedirs(os.path.join(stg, '_internal'))
    for d in (inst, stg):
        for i in range(60):
            with open(os.path.join(d, '_internal', f'f{i}.bin'), 'wb') as f:
                f.write(b'x' * 10)
    return base, inst, stg


def test_script_text():
    print('\n[1] script gerado: toda saida de erro reabre a versao atual')
    base, inst, stg = sandbox()
    for s in (os.path.join(stg, 'MBChat.exe'), os.path.join(inst, 'MBChat.exe')):
        with open(s, 'wb') as f:
            f.write(b'exe')
    txt = gen_script(base, inst, stg)
    check('$RelaunchOnFail = $true' in txt, 'padrao (boot / Reiniciar): reabre se falhar')
    txt_quit = gen_script(base, inst, stg, relaunch_on_fail=False)
    check('$RelaunchOnFail = $false' in txt_quit, '"Sair" da bandeja: nao reabre')
    lines = txt.splitlines()
    exits = [i for i, l in enumerate(lines) if l.strip() == 'exit 1']
    check(exits and all(lines[i - 1].strip() == 'Start-OldApp' for i in exits),
          f'os {len(exits)} "exit 1" chamam Start-OldApp logo antes')
    def_line = next(i for i, l in enumerate(lines) if l.startswith('function Start-OldApp'))
    call_lines = [i for i, l in enumerate(lines) if l.strip() == 'Start-OldApp']
    check(call_lines and def_line < min(call_lines), 'Start-OldApp definida antes do primeiro uso')
    fdef = txt.index('function Start-OldApp')
    body = txt[fdef:txt.index('\n}\n', fdef)]
    check('"--show --skip-update"' in body and 'UseShellExecute = $false' in body,
          'reabre com --show --skip-update via CreateProcess (8.3 ok)')
    ok_path = txt[txt.index('# Sucesso confirmado'):]
    check('Start-OldApp' not in ok_path, 'caminho de sucesso nao usa Start-OldApp')
    check(updater.apply_update(os.path.join(base, 'nao_existe')) is False,
          'staging invalido continua devolvendo False (boot segue normal)')


def test_gui_wiring():
    print('\n[2] gui.py: --skip-update no boot e "Sair" x "Reiniciar"')
    with open(os.path.join(root_dir, 'gui.py'), encoding='utf-8') as f:
        src = f.read()
    tree = ast.parse(src)
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main')
    msrc = ast.get_source_segment(src, main)
    m = re.search(r"if pending_update_dir and '--skip-update' in sys\.argv\[1:\]:(.*?)\n        elif pending_update_dir:",
                  msrc, re.S)
    check(m is not None, 'boot: --skip-update checado ANTES de aplicar o update')
    if m:
        check('apply_update' not in m.group(1) and 'reset_update_attempts' not in m.group(1)
              and 'clear_update_pending' not in m.group(1),
              'com --skip-update: nao aplica, nao zera o contador, mantem o pedido')
    check(re.search(r"apply_update\(\s*pending, relaunch_on_fail=getattr\(self, '_restart_requested', False\)\)",
                    src) is not None, '_quit: reabre so se o usuario pediu "Reiniciar para Atualizar"')
    check(re.search(r"self\._restart_requested = True\n\s*self\.root\.after\(400, self\._quit\)", src)
          is not None, 'botao OK do "Reiniciar para Atualizar" marca o pedido de reinicio')


def test_real_powershell():
    print('\n[3] PowerShell de verdade: pasta travada -> reabre a versao atual')
    if os.name != 'nt' or not shutil.which('powershell.exe'):
        ok('SKIP  teste especifico de Windows/PowerShell')
        return
    import win32file
    for relaunch in (True, False):
        base, inst, stg = sandbox()
        # exe de verdade (qualquer um serve: so precisa iniciar)
        shutil.copy(os.path.join(os.environ['SystemRoot'], 'System32', 'where.exe'),
                    os.path.join(inst, 'MBChat.exe'))
        with open(os.path.join(stg, 'MBChat.exe'), 'wb') as f:
            f.write(b'novo')
        txt = gen_script(base, inst, stg, relaunch_on_fail=relaunch)
        txt = '$isAdmin = $true\n' + txt[txt.index('$LogFile ='):]
        txt = txt.replace('Start-Sleep -Seconds 5', 'Start-Sleep -Milliseconds 50')
        txt = txt.replace('Start-Sleep -Seconds 2', 'Start-Sleep -Milliseconds 50')
        txt = txt.replace('Stop-Process -Name "MBChat" -Force -ErrorAction SilentlyContinue', '')
        ps = os.path.join(base, 'update.ps1')
        with open(ps, 'w', encoding='utf-8') as f:
            f.write(txt)
        lock = win32file.CreateFile(os.path.join(inst, '_internal', 'f0.bin'),
                                    win32file.GENERIC_READ, win32file.FILE_SHARE_READ,
                                    None, win32file.OPEN_EXISTING, 0, None)
        try:
            r = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                                '-File', ps], capture_output=True, timeout=120)
        finally:
            win32file.CloseHandle(lock)
        with open(os.path.join(base, 'update.log'), 'rb') as f:
            raw = f.read()
        log = raw.decode('utf-16', errors='replace') if raw[:2] == b'\xff\xfe' else raw.decode('utf-8', 'replace')
        label = 'boot/Reiniciar' if relaunch else '"Sair"'
        check(r.returncode == 1 and 'Nada foi alterado' in log, f'{label}: script desiste sem mexer em nada')
        check(os.path.isdir(os.path.join(inst, '_internal'))
              and not os.path.exists(os.path.join(inst, '_internal.bak')),
              f'{label}: versao atual intacta')
        if relaunch:
            check('Versao atual reaberta (--skip-update)' in log, 'boot/Reiniciar: app reaberto', log[-300:])
        else:
            check('reaberta' not in log, '"Sair": app continua fechado')


if __name__ == '__main__':
    test_script_text()
    test_gui_wiring()
    test_real_powershell()
    print(f'\n{len(PASS)} PASS, {len(FAIL)} FAIL')
    print(f'{len(PASS)} passou {len(FAIL)} falhou')  # resumo lido pelo gate
    sys.exit(0 if not FAIL else 1)
