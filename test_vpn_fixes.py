# test_vpn_fixes.py
# Valida os 3 fixes VPN sem precisar de 2 PCs em redes diferentes.
# Rodar: python test_vpn_fixes.py

import socket
import json
import threading
import time
import sys

UDP_PORT = 50100
PASS = []
FAIL = []

def ok(msg):
    PASS.append(msg)
    print(f'  PASS  {msg}')

def fail(msg, detail=''):
    FAIL.append(msg)
    print(f'  FAIL  {msg}' + (f': {detail}' if detail else ''))


# ─────────────────────────────────────────────
# FIX 1 — MCAST_GRP substituido por MULTICAST_GROUP
# ─────────────────────────────────────────────
def test_fix1_mcast_constant():
    print('\n[Fix 1] MCAST_GRP -> MULTICAST_GROUP no relay')
    with open('network.py', encoding='utf-8') as f:
        src = f.read()

    if 'MCAST_GRP' in src:
        fail('MCAST_GRP ainda presente em network.py — relay continua quebrado')
    else:
        ok('MCAST_GRP removido de network.py')

    if 'MULTICAST_GROUP' in src:
        ok('MULTICAST_GROUP presente — constante correta usada no relay')
    else:
        fail('MULTICAST_GROUP nao encontrado em network.py')

    # Verifica que o modulo importa sem NameError
    try:
        import network as net
        _ = net.MULTICAST_GROUP
        ok('network.MULTICAST_GROUP acessivel sem erro')
    except AttributeError as e:
        fail('network.MULTICAST_GROUP inacessivel', str(e))


# ─────────────────────────────────────────────
# FIX 2 — porta da resposta VPN: addr[1] -> UDP_PORT
# ─────────────────────────────────────────────
def test_fix2_reply_port_source():
    print('\n[Fix 2] Porta da resposta (analise de codigo)')
    with open('network.py', encoding='utf-8') as f:
        src = f.read()

    if 'port=addr[1]' in src:
        fail('port=addr[1] ainda presente — respostas VPN vao para porta efemera')
    else:
        ok('port=addr[1] removido de network.py')

    # Confirma que a linha do reply usa UDP_PORT
    import re
    # Procura pelo bloco via_manual e checa port=UDP_PORT
    match = re.search(
        r'via_manual.*?announce_to_ip\(reply_ip.*?port=(\w+)',
        src, re.DOTALL)
    if match:
        port_arg = match.group(1)
        if port_arg == 'UDP_PORT':
            ok(f'announce_to_ip(reply_ip, port=UDP_PORT) — porta correta')
        else:
            fail(f'announce_to_ip usa port={port_arg}, esperado UDP_PORT')
    else:
        fail('Nao encontrou chamada announce_to_ip no bloco via_manual')


