# tools/soak/soak_gen.py -- gerador de trafego para o tools/soak/soak_app.py.
# 30 colegas (cada um com seu IP 127.0.0.x), anunciando por UDP a cada 0.5s (30x o
# ritmo real de 15s), respondendo o sync de reunioes como um colega responde, e
# mandando mensagens por TCP real. So fala com 127.0.0.1. Perfis (2o argumento):
#   extremo (padrao): 2 colegas conversando sem parar (1 mensagem/s cada, com
#            "digitando..."), os outros mandando a cada 2s -- ~1.170 mensagens em 8 min
#   dia:     3 conversas no ritmo de gente (1 mensagem a cada ~6s cada) e um colega
#            qualquer mandando a cada 90s -- o dia de quem usa muito o chat
import socket, json, time, struct, threading, random, uuid, sys, os
import tempfile
S = os.path.join(tempfile.gettempdir(), 'mbchat_soak')
duration = float(sys.argv[1])
perfil = sys.argv[2] if len(sys.argv) > 2 else 'extremo'
CONVERSAS = 3 if perfil == 'dia' else 2
PAUSA_CONVERSA = 5.6 if perfil == 'dia' else 0.6
PAUSA_AVULSA = 90 if perfil == 'dia' else 2
info_path = os.path.join(S, 'soak_info.json')
t_end = time.time() + 120
while not os.path.exists(info_path) and time.time() < t_end:
    time.sleep(0.2)
time.sleep(0.5)
info = json.load(open(info_path))
APP_UID, APP_TCP = info['uid'], info['tcp']
N, SINK = 30, 50900
peers = [dict(uid=f'soakpeer{i:02d}', name=f'Colega {i:02d} Conceição', ip=f'127.0.0.{10 + i}')
         for i in range(N)]
by_ip = {p['ip']: p for p in peers}
stop = time.time() + duration
stats = {'ann': 0, 'msg': 0, 'typ': 0, 'sync': 0, 'err': 0}
TEXTOS = ['bom dia! 😀 tudo certo com o fechamento?', 'segue o link https://exemplo.com.br/doc?id=123',
          'ok, obrigado 🤌🙏', 'codigo:\n```python\ndef soma(a, b):\n    return a + b\n```',
          'Atenção: reunião às 15h na sala 2. Não esqueçam do relatório de ' + 'conciliação ' * 8,
          'kkkk 😂😂', 'pode me mandar a planilha de março?']


def sink():
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(('0.0.0.0', SINK))
    srv.listen(50)
    srv.settimeout(1)
    while time.time() < stop:
        try:
            c, _ = srv.accept()
            c.settimeout(2)
            try:
                c.recv(1 << 20)
            except Exception:
                pass
            c.close()
        except Exception:
            pass


def tcp_send(p, payload):
    try:
        s = socket.socket()
        s.bind((p['ip'], 0))
        s.settimeout(5)
        s.connect(('127.0.0.1', APP_TCP))
        data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        s.sendall(struct.pack('!I', len(data)) + data)
        s.close()
        return True
    except Exception:
        stats['err'] += 1
        return False


def announcer():
    socks = {}
    for p in peers:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind((p['ip'], 0))
        socks[p['uid']] = s
    while time.time() < stop:
        for p in peers:
            pkt = {'app': 'mbchat', 'type': 'announce', 'user_id': p['uid'], 'display_name': p['name'],
                   'status': 'online', 'note': 'no escritório ☕', 'avatar_index': 2, 'avatar_data': '',
                   'department': 'Fiscal', 'ramal': '2%03d' % peers.index(p), 'ip': p['ip'], 'ts_ip': '',
                   'hostname': 'PC-' + p['uid'], 'winuser': p['uid'], 'os': 'Windows 10',
                   'version': '1.8.38', 'tcp_port': SINK, 'file_port': SINK, 'time': time.time()}
            try:
                socks[p['uid']].sendto(json.dumps(pkt, ensure_ascii=False).encode('utf-8'), ('127.0.0.1', 50100))
                stats['ann'] += 1
            except Exception:
                stats['err'] += 1
        time.sleep(0.5)


def sync_responder():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(('127.0.0.1', 50950))
    s.settimeout(1)
    while time.time() < stop:
        try:
            data, _ = s.recvfrom(256)
        except Exception:
            continue
        p = by_ip.get(data.decode())
        if p and tcp_send(p, {'type': 'meeting_sync_res', 'from_user': p['uid'], 'bookings': [], 'participants': {}}):
            stats['sync'] += 1


def msg(p, texto):
    return {'type': 'message', 'from_user': p['uid'], 'to_user': APP_UID, 'display_name': p['name'],
            'msg_id': str(uuid.uuid4()), 'content': texto, 'timestamp': time.time()}


def conversa(p):
    time.sleep(12)
    while time.time() < stop:
        if tcp_send(p, {'type': 'typing', 'from_user': p['uid'], 'to_user': APP_UID, 'is_typing': True}):
            stats['typ'] += 1
        time.sleep(0.4)
        if tcp_send(p, msg(p, random.choice(TEXTOS))):
            stats['msg'] += 1
        tcp_send(p, {'type': 'typing', 'from_user': p['uid'], 'to_user': APP_UID, 'is_typing': False})
        time.sleep(PAUSA_CONVERSA)


def avulsas():
    time.sleep(15)
    while time.time() < stop:
        p = random.choice(peers[CONVERSAS:])
        if tcp_send(p, msg(p, random.choice(TEXTOS))):
            stats['msg'] += 1
        time.sleep(PAUSA_AVULSA)


random.seed(7)
ts = [threading.Thread(target=f, daemon=True) for f in (sink, announcer, sync_responder, avulsas)]
ts += [threading.Thread(target=conversa, args=(peers[i],), daemon=True) for i in range(CONVERSAS)]
for t in ts:
    t.start()
while time.time() < stop:
    time.sleep(30)
    print('gen', json.dumps(stats), flush=True)
print('gen FIM', json.dumps(stats), flush=True)
with open(os.path.join(S, 'soak_gen.json'), 'w') as f:
    json.dump(stats, f)
