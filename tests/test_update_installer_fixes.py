# test_update_installer_fixes.py
# Valida os fixes de desinstalacao (installer.iss), instalacao limpa e
# auto-update silencioso (updater.py + gui.py) sem precisar de Windows.
#
# Cobre:
#   - updater.apply_update agora retorna bool e NUNCA trava o boot (anti-brick)
#   - updater.clear_update_pending remove o marcador
#   - script PowerShell gerado: CreateProcess + --show + cleanup + sanity (sem leftovers)
#   - gui.py boot/quit so saem se apply_update teve sucesso, senao limpam o pending
#   - installer.iss: UninstallSilent (nao WizardSilent), try/except, _internal limpo,
#     registro orfao removido, DB (.mbchat) preservado
#
# Rodar: python tests/test_update_installer_fixes.py
#
# NOTA: a COMPILACAO do installer.iss (Inno Setup) e os testes de instalacao/
# reinstalacao/update reais SO podem ser feitos no Windows. Aqui validamos a
# logica e a estrutura do codigo que sustentam esses fluxos.

import os
import sys
import re
import tempfile
import shutil

here = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(here) if os.path.basename(here) == 'tests' else here
sys.path.insert(0, root_dir)

PASS = []
FAIL = []

def ok(msg):
    PASS.append(msg)
    print(f'  PASS  {msg}')

def fail(msg, detail=''):
    FAIL.append(msg)
    print(f'  FAIL  {msg}' + (f': {detail}' if detail else ''))

def read(name):
    with open(os.path.join(root_dir, name), encoding='utf-8') as f:
        return f.read()


# ─────────────────────────────────────────────
# UPDATER — anti-brick (staging invalido nao pode travar o boot)
# ─────────────────────────────────────────────
def test_updater_invalid_staging_antibrick():
    print('\n[Updater] staging invalido -> apply_update=False e limpa pending')
    import updater
    os.makedirs(updater._UPDATE_DIR, exist_ok=True)

    if not hasattr(updater, 'clear_update_pending'):
        fail('updater.clear_update_pending nao existe')
        return

    fake = os.path.join(tempfile.gettempdir(), 'mbchat_staging_inexistente_xyz')
    if os.path.isdir(fake):
        shutil.rmtree(fake, ignore_errors=True)

    updater.mark_update_ready(fake)
    if updater.is_update_pending() != fake:
        fail('mark_update_ready/is_update_pending nao fez roundtrip')
        return

    result = updater.apply_update(fake)
    if result is False:
        ok('apply_update(staging_invalido) retornou False')
    else:
        fail(f'apply_update deveria retornar False, veio {result!r}')

    if updater.is_update_pending() is None:
        ok('update_pending limpo apos staging invalido (nao trava boot)')
    else:
        fail('update_pending NAO foi limpo — risco de loop de brick no boot')


def test_updater_clear_idempotent():
    print('\n[Updater] clear_update_pending idempotente')
    import updater
    os.makedirs(updater._UPDATE_DIR, exist_ok=True)
    updater.clear_update_pending()
    if updater.clear_update_pending() is True:
        ok('clear_update_pending nao falha quando nao ha pending')
    else:
        fail('clear_update_pending retornou False sem pending')


