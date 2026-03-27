"""
LAN Messenger - Camada de rede
UDP broadcast discovery + TCP messaging + File transfer
"""
import socket
import struct
import json
import threading
import time
import uuid
import os
import platform
import subprocess
from pathlib import Path


UDP_PORT = 50100
TCP_PORT = 50101


def _add_firewall_rule():
    """Tenta adicionar regra de firewall no Windows para as portas do app."""
    if platform.system() != 'Windows':
        return
    try:
        # Verifica se a regra ja existe
        result = subprocess.run(
            ['netsh', 'advfirewall', 'firewall', 'show', 'rule',
             'name=MBChat'],
            capture_output=True, text=True, timeout=10,
            creationflags=0x08000000  # CREATE_NO_WINDOW
        )
        if 'MBChat' in result.stdout:
            return  # Regra ja existe
    except Exception:
        pass
    try:
        # Adiciona regras para UDP e TCP
        for proto in ['UDP', 'TCP']:
            ports = f'{UDP_PORT},{TCP_PORT},{TCP_PORT + 1}'
            subprocess.run(
                ['netsh', 'advfirewall', 'firewall', 'add', 'rule',
                 f'name=MBChat', 'dir=in', 'action=allow',
                 f'protocol={proto}', f'localport={ports}',
                 'profile=any'],
                capture_output=True, timeout=10,
                creationflags=0x08000000
            )
    except Exception:
        pass


# Tenta configurar firewall na importacao
_add_firewall_rule()
MULTICAST_GROUP = '239.255.100.200'
BROADCAST_ADDR = '255.255.255.255'
BUFFER_SIZE = 65536
FILE_CHUNK = 65536
DISCOVERY_INTERVAL = 5  # seconds
PING_INTERVAL = 10
PING_TIMEOUT = 30

# Message types
MT_ANNOUNCE = 'announce'
MT_DEPART = 'depart'
MT_PING = 'ping'
MT_PONG = 'pong'
MT_MESSAGE = 'message'
MT_FILE_REQ = 'file_request'
MT_FILE_ACC = 'file_accept'
MT_FILE_DEC = 'file_decline'
MT_FILE_CANCEL = 'file_cancel'
MT_STATUS = 'status_change'
MT_TYPING = 'typing'
MT_ACK = 'ack'


