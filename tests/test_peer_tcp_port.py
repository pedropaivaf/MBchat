# test_peer_tcp_port.py
# Valida o fix de porta TCP por peer (messenger.py _peer_tcp_port) --
# garante que mensagens usam a porta REAL anunciada pelo peer (resolve o
# caso de porta 50101 excluida por Hyper-V/WinNAT, ja documentado em
# DECISIONS.md) SEM mudar comportamento pra peers saudaveis (a maioria).
# Rodar: python tests/test_peer_tcp_port.py

import sys
import os
from types import SimpleNamespace

here = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(here) if os.path.basename(here) == 'tests' else here
sys.path.insert(0, root_dir)

PASS = []
FAIL = []


def ok(msg):
    PASS.append(msg)
    print(f'  PASS  {msg}')


def fail(msg, detail=''):
    FAIL.append(msg)
    print(f'  FAIL  {msg}' + (f': {detail}' if detail else ''))


# ─────────────────────────────────────────────
# 1 — _peer_tcp_port: fallback nunca regride o caso saudavel
# ─────────────────────────────────────────────
def test_peer_tcp_port_fallback():
    print('\n[1] _peer_tcp_port (logica de fallback)')
    import messenger
    from network import TCP_PORT

    def make_self(peers):
        return SimpleNamespace(discovery=SimpleNamespace(peers=peers))

    # Peer desconhecido (nunca visto no discovery) -> comportamento de hoje
    fake = make_self({})
    got = messenger.Messenger._peer_tcp_port(fake, 'uid_desconhecido')
    if got == TCP_PORT:
        ok(f'peer desconhecido -> TCP_PORT ({TCP_PORT}), sem regressao')
    else:
        fail(f'peer desconhecido -> {got}, esperado TCP_PORT ({TCP_PORT})')

    # Peer conhecido mas sem campo tcp_port (peer antigo/incompleto) -> hoje
    fake = make_self({'uidA': {'ip': '10.0.0.5'}})
    got = messenger.Messenger._peer_tcp_port(fake, 'uidA')
    if got == TCP_PORT:
        ok(f'peer sem campo tcp_port -> TCP_PORT ({TCP_PORT}), sem regressao')
    else:
        fail(f'peer sem campo tcp_port -> {got}, esperado TCP_PORT ({TCP_PORT})')

    # Peer saudavel: tcp_port anunciado == TCP_PORT (caso comum, ~29/30 PCs)
    fake = make_self({'uidB': {'ip': '10.0.0.6', 'tcp_port': TCP_PORT}})
    got = messenger.Messenger._peer_tcp_port(fake, 'uidB')
    if got == TCP_PORT:
        ok(f'peer saudavel (tcp_port==TCP_PORT) -> {got}, identico a hoje')
    else:
        fail(f'peer saudavel -> {got}, esperado TCP_PORT ({TCP_PORT}) -- REGRESSAO')

    # Peer em fallback (Hyper-V/WinNAT excluiu TCP_PORT nele) -> usa a porta real
    fake = make_self({'uidC': {'ip': '10.0.0.7', 'tcp_port': 50228}})
    got = messenger.Messenger._peer_tcp_port(fake, 'uidC')
    if got == 50228:
        ok('peer em fallback (tcp_port=50228) -> 50228 (o fix)')
    else:
        fail(f'peer em fallback -> {got}, esperado 50228')

    # self.discovery None (janela de inicializacao) -> nao quebra, cai pro default
    fake = SimpleNamespace(discovery=None)
    try:
        got = messenger.Messenger._peer_tcp_port(fake, 'qualquer')
        if got == TCP_PORT:
            ok('discovery=None -> TCP_PORT sem excecao')
        else:
            fail(f'discovery=None -> {got}, esperado TCP_PORT')
    except Exception as e:
        fail('discovery=None levantou excecao (deveria degradar com seguranca)', str(e))


# ─────────────────────────────────────────────
# 2 — Analise de codigo: os 3 pontos de envio usam o helper, nao a constante direta
# ─────────────────────────────────────────────
def test_send_paths_use_helper():
    print('\n[2] send_message / send_group_invite / send_group_message usam o helper')
    with open(os.path.join(root_dir, 'messenger.py'), encoding='utf-8') as f:
        src = f.read()

    if 'def _peer_tcp_port(self, uid):' in src:
        ok('_peer_tcp_port definido')
    else:
        fail('_peer_tcp_port nao encontrado')

    checks = [
        ("ok = TCPClient.send_message(contact['ip_address'], port, payload)",
         'send_message usa "port" resolvido (nao TCP_PORT direto)'),
        ('ok = TCPClient.send_message(ip, port, pkt)',
         'send_group_invite (_send_invite) usa "port" resolvido'),
        ("TCPClient.send_message(member['ip'], port, payload)",
         'send_group_message usa "port" resolvido'),
    ]
    for needle, label in checks:
        if needle in src:
            ok(label)
        else:
            fail(f'{label} -- padrao nao encontrado no codigo')

    # Nota: outros tipos de mensagem (imagem, audio, enquete, reuniao, etc.)
    # continuam usando TCP_PORT direto -- fora do escopo deste fix, que so
    # cobriu texto individual/grupo e convite de grupo. Nao checar ausencia
    # global de TCP_PORT no arquivo (falso-positivo: eles sao esperados).


# ─────────────────────────────────────────────
# 3 — Comportamental: socket real confirma que a porta certa e alcancada
# ─────────────────────────────────────────────
def test_behavioral_correct_port_reached():
    print('\n[3] Teste comportamental (socket real)')
    import socket
    import threading
    import time
    import json
    import struct

    FALLBACK_PORT = 50999  # porta livre generica so pro teste
    received = {'ok': False}

    def server():
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(('127.0.0.1', FALLBACK_PORT))
        srv.listen(1)
        srv.settimeout(3.0)
        try:
            conn, _ = srv.accept()
            header = conn.recv(4)
            msg_len = struct.unpack('!I', header)[0]
            data = conn.recv(msg_len)
            msg = json.loads(data.decode('utf-8'))
            received['ok'] = msg.get('content') == 'teste_porta_fallback'
            conn.close()
        except Exception:
            pass
        finally:
            srv.close()

    t = threading.Thread(target=server, daemon=True)
    t.start()
    time.sleep(0.3)

    from network import TCPClient
    from types import SimpleNamespace
    import messenger

    fake_self = SimpleNamespace(discovery=SimpleNamespace(
        peers={'bot_teste': {'ip': '127.0.0.1', 'tcp_port': FALLBACK_PORT}}))
    port = messenger.Messenger._peer_tcp_port(fake_self, 'bot_teste')
    TCPClient.send_message('127.0.0.1', port, {'content': 'teste_porta_fallback'})

    t.join(timeout=3.0)
    if received['ok']:
        ok(f'Mensagem chegou na porta de fallback real ({FALLBACK_PORT}) via _peer_tcp_port')
    else:
        fail('Mensagem NAO chegou na porta de fallback -- fix nao funciona de verdade')


# ─────────────────────────────────────────────
# Resultado final
# ─────────────────────────────────────────────
if __name__ == '__main__':
    test_peer_tcp_port_fallback()
    test_send_paths_use_helper()
    test_behavioral_correct_port_reached()

    print(f'\n{"="*50}')
    print(f'  {len(PASS)} passou   {len(FAIL)} falhou')
    print('='*50)
    sys.exit(0 if not FAIL else 1)
