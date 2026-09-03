# Script auxiliar para testes do MB Chat: cria um peer virtual ("Bot de Teste") na rede local.
# O Bot anuncia sua presenca via UDP e responde automaticamente mensagens recebidas via TCP.
# Uso: python tools/mock_peer.py [--index N]  -- N=1 (padrao) e o "Bot de Teste" original;
# N=2,3,4... gera bots adicionais com uid/nome/porta proprios, pra testar grupos com varios
# participantes ao mesmo tempo na mesma maquina.
import argparse
import socket
import struct
import json
import time
import threading
import uuid

_parser = argparse.ArgumentParser()
_parser.add_argument('--index', type=int, default=1,
                     help='Numero do bot: 1=Bot de Teste (padrao), 2+=bots adicionais')
_parser.add_argument('--target', default='',
                     help='IP:UDP_PORT[:TCP_PORT] do app alvo. Use quando o discovery '
                          'normal falha porque o SO reservou a faixa 50100+ (Hyper-V/'
                          'WinNAT). Ex: 127.0.0.1:62732:52754')
_parser.add_argument('--spam', type=float, default=0.0,
                     help='Manda uma mensagem nao solicitada a cada N segundos (0=off). '
                          'Serve pra testar toast/flash/render de mensagem recebida.')
_args = _parser.parse_args()

UDP_PORT = 50100
MULTICAST_GROUP = '239.255.100.200'

# --target IP:UDP[:TCP] -- rota direta pro app quando o discovery multicast/
# broadcast nao chega (porta 50100 na faixa de exclusao do SO). Com isso o bot
# anuncia direto no socket de recepcao do app e responde direto na porta TCP
# real dele, sem depender de aprender nada via UDP.
TARGET_IP = TARGET_UDP = TARGET_TCP = None
if _args.target:
    _tp = _args.target.split(':')
    TARGET_IP = _tp[0]
    TARGET_UDP = int(_tp[1]) if len(_tp) > 1 and _tp[1] else UDP_PORT
    TARGET_TCP = int(_tp[2]) if len(_tp) > 2 and _tp[2] else None
if _args.index <= 1:
    MOCK_UID = 'mock_peer_bot_teste'
    MOCK_NAME = 'Bot de Teste'
    MOCK_TCP_PORT = 50350
else:
    MOCK_UID = f'mock_peer_bot_teste_{_args.index}'
    MOCK_NAME = f'Bot de Teste {_args.index}'
    MOCK_TCP_PORT = 50350 + (_args.index - 1) * 10


def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'


# Grupos que o bot conhece: group_id -> {'name', 'group_type', 'members': [...]}.
# Populado via group_invite; usado pra saber pra quem mandar group_message
# (o protocolo de grupo do MBChat e mesh: cada membro manda TCP unicast
# direto pra todo mundo, nao existe broadcast/relay central).
KNOWN_GROUPS = {}
_groups_lock = threading.Lock()

# Peers descobertos via anuncio UDP: uid -> {'ip', 'tcp_port'}. Necessario
# porque o app real (e este bot) pode cair em porta de fallback quando
# TCP_PORT=50101 esta ocupada/excluida pelo SO (ex.: reserva Hyper-V/WinNAT,
# documentada no DECISIONS.md do projeto) -- sem isso o bot responderia
# sempre na porta fixa 50101 e a resposta nunca chegaria em quem pediu.
KNOWN_PEERS = {}
_peers_lock = threading.Lock()


def listen_announces():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    except (AttributeError, OSError):
        pass
    try:
        sock.bind(('0.0.0.0', UDP_PORT))
    except OSError as e:
        print(f"[Bot] AVISO: nao consegui escutar UDP {UDP_PORT} pra descobrir "
              f"a porta real dos outros peers ({e}). Respostas vao cair no "
              f"fallback fixo 50101, que pode estar indisponivel.")
        return
    print(f"[Bot] Escutando anuncios UDP em {UDP_PORT} pra aprender a porta real dos peers...")
    while True:
        try:
            data, addr = sock.recvfrom(65536)
            pkt = json.loads(data.decode('utf-8'))
            if pkt.get('app') != 'mbchat' or pkt.get('type') != 'announce':
                continue
            uid = pkt.get('user_id')
            if not uid or uid == MOCK_UID:
                continue
            tcp_port = pkt.get('tcp_port')
            if not tcp_port:
                continue
            with _peers_lock:
                is_new = uid not in KNOWN_PEERS or KNOWN_PEERS[uid].get('tcp_port') != tcp_port
                KNOWN_PEERS[uid] = {'ip': pkt.get('ip') or addr[0], 'tcp_port': tcp_port}
            if is_new:
                print(f"[Bot] Peer descoberto: {uid} em {pkt.get('ip') or addr[0]}:{tcp_port}")
        except json.JSONDecodeError:
            continue
        except Exception as e:
            print(f"[Bot] Erro no listener de anuncios: {e}")


