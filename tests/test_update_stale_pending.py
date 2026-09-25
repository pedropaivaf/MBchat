# test_update_stale_pending.py
# Update pendente da versao ja instalada (ou mais velha) e descartado, nunca
# reaplicado. Cenario real: ao publicar, a versao anterior baixa o update sozinha
# no %APPDATA% do funcionario; o admin roda o instalador web / deploy com a conta
# DELE (ou SYSTEM), o setup limpa o %APPDATA% dele e o do funcionario fica com o
# pendente. Sem este descarte o app novo reaplicava a mesma versao (UAC a toa, ate
# 3x para quem nao e admin) ou, com um pendente mais velho, VOLTAVA de versao.
# Rodar: python tests/test_update_stale_pending.py

import os
import re
import shutil
import sys
import tempfile

here = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(here) if os.path.basename(here) == 'tests' else here
sys.path.insert(0, root_dir)

IS_WIN = sys.platform == 'win32'
PASS, FAIL, SKIP = [], [], []


def ok(msg):
    PASS.append(msg)
    print(f'  PASS  {msg}')


def fail(msg, detail=''):
    FAIL.append(msg)
    print(f'  FAIL  {msg}' + (f': {detail}' if detail else ''))


def skip(msg):
    SKIP.append(msg)
    print(f'  SKIP  {msg}')


def check(cond, msg, detail=''):
    ok(msg) if cond else fail(msg, detail)


def read(name):
    with open(os.path.join(root_dir, name), encoding='utf-8') as f:
        return f.read()


def test_static():
    print('\n[1] boot e encerramento conferem a versao do pendente antes de aplicar')
    src = read('gui.py')
    m = re.search(r'pending_update_dir = updater\.is_update_pending\(\).*?(?=\n    _register_url_protocol)',
                  src, re.DOTALL)
    b = m.group(0) if m else ''
    i_stale = b.find('updater.pending_is_stale(pending_update_dir)')
    i_bump = b.find('bump_update_attempt()')
    i_apply = b.find('updater.apply_update(pending_update_dir)')
    i_run = b.find('_update_script_running()')
    check(0 <= i_stale < min(i_bump, i_apply, i_run),
          'boot: pendente velho descartado ANTES de contar tentativa / aplicar', f'{i_stale} {i_bump} {i_apply}')
    check('updater.discard_pending(pending_update_dir)' in b, 'boot: descarte limpa marcador e staging')
    q = re.search(r'# Se houver update baixado silenciosamente, aplica ele agora na saida.*?os\._exit\(0\)',
                  src, re.DOTALL)
    qb = q.group(0) if q else ''
    check('pending_is_stale(pending)' in qb and qb.find('pending_is_stale') < qb.find('apply_update('),
          'encerramento: mesma conferencia antes de aplicar')


def test_logic():
    print('\n[2] mais novo aplica; igual ou mais velho descarta; sem versao legivel segue como antes')
    import updater
    orig = updater.staged_version
    try:
        casos = [('1.8.40', '1.8.39', False), ('1.8.39', '1.8.39', True), ('1.8.38', '1.8.39', True),
                 ('1.9.0', '1.8.99', False), ('1.8.99', '1.9.0', True), ('1.8.39', '1.8.39-dev', True),
                 (None, '1.8.39', False)]
        for staged, cur, esperado in casos:
            updater.staged_version = lambda d, s=staged: s
            stale, got = updater.pending_is_stale('x', cur)
            check(stale is esperado and got == staged,
                  f'staging {staged} com app {cur}: {"descarta" if esperado else "aplica"}', f'{stale} {got}')
    finally:
        updater.staged_version = orig


def test_discard():
    print('\n[3] descarte apaga marcador, contador e staging (so dentro da pasta do updater)')
    import updater
    tmp = tempfile.mkdtemp(prefix='mbchat_stale_')
    old = updater._UPDATE_DIR
    updater._UPDATE_DIR = tmp
    try:
        staging = os.path.join(tmp, 'update_staging')
        os.makedirs(os.path.join(staging, '_internal'))
        open(os.path.join(staging, 'MBChat.exe'), 'wb').close()
        updater.mark_update_ready(staging)
        updater.bump_update_attempt()
        fora = tempfile.mkdtemp(prefix='mbchat_fora_')
        updater.discard_pending(fora)
        check(os.path.isdir(fora), 'pasta FORA da pasta do updater nunca e apagada')
        shutil.rmtree(fora, ignore_errors=True)
        updater.mark_update_ready(staging)
        updater.bump_update_attempt()
        updater.discard_pending(staging)
        check(updater.is_update_pending() is None, 'marcador update_pending.txt removido')
        check(not os.path.exists(os.path.join(tmp, 'update_attempts.txt')), 'contador de tentativas zerado')
        check(not os.path.exists(staging), 'staging (~100MB) apagado')
    finally:
        updater._UPDATE_DIR = old
        shutil.rmtree(tmp, ignore_errors=True)


def test_staged_version_real():
    print('\n[4] versao lida do recurso VERSIONINFO de um exe de verdade (Windows)')
    import updater
    if not IS_WIN:
        check(updater.staged_version(tempfile.gettempdir()) is None, 'fora do Windows: None (segue como antes)')
        skip('leitura do VERSIONINFO -- so no Windows')
        return
    tmp = tempfile.mkdtemp(prefix='mbchat_ver_')
    try:
        check(updater.staged_version(tmp) is None, 'staging sem MBChat.exe: None')
        shutil.copy(sys.executable, os.path.join(tmp, 'MBChat.exe'))
        v = updater.staged_version(tmp)
        esperado = f'{sys.version_info.major}.{sys.version_info.minor}.'
        check(bool(v) and re.match(r'^\d+\.\d+\.\d+$', v) and v.startswith(esperado),
              f'python.exe copiado como MBChat.exe: FileVersion {v}', repr(v))
        with open(os.path.join(tmp, 'MBChat.exe'), 'wb') as f:
            f.write(b'nao e um exe')
        check(updater.staged_version(tmp) is None, 'exe sem VERSIONINFO: None (segue como antes)')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    test_static()
    test_logic()
    test_discard()
    test_staged_version_real()
    print(f'\n{len(PASS)} PASS, {len(FAIL)} FAIL, {len(SKIP)} SKIP')
    sys.exit(0 if not FAIL else 1)
