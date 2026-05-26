# test_vpn_relay.py
# Valida as novas correções de VPN e retransmissão de mensagens.
# Rodar: python test_vpn_relay.py

import socket
import json
import threading
import time
import sys
from network import UDPDiscovery, TCPClient, MT_ANNOUNCE
from messenger import Messenger
from database import Database

PASS = []
FAIL = []

def ok(msg):
    PASS.append(msg)
    print(f'  PASS  {msg}')

def fail(msg, detail=''):
    FAIL.append(msg)
    print(f'  FAIL  {msg}' + (f': {detail}' if detail else ''))

# Mock do Database para testes rápidos
class MockDB:
    def __init__(self):
        self.settings = {}
        self.contacts = {}
        self.blocked = set()

    def get_setting(self, key, default):
        return self.settings.get(key, default)

    def set_setting(self, key, val):
        self.settings[key] = val

    def get_manual_peers(self):
        return [{'ip': '127.0.0.1', 'note': 'Mock Anchor'}]

    def get_contact(self, uid):
        return self.contacts.get(uid)

    def get_contacts(self):
        return list(self.contacts.values())

    def is_blocked(self, uid):
        return uid in self.blocked

# Mock do UDPDiscovery/Messenger
class MockMessenger:
    def __init__(self):
        self.db = MockDB()
        self.user_id = 'my_user_id'
        self.display_name = 'My User'
        self.discovery = type('MockDiscovery', (object,), {'peers': {}})()
        
    def is_vpn_enabled(self):
        val = self.db.get_setting('vpn_enabled', '0')
        return str(val) in ('1', 'true', 'True')

    def get_manual_peers(self):
        return self.db.get_manual_peers()

# -------------------------------------------------------------
# 1. Teste de Resolução de IP do Peer Unicast (via_manual = True)
# -------------------------------------------------------------
def test_peer_ip_resolution():
    print('\n[Teste 1] Resolução de IP de Peer Unicast via VPN')
    
    # Criamos uma instância do UDPDiscovery
    discovery = UDPDiscovery('test_user', 'Test User', 'online')
    discovery.running = True
    
    # Pacote simulando announce vindo via_manual (VPN) sem ts_ip
    pkt = {
        'app': 'mbchat',
        'type': MT_ANNOUNCE,
        'user_id': 'remote_user',
        'display_name': 'Remote User',
        'ip': '192.168.1.50', # IP local doméstico do remote_user
        'ts_ip': None,        # Sem Tailscale
        'via_manual': True
    }
    
    # Simula recebimento de pacote vindo do IP de VPN '10.8.0.50'
    addr = ('10.8.0.50', 50100)
    data = json.dumps(pkt).encode('utf-8')
    
    # Vamos rodar _handle_packet de forma segura
    try:
        discovery._handle_packet(data, addr)
        peer = discovery.peers.get('remote_user')
        if peer:
            # Deve ter resolvido o IP do peer como '10.8.0.50' (addr[0]) e não '192.168.1.50'
            if peer['ip'] == '10.8.0.50':
                ok('IP resolvido corretamente para o IP da VPN (addr[0])')
            else:
                fail(f"IP resolvido incorretamente: esperado 10.8.0.50, obteve {peer['ip']}")
        else:
            fail('Peer remote_user não foi adicionado ao discovery.peers')
    except Exception as e:
        fail('Falha ao processar _handle_packet', str(e))
    finally:
        discovery.running = False

# -------------------------------------------------------------
# 2. Teste de Relatório de IP no Announce Relay (Proxy)
# -------------------------------------------------------------
def test_announce_relay():
    print('\n[Teste 2] Modificação de IP no Announce Relay')
    
    discovery = UDPDiscovery('test_user', 'Test User', 'online')
    discovery.running = True
    
    # Capturador de envio UDP
    sent_packets = []
    def mock_sendto(self_mock, data, dest):
        sent_packets.append((data, dest))
    
    discovery._sock_send = type('MockSocket', (object,), {'sendto': mock_sendto})()
    
    pkt = {
        'app': 'mbchat',
        'type': MT_ANNOUNCE,
        'user_id': 'remote_user',
        'display_name': 'Remote User',
        'ip': '192.168.1.50', # IP local doméstico
        'ts_ip': None,
        'via_manual': True
    }
    addr = ('10.8.0.50', 50100)
    data = json.dumps(pkt).encode('utf-8')
    
    try:
        discovery._handle_packet(data, addr)
        
        # O socket deve ter recebido anúncios de retransmissão
        relayed = False
        for d, dest in sent_packets:
            try:
                p = json.loads(d.decode('utf-8'))
                if p.get('user_id') == 'remote_user':
                    # O IP no pacote retransmitido deve ter sido alterado para '10.8.0.50' (addr[0])
                    if p.get('ip') == '10.8.0.50':
                        relayed = True
            except Exception:
                pass
        
        if relayed:
            ok('IP no Announce Relay alterado corretamente para o IP da VPN (addr[0])')
        else:
            print("DEBUG: sent_packets =", sent_packets)
            print("DEBUG: health =", discovery.health)
            fail('IP do Announce Relay permaneceu conflituoso ou não foi retransmitido')
    except Exception as e:
        import traceback
        traceback.print_exc()
        fail('Erro no teste de Announce Relay', str(e))
    finally:
        discovery.running = False