# ─────────────────────────────────────────────
# UPDATER — staging valido gera PS correto e retorna True (Popen mockado)
# ─────────────────────────────────────────────
def test_updater_valid_staging_ps_script():
    print('\n[Updater] staging valido -> PS gerado correto + return True (Popen mockado)')
    import updater

    os.makedirs(updater._UPDATE_DIR, exist_ok=True)
    staging = tempfile.mkdtemp(prefix='mbchat_staging_ok_')
    # popula staging com um arquivo qualquer (precisa ser um dir valido)
    with open(os.path.join(staging, 'MBChat.exe'), 'w') as f:
        f.write('x')

    calls = {'n': 0, 'args': None}
    real_popen = updater.subprocess.Popen
    def fake_popen(*a, **k):
        calls['n'] += 1
        calls['args'] = a
        class _P:  # objeto dummy
            pid = 12345
        return _P()
    updater.subprocess.Popen = fake_popen
    try:
        result = updater.apply_update(staging)
    finally:
        updater.subprocess.Popen = real_popen

    if result is True:
        ok('apply_update(staging_valido) retornou True')
    else:
        fail(f'apply_update deveria retornar True, veio {result!r}')

    if calls['n'] == 1:
        ok('subprocess.Popen chamado exatamente 1x (powershell lancado)')
    else:
        fail(f'Popen chamado {calls["n"]}x (esperado 1)')

    # Le o update.ps1 gerado
    ps_path = os.path.join(updater._UPDATE_DIR, 'update.ps1')
    if not os.path.isfile(ps_path):
        fail('update.ps1 nao foi gerado')
        shutil.rmtree(staging, ignore_errors=True)
        return
    with open(ps_path, encoding='utf-8') as f:
        ps = f.read()

    checks = [
        ('[System.Diagnostics.Process]::Start', 'relanca via CreateProcess (herda env, resolve 8.3)'),
        ('--show', 'passa --show para reabrir a janela'),
        ('update_pending.txt', 'remove o marcador update_pending.txt'),
        ('-lt 50', 'sanity check de _internal (>=50 arquivos)'),
        ('RunAs', 'auto-elevacao UAC presente'),
        ('UseShellExecute = $false', 'CreateProcess com UseShellExecute=$false'),
    ]
    for needle, desc in checks:
        if needle in ps:
            ok(f'PS contem: {desc}')
        else:
            fail(f'PS NAO contem: {desc} ({needle!r})')

    # CreateProcess deve vir ANTES do fallback Start-Process
    cp = ps.find('[System.Diagnostics.Process]::Start')
    sp = ps.find('Start-Process -FilePath')
    if cp != -1 and sp != -1 and cp < sp:
        ok('CreateProcess e o metodo primario; Start-Process e fallback')
    elif cp != -1 and sp == -1:
        ok('CreateProcess presente (sem Start-Process)')
    else:
        fail('Ordem CreateProcess/Start-Process incorreta (Start-Process nao pode ser primario)')

    # Nenhum placeholder Python nao-renderizado deve sobrar
    leftovers = [p for p in ('{target_dir}', '{staging_dir}', '{target_exe}', '{log_path}')
                 if p in ps]
    if not leftovers:
        ok('Sem placeholders f-string nao-renderizados no PS')
    else:
        fail(f'Placeholders nao-renderizados no PS: {leftovers}')

    # O staging real deve aparecer literalmente no script (foi substituido)
    if staging.replace('/', os.sep) in ps or staging in ps:
        ok('Caminho real do staging presente no PS (substituicao ok)')
    else:
        fail('Caminho do staging nao aparece no PS')

    shutil.rmtree(staging, ignore_errors=True)
    updater.clear_update_pending()


# ─────────────────────────────────────────────
# GUI — boot nao-travante e quit honesto (analise de codigo)
# ─────────────────────────────────────────────
def test_gui_boot_non_bricking():
    print('\n[GUI] boot so faz os._exit(0) se apply_update teve sucesso')
    src = read('gui.py')

    boot = re.search(
        r'pending_update_dir = updater\.is_update_pending\(\).*?'
        r'(?=\n    _register_url_protocol)', src, re.DOTALL)
    if not boot:
        fail('Bloco de boot do update nao encontrado em gui.py')
        return
    b = boot.group(0)

    if re.search(r'if updater\.apply_update\(pending_update_dir\):\s*\n\s*os\._exit\(0\)', b):
        ok('Boot: os._exit(0) so dentro do if apply_update(...) (condicional)')
    else:
        fail('Boot: os._exit(0) nao esta condicionado ao sucesso de apply_update')

    if 'clear_update_pending()' in b:
        ok('Boot: limpa pending no else (anti-brick)')
    else:
        fail('Boot: nao limpa pending quando apply_update falha')

    # Garante que NAO sobrou o padrao antigo (apply incondicional + exit)
    if re.search(r'updater\.apply_update\(pending_update_dir\)\s*\n\s*os\._exit\(0\)', b):
        fail('Boot: ainda existe apply_update incondicional seguido de os._exit(0)')
    else:
        ok('Boot: padrao antigo (apply incondicional + exit) removido')


