# Script auxiliar para testes do MB Chat: cria um peer virtual ("Bot de Teste") na rede local.
# O Bot anuncia sua presenca via UDP e responde automaticamente mensagens recebidas via TCP.
import socket
import struct
import json
import time
import threading
import uuid

UDP_PORT = 50100
MULTICAST_GROUP = '239.255.100.200'
MOCK_UID = 'mock_peer_bot_teste'
MOCK_NAME = 'Bot de Teste'
MOCK_TCP_PORT = 50350


def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'


def send_announces():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    try:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    except Exception:
        pass

    local_ip = get_local_ip()
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
    while True:
        data['time'] = time.time()
        pkt = json.dumps(data, ensure_ascii=False).encode('utf-8')
        for target in targets:
            try:
                sock.sendto(pkt, target)
            except Exception:
                pass
        time.sleep(2.0)


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
        print(f"[Bot] Recebeu mensagem de {msg.get('from_user')}")

        from_user = msg.get('from_user')
        if from_user and msg.get('type') == 'message':
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
            try:
                sender_ip = addr[0]
                tx_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                tx_sock.settimeout(5.0)
                tx_sock.connect((sender_ip, 50101))
                rdata = json.dumps(reply_msg, ensure_ascii=False).encode('utf-8')
                tx_sock.sendall(struct.pack('!I', len(rdata)) + rdata)
                tx_sock.close()
                print(f"[Bot] Resposta enviada com sucesso para {sender_ip}:50101!")
            except Exception as e:
                print(f"[Bot] Erro ao responder via TCP: {e}")
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
    t_ann = threading.Thread(target=send_announces, daemon=True)
    t_ann.start()
    run_tcp_server()
