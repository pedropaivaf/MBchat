# test_undefined_names.py
# "NameError engolido por except" -- nome usado que nao existe, dentro de um
# try/except Exception: nada aparece pro usuario, a funcao so deixa de fazer
# o que devia. Ja aconteceu varias vezes (MCAST_GRP no relay VPN da v1.8.12,
# "ep" no seletor de emoji do recado) e este teste pega a classe inteira:
#   1. Guarda geral: todo nome GLOBAL usado por qualquer funcao dos modulos
#      do app precisa existir no modulo (import, atribuicao, def/class) ou
#      nos builtins -- analisado pelo bytecode, sem executar nada.
#   2. Transferencias: duplo clique num arquivo abre o Explorer com o arquivo
#      SELECIONADO (faltava importar subprocess: so a pasta abria).
#   3. Lembrete compartilhado: quando o criador cancela, TODOS os convidados
#      recebem o cancelamento e o lembrete some deles (faltava importar json:
#      a lista de convidados virava vazia e ninguem era avisado).
# Rodar: python tests/test_undefined_names.py

import os
import re
import sys
import ast
import dis
import json
import time
import types
import socket
import struct
import builtins
import tempfile
import threading

here = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(here) if os.path.basename(here) == 'tests' else here
sys.path.insert(0, root_dir)

try:
    sys.stdout.reconfigure(errors='backslashreplace')
except Exception:
    pass

# Nunca abrir o banco de producao
import database
_TMP = tempfile.mkdtemp(prefix='mbchat_test_names_')
_DB_PATH = [os.path.join(_TMP, 'a.db')]
database.get_db_path = lambda *a, **k: _DB_PATH[0]

PASS, FAIL = [], []


def ok(msg):
    PASS.append(msg)
    print(f'  PASS  {msg}')


def fail(msg, detail=''):
    FAIL.append(msg)
    print(f'  FAIL  {msg}' + (f': {detail}' if detail else ''))


def check(cond, msg, detail=''):
    ok(msg) if cond else fail(msg, detail)


# ─────────────────────────────────────────────
# 1 — Guarda geral de nomes inexistentes
# ─────────────────────────────────────────────
MODULES = ['gui.py', 'messenger.py', 'network.py', 'database.py', 'updater.py',
           'audio_recorder.py', 'meeting_gui.py', 'tools/theme_builder.py']

# Conhecidos e aceitos (com motivo). Nao acrescentar sem motivo real.
ALLOWED = {
    ('gui.py', '_setup_autostart', 'python'),  # ramos Linux/Mac; app e Windows-only
}


def _module_names(tree):
    # Nomes que existem no modulo em runtime: tudo que o nivel de modulo
    # vincula (inclusive dentro de if/try, ex. imports opcionais HAS_*) +
    # nomes declarados "global" e atribuidos dentro de funcoes.
    names = set()

    def bind_target(t):
        if isinstance(t, ast.Name):
            names.add(t.id)
        elif isinstance(t, (ast.Tuple, ast.List)):
            for e in t.elts:
                bind_target(e)

    def visit(nodes):
        for n in nodes:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(n.name)
                continue
            if isinstance(n, (ast.Import, ast.ImportFrom)):
                for a in n.names:
                    names.add(a.asname or a.name.split('.')[0])
            elif isinstance(n, (ast.Assign,)):
                for t in n.targets:
                    bind_target(t)
            elif isinstance(n, (ast.AnnAssign, ast.AugAssign)):
                bind_target(n.target)
            elif isinstance(n, (ast.For, ast.AsyncFor)):
                bind_target(n.target)
            elif isinstance(n, (ast.With, ast.AsyncWith)):
                for it in n.items:
                    if it.optional_vars is not None:
                        bind_target(it.optional_vars)
            elif isinstance(n, ast.Try):
                for h in n.handlers:
                    if h.name:
                        names.add(h.name)
            for field in ('body', 'orelse', 'finalbody', 'handlers'):
                sub = getattr(n, field, None)
                if isinstance(sub, list):
                    visit([s for s in sub if isinstance(s, ast.AST)])
    visit(tree.body)
    for n in ast.walk(tree):
        if isinstance(n, ast.Global):
            names.update(n.names)
    return names


def _global_loads(code, path=''):
    # (qualname, nome) de cada LOAD_GLOBAL, descendo nas funcoes internas
    out = []
    qual = getattr(code, 'co_qualname', code.co_name)
    for ins in dis.get_instructions(code):
        if ins.opname == 'LOAD_GLOBAL' and isinstance(ins.argval, str):
            out.append((qual, ins.argval))
    for c in code.co_consts:
        if isinstance(c, types.CodeType):
            out.extend(_global_loads(c))
    return out


def test_no_undefined_names():
    print('\n[1] Nenhum nome inexistente nos modulos do app')
    total_refs = 0
    for rel in MODULES:
        path = os.path.join(root_dir, rel)
        with open(path, encoding='utf-8') as f:
            src = f.read()
        tree = ast.parse(src)
        # + nomes que todo modulo tem em runtime (__file__, __name__...)
        known = _module_names(tree) | set(dir(builtins)) | set(vars(types.ModuleType('m'))) | {'__file__', '__builtins__', '__cached__'}
        code = compile(src, path, 'exec')
        refs = _global_loads(code)
        total_refs += len(refs)
        bad = sorted({(q, n) for q, n in refs if n not in known
                      and (rel, q.rsplit('.', 1)[-1], n) not in ALLOWED})
        if bad:
            fail(f'{rel}: nome usado que nao existe',
                 ', '.join(f'{n} em {q}' for q, n in bad[:8]))
        else:
            ok(f'{rel}: todo nome global usado existe')
    ok(f'({total_refs} referencias verificadas)')


