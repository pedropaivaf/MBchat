# test_memory_leak_fixes.py
# Trava as correcoes de RAM/desempenho do app aberto por muitas horas:
#
# 1. _safe/_post: callbacks de rede vindos de threads de vida curta NAO podem
#    chamar o Tk (nem root.after) de dentro da thread -- cada thread que toca
#    o Tk vaza ~16KB que nunca voltam (medido: 20 mil eventos de rede no app
#    real = +321MB antes, +0MB depois). Cada mensagem TCP recebida roda numa
#    thread nova, entao a RAM crescia sem parar (130MB -> 600MB/1GB).
# 2. Sync de reunioes: rodava a CADA announce (15s por peer). Agora so ao
#    (re)conectar ou no maximo a cada MEETING_SYNC_INTERVAL_S.
# 3. Announce so grava o contato no banco se algo mudou (ou last_seen velho),
#    numa transacao so -- antes eram 2-3 commits (fsync) por announce.
# 4. get_local_ip() com cache curto -- antes abria uma conexao SQLite nova a
#    cada pacote UDP recebido.
# Rodar: python tests/test_memory_leak_fixes.py

import os
import sys
import time
import queue
import tempfile
import threading

here = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(here) if os.path.basename(here) == 'tests' else here
sys.path.insert(0, root_dir)

# Nunca abrir o banco de producao (%APPDATA%\.mbchat\mbchat.db)
import database
_TMP_DIR = tempfile.mkdtemp(prefix='mbchat_test_mem_')
_TMP_DB = os.path.join(_TMP_DIR, 'test.db')
database.get_db_path = lambda *a, **k: _TMP_DB

import tkinter as tk

PASS, FAIL = [], []


def ok(msg):
    PASS.append(msg)
    print(f'  PASS  {msg}')


def fail(msg, detail=''):
    FAIL.append(msg)
    print(f'  FAIL  {msg}' + (f': {detail}' if detail else ''))