def test_gui_quit_honest():
    print('\n[GUI] quit limpa pending se apply_update falhar')
    src = read('gui.py')
    quit_blk = re.search(
        r'# Se houver update baixado silenciosamente, aplica ele agora na saida.*?'
        r'os\._exit\(0\)', src, re.DOTALL)
    if not quit_blk:
        fail('Bloco de quit do update nao encontrado em gui.py')
        return
    q = quit_blk.group(0)
    if 'if not updater.apply_update(pending)' in q and 'clear_update_pending()' in q:
        ok('Quit: trata retorno de apply_update e limpa pending se falhar')
    else:
        fail('Quit: nao trata retorno/limpeza de apply_update')


# ─────────────────────────────────────────────
# INSTALLER.ISS — uninstall fix + harden + clean install + DB preservado
# ─────────────────────────────────────────────
def test_iss_uninstall_silent():
    print('\n[installer.iss] WizardSilent -> UninstallSilent no uninstall')
    src = read('installer.iss')

    # WizardSilent nao pode aparecer em NENHUM lugar do codigo de uninstall.
    # (O fix trocou pela UninstallSilent.) Procuramos a procedure de uninstall.
    proc = re.search(r'procedure CurUninstallStepChanged.*?\nend;\s*$', src, re.DOTALL | re.MULTILINE)
    body = proc.group(0) if proc else src
    # Remove comentarios Pascal (//...) — eles citam WizardSilent() de proposito
    # ao documentar o motivo do fix. So importam linhas de codigo de verdade.
    body_nc = re.sub(r'//[^\n]*', '', body)

    if not re.search(r'WizardSilent\s*\(', body_nc):
        ok('Nenhuma chamada WizardSilent() no codigo de uninstall')
    else:
        fail('Chamada WizardSilent() ainda presente no uninstall — dispara runtime error')

    if 'UninstallSilent()' in body_nc:
        ok('UninstallSilent() em uso (funcao correta no uninstall)')
    else:
        fail('UninstallSilent() nao encontrado')


def test_iss_uninstall_harden():
    print('\n[installer.iss] harden: try/except no tratamento de dados')
    src = read('installer.iss')
    proc = re.search(r'procedure CurUninstallStepChanged.*?\nend;\s*$', src, re.DOTALL | re.MULTILINE)
    if not proc:
        fail('CurUninstallStepChanged nao encontrada')
        return
    body = proc.group(0)
    n_try = len(re.findall(r'\btry\b', body))
    n_except = len(re.findall(r'\bexcept\b', body))
    if n_try >= 1 and n_except >= 1:
        ok(f'try/except presentes (try={n_try}, except={n_except}) — limpeza nao aborta')
    else:
        fail(f'try/except ausentes no uninstall (try={n_try}, except={n_except})')

    # IsSilent capturado uma vez no inicio
    if 'IsSilent := UninstallSilent();' in body:
        ok('IsSilent capturado uma vez no inicio da procedure')
    else:
        fail('IsSilent nao capturado no inicio')


def test_iss_begin_end_balance():
    print('\n[installer.iss] balanco begin/end no [Code]')
    src = read('installer.iss')
    code = src[src.find('[Code]'):]
    # remove comentarios de linha // e {...} para nao contar palavras dentro
    code_nc = re.sub(r'//[^\n]*', '', code)
    begins = len(re.findall(r'\bbegin\b', code_nc))
    ends = len(re.findall(r'\bend\b', code_nc))  # inclui 'end;' e 'end.'
    # cada 'begin' casa com um 'end'; procedures fecham com 'end;' tambem.
    # Heuristica: ends == begins + N(procedures) nao e exato, mas begins<=ends sempre.
    if ends >= begins and begins > 0:
        ok(f'begin({begins}) <= end({ends}) — estrutura coerente')
    else:
        fail(f'Desbalanco begin/end: begin={begins}, end={ends}')