# -------------------------------------------------------------
# 3. Teste do Handler de Fallback do TCPClient
# -------------------------------------------------------------
def test_tcp_client_fallback():
    print('\n[Teste 3] Acionamento de Fallback do TCPClient')
    
    # Registra fallback handler manual
    fallback_invoked = threading.Event()
    def mock_fallback(ip, port, message_dict):
        fallback_invoked.set()
        return True
        
    TCPClient.fallback_handler = mock_fallback
    
    # Tenta enviar para um IP inválido/fechado
    res = TCPClient.send_message('127.0.0.1', 9999, {'type': 'test'})
    
    if fallback_invoked.is_set() and res:
        ok('Fallback handler foi chamado e executado após falha de conexão')
    else:
        fail('Fallback handler não foi acionado ou retornou False')
        
    # Limpa fallback
    TCPClient.fallback_handler = None

# -------------------------------------------------------------
# 4. Teste de Não-Regressão na Rede Local (Sem VPN)
# -------------------------------------------------------------
def test_non_regression_local_lan():
    print('\n[Teste 4] Não-Regressão na LAN Local (VPN desligada)')
    
    msg_instance = MockMessenger()
    msg_instance.db.set_setting('vpn_enabled', '0') # VPN desligada
    
    fallback_invoked = threading.Event()
    def fallback_wrapper(ip, port, message_dict):
        fallback_invoked.set()
        return msg_instance._tcp_fallback_handler(ip, port, message_dict)
        
    TCPClient.fallback_handler = fallback_wrapper
    
    # Tenta enviar (falhará porque a porta 9999 está fechada)
    res = TCPClient.send_message('127.0.0.1', 9999, {'type': 'test'})
    
    if fallback_invoked.is_set() and not res:
        ok('Fallback wrapper invocado, mas retornou False porque a VPN está desativada (Correto)')
    else:
        fail('Lógica de fallback se comportou incorretamente com VPN desativada')
        
    TCPClient.fallback_handler = None

# -------------------------------------------------------------
# Resultado final
# -------------------------------------------------------------
# 5. Teste de Relacionamento Completo: Fallback + Anchor Forwarding
# -------------------------------------------------------------
def test_full_relay_flow():
    print('\n[Teste 5] Fluxo Completo de Relay (Cliente -> Anchor -> Destinatário)')
    
    # 1. Setup do Anchor (Ponte)
    anchor = MockMessenger()
    anchor.user_id = 'anchor_user'
    anchor.display_name = 'Anchor User'
    anchor.db.set_setting('vpn_enabled', '1') # VPN ativada
    
    # Adiciona o destinatário final nos contatos do Anchor
    target_contact = {
        'user_id': 'target_user',
        'display_name': 'Target User',
        'ip_address': '192.168.0.20'
    }
    anchor.db.contacts['target_user'] = target_contact
    
    # Mock do envio final da âncora para o destinatário
    forwarded_packets = []
    def mock_send_message_anchor(ip, port, message_dict):
        forwarded_packets.append((ip, port, message_dict))
        return True
        
    # Salva original
    orig_send = TCPClient.send_message
    TCPClient.send_message = mock_send_message_anchor
    
    # 2. Simula o Anchor recebendo a mensagem TCP do cliente remoto
    # O cliente remoto quer enviar para 'target_user', mas enviou para o Anchor.
    incoming_msg = {
        'type': 'message',
        'from_user': 'remote_user',
        'to_user': 'target_user',
        'content': 'Ola!',
        'msg_id': 'msg123',
        'timestamp': time.time(),
        'is_relayed': True
    }
    
    # Aciona _on_tcp_message no Anchor
    # (Como o to_user 'target_user' != self.user_id 'anchor_user', a âncora deve retransmitir para '192.168.0.20')
    anchor._on_tcp_message = Messenger._on_tcp_message.__get__(anchor, MockMessenger)
    anchor._on_tcp_message(incoming_msg, ('10.8.0.50', 50101))
    
    # Aguarda a thread assíncrona de retransmissão
    time.sleep(0.1)
    
    # Restaura original
    TCPClient.send_message = orig_send
    
    if len(forwarded_packets) == 1:
        ip, port, msg = forwarded_packets[0]
        if ip == '192.168.0.20' and msg.get('to_user') == 'target_user' and msg.get('is_relayed'):
            ok('Anchor retransmitiu com sucesso a mensagem para o destinatário final na LAN')
        else:
            fail(f'Retransmissão incorreta: IP={ip}, MSG={msg}')
    else:
        fail(f'Nenhuma ou múltiplas retransmissões detectadas: {len(forwarded_packets)}')

