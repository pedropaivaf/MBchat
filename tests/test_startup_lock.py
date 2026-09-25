# test_startup_lock.py
# Trava de inicializacao do MB Chat (gui.py main): duas aberturas quase juntas
# nao podem passar AS DUAS pela checagem de instancia unica. Antes a porta so
# era aberta depois de montar a janela (segundos), entao o logon (que abre o
# app 2x) ou um clique enquanto o updater reabria o app deixava as duas
# passarem -- e cada uma matava a outra no _cleanup_zombie_processes: nenhum
# MB Chat ficava aberto. Visto no installer-e2e (next-update-cliques, Win 11).
# Rodar: python tests/test_startup_lock.py

import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time

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


def free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    p = s.getsockname()[1]
    s.close()
    return p


# ─────────────────────────────────────────────
# Estatico: ordem do boot em main()
# ─────────────────────────────────────────────
def test_main_order():
    print('\n[1] main(): trava -> checagem -> zumbis -> porta -> solta a trava')
    src = read('gui.py')
    m = re.search(r'\ndef main\(\):.*?(?=\nif __name__)', src, re.DOTALL)
    if not m:
        fail('def main() nao encontrado em gui.py')
        return
    b = m.group(0)
    marcos = ['startup_lock = _acquire_startup_lock()',
              '_check_single_instance(',
              '_cleanup_zombie_processes()',
              'instance_sock = _bind_instance_socket()',
              '_release_startup_lock(startup_lock)\n\n',
              'LanMessengerApp()']
    pos = [b.find(x) for x in marcos]
    check(all(p >= 0 for p in pos), 'todos os passos do boot existem', repr(list(zip(marcos, pos))))
    check(pos == sorted(pos), 'ordem: trava, checagem, zumbis, porta, solta, janela', repr(pos))
    # a saida por "ja existe instancia" solta a trava antes do os._exit
    check(re.search(r'if not _check_single_instance\([^)]*\):\s*\n\s*_release_startup_lock\(startup_lock\)'
                    r'\s*\n\s*os\._exit\(0\)', b) is not None,
          'duplicata solta a trava antes de sair')
    check("send_show='--silent' not in sys.argv[1:]" in b,
          'abertura do logon (--silent) nao faz a janela saltar')
    check('_start_instance_listener(app, instance_sock)' in b,
          'listener usa a porta aberta no inicio do boot')
    i_run = b.find('_update_script_running()')
    i_bump = b.find('bump_update_attempt()')
    check(0 <= i_run < i_bump, 'update em andamento e checado ANTES de contar tentativa',
          f'{i_run} {i_bump}')


def test_mutex_name_matches_updater():
    print('\n[2] mesmo mutex no script de update e no app')
    up = re.search(r"System\.Threading\.Mutex\(\$false, '([^']+)'\)", read('updater.py'))
    gu = re.search(r"OpenMutexW\([^,]+, False, '([^']+)'\)", read('gui.py'))
    check(up is not None and gu is not None and up.group(1) == gu.group(1),
          'Local\\MBChatUpdate igual nos dois lados',
          f'{up and up.group(1)} vs {gu and gu.group(1)}')


# ─────────────────────────────────────────────
# Comportamento da porta (qualquer SO)
# ─────────────────────────────────────────────
class _Root:
    def __init__(self):
        self.calls = []

    def after(self, ms, fn):
        self.calls.append(fn)


class _App:
    def __init__(self):
        self.root = _Root()
        self.opened = []

    def _restore_and_open(self):
        pass

    def _open_from_notification(self, peer):
        self.opened.append(peer)