# ─────────────────────────────────────────────
# 2 — Transferencias: Explorer com o arquivo selecionado
# ─────────────────────────────────────────────
def test_open_entry_file_selects_file():
    print('\n[2] Transferencias: duplo clique abre o Explorer com o arquivo marcado')
    import gui
    import subprocess
    calls, folders = [], []
    orig_popen = subprocess.Popen
    had_startfile = hasattr(os, 'startfile')
    orig_startfile = getattr(os, 'startfile', None)
    subprocess.Popen = lambda cmd, *a, **k: calls.append(cmd)
    os.startfile = lambda p, *a, **k: folders.append(p)
    try:
        f = os.path.join(_TMP, 'relatorio final.pdf')
        with open(f, 'w') as fh:
            fh.write('x')

        class _Row:
            _entry = {'filepath': f, 'filename': 'relatorio final.pdf',
                      'direction': 'receive'}
        gui.FileTransfersWindow._open_entry_file(object(), _Row())
        exp = f'explorer /select,"{os.path.normpath(f)}"'
        check(calls == [exp], 'chama explorer /select com o caminho do arquivo', repr(calls))
        check(folders == [], 'nao cai no fallback de abrir so a pasta', repr(folders))
    finally:
        subprocess.Popen = orig_popen
        if had_startfile:
            os.startfile = orig_startfile
        else:
            del os.startfile


# ─────────────────────────────────────────────
# 3 — Lembrete compartilhado: cancelamento chega aos convidados
# ─────────────────────────────────────────────
def _start_sink():
    got = []
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(('127.0.0.1', 0))
    srv.listen(32)

    def loop():
        while True:
            try:
                c, _ = srv.accept()
            except OSError:
                return
            try:
                c.settimeout(5)
                hdr = b''
                while len(hdr) < 4:
                    ch = c.recv(4 - len(hdr))
                    if not ch:
                        break
                    hdr += ch
                if len(hdr) == 4:
                    n = struct.unpack('!I', hdr)[0]
                    data = b''
                    while len(data) < n:
                        ch = c.recv(n - len(data))
                        if not ch:
                            break
                        data += ch
                    got.append(json.loads(data.decode('utf-8')))
            except Exception:
                pass
            finally:
                c.close()
    threading.Thread(target=loop, daemon=True).start()
    return srv.getsockname()[1], got


def _wait(pred, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.05)
    return pred()


def test_shared_reminder_cancel_reaches_invited():
    print('\n[3] Lembrete compartilhado: cancelamento chega a todos os convidados')
    import messenger
    port, got = _start_sink()
    messenger.TCP_PORT = port  # tudo que sai vai pro receptor local

    _DB_PATH[0] = os.path.join(_TMP, 'criador.db')
    creator = messenger.Messenger(display_name='Criador')
    creator.user_id = 'criador_uid'
    _DB_PATH[0] = os.path.join(_TMP, 'convidado.db')
    guest = messenger.Messenger(display_name='Convidado')
    guest.user_id = 'convidado_uid'
    cancels_cb = []
    guest.on_reminder_cancel = lambda ext: cancels_cb.append(ext)

    for uid, name in (('convidado_uid', 'Convidado'), ('convidado2_uid', 'Convidado 2')):
        creator.db.upsert_contact(uid, name, '127.0.0.1')
    guest.db.upsert_contact('criador_uid', 'Criador', '127.0.0.1')

    ext = creator.create_shared_reminder('Entregar DCTF', time.time() + 3600,
                                         ['convidado_uid', 'convidado2_uid'])
    _wait(lambda: sum(1 for p in got if p.get('type') == 'reminder_invite') >= 2)
    invites = [p for p in got if p.get('type') == 'reminder_invite']
    check(len(invites) == 2, 'convite saiu para os 2 convidados', str(len(invites)))

    # convidado recebe o convite (caminho real de recebimento)
    guest._on_tcp_message(invites[0], ('127.0.0.1', 50000))
    check(guest.db.get_reminder_by_external_id(ext) is not None,
          'convidado tem o lembrete depois do convite')

    creator.cancel_shared_reminder(ext)
    _wait(lambda: sum(1 for p in got if p.get('type') == 'reminder_cancel') >= 2)
    cancels = [p for p in got if p.get('type') == 'reminder_cancel']
    check(len(cancels) == 2 and all(p.get('external_id') == ext for p in cancels),
          'cancelamento saiu para os 2 convidados (antes: para nenhum)', str(len(cancels)))
    check(creator.db.get_reminder_by_external_id(ext) is None,
          'lembrete removido do lado de quem criou')

    if cancels:
        guest._on_tcp_message(cancels[0], ('127.0.0.1', 50000))
    check(guest.db.get_reminder_by_external_id(ext) is None,
          'lembrete removido do lado do convidado (nao dispara mais)')
    check(cancels_cb == [ext], 'tela do convidado e avisada do cancelamento', repr(cancels_cb))


if __name__ == '__main__':
    test_no_undefined_names()
    test_open_entry_file_selects_file()
    test_shared_reminder_cancel_reaches_invited()
    print(f'\n{len(PASS)} PASS, {len(FAIL)} FAIL')
    print(f'{len(PASS)} passou {len(FAIL)} falhou')  # resumo lido pelo gate
    sys.exit(0 if not FAIL else 1)
