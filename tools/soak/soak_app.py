# tools/soak/soak_app.py -- medidor de memoria do MB Chat REAL sob trafego de rede.
# Uso (feche o MB Chat antes; precisa das portas UDP 50100 e TCP 50101 livres):
#   python tools/soak/run_soak.py [SEGUNDOS] [--repo CAMINHO] [--close-at SEGUNDOS]
# Sobe o app do repositorio com dados numa pasta temporaria (nunca toca no
# %APPDATA% de verdade), abre 2 chats quando os colegas aparecem e mede a cada 15s,
# na main thread: RSS, threads, imagens e timers do Tk, widgets e objetos Python.
# A unica troca: o pedido de sync de reunioes vai para o gerador (que responde como o
# colega responderia), em vez de 127.0.0.x:50101 (que seria o proprio app).
import sys, os, time, json, socket, threading, gc, shutil
import tempfile, types
S = os.path.join(tempfile.gettempdir(), 'mbchat_soak')
os.makedirs(S, exist_ok=True)
repo, tag, duration = sys.argv[1], sys.argv[2], float(sys.argv[3])
close_at = float(sys.argv[4]) if len(sys.argv) > 4 else None
closed = {'done': False}
home = os.path.join(S, 'home_' + tag)
shutil.rmtree(home, ignore_errors=True)
os.makedirs(home)
os.environ['HOME'] = home
os.environ['APPDATA'] = home
if sys.platform != 'win32':
    sys.modules['winsound'] = types.SimpleNamespace(
        SND_FILENAME=0x20000, SND_ASYNC=1, SND_MEMORY=4, SND_PURGE=0x40, SND_NODEFAULT=2,
        PlaySound=lambda *a, **k: None, Beep=lambda *a, **k: None,
        MessageBeep=lambda *a, **k: None, MB_OK=0)
sys.argv = ['gui.py', '--instance', 'soak']
sys.path.insert(0, repo)
try:
    import psutil
except ImportError:
    print('Falta o psutil: pip install psutil')
    sys.exit(2)
proc = psutil.Process()
import gui
app = gui.LanMessengerApp()
ctrl = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)


def hook():
    m = getattr(app, 'messenger', None)
    if m is None or getattr(m, 'tcp_server', None) is None or not getattr(m.tcp_server, 'port', None):
        app.root.after(200, hook)
        return
    m.sync_meetings_with_peer = lambda ip: ctrl.sendto(ip.encode(), ('127.0.0.1', 50950))
    with open(os.path.join(S, 'soak_info.json'), 'w') as f:
        json.dump({'uid': m.user_id, 'tcp': m.tcp_server.port}, f)
    print('hook ok', m.user_id, m.tcp_server.port, flush=True)


app.root.after(200, hook)
t0 = time.time()
rows = []
opened = set()


def nwidgets(w):
    n = 1
    for c in w.winfo_children():
        n += nwidgets(c)
    return n


def sample():
    el = time.time() - t0
    peers = app.messenger.discovery.peers if getattr(app, 'messenger', None) else {}
    for uid in ('soakpeer00', 'soakpeer01'):
        if uid in peers and uid not in opened:
            try:
                app._open_chat(uid)
                opened.add(uid)
            except Exception as e:
                print('open_chat falhou', e, flush=True)
    if close_at is not None and el >= close_at and not closed['done']:
        for cw in list(app.chat_windows.values()):
            try:
                cw._on_close()
            except Exception as e:
                print('close falhou', e, flush=True)
        closed['done'] = True
        gc.collect()
        print('JANELAS FECHADAS', flush=True)
    lines = []
    for cw in list(app.chat_windows.values()):
        try:
            lines.append(int(cw.chat_text.index('end-1c').split('.')[0]))
        except Exception:
            pass
    row = dict(t=round(el), rss=round(proc.memory_info().rss / 1e6, 1),
               threads=threading.active_count(),
               images=len(app.root.tk.call('image', 'names')),
               afters=len(app.root.tk.call('after', 'info')),
               widgets=nwidgets(app.root), peers=len(peers),
               gc=len(gc.get_objects()), chats=len(app.chat_windows), chat_lines=lines)
    rows.append(row)
    print(json.dumps(row), flush=True)
    if el >= duration:
        with open(os.path.join(S, f'soak_{tag}.json'), 'w') as f:
            json.dump(rows, f)
        os._exit(0)
    app.root.after(15000, sample)


app.root.after(8000, sample)
app.root.mainloop()