def _reply_target(uid, fallback_ip):
    # --target manda tudo direto pro app, sem depender de aprender porta via UDP.
    if TARGET_TCP:
        return TARGET_IP, TARGET_TCP
    # Porta real do peer (aprendida via UDP) -- fallback pra 50101 (o
    # default historico) so se nunca vimos o anuncio dele.
    with _peers_lock:
        peer = KNOWN_PEERS.get(uid)
    if peer and peer.get('tcp_port'):
        return peer.get('ip') or fallback_ip, peer['tcp_port']
    return fallback_ip, 50101


def _tcp_send(uid, fallback_ip, payload):
    ip, port = _reply_target(uid, fallback_ip)
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5.0)
        sock.connect((ip, port))
        data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        sock.sendall(struct.pack('!I', len(data)) + data)
        sock.close()
        print(f"[Bot] Enviado pra {uid} ({ip}:{port})")
        return True
    except Exception as e:
        print(f"[Bot] Erro ao enviar pra {uid} ({ip}:{port}): {e}")
        return False


def send_group_message_to_all(group_id, content):
    with _groups_lock:
        group = KNOWN_GROUPS.get(group_id)
    if not group:
        print(f"[Bot] Grupo {group_id} desconhecido -- nao consigo mandar mensagem")
        return
    msg_id = str(uuid.uuid4())
    for member in group['members']:
        uid = member.get('uid')
        if uid == MOCK_UID or not member.get('ip'):
            continue
        payload = {
            'type': 'group_message',
            'to_user': uid,
            'from_user': MOCK_UID,
            'display_name': '🤖 ' + MOCK_NAME,
            'group_id': group_id,
            'group_name': group.get('name', 'Grupo'),
            'group_type': group.get('group_type', 'temp'),
            'msg_id': msg_id,
            'content': content,
            'timestamp': time.time(),
        }
        _tcp_send(uid, member['ip'], payload)


def send_announces():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    try:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    except Exception:
        pass

    local_ip = get_local_ip()
    # Com --target o app vai conectar de volta no IP que anunciamos; usar o
    # mesmo IP do alvo (ex: 127.0.0.1) garante que a resposta chega no bot.
    if TARGET_IP:
        local_ip = TARGET_IP
    parts = local_ip.split('.')
    subnet_bcast = f"{parts[0]}.{parts[1]}.{parts[2]}.255" if len(parts) == 4 else '255.255.255.255'

    data = {
        'app': 'mbchat',
        'type': 'announce',
        'user_id': MOCK_UID,
        'display_name': '🤖 ' + MOCK_NAME,
        'status': 'online',
        'note': 'Bot de Teste Online 🤌',
        'avatar_index': 3,
        'avatar_data': '',
        'department': 'TI / Testes',
        'ramal': '9999',
        'ip': local_ip,
        'hostname': 'TEST-BOT-PC',
        'winuser': 'bot',
        'os': 'Windows 11',
        'version': '1.8.35',
        'tcp_port': MOCK_TCP_PORT,
        'file_port': MOCK_TCP_PORT + 1,
        'time': time.time()
    }

    print(f"[Bot] Anunciando '{MOCK_NAME}' em {local_ip} na porta UDP {UDP_PORT}...")
    targets = [
        (local_ip, UDP_PORT),
        (subnet_bcast, UDP_PORT),
        (MULTICAST_GROUP, UDP_PORT),
        ('255.255.255.255', UDP_PORT),
        ('127.0.0.1', UDP_PORT)
    ]
    if TARGET_IP:
        targets.append((TARGET_IP, TARGET_UDP))
    while True:
        data['time'] = time.time()
        pkt = json.dumps(data, ensure_ascii=False).encode('utf-8')
        for target in targets:
            try:
                sock.sendto(pkt, target)
            except Exception:
                pass
        time.sleep(2.0)


def _handle_individual_message(msg, addr):
    from_user = msg.get('from_user')
    user_text = msg.get('content', '')
    reply_text = f"Olá! Recebi sua mensagem: '{user_text}'. Teste OK! 🤌"
    time.sleep(0.8)
    reply_msg = {
        'type': 'message',
        'from_user': MOCK_UID,
        'to_user': from_user,
        'display_name': '🤖 ' + MOCK_NAME,
        'msg_id': str(uuid.uuid4()),
        'content': reply_text,
        'timestamp': time.time()
    }
    _tcp_send(from_user, addr[0], reply_msg)