# -------------------------------------------------------------
# 6. Teste de Fallback do Cliente (Envio falha -> tenta Anchor)
# -------------------------------------------------------------
def test_client_fallback_to_anchor():
    print('\n[Teste 6] Fallback do Cliente (Direto falha -> envia para Anchor)')
    
    client = MockMessenger()
    client.user_id = 'remote_user'
    client.db.set_setting('vpn_enabled', '1') # VPN ativada
    # Cadastra o Anchor como manual peer do cliente
    client.db.settings['vpn_enabled'] = '1'
    client.db.get_manual_peers = lambda: [{'ip': '10.8.0.1', 'note': 'Anchor'}]
    
    # Registra o fallback_handler no TCPClient (como o Messenger original faz)
    client._tcp_fallback_handler = Messenger._tcp_fallback_handler.__get__(client, MockMessenger)
    TCPClient.fallback_handler = client._tcp_fallback_handler
    
    # Mock do banco para obter contatos
    target_contact = {
        'user_id': 'target_user',
        'display_name': 'Target User',
        'ip_address': '192.168.0.20'
    }
    client.db.contacts['target_user'] = target_contact
    # Popula cache de discovery.peers para resolução do to_user pelo IP
    client.discovery.peers['target_user'] = {'ip': '192.168.0.20'}
    
    # Mock do socket TCP: envio direto falha, envio para o Anchor funciona
    socket_calls = []
    def mock_send_message_client(ip, port, message_dict):
        socket_calls.append((ip, port, message_dict))
        if ip == '192.168.0.20':
            # Simula falha e repassa para o fallback handler
            if TCPClient.fallback_handler:
                return TCPClient.fallback_handler(ip, port, message_dict)
            return False
        if ip == '10.8.0.1':
            return True # Envio para o Anchor funciona
        return False
        
    orig_send = TCPClient.send_message
    TCPClient.send_message = mock_send_message_client
    
    # Executa a ação de envio
    payload = {
        'type': 'message',
        'from_user': 'remote_user',
        'content': 'Ola!',
        'msg_id': 'msg123'
    }
    
    # Tenta enviar diretamente para o IP do destinatário (que vai falhar e acionar o fallback)
    res = TCPClient.send_message('192.168.0.20', 50101, payload)
    
    TCPClient.send_message = orig_send
    TCPClient.fallback_handler = None
    
    if res:
        # Verifica se tentou enviar primeiro direto e depois via Anchor
        if len(socket_calls) == 2:
            first_ip, _, _ = socket_calls[0]
            second_ip, _, second_msg = socket_calls[1]
            if first_ip == '192.168.0.20' and second_ip == '10.8.0.1':
                if second_msg.get('to_user') == 'target_user' and second_msg.get('is_relayed'):
                    ok('Cliente desviou com sucesso o envio da mensagem para o Anchor após falha direta')
                else:
                    fail(f'Mensagem desviada incorreta: {second_msg}')
            else:
                fail(f'Ordem de IPs incorreta: 1o={first_ip}, 2o={second_ip}')
        else:
            fail(f'Número incorreto de tentativas: {len(socket_calls)}')
    else:
        fail('Envio falhou completamente mesmo com o fallback ativado')