def rss_mb():
    # RSS/working set do proprio processo, sem depender de psutil
    try:
        import psutil
        return psutil.Process().memory_info().rss / 1e6
    except ImportError:
        pass
    if sys.platform == 'win32':
        try:
            import ctypes
            from ctypes import wintypes

            class PMC(ctypes.Structure):
                _fields_ = [('cb', wintypes.DWORD),
                            ('PageFaultCount', wintypes.DWORD),
                            ('PeakWorkingSetSize', ctypes.c_size_t),
                            ('WorkingSetSize', ctypes.c_size_t),
                            ('QuotaPeakPagedPoolUsage', ctypes.c_size_t),
                            ('QuotaPagedPoolUsage', ctypes.c_size_t),
                            ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t),
                            ('QuotaNonPagedPoolUsage', ctypes.c_size_t),
                            ('PagefileUsage', ctypes.c_size_t),
                            ('PeakPagefileUsage', ctypes.c_size_t)]
            pmc = PMC()
            pmc.cb = ctypes.sizeof(PMC)
            k32 = ctypes.windll.kernel32
            k32.GetCurrentProcess.restype = wintypes.HANDLE
            k32.K32GetProcessMemoryInfo.argtypes = [
                wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
            k32.K32GetProcessMemoryInfo.restype = wintypes.BOOL
            if k32.K32GetProcessMemoryInfo(
                    k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb):
                return pmc.WorkingSetSize / 1e6
        except Exception:
            pass
        return None
    try:
        with open('/proc/self/statm') as f:
            return int(f.read().split()[1]) * os.sysconf('SC_PAGE_SIZE') / 1e6
    except Exception:
        return None


# ─────────────────────────────────────────────
# 1 — _safe/_post: fila drenada pela main thread
# ─────────────────────────────────────────────
def test_ui_queue():
    print('\n[1] Callbacks de threads de rede passam pela fila (sem tocar o Tk na thread)')
    import gui

    # App minimo: so o que _safe/_post/_drain_ui_queue usam
    app = gui.LanMessengerApp.__new__(gui.LanMessengerApp)
    app.root = tk.Tk()
    app.root.withdraw()
    reported = []
    app.root.report_callback_exception = lambda *exc: reported.append(exc[1])
    app._ui_queue = queue.Queue()
    app.root.after(gui.UI_QUEUE_POLL_MS, app._drain_ui_queue)

    N = 5000
    main_ident = threading.get_ident()
    got = []
    wrong_thread = []
    kw_ok = []

    def on_event(i):
        if threading.get_ident() != main_ident:
            wrong_thread.append(i)
        got.append(i)

    def on_kw(a, b=None):
        kw_ok.append((a, b))

    def boom():
        raise ValueError('callback com erro')

    cb = app._safe(on_event)
    cb_kw = app._safe(on_kw)
    result = {}

    def spawner():
        time.sleep(0.3)
        start = rss_mb()
        for i in range(N):
            t = threading.Thread(target=cb, args=(i,), daemon=True)
            t.start()
            t.join()
        app._safe(boom)()
        cb_kw(1, b=2)
        deadline = time.time() + 60
        while (len(got) < N or not kw_ok) and time.time() < deadline:
            time.sleep(0.05)
        time.sleep(0.3)
        end = rss_mb()
        result['delta'] = (end - start) if (start is not None and end is not None) else None
        app.root.after(0, app.root.quit)

    threading.Thread(target=spawner, daemon=True).start()
    app.root.mainloop()

    if len(got) == N:
        ok(f'{N} callbacks de {N} threads curtas executados')
    else:
        fail(f'callbacks executados: {len(got)} de {N}')
    if got == sorted(got):
        ok('ordem de chegada preservada (FIFO)')
    else:
        fail('ordem dos callbacks mudou')
    if not wrong_thread:
        ok('todos os callbacks rodaram na main thread')
    else:
        fail(f'{len(wrong_thread)} callbacks fora da main thread')
    if kw_ok == [(1, 2)]:
        ok('kwargs repassados ao callback')
    else:
        fail('kwargs nao repassados', repr(kw_ok))
    if reported and isinstance(reported[0], ValueError):
        ok('excecao de um callback vai pro report_callback_exception e nao para a fila')
    else:
        fail('excecao do callback nao foi reportada', repr(reported))

    delta = result.get('delta')
    if delta is None:
        ok('(medicao de RAM indisponivel neste ambiente -- pulado)')
    elif delta < 20:
        ok(f'RAM estavel apos {N} threads: +{delta:.1f}MB (antes do fix: ~16KB por thread)')
    else:
        fail(f'RAM cresceu +{delta:.1f}MB com {N} threads -- vazamento voltou?')

    app.root.destroy()


def test_no_tk_calls_from_worker_threads():
    print('\n[2] Guarda estatica: _safe e as threads de envio nao chamam o Tk')
    with open(os.path.join(root_dir, 'gui.py'), encoding='utf-8') as f:
        src = f.read()
    i = src.find('    def _safe(self, func):')
    body = src[i:src.find('\n    def ', i + 10)]
    if i >= 0 and 'after(' not in body and '_post(' in body:
        ok('_safe so enfileira (sem root.after dentro da thread)')
    else:
        fail('_safe voltou a chamar o Tk a partir da thread de rede')

    workers = [
        'self.messenger.send_message(self.peer_id, cnt, rid, msg_id=lid)',
        'self.messenger.send_audio(self.peer_id, wav_bytes)',
        'self.messenger.send_image(self.peer_id, image_bytes)',
        'self.app.messenger.create_poll(self.group_id, question, options)',
        'self.app.messenger.vote_poll(self.group_id, poll_id, option_index)',
        'self.app.messenger.send_group_audio(self.group_id, wav_bytes)',
        'self.app.messenger.send_group_image(self.group_id, image_bytes)',
    ]
    for needle in workers:
        j = src.find(needle)
        chunk = src[j:j + 300].split('threading.Thread(')[0]
        if j < 0:
            fail(f'trecho nao encontrado: {needle}')
        elif 'self.after(' in chunk or 'root.after(' in chunk:
            fail(f'thread de envio chama o Tk direto: {needle}')
        elif 'self.app._post(' in chunk:
            ok(f'usa _post: {needle.split("(")[0]}')
        else:
            fail(f'thread de envio sem _post: {needle}')


# ─────────────────────────────────────────────
# 3 — Sync de reunioes limitado por peer
# ─────────────────────────────────────────────
def test_meeting_sync_throttle():
    print('\n[3] Sync de reunioes: na (re)conexao e no maximo a cada intervalo')
    import messenger

    m = messenger.Messenger.__new__(messenger.Messenger)
    m._meeting_sync_at = {}

    class _DB:
        def set_contact_offline(self, uid):
            pass
    m.db = _DB()
    m.on_user_lost = None

    if m._should_sync_meetings('u1', '192.168.0.5'):
        ok('primeiro announce do peer sincroniza')
    else:
        fail('primeiro announce nao sincronizou')
    if not m._should_sync_meetings('u1', '192.168.0.5'):
        ok('announce seguinte (mesmo IP, dentro do intervalo) nao sincroniza')
    else:
        fail('sincronizou de novo a cada announce')
    if m._should_sync_meetings('u2', '192.168.0.6'):
        ok('outro peer tem controle proprio')
    else:
        fail('peer diferente bloqueado')
    if m._should_sync_meetings('u1', '10.0.0.9'):
        ok('IP novo do peer sincroniza na hora')
    else:
        fail('troca de IP nao sincronizou')
    m._on_peer_lost('u1', {})
    if m._should_sync_meetings('u1', '10.0.0.9'):
        ok('reconexao (depois de perdido) sincroniza na hora')
    else:
        fail('reconexao nao sincronizou')
    m._meeting_sync_at['u2'] = ('192.168.0.6', time.time() - messenger.MEETING_SYNC_INTERVAL_S - 1)
    if m._should_sync_meetings('u2', '192.168.0.6'):
        ok('passado o intervalo, sincroniza de novo')
    else:
        fail('nao sincronizou depois do intervalo')


# ─────────────────────────────────────────────
# 4 — Announce so grava contato quando algo mudou
# ─────────────────────────────────────────────
def test_announce_persistence():
    print('\n[4] Announce grava contato so quando algo mudou (1 transacao)')
    import messenger

    db = database.Database(db_path=os.path.join(_TMP_DIR, 'announce.db'))
    m = messenger.Messenger.__new__(messenger.Messenger)
    m.db = db
    info = {
        'display_name': 'Ana', 'ip': '192.168.0.20', 'hostname': 'PC-ANA',
        'os': 'Windows 11', 'status': 'online', 'note': 'oi',
        'avatar_index': 3, 'avatar_data': 'abc', 'winuser': 'ana',
        'department': 'Fiscal', 'ramal': '1234',
    }

    def changes(fn):
        before = db.conn.total_changes
        fn()
        return db.conn.total_changes - before

    n = changes(lambda: m._persist_announced_contact('ana_uid', info))
    c = db.get_contact('ana_uid')
    if n > 0 and c and c['department'] == 'Fiscal' and c['ramal'] == '1234' \
            and c['note'] == 'oi' and c['winuser'] == 'ana':
        ok('primeiro announce grava contato + setor + ramal')
    else:
        fail('primeiro announce nao gravou tudo', repr(c))
    if not db.conn.in_transaction:
        ok('transacao fechada (commit feito)')
    else:
        fail('transacao ficou aberta')

    n = changes(lambda: m._persist_announced_contact('ana_uid', dict(info)))
    if n == 0:
        ok('announce identico logo em seguida nao grava nada')
    else:
        fail(f'announce identico gravou {n} linhas')

    n = changes(lambda: m._persist_announced_contact('ana_uid', dict(info, note='almoco')))
    if n > 0 and db.get_contact('ana_uid')['note'] == 'almoco':
        ok('nota mudou -> grava na hora')
    else:
        fail('mudanca de nota nao gravou')

    n = changes(lambda: m._persist_announced_contact('ana_uid', dict(info, note='almoco', department='')))
    if n == 0 and db.get_contact('ana_uid')['department'] == 'Fiscal':
        ok('announce sem setor nao apaga o setor salvo (igual antes)')
    else:
        fail('setor vazio mexeu no banco', repr(db.get_contact('ana_uid')['department']))

    db.set_contact_offline('ana_uid')
    n = changes(lambda: m._persist_announced_contact('ana_uid', dict(info, note='almoco')))
    if n > 0 and db.get_contact('ana_uid')['status'] == 'online':
        ok('contato marcado offline no banco volta a online no announce')
    else:
        fail('status offline no banco nao foi corrigido')

    db.conn.execute("UPDATE contacts SET last_seen=? WHERE user_id='ana_uid'",
                    (time.time() - messenger.CONTACT_LAST_SEEN_REFRESH_S - 5,))
    db.conn.commit()
    n = changes(lambda: m._persist_announced_contact('ana_uid', dict(info, note='almoco')))
    if n > 0 and time.time() - db.get_contact('ana_uid')['last_seen'] < 5:
        ok('last_seen velho e renovado mesmo sem outra mudanca')
    else:
        fail('last_seen nao foi renovado')

    db.delete_contact('ana_uid')
    n = changes(lambda: m._persist_announced_contact('ana_uid', dict(info, note='almoco')))
    if n > 0 and db.get_contact('ana_uid'):
        ok('contato excluido do banco e recriado no announce')
    else:
        fail('contato excluido nao foi recriado')


# ─────────────────────────────────────────────
# 5 — get_local_ip com cache curto
# ─────────────────────────────────────────────
def test_local_ip_cache():
    print('\n[5] get_local_ip() com cache curto (sem SQLite/sockets a cada pacote)')
    import network

    calls = []
    orig = network._get_local_ip_uncached
    network._get_local_ip_uncached = lambda: calls.append(1) or '192.168.0.77'
    network._local_ip_cache = (0.0, None)
    try:
        ips = [network.get_local_ip() for _ in range(500)]
        if len(calls) == 1 and set(ips) == {'192.168.0.77'}:
            ok('500 chamadas seguidas = 1 deteccao real')
        else:
            fail(f'deteccoes reais: {len(calls)}')
        ts, ip = network._local_ip_cache
        network._local_ip_cache = (ts - network._LOCAL_IP_TTL - 1, ip)
        network.get_local_ip()
        if len(calls) == 2:
            ok('cache expirado detecta de novo (troca de rede continua detectada)')
        else:
            fail('cache nao expirou')
    finally:
        network._get_local_ip_uncached = orig
        network._local_ip_cache = (0.0, None)


if __name__ == '__main__':
    test_ui_queue()
    test_no_tk_calls_from_worker_threads()
    test_meeting_sync_throttle()
    test_announce_persistence()
    test_local_ip_cache()
    print(f'\n{len(PASS)} PASS, {len(FAIL)} FAIL')
    sys.exit(0 if not FAIL else 1)