def test_iss_clean_internal():
    print('\n[installer.iss] instalacao limpa: {app}\\_internal apagado antes da copia')
    src = read('installer.iss')
    # Usa cabecalhos de secao no inicio de linha (o texto "[Files]" tambem aparece
    # dentro de um comentario, entao find() simples cortaria o slice cedo demais).
    m_start = re.search(r'^\[InstallDelete\]', src, re.M)
    m_end = re.search(r'^\[Files\]', src, re.M)
    instdel = src[m_start.start():m_end.start()]
    if re.search(r'Type:\s*filesandordirs;\s*Name:\s*"\{app\}\\_internal"', instdel):
        ok('{app}\\_internal em [InstallDelete] — _internal recriado limpo a cada install')
    else:
        fail('{app}\\_internal NAO esta em [InstallDelete] — DLLs orfas podem persistir')


def test_iss_orphan_registry():
    print('\n[installer.iss] limpeza de registro orfao em UninstallPreviousVersion')
    src = read('installer.iss')
    if 'RegDeleteKeyIncludingSubkeys' in src:
        ok('RegDeleteKeyIncludingSubkeys presente (limpa entrada orfa)')
    else:
        fail('RegDeleteKeyIncludingSubkeys ausente')


def test_iss_db_preserved():
    print('\n[installer.iss] DB do usuario (.mbchat) NUNCA entra no [InstallDelete]')
    src = read('installer.iss')
    m_start = re.search(r'^\[InstallDelete\]', src, re.M)
    m_end = re.search(r'^\[Files\]', src, re.M)
    instdel = src[m_start.start():m_end.start()]
    # Remove linhas de comentario (;) — elas podem mencionar .mbchat de forma legitima
    # (ex.: "NAO mexer no DB (.mbchat)"). So importam as diretivas Type:/Name:.
    instdel = '\n'.join(l for l in instdel.splitlines() if not l.strip().startswith(';'))
    # .mbchat (com ponto) nao pode ser apagado no install
    if '.mbchat' not in instdel:
        ok('%APPDATA%\\.mbchat nao aparece em [InstallDelete] — historico preservado')
    else:
        fail('%APPDATA%\\.mbchat aparece em [InstallDelete] — RISCO de apagar historico!')

    # E o uninstall preserva .mbchat no caminho KeepData (DelTree so no else)
    if re.search(r'if KeepData then', src) and re.search(r'DelTree\(DataPath', src):
        ok('Uninstall: DataPath (.mbchat) so apagado no ramo "remover tudo"')
    else:
        fail('Logica KeepData/DataPath nao confirmada no uninstall')


# ─────────────────────────────────────────────
# SANIDADE — modulos importam / sintaxe ok
# ─────────────────────────────────────────────
def test_imports_and_syntax():
    print('\n[Sanidade] sintaxe e import dos modulos sem GUI')
    import ast
    for mod in ('gui.py', 'updater.py', 'messenger.py', 'network.py', 'database.py'):
        try:
            ast.parse(read(mod))
            ok(f'{mod} ast.parse OK')
        except SyntaxError as e:
            fail(f'{mod} SyntaxError', str(e))
    for mod in ('updater', 'messenger', 'network', 'database'):
        try:
            __import__(mod)
            ok(f'import {mod} OK')
        except Exception as e:
            fail(f'import {mod} falhou', f'{type(e).__name__}: {e}')


if __name__ == '__main__':
    test_updater_invalid_staging_antibrick()
    test_updater_clear_idempotent()
    test_updater_valid_staging_ps_script()
    test_gui_boot_non_bricking()
    test_gui_quit_honest()
    test_iss_uninstall_silent()
    test_iss_uninstall_harden()
    test_iss_begin_end_balance()
    test_iss_clean_internal()
    test_iss_orphan_registry()
    test_iss_db_preserved()
    test_imports_and_syntax()

    print(f'\n{"="*52}')
    print(f'  {len(PASS)} passou   {len(FAIL)} falhou')
    print('='*52)
    sys.exit(0 if not FAIL else 1)