# -------------------------------------------------------------
# 7. Teste de IP Pinning Bypass para Pacotes Relayed e de Mesma Subrede
# -------------------------------------------------------------
def test_ip_pinning_bypass_and_subnet_handling():
    print('\n[Teste 7] Bypass de IP Pinning (via_relay) e Tratamento de Subrede')
    
    discovery = UDPDiscovery('test_user', 'Test User', 'online')
    discovery.running = True
    
    # Caso A: via_relay = True. O IP declarado do peer NÃO deve ser sobrescrito pelo IP de origem
    pkt_relay = {
        'app': 'mbchat',
        'type': MT_ANNOUNCE,
        'user_id': 'relay_user',
        'display_name': 'Relayed User',
        'ip': '10.0.0.5', # IP da VPN real do peer
        'via_manual': False,
        'via_relay': True
    }
    
    # Pedro's PC retransmite, então chega com IP de Pedro (192.168.0.216)
    addr_pedro = ('192.168.0.216', 50100)
    data_relay = json.dumps(pkt_relay).encode('utf-8')
    
    # Caso B: via_manual = True, mas o IP de origem (addr[0]) foi mascarado (NATed) na mesma subrede que a nossa
    # ex: Pedro está em 192.168.0.216 (mesma subrede que 192.168.0.238), e recebe de 192.168.0.238
    pkt_masqueraded = {
        'app': 'mbchat',
        'type': MT_ANNOUNCE,
        'user_id': 'masq_user',
        'display_name': 'Masqueraded User',
        'ip': '10.0.0.9', # IP real da VPN
        'via_manual': True
    }
    # Chega do IP mascarado pelo gateway (192.168.0.238)
    addr_masq = ('192.168.0.238', 50100)
    data_masq = json.dumps(pkt_masqueraded).encode('utf-8')

    try:
        # Executa Caso A (via_relay)
        discovery._handle_packet(data_relay, addr_pedro)
        peer_a = discovery.peers.get('relay_user')
        if peer_a and peer_a['ip'] == '10.0.0.5':
            ok('IP Pinning pulado com sucesso para pacotes com via_relay=True')
        else:
            fail(f"IP Pinning falhou para via_relay: esperado 10.0.0.5, obteve {peer_a['ip'] if peer_a else 'None'}")
            
        # Executa Caso B (VPN NATed)
        discovery._handle_packet(data_masq, addr_masq)
        peer_b = discovery.peers.get('masq_user')
        if peer_b and peer_b['ip'] == '10.0.0.9':
            ok('IP resolvido para o IP declarado da VPN quando o IP do socket está mascarado na mesma LAN')
        else:
            fail(f"IP resolvido incorretamente para pacote mascarado: esperado 10.0.0.9, obteve {peer_b['ip'] if peer_b else 'None'}")
            
    except Exception as e:
        fail('Erro ao executar testes de bypass e subrede', str(e))
    finally:
        discovery.running = False

# -------------------------------------------------------------
# 8. Teste de Proteção contra Relays Incorretos de Clientes Antigos
# -------------------------------------------------------------
def test_old_client_relay_protection():
    print('\n[Teste 8] Proteção contra Relays Incorretos de Clientes Antigos na LAN')
    
    discovery = UDPDiscovery('test_user', 'Test User', 'online')
    discovery.running = True
    
    # 1. Popula Aline na nossa lista com o IP de VPN correto (10.0.0.5)
    discovery.peers['aline_user'] = {
        'user_id': 'aline_user',
        'display_name': 'Aline',
        'ip': '10.0.0.5',
        'status': 'online',
        'last_seen': time.time()
    }
    
    # 2. Popula Lucas Mendes na nossa lista com o IP dele (192.168.0.14)
    discovery.peers['lucas_user'] = {
        'user_id': 'lucas_user',
        'display_name': 'Lucas Mendes',
        'ip': '192.168.0.14',
        'status': 'online',
        'last_seen': time.time()
    }
    
    # Caso A: Chega um anúncio da Aline enviado (relatado) por Lucas Mendes (IP de origem = 192.168.0.14)
    # por causa do cliente antigo rodando na máquina de Lucas, que mandou via_manual = False.
    pkt_old_relay = {
        'app': 'mbchat',
        'type': MT_ANNOUNCE,
        'user_id': 'aline_user',
        'display_name': 'Aline',
        'ip': '192.168.0.14', # O cliente antigo inseriu o IP NATed no pacote
        'via_manual': False
    }
    
    addr_lucas = ('192.168.0.14', 50100)
    data_old_relay = json.dumps(pkt_old_relay).encode('utf-8')
    
    try:
        discovery._handle_packet(data_old_relay, addr_lucas)
        peer = discovery.peers.get('aline_user')
        if peer and peer['ip'] == '10.0.0.5':
            ok('IP da Aline protegido contra relay incorreto do Lucas Mendes (IP manteve 10.0.0.5)')
        else:
            fail(f"IP da Aline foi poluído/sobrescrito: esperado 10.0.0.5, obteve {peer['ip'] if peer else 'None'}")
            
    except Exception as e:
        fail('Erro ao executar teste de proteção contra relays antigos', str(e))
    finally:
        discovery.running = False

# -------------------------------------------------------------
# Resultado final
# -------------------------------------------------------------
if __name__ == '__main__':
    test_peer_ip_resolution()
    test_announce_relay()
    test_tcp_client_fallback()
    test_non_regression_local_lan()
    test_full_relay_flow()
    test_client_fallback_to_anchor()
    test_ip_pinning_bypass_and_subnet_handling()
    test_old_client_relay_protection()

    print(f'\n{"="*50}')
    print(f'  {len(PASS)} passou   {len(FAIL)} falhou')
    print('='*50)
    sys.exit(0 if not FAIL else 1)