def test_early_socket():
    print('\n[3] porta aberta cedo: SHOW/OPEN esperam na fila ate a janela existir')
    import gui
    old_port = gui.SINGLE_INSTANCE_PORT
    gui.SINGLE_INSTANCE_PORT = free_port()
    srv = None
    try:
        check(gui._check_single_instance(send_show=False) is True,
              'porta livre: somos a primeira instancia')
        srv = gui._bind_instance_socket()
        check(srv is not None, 'bind da porta de instancia unica')
        # outras aberturas ANTES do listener existir (janela ainda montando)
        check(gui._check_single_instance() is False, 'abertura com a porta aberta ve a instancia (SHOW)')
        check(gui._check_single_instance(send_show=False) is False,
              'abertura --silent tambem ve a instancia (sem SHOW)')
        c = socket.create_connection(('127.0.0.1', gui.SINGLE_INSTANCE_PORT), 1)
        c.sendall(b'OPEN:peer123')
        c.close()
        app = _App()
        gui._start_instance_listener(app, srv)
        t_end = time.time() + 5
        while time.time() < t_end and (len(app.root.calls) < 2):
            time.sleep(0.05)
        time.sleep(0.5)  # da tempo de um 3o comando (nao deveria existir) chegar
        shows = [f for f in app.root.calls if getattr(f, '__name__', '') == '_restore_and_open']
        check(len(shows) == 1, 'exatamente 1 SHOW atendido (o --silent nao manda)',
              repr(app.root.calls))
        for f in app.root.calls:
            if getattr(f, '__name__', '') != '_restore_and_open':
                f()
        check(app.opened == ['peer123'], 'OPEN da notificacao atendido', repr(app.opened))
    finally:
        if srv is not None:
            srv.close()
        gui.SINGLE_INSTANCE_PORT = old_port


# ─────────────────────────────────────────────
# Windows: corrida de verdade entre processos
# ─────────────────────────────────────────────
CHILD = r'''
import os, sys, time
root, mode, go, port, inst, ready = sys.argv[1:7]
sys.path.insert(0, root)
import gui
gui.SINGLE_INSTANCE_PORT = int(port)
sys.argv = [sys.argv[0], '--instance', inst]
open(ready, 'w').close()
while not os.path.exists(go):
    time.sleep(0.002)
if mode == 'novo':
    lock = gui._acquire_startup_lock(timeout_s=20)
    first = gui._check_single_instance(send_show=False)
    srv = gui._bind_instance_socket() if first else None
    gui._release_startup_lock(lock)
else:
    # fluxo antigo: checa, monta a janela (segundos) e so depois abre a porta
    first = gui._check_single_instance(send_show=False)
    time.sleep(2)
    srv = gui._bind_instance_socket() if first else None
print('PASSOU' if first else 'SAIU', flush=True)
if first:
    time.sleep(4)
'''


def _race(mode, n=6):
    tmp = tempfile.mkdtemp(prefix='mbchat_lock_')
    child = os.path.join(tmp, 'child.py')
    with open(child, 'w', encoding='utf-8') as f:
        f.write(CHILD)
    go = os.path.join(tmp, 'go')
    port = str(free_port())
    inst = f'locktest_{os.getpid()}_{mode}'
    procs = []
    for i in range(n):
        ready = os.path.join(tmp, f'ready{i}')
        procs.append((subprocess.Popen([sys.executable, child, root_dir, mode, go, port, inst, ready],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True), ready))
    t_end = time.time() + 120
    while time.time() < t_end and not all(os.path.exists(r) for _, r in procs):
        time.sleep(0.05)
    open(go, 'w').close()
    outs = []
    for p, _ in procs:
        try:
            out, err = p.communicate(timeout=90)
        except subprocess.TimeoutExpired:
            p.kill()
            out, err = p.communicate()
        outs.append((out.strip(), err.strip()[-300:]))
    return outs


def test_race_windows():
    print('\n[4] 6 aberturas no mesmo instante: so 1 passa (Windows, processos reais)')
    if not IS_WIN:
        skip('corrida entre processos (mutex do Windows) -- so no Windows')
        return
    antigo = _race('antigo')
    n_old = sum(1 for o, _ in antigo if o == 'PASSOU')
    # controle: prova que o teste reproduz a corrida do codigo anterior
    check(n_old > 1, f'controle: no fluxo antigo {n_old} de 6 passaram (a corrida existe)', repr(antigo))
    novo = _race('novo')
    n_new = sum(1 for o, _ in novo if o == 'PASSOU')
    n_out = sum(1 for o, _ in novo if o == 'SAIU')
    check(n_new == 1 and n_out == 5, f'com a trava: {n_new} passou, {n_out} sairam', repr(novo))


