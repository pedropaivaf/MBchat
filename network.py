# MB Chat - Camada de rede
# UDP broadcast/multicast discovery + TCP messaging + File transfer
#
# Este modulo implementa toda a comunicacao de rede do app:
# - UDPDiscovery: descobre peers na LAN via multicast (239.255.100.200) e broadcast
# - TCPServer/TCPClient: mensagens ponto-a-ponto com protocolo length-prefixed
# - FileSender/FileReceiver: transferencia de arquivos em chunks de 256KB
# - Constantes de tipos de mensagem (MT_*) usadas por todas as camadas
#
# Portas:
# - UDP 50100: Discovery (multicast + broadcast)
# - TCP 50101: Mensagens (texto, grupo, convites, status, typing)
# - TCP 50102: Transferencia de arquivos (file port = TCP_PORT + 1)
# - TCP 50199: Lock de instancia unica (loopback, definido em gui.py)
#
# IMPORTANTE: Portas escolhidas para NAO conflitar com LAN Messenger (50000-50002)

import socket      # Sockets UDP e TCP
import struct      # Pack/unpack de headers binarios (4 bytes length)
import json        # Serializacao de mensagens
import threading   # Threads para servidor e discovery
import time        # Timestamps e intervalos
import uuid        # Geracao de IDs unicos
import os          # Caminhos de arquivos
import platform    # Deteccao de OS
import subprocess  # Execucao de netsh para firewall
from pathlib import Path  # Manipulacao de caminhos


# === Portas de rede ===
UDP_PORT = 50100  # Porta para discovery UDP (multicast + broadcast)
TCP_PORT = 50101  # Porta para mensagens TCP (texto, grupo, etc.)
# File transfer usa TCP_PORT + 1 = 50102


# Tenta adicionar regra de firewall no Windows para as portas do app.
# Executado automaticamente em background na importacao do modulo.
# Usa netsh para criar regra "MBChat" se nao existir.
# Silencia todos os erros (pode nao ter permissao de admin).
def _add_firewall_rule():
    if platform.system() != 'Windows':
        return  # So funciona no Windows
    try:
        # Verifica se a regra ja existe no firewall
        result = subprocess.run(
            ['netsh', 'advfirewall', 'firewall', 'show', 'rule',
             'name=MBChat'],
            capture_output=True, text=True, timeout=3,
            creationflags=0x08000000  # CREATE_NO_WINDOW (sem janela cmd)
        )
        if 'MBChat' in result.stdout:
            return  # Regra ja existe, nao precisa criar
    except Exception:
        pass  # Ignora erros ao verificar

    try:
        # Adiciona regras de entrada para UDP e TCP
        for proto in ['UDP', 'TCP']:
            ports = f'{UDP_PORT},{TCP_PORT},{TCP_PORT + 1}'  # 50100,50101,50102
            subprocess.run(
                ['netsh', 'advfirewall', 'firewall', 'add', 'rule',
                 f'name=MBChat', 'dir=in', 'action=allow',
                 f'protocol={proto}', f'localport={ports}',
                 'profile=any'],  # Aplica a todos os perfis de rede
                capture_output=True, timeout=3,
                creationflags=0x08000000  # Sem janela
            )
    except Exception:
        pass  # Sem permissao de admin, ignora silenciosamente


# Configura firewall em thread background (nao bloqueia startup)
threading.Thread(target=_add_firewall_rule, daemon=True).start()

# === Constantes de rede ===
MULTICAST_GROUP = '239.255.100.200'  # Grupo multicast para discovery
BROADCAST_ADDR = '255.255.255.255'   # Endereco de broadcast para fallback
BUFFER_SIZE = 65536    # 64KB - tamanho maximo de pacote UDP
FILE_CHUNK = 262144    # 256KB - tamanho de chunk para transferencia de arquivos
DISCOVERY_INTERVAL = 5  # Segundos entre announcements periodicos
PING_INTERVAL = 10      # Segundos entre verificacoes de peers perdidos
PING_TIMEOUT = 30       # Segundos sem resposta para considerar peer perdido