def _handle_group_invite(msg):
    group_id = msg.get('group_id')
    members = msg.get('members', [])
    with _groups_lock:
        KNOWN_GROUPS[group_id] = {
            'name': msg.get('group_name', 'Grupo'),
            'group_type': msg.get('group_type', 'temp'),
            'members': members,
        }
    print(f"[Bot] Convidado pro grupo '{msg.get('group_name')}' ({group_id}), "
          f"{len(members)} membro(s)")
    time.sleep(1.0)
    send_group_message_to_all(group_id, f"Oi! {MOCK_NAME} entrou no grupo 🤌")


def _handle_group_message(msg):
    group_id = msg.get('group_id')
    sender = msg.get('from_user', '')
    # So responde mensagem de humano (nao de outro bot) -- evita loop de
    # bots respondendo uns aos outros infinitamente.
    if sender.startswith('mock_peer_bot_teste'):
        print(f"[Bot] Ignorando msg de grupo de outro bot ({sender})")
        return
    # Recovery: se o convite foi perdido, tenta reconstruir a lista de
    # membros a partir do que a propria mensagem carrega (mesmo esquema
    # que o app real usa em messenger.py).
    with _groups_lock:
        known = group_id in KNOWN_GROUPS
    if not known:
        print(f"[Bot] Grupo {group_id} desconhecido (convite perdido?) -- "
              f"nao consigo responder no grupo")
        return
    content = msg.get('content', '')
    time.sleep(0.8)
    send_group_message_to_all(group_id, f"Recebi no grupo: '{content}'. Teste OK! 🤌")


# Manda mensagens nao solicitadas num intervalo fixo -- pra testar como o app
# renderiza mensagem recebida (toast, flash da taskbar, bolha, badge de nao lido)
# sem precisar de um humano do outro lado digitando.
def spam_loop(interval):
    n = 0
    time.sleep(5)  # da tempo do app descobrir o bot antes da 1a mensagem
    while True:
        n += 1
        now = time.strftime('%H:%M:%S')
        base = {
            'type': 'message',
            'from_user': MOCK_UID,
            'display_name': '🤖 ' + MOCK_NAME,
            'msg_id': str(uuid.uuid4()),
            'content': f'[auto #{n}] {now} — mensagem de teste de visualizacao 🤌',
            'timestamp': time.time(),
        }
        if TARGET_TCP:
            _tcp_send(MOCK_UID, TARGET_IP, base)  # _reply_target ignora o uid quando --target
        else:
            with _peers_lock:
                peers = list(KNOWN_PEERS.items())
            if not peers:
                print(f"[Bot] spam #{n}: nenhum peer conhecido ainda, pulando")
            for uid, info in peers:
                p = dict(base)
                p['to_user'] = uid
                _tcp_send(uid, info['ip'], p)
        time.sleep(interval)


def handle_tcp_client(client_sock, addr):
    try:
        header = client_sock.recv(4)
        if not header or len(header) < 4:
            return
        msg_len = struct.unpack('!I', header)[0]
        data = bytearray()
        while len(data) < msg_len:
            chunk = client_sock.recv(msg_len - len(data))
            if not chunk:
                break
            data.extend(chunk)
        msg = json.loads(data.decode('utf-8'))
        msg_type = msg.get('type')
        print(f"[Bot] Recebeu '{msg_type}' de {msg.get('from_user')}")

        if msg_type == 'message':
            _handle_individual_message(msg, addr)
        elif msg_type == 'group_invite':
            _handle_group_invite(msg)
        elif msg_type == 'group_message':
            _handle_group_message(msg)
    except Exception as e:
        print(f"[Bot] Erro no cliente TCP: {e}")
    finally:
        try:
            client_sock.close()
        except Exception:
            pass


def run_tcp_server():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(('0.0.0.0', MOCK_TCP_PORT))
    srv.listen(5)
    print(f"[Bot] Servidor TCP ouvindo na porta {MOCK_TCP_PORT}...")
    while True:
        client, addr = srv.accept()
        threading.Thread(target=handle_tcp_client, args=(client, addr), daemon=True).start()


if __name__ == '__main__':
    if _args.target:
        print(f"[Bot] Modo --target: app em {TARGET_IP} (UDP {TARGET_UDP}"
              + (f", TCP {TARGET_TCP}" if TARGET_TCP else "") + ")")
    t_ann = threading.Thread(target=send_announces, daemon=True)
    t_ann.start()
    t_listen = threading.Thread(target=listen_announces, daemon=True)
    t_listen.start()
    if _args.spam and _args.spam > 0:
        print(f"[Bot] Spam ligado: 1 mensagem a cada {_args.spam:g}s")
        threading.Thread(target=spam_loop, args=(_args.spam,), daemon=True).start()
    run_tcp_server()