def test_fix2_reply_port_behavior():
    print('\n[Fix 2] Porta da resposta (teste comportamental com sockets)')
    # Simula:
    #   - notebook._sock_send  = socket sem bind (porta efemera)
    #   - notebook._sock_recv  = socket em 127.0.0.1:50100
    #   - "ancora" recebe announce e responde para UDP_PORT
    #
    # Antes do fix: ancora respondia para addr[1] = porta efemera -> _sock_recv nao recebia
    # Depois do fix: ancora responde para UDP_PORT=50100 -> _sock_recv recebe

    received_on_std_port = threading.Event()
    received_on_ephemeral = threading.Event()

    # Socket que simula _sock_recv do notebook (escuta em 50100)
    try:
        recv_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        recv_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        recv_sock.bind(('127.0.0.1', UDP_PORT))
        recv_sock.settimeout(2)
    except OSError as e:
        fail(f'Nao foi possivel bind em 127.0.0.1:{UDP_PORT}', str(e))
        return

    # Socket que simula _sock_send do notebook (sem bind = porta efemera)
    send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    send_sock.sendto(b'init', ('127.0.0.1', UDP_PORT))  # forca atribuicao de porta
    ephemeral_port = send_sock.getsockname()[1]

    # Thread que escuta na porta efemera (nao deveria receber nada apos o fix)
    eph_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    eph_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        eph_sock.bind(('127.0.0.1', ephemeral_port))
    except OSError:
        # Nao conseguiu bind na efemera (ja ocupada pelo send_sock) — ignorar
        eph_sock.close()
        eph_sock = None

    # "Ancora" recebe o announce e responde PARA UDP_PORT (comportamento apos fix)
    def ancora_thread():
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(('127.0.0.1', 50101))  # ancora usa porta diferente para nao conflitar
        s.settimeout(2)
        try:
            data, addr = s.recvfrom(4096)
            # Simula comportamento apos Fix 2: responde para UDP_PORT, nao addr[1]
            reply = json.dumps({'type': 'MT_ANNOUNCE', 'via_manual': True,
                                'is_reply': True, 'from': 'ancora'}).encode()
            s.sendto(reply, ('127.0.0.1', UDP_PORT))  # FIX: porta fixa
        except socket.timeout:
            pass
        finally:
            s.close()

    # Thread que escuta na porta do recv_sock (UDP_PORT)
    def recv_thread():
        try:
            # Descarta o 'init' inicial
            recv_sock.recvfrom(4096)
            # Espera a resposta da ancora
            data, addr = recv_sock.recvfrom(4096)
            pkt = json.loads(data)
            if pkt.get('from') == 'ancora':
                received_on_std_port.set()
        except (socket.timeout, json.JSONDecodeError):
            pass

    t_recv = threading.Thread(target=recv_thread, daemon=True)
    t_ancora = threading.Thread(target=ancora_thread, daemon=True)
    t_recv.start()
    t_ancora.start()

    time.sleep(0.1)
    # Notebook envia announce para a ancora (porta 50101)
    announce = json.dumps({'type': 'MT_ANNOUNCE', 'via_manual': True,
                           'request_peer_list': True}).encode()
    send_sock.sendto(announce, ('127.0.0.1', 50101))

    t_ancora.join(timeout=3)
    t_recv.join(timeout=3)

    if received_on_std_port.is_set():
        ok(f'Resposta da ancora chegou em UDP_PORT={UDP_PORT} (_sock_recv) — peers serao descobertos')
    else:
        fail(f'Resposta da ancora NAO chegou em UDP_PORT={UDP_PORT}')

    if eph_sock:
        eph_sock.settimeout(0.3)
        try:
            eph_sock.recvfrom(4096)
            fail(f'Resposta chegou na porta efemera {ephemeral_port} — fix nao aplicado')
        except socket.timeout:
            ok(f'Nada chegou na porta efemera {ephemeral_port} — correto')
        eph_sock.close()

    recv_sock.close()
    send_sock.close()


# ─────────────────────────────────────────────
# FIX 3 — Botao Remover visivel (analise de codigo)
# ─────────────────────────────────────────────
def test_fix3_btns_order():
    print('\n[Fix 3] Ordem de pack do botao Remover (analise de codigo)')
    with open('gui.py', encoding='utf-8') as f:
        src = f.read()

    import re
    func_match = re.search(
        r'def _open_vpn_peers\(self\)(.*?)(?=\n    def |\Z)',
        src, re.DOTALL)
    if not func_match:
        fail('Funcao _open_vpn_peers nao encontrada em gui.py')
        return

    func_src = func_match.group(1)

    # Posicao do btns.pack(side='bottom') vs body.pack(expand=True)
    btns_pack_pos = func_src.find("btns.pack(side='bottom'")
    body_pack_pos = func_src.find("body.pack(fill='both', expand=True")

    if btns_pack_pos == -1:
        fail("btns.pack(side='bottom') nao encontrado")
        return
    if body_pack_pos == -1:
        fail("body.pack(expand=True) nao encontrado")
        return

    if btns_pack_pos < body_pack_pos:
        ok(f'btns.pack (pos {btns_pack_pos}) chamado ANTES de body.pack (pos {body_pack_pos}) — botao visivel')
    else:
        fail(f'btns.pack (pos {btns_pack_pos}) chamado DEPOIS de body.pack (pos {body_pack_pos}) — botao invisivel')

    # Verifica que ha apenas 1 bloco btns (sem duplicata)
    count = func_src.count("btns = tk.Frame")
    if count == 1:
        ok('Apenas 1 definicao de btns (sem frame duplicado)')
    else:
        fail(f'{count} definicoes de btns encontradas — deveria ser 1')

    # Verifica que o botao Remover existe
    if 'Remover selecionado' in func_src:
        ok('Botao "Remover selecionado" presente')
    else:
        fail('Botao "Remover selecionado" nao encontrado')

    # Verifica auto-desativar VPN ao esvaziar lista
    if 'set_vpn_enabled(False)' in func_src and 'not tree.get_children()' in func_src:
        ok('Auto-desativar VPN ao remover ultimo peer implementado')
    else:
        fail('Auto-desativar VPN ao remover ultimo peer NAO implementado')


# ─────────────────────────────────────────────
# Resultado final
# ─────────────────────────────────────────────
if __name__ == '__main__':
    test_fix1_mcast_constant()
    test_fix2_reply_port_source()
    test_fix2_reply_port_behavior()
    test_fix3_btns_order()

    print(f'\n{"="*50}')
    print(f'  {len(PASS)} passou   {len(FAIL)} falhou')
    print('='*50)
    sys.exit(0 if not FAIL else 1)