HOLDER = r'''
import os, sys, time
root, inst, hold, mode = sys.argv[1:5]
sys.path.insert(0, root)
import gui
sys.argv = [sys.argv[0], '--instance', inst]
h = gui._acquire_startup_lock(timeout_s=5)
print('HELD' if h else 'NOLOCK', flush=True)
time.sleep(float(hold))
if mode == 'abandona':
    os._exit(0)
gui._release_startup_lock(h)
'''


def _holder(inst, hold, mode):
    tmp = tempfile.mkdtemp(prefix='mbchat_hold_')
    path = os.path.join(tmp, 'holder.py')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(HOLDER)
    p = subprocess.Popen([sys.executable, path, root_dir, inst, str(hold), mode],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    line = p.stdout.readline().strip()
    return p, line


def test_lock_timeout_and_abandoned():
    print('\n[5] trava presa nao trava o boot; dono que morre libera')
    if not IS_WIN:
        skip('mutex do Windows -- so no Windows')
        return
    import gui
    old_argv = sys.argv
    inst = f'lockhold_{os.getpid()}'
    sys.argv = [old_argv[0], '--instance', inst]
    try:
        p, line = _holder(inst, 6, 'solta')
        check(line == 'HELD', 'outro processo pegou a trava', line)
        t0 = time.time()
        h = gui._acquire_startup_lock(timeout_s=1)
        dt = time.time() - t0
        check(h is None and dt < 4, f'trava presa: desiste em {dt:.1f}s e o boot segue sem ela')
        gui._release_startup_lock(h)
        p.wait(30)
        h = gui._acquire_startup_lock(timeout_s=5)
        check(h is not None, 'trava livre de novo depois que o dono soltou')
        gui._release_startup_lock(h)

        p, line = _holder(inst, 0.5, 'abandona')
        check(line == 'HELD', 'dono vai morrer segurando a trava', line)
        t0 = time.time()
        h = gui._acquire_startup_lock(timeout_s=10)
        dt = time.time() - t0
        check(h is not None and dt < 8, f'dono morreu segurando: trava assumida em {dt:.1f}s')
        gui._release_startup_lock(h)
        p.wait(30)
    finally:
        sys.argv = old_argv


def test_update_script_running():
    print('\n[6] app aberto durante o update: ve o mutex do script e nao dispara outro')
    import gui
    check(gui._update_script_running() is False, 'sem script rodando: False')
    if not IS_WIN:
        skip('mutex do Windows -- so no Windows')
        return
    tmp = tempfile.mkdtemp(prefix='mbchat_upd_')
    ulog = os.path.join(tmp, 'update.log')
    with open(ulog, 'w') as f:
        f.write('Update iniciado\n')
    old_dir = gui.updater._UPDATE_DIR
    gui.updater._UPDATE_DIR = tmp
    ps = subprocess.Popen(['powershell.exe', '-NoProfile', '-Command',
                           "$m = New-Object System.Threading.Mutex($false, 'Local\\MBChatUpdate'); "
                           "$null = $m.WaitOne(0); 'ready'; Start-Sleep 30"],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        line = ps.stdout.readline().strip()
        check(line == 'ready', 'PowerShell segurando o mutex como o script de update', line)
        check(gui._update_script_running() is True, 'script ativo: o boot sai sem mexer em nada')
        velho = time.time() - 20 * 60
        os.utime(ulog, (velho, velho))
        check(gui._update_script_running() is False,
              'valvula: update.log parado ha 20 min = script travado, boot segue')
    finally:
        ps.kill()
        ps.wait(10)
        gui.updater._UPDATE_DIR = old_dir
    time.sleep(0.5)
    check(gui._update_script_running() is False, 'script terminou: mutex some, boot normal')


if __name__ == '__main__':
    test_main_order()
    test_mutex_name_matches_updater()
    test_early_socket()
    test_race_windows()
    test_lock_timeout_and_abandoned()
    test_update_script_running()
    print(f'\n{len(PASS)} PASS, {len(FAIL)} FAIL, {len(SKIP)} SKIP')
    sys.exit(0 if not FAIL else 1)