# === Tipos de mensagem ===
# Usados como campo 'type' nos JSONs de comunicacao
MT_ANNOUNCE = 'announce'        # UDP: anuncio de presenca (discovery)
MT_DEPART = 'depart'            # UDP: saida da rede (app fechando)
MT_PING = 'ping'                # UDP: verificacao de vida (nao usado atualmente)
MT_PONG = 'pong'                # UDP: resposta ao ping (nao usado atualmente)
MT_MESSAGE = 'message'          # TCP: mensagem de texto individual
MT_FILE_REQ = 'file_request'    # TCP: solicitacao de envio de arquivo
MT_FILE_ACC = 'file_accept'     # TCP: aceitacao de arquivo
MT_FILE_DEC = 'file_decline'    # TCP: recusa de arquivo
MT_FILE_CANCEL = 'file_cancel'  # TCP: cancelamento de transferencia
MT_STATUS = 'status_change'     # TCP: mudanca de status (online/away/busy)
MT_TYPING = 'typing'            # TCP: indicador de digitacao
MT_ACK = 'ack'                  # TCP: confirmacao de recebimento de mensagem
MT_GROUP_INV = 'group_invite'   # TCP: convite para entrar em grupo
MT_GROUP_MSG = 'group_message'  # TCP: mensagem de texto em grupo (mesh)
MT_GROUP_LEAVE = 'group_leave'  # TCP: notificacao de saida do grupo
MT_GROUP_JOIN = 'group_join'    # TCP: notificacao de entrada no grupo
MT_IMAGE = 'image'              # TCP: imagem inline (clipboard, base64)
MT_POLL_CREATE = 'poll_create'  # TCP: criacao de enquete em grupo
MT_POLL_VOTE = 'poll_vote'      # TCP: voto em enquete de grupo


# Detecta IP local da maquina na rede.
# Cria socket UDP e "conecta" ao DNS do Google (8.8.8.8)
# para descobrir qual interface de rede seria usada.
# Nao envia dados, apenas verifica o roteamento.
# Retorna '127.0.0.1' se nao conseguir detectar.
def get_local_ip():
    # Tenta via rota UDP (nao precisa de internet, so verifica roteamento)
    for target in ['10.255.255.255', '8.8.8.8']:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0.1)
            s.connect((target, 1))
            ip = s.getsockname()[0]
            s.close()
            if ip and ip != '127.0.0.1' and not ip.startswith('169.254'):
                return ip
        except Exception:
            pass
    # Fallback: enumera interfaces e pega o primeiro IP privado valido
    try:
        hostname = socket.gethostname()
        for ip in socket.gethostbyname_ex(hostname)[2]:
            if ip != '127.0.0.1' and not ip.startswith('169.254'):
                return ip
    except Exception:
        pass
    return '127.0.0.1'


# Calcula endereco de broadcast da subnet local
def _get_subnet_broadcast():
    ip = get_local_ip()
    if ip == '127.0.0.1':
        return None
    # Assume /24 para redes corporativas tipicas
    parts = ip.split('.')
    if len(parts) == 4:
        return f'{parts[0]}.{parts[1]}.{parts[2]}.255'
    return None


# Gera ID unico baseado no MAC address + hostname.
# Formato: "mac12digitos_hostname"
# Garante que o mesmo PC sempre gere o mesmo ID.
def generate_user_id():
    mac = uuid.getnode()  # MAC address como inteiro
    host = socket.gethostname()  # Nome da maquina
    return f"{mac:012x}_{host}"  # MAC em hex (12 digitos) + underscore + hostname


# Retorna informacoes da maquina local como dict
def get_machine_info():
    return {
        'hostname': socket.gethostname(),       # Nome da maquina
        'os': f"{platform.system()} {platform.release()}",  # Ex: "Windows 11"
        'ip': get_local_ip()                    # IP local
    }


# ========================================
# UDP DISCOVERY — Descoberta de peers na LAN
# ========================================