def get_local_ip():
    """Detecta IP local da máquina na rede."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'


def generate_user_id():
    """Gera ID único baseado no MAC + hostname."""
    mac = uuid.getnode()
    host = socket.gethostname()
    return f"{mac:012x}_{host}"


def get_machine_info():
    return {
        'hostname': socket.gethostname(),
        'os': f"{platform.system()} {platform.release()}",
        'ip': get_local_ip()
    }


class UDPDiscovery:
    """Descoberta de peers via UDP multicast + broadcast."""

    def __init__(self, user_id, display_name, status='online',
                 on_peer_found=None, on_peer_lost=None):
        self.user_id = user_id
        self.display_name = display_name
        self.status = status
        self.on_peer_found = on_peer_found
        self.on_peer_lost = on_peer_lost
        self.peers = {}  # user_id -> {info + last_seen}
        self.running = False
        self._sock_recv = None
        self._sock_send = None
        self._lock = threading.Lock()

    def start(self):
        self.running = True
        # Receiver socket
        self._sock_recv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM,
                                        socket.IPPROTO_UDP)
        self._sock_recv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, 'SO_REUSEPORT'):
            try:
                self._sock_recv.setsockopt(socket.SOL_SOCKET,
                                           socket.SO_REUSEPORT, 1)
            except (AttributeError, OSError):
                pass
        # Tenta bind na porta principal, fallback para alternativas
        bound = False
        for port in [UDP_PORT, UDP_PORT + 10, UDP_PORT + 20]:
            try:
                self._sock_recv.bind(('', port))
                bound = True
                break
            except PermissionError:
                continue
            except OSError:
                continue
        if not bound:
            # Ultimo recurso: porta aleatoria
            self._sock_recv.bind(('', 0))

        # Join multicast
        try:
            local_ip = get_local_ip()
            mreq = struct.pack('4s4s',
                               socket.inet_aton(MULTICAST_GROUP),
                               socket.inet_aton(local_ip))
            self._sock_recv.setsockopt(socket.IPPROTO_IP,
                                       socket.IP_ADD_MEMBERSHIP, mreq)
        except Exception:
            pass  # Multicast may not be available

        # Aumenta buffer UDP para suportar 30+ peers
        try:
            self._sock_recv.setsockopt(socket.SOL_SOCKET,
                                       socket.SO_RCVBUF, 262144)
        except Exception:
            pass
        self._sock_recv.settimeout(1.0)

        # Sender socket
        self._sock_send = socket.socket(socket.AF_INET, socket.SOCK_DGRAM,
                                        socket.IPPROTO_UDP)
        self._sock_send.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        try:
            self._sock_send.setsockopt(socket.IPPROTO_IP,
                                       socket.IP_MULTICAST_TTL, 2)
        except Exception:
            pass

        # Start threads
        self._recv_thread = threading.Thread(target=self._receive_loop,
                                             daemon=True)
        self._announce_thread = threading.Thread(target=self._announce_loop,
                                                 daemon=True)
        self._cleanup_thread = threading.Thread(target=self._cleanup_loop,
                                                daemon=True)
        self._recv_thread.start()
        self._announce_thread.start()
        self._cleanup_thread.start()

        # Initial announce
        self._send_announce()

    def stop(self):
        self.running = False
        self._send_depart()
        time.sleep(0.2)
        if self._sock_recv:
            self._sock_recv.close()
        if self._sock_send:
            self._sock_send.close()

    def update_status(self, status):
        self.status = status
        self._send_announce()

    def update_name(self, name):
        self.display_name = name
        self._send_announce()

    def _make_packet(self, msg_type, extra=None):
        data = {
            'app': 'mbchat',
            'type': msg_type,
            'user_id': self.user_id,
            'display_name': self.display_name,
            'status': self.status,
            'ip': get_local_ip(),
            'hostname': socket.gethostname(),
            'os': f"{platform.system()} {platform.release()}",
            'tcp_port': TCP_PORT,
            'time': time.time()
        }
        if extra:
            data.update(extra)
        return json.dumps(data, ensure_ascii=False).encode('utf-8')

    def _send_announce(self):
        pkt = self._make_packet(MT_ANNOUNCE)
        try:
            self._sock_send.sendto(pkt, (MULTICAST_GROUP, UDP_PORT))
        except Exception:
            pass
        try:
            self._sock_send.sendto(pkt, (BROADCAST_ADDR, UDP_PORT))
        except Exception:
            pass

    def _send_depart(self):
        pkt = self._make_packet(MT_DEPART)
        try:
            self._sock_send.sendto(pkt, (MULTICAST_GROUP, UDP_PORT))
        except Exception:
            pass
        try:
            self._sock_send.sendto(pkt, (BROADCAST_ADDR, UDP_PORT))
        except Exception:
            pass

    def _receive_loop(self):
        while self.running:
            try:
                data, addr = self._sock_recv.recvfrom(BUFFER_SIZE)
                self._handle_packet(data, addr)
            except socket.timeout:
                continue
            except OSError:
                if self.running:
                    time.sleep(0.5)

    def _handle_packet(self, data, addr):
        try:
            pkt = json.loads(data.decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return

        if pkt.get('app') != 'mbchat':
            return
        if pkt.get('user_id') == self.user_id:
            return  # Ignore own packets

        uid = pkt['user_id']
        msg_type = pkt.get('type')

        if msg_type == MT_DEPART:
            with self._lock:
                if uid in self.peers:
                    peer = self.peers.pop(uid)
                    if self.on_peer_lost:
                        self.on_peer_lost(uid, peer)
            return

        if msg_type == MT_ANNOUNCE:
            peer_info = {
                'user_id': uid,
                'display_name': pkt.get('display_name', 'Unknown'),
                'ip': pkt.get('ip', addr[0]),
                'hostname': pkt.get('hostname', ''),
                'os': pkt.get('os', ''),
                'status': pkt.get('status', 'online'),
                'tcp_port': pkt.get('tcp_port', TCP_PORT),
                'last_seen': time.time()
            }
            is_new = False
            with self._lock:
                if uid not in self.peers:
                    is_new = True
                self.peers[uid] = peer_info

            if self.on_peer_found:
                self.on_peer_found(uid, peer_info)
            if is_new:
                # Respond to new peer (only once, not on updates)
                self._send_announce()

    def _announce_loop(self):
        while self.running:
            time.sleep(DISCOVERY_INTERVAL)
            if self.running:
                self._send_announce()

    def _cleanup_loop(self):
        while self.running:
            time.sleep(PING_INTERVAL)
            now = time.time()
            lost = []
            with self._lock:
                for uid, info in list(self.peers.items()):
                    if now - info['last_seen'] > PING_TIMEOUT:
                        lost.append((uid, self.peers.pop(uid)))
            for uid, info in lost:
                if self.on_peer_lost:
                    self.on_peer_lost(uid, info)


class TCPServer:
    """Servidor TCP para receber mensagens e arquivos."""

    def __init__(self, on_message=None, on_file_request=None,
                 on_file_data=None):
        self.on_message = on_message
        self.on_file_request = on_file_request
        self.on_file_data = on_file_data
        self.running = False
        self._server = None
        self._connections = {}  # user_id -> socket
        self._lock = threading.Lock()

    def start(self):
        self.running = True
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # Tenta bind com fallback
        for port in [TCP_PORT, TCP_PORT + 10, TCP_PORT + 20]:
            try:
                self._server.bind(('', port))
                break
            except (PermissionError, OSError):
                continue
        self._server.listen(100)
        self._server.settimeout(1.0)

        self._accept_thread = threading.Thread(target=self._accept_loop,
                                               daemon=True)
        self._accept_thread.start()

    def stop(self):
        self.running = False
        with self._lock:
            for sock in self._connections.values():
                try:
                    sock.close()
                except Exception:
                    pass
            self._connections.clear()
        if self._server:
            self._server.close()

    def _accept_loop(self):
        while self.running:
            try:
                client, addr = self._server.accept()
                t = threading.Thread(target=self._handle_client,
                                     args=(client, addr), daemon=True)
                t.start()
            except socket.timeout:
                continue
            except OSError:
                if self.running:
                    time.sleep(0.5)

    def _handle_client(self, client, addr):
        client.settimeout(30.0)
        try:
            while self.running:
                # Read 4-byte length header
                header = self._recv_exact(client, 4)
                if not header:
                    break
                msg_len = struct.unpack('!I', header)[0]
                if msg_len > 10 * 1024 * 1024:  # 10MB max message
                    break
                data = self._recv_exact(client, msg_len)
                if not data:
                    break
                self._process_message(data, addr, client)
        except (socket.timeout, ConnectionResetError, OSError):
            pass
        finally:
            client.close()

    def _recv_exact(self, sock, n):
        buf = bytearray()
        while len(buf) < n:
            try:
                chunk = sock.recv(n - len(buf))
                if not chunk:
                    return None
                buf.extend(chunk)
            except (socket.timeout, OSError):
                return None
        return bytes(buf)

    def _process_message(self, data, addr, client):
        try:
            msg = json.loads(data.decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return

        msg_type = msg.get('type')
        if msg_type == MT_FILE_REQ and self.on_file_request:
            self.on_file_request(msg, addr)
        elif msg_type == MT_FILE_ACC:
            pass  # Handled by sender
        elif self.on_message:
            self.on_message(msg, addr)


class TCPClient:
    """Cliente TCP para enviar mensagens."""

    @staticmethod
    def send_message(ip, port, message_dict):
        """Envia uma mensagem JSON via TCP."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(10.0)
            sock.connect((ip, port))
            data = json.dumps(message_dict, ensure_ascii=False).encode('utf-8')
            sock.sendall(struct.pack('!I', len(data)) + data)
            sock.close()
            return True
        except Exception as e:
            return False

    @staticmethod
    def send_message_with_response(ip, port, message_dict, timeout=10):
        """Envia mensagem e aguarda resposta."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect((ip, port))
            data = json.dumps(message_dict, ensure_ascii=False).encode('utf-8')
            sock.sendall(struct.pack('!I', len(data)) + data)

            header = b''
            while len(header) < 4:
                chunk = sock.recv(4 - len(header))
                if not chunk:
                    sock.close()
                    return None
                header += chunk
            resp_len = struct.unpack('!I', header)[0]
            resp_data = b''
            while len(resp_data) < resp_len:
                chunk = sock.recv(resp_len - len(resp_data))
                if not chunk:
                    break
                resp_data += chunk
            sock.close()
            return json.loads(resp_data.decode('utf-8'))
        except Exception:
            return None


class FileSender:
    """Envia arquivo via TCP dedicado."""

    def __init__(self, filepath, peer_ip, peer_port, file_id,
                 on_progress=None, on_complete=None, on_error=None):
        self.filepath = filepath
        self.peer_ip = peer_ip
        self.peer_port = peer_port
        self.file_id = file_id
        self.on_progress = on_progress
        self.on_complete = on_complete
        self.on_error = on_error
        self.cancelled = False
        self.filesize = os.path.getsize(filepath)

    def start(self):
        t = threading.Thread(target=self._send, daemon=True)
        t.start()

    def cancel(self):
        self.cancelled = True

    def _send(self):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(120.0)  # Tempo para o usuario aceitar
            sock.connect((self.peer_ip, self.peer_port + 1))  # File port = TCP+1

            # Send file header
            header = json.dumps({
                'file_id': self.file_id,
                'filename': os.path.basename(self.filepath),
                'filesize': self.filesize
            }).encode('utf-8')
            sock.sendall(struct.pack('!I', len(header)) + header)

            # Wait for accept
            resp = sock.recv(4)
            if resp != b'OKAY':
                if self.on_error:
                    self.on_error(self.file_id, 'Recusado')
                sock.close()
                return

            # Send file data
            sent = 0
            with open(self.filepath, 'rb') as f:
                while not self.cancelled:
                    chunk = f.read(FILE_CHUNK)
                    if not chunk:
                        break
                    sock.sendall(chunk)
                    sent += len(chunk)
                    if self.on_progress:
                        self.on_progress(self.file_id, sent, self.filesize)

            sock.close()
            if not self.cancelled and self.on_complete:
                self.on_complete(self.file_id)
            elif self.cancelled and self.on_error:
                self.on_error(self.file_id, 'Cancelado')
        except Exception as e:
            if self.on_error:
                self.on_error(self.file_id, str(e))


class FileReceiver:
    """Servidor para receber arquivos."""

    def __init__(self, save_dir, on_incoming=None, on_progress=None,
                 on_complete=None, on_error=None):
        self.save_dir = save_dir
        self.on_incoming = on_incoming
        self.on_progress = on_progress
        self.on_complete = on_complete
        self.on_error = on_error
        self.running = False
        self._server = None
        self._pending_accepts = {}  # file_id -> True/False/None
        self._lock = threading.Lock()

    def start(self):
        self.running = True
        os.makedirs(self.save_dir, exist_ok=True)
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # Tenta bind com fallback
        for port in [TCP_PORT + 1, TCP_PORT + 11, TCP_PORT + 21]:
            try:
                self._server.bind(('', port))
                break
            except (PermissionError, OSError):
                continue
        self._server.listen(100)
        self._server.settimeout(1.0)

        t = threading.Thread(target=self._accept_loop, daemon=True)
        t.start()

    def stop(self):
        self.running = False
        if self._server:
            self._server.close()

    def accept_file(self, file_id):
        with self._lock:
            self._pending_accepts[file_id] = True

    def decline_file(self, file_id):
        with self._lock:
            self._pending_accepts[file_id] = False

    def _accept_loop(self):
        while self.running:
            try:
                client, addr = self._server.accept()
                t = threading.Thread(target=self._handle_file,
                                     args=(client, addr), daemon=True)
                t.start()
            except socket.timeout:
                continue
            except OSError:
                if self.running:
                    time.sleep(0.5)

    def _handle_file(self, client, addr):
        try:
            client.settimeout(120.0)

            # Read file header
            hdr_len_data = b''
            while len(hdr_len_data) < 4:
                chunk = client.recv(4 - len(hdr_len_data))
                if not chunk:
                    client.close()
                    return
                hdr_len_data += chunk

            hdr_len = struct.unpack('!I', hdr_len_data)[0]
            hdr_data = b''
            while len(hdr_data) < hdr_len:
                chunk = client.recv(hdr_len - len(hdr_data))
                if not chunk:
                    break
                hdr_data += chunk

            info = json.loads(hdr_data.decode('utf-8'))
            file_id = info['file_id']
            filename = info['filename']
            filesize = info['filesize']

            # Notify UI and wait for accept/decline
            if self.on_incoming:
                self.on_incoming(file_id, filename, filesize, addr[0])

            # Wait for user decision (max 60 seconds)
            deadline = time.time() + 60
            accepted = None
            while time.time() < deadline:
                with self._lock:
                    if file_id in self._pending_accepts:
                        accepted = self._pending_accepts.pop(file_id)
                        break
                time.sleep(0.2)

            if not accepted:
                client.sendall(b'DENY')
                client.close()
                return

            client.sendall(b'OKAY')

            # Receive file
            safe_name = "".join(c for c in filename
                                if c.isalnum() or c in '.-_ ')
            save_path = os.path.join(self.save_dir, safe_name)

            # Handle duplicates
            base, ext = os.path.splitext(save_path)
            counter = 1
            while os.path.exists(save_path):
                save_path = f"{base}_{counter}{ext}"
                counter += 1

            received = 0
            with open(save_path, 'wb') as f:
                while received < filesize:
                    chunk = client.recv(min(FILE_CHUNK, filesize - received))
                    if not chunk:
                        break
                    f.write(chunk)
                    received += len(chunk)
                    if self.on_progress:
                        self.on_progress(file_id, received, filesize)

            client.close()

            if received >= filesize and self.on_complete:
                self.on_complete(file_id, save_path)
            elif self.on_error:
                self.on_error(file_id, 'Transferência incompleta')
        except Exception as e:
            if self.on_error:
                self.on_error(file_id, str(e))
            try:
                client.close()
            except Exception:
                pass