# Descoberta de peers via UDP multicast + broadcast.
# Funciona assim:
# 1. Envia announcements periodicos (a cada 5s) via multicast E broadcast
# 2. Recebe announcements de outros peers e registra em self.peers
# 3. Se um peer nao responde por 30s, e considerado perdido
# 4. Ao fechar, envia MT_DEPART para notificar saida imediata
# O pacote de announce inclui: user_id, display_name, status, note,
# avatar_index, avatar_data (thumbnail base64), ip, hostname, os.
class UDPDiscovery:

    # Inicializa o discovery
    # user_id: ID unico deste usuario
    # display_name: Nome de exibicao
    # status: Status inicial (online/away/busy)
    # on_peer_found: Callback(uid, info) quando peer encontrado
    # on_peer_lost: Callback(uid, info) quando peer perdido
    def __init__(self, user_id, display_name, status='online',
                 on_peer_found=None, on_peer_lost=None):
        self.user_id = user_id
        self.display_name = display_name
        self.status = status
        self.note = ''           # Nota pessoal (sincronizada via announce)
        self.avatar_index = 0    # Indice do avatar padrao
        self.avatar_data = ''    # Thumbnail base64 JPEG do avatar custom
        self.on_peer_found = on_peer_found  # Callback: peer descoberto
        self.on_peer_lost = on_peer_lost    # Callback: peer perdido
        self.peers = {}          # user_id -> {info + last_seen}
        self.running = False     # Flag de controle do loop
        self._sock_recv = None   # Socket de recebimento
        self._sock_send = None   # Socket de envio
        self._lock = threading.Lock()  # Lock para acesso thread-safe a self.peers

    # Inicia o discovery: sockets, threads e primeiro announce
    def start(self):
        self.running = True

        # --- Socket de recebimento (bind na porta UDP) ---
        self._sock_recv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM,
                                        socket.IPPROTO_UDP)
        self._sock_recv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        # SO_REUSEPORT permite multiplas instancias na mesma porta (Linux/Mac)
        if hasattr(socket, 'SO_REUSEPORT'):
            try:
                self._sock_recv.setsockopt(socket.SOL_SOCKET,
                                           socket.SO_REUSEPORT, 1)
            except (AttributeError, OSError):
                pass  # Nem todo OS suporta

        # Tenta bind na porta principal, com fallbacks
        bound = False
        for port in [UDP_PORT, UDP_PORT + 10, UDP_PORT + 20]:
            try:
                self._sock_recv.bind(('', port))  # '' = todas as interfaces
                bound = True
                break
            except PermissionError:
                continue  # Porta ocupada por outro processo
            except OSError:
                continue
        if not bound:
            self._sock_recv.bind(('', 0))  # Ultimo recurso: porta aleatoria

        # Junta ao grupo multicast para receber announcements
        # Tenta com IP local especifico primeiro, depois INADDR_ANY como fallback
        multicast_joined = False
        for iface_ip in [get_local_ip(), '0.0.0.0']:
            try:
                mreq = struct.pack('4s4s',
                                   socket.inet_aton(MULTICAST_GROUP),
                                   socket.inet_aton(iface_ip))
                self._sock_recv.setsockopt(socket.IPPROTO_IP,
                                           socket.IP_ADD_MEMBERSHIP, mreq)
                multicast_joined = True
                break
            except Exception:
                continue
        # Se nao juntou ao multicast, broadcast sera o unico meio de discovery

        # Aumenta buffer UDP para suportar 30+ peers simultaneos
        try:
            self._sock_recv.setsockopt(socket.SOL_SOCKET,
                                       socket.SO_RCVBUF, 262144)  # 256KB
        except Exception:
            pass
        self._sock_recv.settimeout(0.3)  # Timeout curto para loop responsivo

        # --- Socket de envio (multicast + broadcast) ---
        self._sock_send = socket.socket(socket.AF_INET, socket.SOCK_DGRAM,
                                        socket.IPPROTO_UDP)
        self._sock_send.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        try:
            # TTL=2 para multicast (alcanca roteadores proximos)
            self._sock_send.setsockopt(socket.IPPROTO_IP,
                                       socket.IP_MULTICAST_TTL, 2)
        except Exception:
            pass

        # --- Inicia as 3 threads de operacao ---
        # Thread 1: recebe pacotes UDP de outros peers
        self._recv_thread = threading.Thread(target=self._receive_loop,
                                             daemon=True)
        # Thread 2: envia announcements periodicos
        self._announce_thread = threading.Thread(target=self._announce_loop,
                                                 daemon=True)
        # Thread 3: limpa peers que nao respondem ha muito tempo
        self._cleanup_thread = threading.Thread(target=self._cleanup_loop,
                                                daemon=True)
        self._recv_thread.start()
        self._announce_thread.start()
        self._cleanup_thread.start()

        # Envia o primeiro announce imediatamente
        self._send_announce()

    # Para o discovery: envia depart e fecha sockets
    def stop(self):
        self.running = False
        self._send_depart()  # Notifica peers que estamos saindo
        time.sleep(0.2)  # Aguarda envio do depart
        if self._sock_recv:
            self._sock_recv.close()
        if self._sock_send:
            self._sock_send.close()

    # Atualiza status e envia announce imediato para propagar
    def update_status(self, status):
        self.status = status
        self._send_announce()

    # Atualiza nome de exibicao e propaga via announce
    def update_name(self, name):
        self.display_name = name
        self._send_announce()

    # Atualiza nota pessoal e propaga via announce
    def update_note(self, note):
        self.note = note
        self._send_announce()

    # Atualiza avatar e propaga via announce
    # index: Indice do avatar padrao
    # data_b64: Thumbnail JPEG em base64 (~1-2KB no pacote UDP)
    def update_avatar(self, index, data_b64=''):
        self.avatar_index = index
        self.avatar_data = data_b64
        self._send_announce()

    # Monta pacote JSON para envio UDP
    # Inclui todos os dados do usuario local no pacote
    # O pacote e serializado como JSON UTF-8
    # msg_type: MT_ANNOUNCE ou MT_DEPART
    # extra: Dict adicional para merge no pacote
    def _make_packet(self, msg_type, extra=None):
        data = {
            'app': 'mbchat',           # Identificador do app (ignora pacotes de outros)
            'type': msg_type,           # Tipo de mensagem
            'user_id': self.user_id,    # ID unico do remetente
            'display_name': self.display_name,  # Nome de exibicao
            'status': self.status,      # Status atual
            'note': self.note,          # Nota pessoal
            'avatar_index': self.avatar_index,  # Indice do avatar
            'avatar_data': self.avatar_data,    # Thumbnail base64 JPEG
            'department': getattr(self, 'department', ''),  # Departamento do usuario
            'ip': get_local_ip(),       # IP local atual
            'hostname': socket.gethostname(),   # Nome da maquina
            'os': f"{platform.system()} {platform.release()}",  # OS info
            'tcp_port': getattr(self, 'tcp_port', TCP_PORT),       # Porta TCP para mensagens
            'time': time.time()         # Timestamp do pacote
        }
        if extra:
            data.update(extra)  # Merge dados extras
        return json.dumps(data, ensure_ascii=False).encode('utf-8')

    # Envia pacote de announce via multicast E broadcast
    # Envia por ambos os metodos para maxima compatibilidade:
    # - Multicast: mais eficiente, mas precisa de suporte da rede
    # - Broadcast: funciona em qualquer rede, mas gera mais trafego
    def _send_announce(self):
        pkt = self._make_packet(MT_ANNOUNCE)
        try:
            self._sock_send.sendto(pkt, (MULTICAST_GROUP, UDP_PORT))
        except Exception:
            pass  # Multicast pode falhar em algumas redes
        try:
            self._sock_send.sendto(pkt, (BROADCAST_ADDR, UDP_PORT))
        except Exception:
            pass  # Broadcast global pode ser bloqueado
        # Subnet-directed broadcast (mais confiavel em algumas redes Windows)
        subnet_bcast = _get_subnet_broadcast()
        if subnet_bcast and subnet_bcast != BROADCAST_ADDR:
            try:
                self._sock_send.sendto(pkt, (subnet_bcast, UDP_PORT))
            except Exception:
                pass

    # Envia pacote de saida (depart) para todos os peers
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
        subnet_bcast = _get_subnet_broadcast()
        if subnet_bcast and subnet_bcast != BROADCAST_ADDR:
            try:
                self._sock_send.sendto(pkt, (subnet_bcast, UDP_PORT))
            except Exception:
                pass

    # Loop de recebimento de pacotes UDP (roda em thread daemon)
    def _receive_loop(self):
        while self.running:
            try:
                data, addr = self._sock_recv.recvfrom(BUFFER_SIZE)
                self._handle_packet(data, addr)
            except socket.timeout:
                continue  # Timeout normal, volta ao loop
            except OSError:
                if self.running:
                    time.sleep(0.5)  # Erro de socket, espera antes de tentar

    # Processa um pacote UDP recebido
    # Ignora pacotes de outros apps (app != 'mbchat') e os proprios
    # Para MT_DEPART: remove peer da lista
    # Para MT_ANNOUNCE: adiciona/atualiza peer e notifica via callback
    def _handle_packet(self, data, addr):
        try:
            pkt = json.loads(data.decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return  # Pacote invalido, ignora

        if pkt.get('app') != 'mbchat':
            return  # Pacote de outro app, ignora
        if pkt.get('user_id') == self.user_id:
            return  # Pacote proprio (eco), ignora

        uid = pkt['user_id']
        msg_type = pkt.get('type')

        if msg_type == MT_DEPART:
            # Peer esta saindo da rede
            with self._lock:
                if uid in self.peers:
                    peer = self.peers.pop(uid)  # Remove da lista
                    if self.on_peer_lost:
                        self.on_peer_lost(uid, peer)  # Notifica GUI
            return

        if msg_type == MT_ANNOUNCE:
            # Peer esta se anunciando (novo ou atualizacao)
            peer_info = {
                'user_id': uid,
                'display_name': pkt.get('display_name', 'Unknown'),
                'ip': pkt.get('ip', addr[0]),  # IP do pacote ou do socket
                'hostname': pkt.get('hostname', ''),
                'os': pkt.get('os', ''),
                'status': pkt.get('status', 'online'),
                'note': pkt.get('note', ''),
                'avatar_index': pkt.get('avatar_index', 0),
                'avatar_data': pkt.get('avatar_data', ''),
                'department': pkt.get('department', ''),
                'tcp_port': pkt.get('tcp_port', TCP_PORT),
                'last_seen': time.time()  # Marca momento do recebimento
            }
            is_new = False
            with self._lock:
                if uid not in self.peers:
                    is_new = True  # Peer novo, nunca visto antes
                self.peers[uid] = peer_info  # Atualiza dados

            if self.on_peer_found:
                self.on_peer_found(uid, peer_info)  # Notifica GUI

            if is_new:
                # Responde ao novo peer para que ele nos descubra tambem
                self._send_announce()

    # Loop periodico de announcements (a cada DISCOVERY_INTERVAL segundos)
    def _announce_loop(self):
        while self.running:
            time.sleep(DISCOVERY_INTERVAL)  # Espera 5 segundos
            if self.running:
                self._send_announce()  # Envia announce

    # Loop de limpeza de peers inativos (a cada PING_INTERVAL segundos)
    # Remove peers que nao enviam announce ha mais de PING_TIMEOUT segundos
    def _cleanup_loop(self):
        while self.running:
            time.sleep(PING_INTERVAL)  # Verifica a cada 10 segundos
            now = time.time()
            lost = []  # Lista de peers perdidos
            with self._lock:
                for uid, info in list(self.peers.items()):
                    if now - info['last_seen'] > PING_TIMEOUT:
                        # Peer sem resposta ha mais de 30s
                        lost.append((uid, self.peers.pop(uid)))
            # Notifica GUI para cada peer perdido (fora do lock)
            for uid, info in lost:
                if self.on_peer_lost:
                    self.on_peer_lost(uid, info)


# ========================================
# TCP SERVER — Recebe mensagens via TCP
# ========================================

# Servidor TCP para receber mensagens e comandos
# Protocolo:
# 1. Cliente conecta via TCP
# 2. Envia header de 4 bytes (big-endian uint32) com tamanho da mensagem
# 3. Envia mensagem JSON de N bytes
# 4. Pode enviar multiplas mensagens na mesma conexao
# 5. Servidor processa cada mensagem e chama callback
class TCPServer:

    # Inicializa o servidor TCP
    # on_message: Callback(msg_dict, addr) para mensagens gerais
    # on_file_request: Callback(msg_dict, addr) para pedidos de arquivo
    # on_file_data: Callback para dados de arquivo (nao usado)
    def __init__(self, on_message=None, on_file_request=None,
                 on_file_data=None):
        self.on_message = on_message
        self.on_file_request = on_file_request
        self.on_file_data = on_file_data
        self.running = False
        self._server = None                # Socket do servidor
        self._connections = {}             # user_id -> socket (conexoes ativas)
        self._lock = threading.Lock()

    # Inicia o servidor TCP na porta TCP_PORT
    def start(self):
        self.running = True
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        # Tenta bind com fallback para portas alternativas, com 0 (dinamico) de ultima opcao
        bound = False
        self.port = TCP_PORT
        for port in [TCP_PORT, TCP_PORT + 10, TCP_PORT + 20, 0]:
            try:
                self._server.bind(('', port))  # '' = todas as interfaces
                self.port = self._server.getsockname()[1]  # Pega a porta efetiva
                bound = True
                break
            except (PermissionError, OSError):
                continue
        
        if not bound:
            return  # Se realmente falhar em tds (ate na 0), aborta sem fechar o app
            
        self._server.listen(100)  # Backlog de 100 conexoes
        self._server.settimeout(0.3)  # Timeout para loop responsivo

        # Thread que aceita novas conexoes
        self._accept_thread = threading.Thread(target=self._accept_loop,
                                               daemon=True)
        self._accept_thread.start()

    # Para o servidor e fecha todas as conexoes
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

    # Loop que aceita novas conexoes TCP (roda em thread daemon)
    def _accept_loop(self):
        while self.running:
            try:
                client, addr = self._server.accept()
                # Cada conexao e tratada em sua propria thread
                t = threading.Thread(target=self._handle_client,
                                     args=(client, addr), daemon=True)
                t.start()
            except socket.timeout:
                continue
            except OSError:
                if self.running:
                    time.sleep(0.5)

    # Trata uma conexao TCP individual
    # Le mensagens em loop enquanto o cliente enviar:
    # 1. Le header de 4 bytes (tamanho da mensagem)
    # 2. Le N bytes da mensagem
    # 3. Processa a mensagem JSON
    # 4. Repete ate desconexao
    def _handle_client(self, client, addr):
        client.settimeout(30.0)  # 30s sem dados = desconecta
        try:
            while self.running:
                # Le header de 4 bytes com tamanho da mensagem
                header = self._recv_exact(client, 4)
                if not header:
                    break  # Conexao fechada
                msg_len = struct.unpack('!I', header)[0]  # Big-endian uint32

                # Protecao contra mensagens gigantes (max 10MB)
                if msg_len > 10 * 1024 * 1024:
                    break

                # Le o corpo da mensagem
                data = self._recv_exact(client, msg_len)
                if not data:
                    break

                # Processa a mensagem
                self._process_message(data, addr, client)
        except (socket.timeout, ConnectionResetError, OSError):
            pass  # Desconexao normal ou timeout
        finally:
            client.close()  # Sempre fecha o socket

    # Recebe exatamente N bytes do socket
    # TCP pode fragmentar dados, entao precisamos ler em loop
    # ate acumular o numero exato de bytes esperados
    # Retorna bytes se sucesso, None se conexao fechada
    def _recv_exact(self, sock, n):
        buf = bytearray()
        while len(buf) < n:
            try:
                chunk = sock.recv(n - len(buf))
                if not chunk:
                    return None  # Conexao fechada pelo peer
                buf.extend(chunk)
            except (socket.timeout, OSError):
                return None
        return bytes(buf)

    # Processa uma mensagem JSON recebida via TCP
    # Roteia para o callback apropriado baseado no tipo:
    # - MT_FILE_REQ: pedido de arquivo -> on_file_request
    # - Outros: mensagem geral -> on_message
    def _process_message(self, data, addr, client):
        try:
            msg = json.loads(data.decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return  # Mensagem invalida

        msg_type = msg.get('type')
        if msg_type == MT_FILE_REQ and self.on_file_request:
            self.on_file_request(msg, addr)  # Pedido de arquivo
        elif msg_type == MT_FILE_ACC:
            pass  # Aceitacao de arquivo (tratada pelo sender)
        elif self.on_message:
            self.on_message(msg, addr)  # Mensagem geral (texto, grupo, etc.)


# ========================================
# TCP CLIENT — Envia mensagens via TCP
# ========================================

# Cliente TCP para enviar mensagens
# Metodos estaticos (sem instancia necessaria)
# Cada envio cria uma conexao TCP nova, envia e fecha
class TCPClient:

    @staticmethod
    # Envia uma mensagem JSON via TCP
    # Protocolo: [4 bytes tamanho][N bytes JSON]
    # ip: IP do destinatario
    # port: Porta TCP do destinatario
    # message_dict: Dict a ser serializado como JSON
    # Retorna True se enviou com sucesso, False se houve erro
    def send_message(ip, port, message_dict):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(10.0)  # 10s para conectar e enviar
            sock.connect((ip, port))
            data = json.dumps(message_dict, ensure_ascii=False).encode('utf-8')
            # Envia header (4 bytes big-endian) + corpo JSON
            sock.sendall(struct.pack('!I', len(data)) + data)
            sock.close()
            return True
        except Exception as e:
            return False

    @staticmethod
    # Envia mensagem e aguarda resposta JSON
    # Usado quando precisamos de confirmacao do destinatario
    # Retorna Dict com resposta se sucesso, None se erro
    def send_message_with_response(ip, port, message_dict, timeout=10):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect((ip, port))
            data = json.dumps(message_dict, ensure_ascii=False).encode('utf-8')
            sock.sendall(struct.pack('!I', len(data)) + data)

            # Le header da resposta
            header = b''
            while len(header) < 4:
                chunk = sock.recv(4 - len(header))
                if not chunk:
                    sock.close()
                    return None
                header += chunk
            resp_len = struct.unpack('!I', header)[0]

            # Le corpo da resposta
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


# ========================================
# FILE SENDER — Envia arquivos via TCP
# ========================================

# Envia arquivo via TCP dedicado (porta TCP_PORT + 1)
# Protocolo:
# 1. Conecta na porta de arquivo do receiver
# 2. Envia header JSON com file_id, filename, filesize
# 3. Aguarda resposta: b'OKAY' (aceito) ou b'DENY' (recusado)
# 4. Se aceito, envia arquivo em chunks de 256KB
# 5. Reporta progresso via callback
class FileSender:

    # Inicializa o sender
    # filepath: Caminho do arquivo a enviar
    # peer_ip: IP do destinatario
    # peer_port: Porta TCP base (file port = peer_port + 1)
    # file_id: ID unico desta transferencia
    # on_progress: Callback(file_id, sent, total) para atualizar progresso
    # on_complete: Callback(file_id) quando envio completar
    # on_error: Callback(file_id, error_msg) quando houver erro
    def __init__(self, filepath, peer_ip, peer_port, file_id,
                 on_progress=None, on_complete=None, on_error=None):
        self.filepath = filepath
        self.peer_ip = peer_ip
        self.peer_port = peer_port
        self.file_id = file_id
        self.on_progress = on_progress
        self.on_complete = on_complete
        self.on_error = on_error
        self.cancelled = False  # Flag para cancelamento
        self.filesize = os.path.getsize(filepath)  # Tamanho do arquivo

    # Inicia envio em thread background
    def start(self):
        t = threading.Thread(target=self._send, daemon=True)
        t.start()

    # Cancela o envio em andamento
    def cancel(self):
        self.cancelled = True

    # Thread de envio do arquivo
    def _send(self):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(120.0)  # 2 min para usuario aceitar
            sock.connect((self.peer_ip, self.peer_port + 1))  # File port = TCP+1

            # Envia header JSON com informacoes do arquivo
            header = json.dumps({
                'file_id': self.file_id,
                'filename': os.path.basename(self.filepath),
                'filesize': self.filesize
            }).encode('utf-8')
            sock.sendall(struct.pack('!I', len(header)) + header)

            # Aguarda resposta do receiver (aceitar ou recusar)
            resp = sock.recv(4)
            if not resp:
                if self.on_error:
                    self.on_error(self.file_id, 'Conexao perdida')
                sock.close()
                return
            if resp != b'OKAY':
                if self.on_error:
                    self.on_error(self.file_id, 'Recusado')
                sock.close()
                return

            # Envia dados do arquivo em chunks de 256KB
            sent = 0
            with open(self.filepath, 'rb') as f:
                while not self.cancelled:
                    chunk = f.read(FILE_CHUNK)  # Le 256KB
                    if not chunk:
                        break  # Fim do arquivo
                    sock.sendall(chunk)  # Envia chunk
                    sent += len(chunk)
                    if self.on_progress:
                        self.on_progress(self.file_id, sent, self.filesize)

            sock.close()
            if not self.cancelled and self.on_complete:
                self.on_complete(self.file_id)  # Sucesso
            elif self.cancelled and self.on_error:
                self.on_error(self.file_id, 'Cancelado')  # Cancelado pelo usuario
        except Exception as e:
            if self.on_error:
                self.on_error(self.file_id, str(e))


# ========================================
# FILE RECEIVER — Recebe arquivos via TCP
# ========================================

# Servidor para receber arquivos (porta TCP_PORT + 1)
# Protocolo:
# 1. Aceita conexao na porta de arquivo
# 2. Le header JSON com file_id, filename, filesize
# 3. Notifica GUI para pedir aceitacao do usuario
# 4. Se aceito, salva arquivo em temp (.tmp) e renomeia ao completar
# 5. Trata duplicatas adicionando sufixo numerico ao nome
class FileReceiver:

    # Inicializa o receiver
    # save_dir: Diretorio onde salvar arquivos recebidos
    # on_incoming: Callback(file_id, filename, filesize, ip) para pedido recebido
    # on_progress: Callback(file_id, received, total) para progresso
    # on_complete: Callback(file_id, save_path) quando completo
    # on_error: Callback(file_id, error_msg) quando erro
    def __init__(self, save_dir, on_incoming=None, on_progress=None,
                 on_complete=None, on_error=None):
        self.save_dir = save_dir
        self.on_incoming = on_incoming
        self.on_progress = on_progress
        self.on_complete = on_complete
        self.on_error = on_error
        self.running = False
        self._server = None
        self._pending_accepts = {}  # file_id -> True/False (decisao do usuario)
        self._lock = threading.Lock()

    # Inicia o servidor de recebimento de arquivos
    def start(self):
        self.running = True
        os.makedirs(self.save_dir, exist_ok=True)  # Cria pasta de downloads
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        # Tenta bind com fallback (porta = TCP_PORT + 1 = 50102) e 0 (dinamico) como ultima opcao
        bound = False
        self.port = TCP_PORT + 1
        for port in [TCP_PORT + 1, TCP_PORT + 11, TCP_PORT + 21, 0]:
            try:
                self._server.bind(('', port))
                self.port = self._server.getsockname()[1]  # Pega a porta efetiva
                bound = True
                break
            except (PermissionError, OSError):
                continue
                
        if not bound:
            return  # Evita erro 10022 de socket se falhar na porta 0 tb
            
        self._server.listen(100)
        self._server.settimeout(0.3)

        # Thread que aceita conexoes de arquivo
        t = threading.Thread(target=self._accept_loop, daemon=True)
        t.start()

    # Para o servidor de arquivos
    def stop(self):
        self.running = False
        if self._server:
            self._server.close()

    # GUI chama este metodo quando usuario aceita o arquivo
    def accept_file(self, file_id):
        with self._lock:
            self._pending_accepts[file_id] = True

    # GUI chama este metodo quando usuario recusa o arquivo
    def decline_file(self, file_id):
        with self._lock:
            self._pending_accepts[file_id] = False

    # Loop que aceita conexoes de arquivo
    def _accept_loop(self):
        while self.running:
            try:
                client, addr = self._server.accept()
                # Cada arquivo em sua propria thread
                t = threading.Thread(target=self._handle_file,
                                     args=(client, addr), daemon=True)
                t.start()
            except socket.timeout:
                continue
            except OSError:
                if self.running:
                    time.sleep(0.5)

    # Trata uma transferencia de arquivo individual
    # 1. Le header com info do arquivo
    # 2. Notifica GUI e aguarda decisao do usuario (ate 60s)
    # 3. Se aceito, recebe dados e salva em temp file
    # 4. Se completo, renomeia temp -> arquivo final
    def _handle_file(self, client, addr):
        file_id = None
        tmp_path = None   # Caminho do arquivo temporario
        save_path = None  # Caminho final
        try:
            client.settimeout(120.0)  # 2 min de timeout

            # Le tamanho do header (4 bytes)
            hdr_len_data = b''
            while len(hdr_len_data) < 4:
                chunk = client.recv(4 - len(hdr_len_data))
                if not chunk:
                    client.close()
                    return
                hdr_len_data += chunk

            # Le o header JSON
            hdr_len = struct.unpack('!I', hdr_len_data)[0]
            hdr_data = b''
            while len(hdr_data) < hdr_len:
                chunk = client.recv(hdr_len - len(hdr_data))
                if not chunk:
                    break
                hdr_data += chunk

            # Extrai informacoes do arquivo
            info = json.loads(hdr_data.decode('utf-8'))
            file_id = info['file_id']
            filename = info['filename']
            filesize = info['filesize']

            # Notifica GUI para mostrar dialogo de aceitacao
            if self.on_incoming:
                self.on_incoming(file_id, filename, filesize, addr[0])

            # Aguarda decisao do usuario (polling a cada 200ms, max 60s)
            deadline = time.time() + 60
            accepted = None
            while time.time() < deadline:
                with self._lock:
                    if file_id in self._pending_accepts:
                        accepted = self._pending_accepts.pop(file_id)
                        break
                time.sleep(0.2)

            if not accepted:
                client.sendall(b'DENY')  # Recusado ou timeout
                client.close()
                return

            client.sendall(b'OKAY')  # Aceito, pode enviar

            # Sanitiza nome do arquivo (remove caracteres perigosos)
            safe_name = "".join(c for c in filename
                                if c.isalnum() or c in '.-_ ')
            if not safe_name:
                safe_name = f'file_{file_id[:8]}'
            save_path = os.path.join(self.save_dir, safe_name)

            # Trata nomes duplicados adicionando _1, _2, etc.
            base, ext = os.path.splitext(save_path)
            counter = 1
            while os.path.exists(save_path):
                save_path = f"{base}_{counter}{ext}"
                counter += 1

            # Salva em arquivo temporario (.tmp) para atomicidade
            tmp_path = save_path + '.tmp'
            received = 0
            with open(tmp_path, 'wb') as f:
                while received < filesize:
                    chunk = client.recv(min(FILE_CHUNK, filesize - received))
                    if not chunk:
                        break  # Conexao perdida
                    f.write(chunk)
                    received += len(chunk)
                    if self.on_progress:
                        self.on_progress(file_id, received, filesize)

            client.close()

            if received >= filesize:
                # Transferencia completa: renomeia temp -> final
                os.rename(tmp_path, save_path)
                tmp_path = None  # Marca como None para nao deletar no finally
                if self.on_complete:
                    self.on_complete(file_id, save_path)
            else:
                # Transferencia incompleta
                if self.on_error:
                    self.on_error(file_id, 'Transferencia incompleta')
        except Exception as e:
            if file_id and self.on_error:
                self.on_error(file_id, str(e))
            try:
                client.close()
            except Exception:
                pass
        finally:
            # Limpa arquivo temporario se transferencia nao completou
            if tmp_path:
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
