# Sniffer passivo de announces MBChat na LAN
# Uso: feche o MBChat local, rode `python tools/sniff_mbchat.py`, aguarde 2 min, Ctrl+C
# Lista cada PC visivel na rede com hostname, user, ip declarado, tcp_port, e deteccao
# de mismatch entre IP de origem do pacote vs IP que o PC anuncia (bug de get_local_ip)
import socket, json, struct, time, sys

MULTICAST = '239.255.100.200'
UDP_PORT = 50100

s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try:
    s.bind(('', UDP_PORT))
except OSError as e:
    print(f'ERRO: nao foi possivel bindar UDP {UDP_PORT}: {e}')
    print('Feche o MBChat local e tente de novo.')
    sys.exit(1)

mreq = struct.pack('4s4s', socket.inet_aton(MULTICAST), socket.inet_aton('0.0.0.0'))
try:
    s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    print('[OK] multicast join 239.255.100.200')
except OSError as e:
    print(f'[AVISO] IGMP join falhou: {e} (so broadcast)')

s.settimeout(1.0)

seen = {}  # (src_ip, user_id) -> {first, last, count, pkt}
start = time.time()
print(f'sniffing UDP {UDP_PORT} ... Ctrl+C para parar e ver resumo')
print()

try:
    while True:
        try:
            data, addr = s.recvfrom(65535)
        except socket.timeout:
            continue
        try:
            pkt = json.loads(data.decode('utf-8', 'ignore'))
        except Exception:
            continue
        if pkt.get('app') != 'mbchat':
            continue

        uid = pkt.get('user_id', '?')
        name = pkt.get('display_name', '?')
        host = pkt.get('hostname', '?')
        ip_pkt = pkt.get('ip', '?')
        tcp = pkt.get('tcp_port', '?')
        mtype = pkt.get('type', '?')
        key = (addr[0], uid)
        now = time.strftime('%H:%M:%S')

        if key not in seen:
            mismatch = '' if addr[0] == ip_pkt else f' [MISMATCH src={addr[0]} declara={ip_pkt}]'
            print(f'[{now}] NEW  {addr[0]:15} {host:18} {name:20} tcp={tcp} type={mtype}{mismatch}')
            seen[key] = {'first': time.time(), 'last': time.time(), 'count': 1, 'pkt': pkt, 'src': addr[0]}
        else:
            seen[key]['last'] = time.time()
            seen[key]['count'] += 1
except KeyboardInterrupt:
    pass

elapsed = time.time() - start
print()
print(f'=== RESUMO apos {elapsed:.0f}s ===')
print(f'{"HOSTNAME":20} {"USUARIO":20} {"IP_SRC":15} {"IP_DECL":15} {"TCP":6} {"PKTS":6} {"ULT":8}')
print('-' * 100)
for (src, uid), info in sorted(seen.items(), key=lambda x: x[1]['src']):
    pkt = info['pkt']
    host = pkt.get('hostname', '?')[:18]
    name = pkt.get('display_name', '?')[:18]
    ip_decl = pkt.get('ip', '?')
    tcp = str(pkt.get('tcp_port', '?'))
    count = info['count']
    last_ago = int(time.time() - info['last'])
    flag = ' <<<' if src != ip_decl else ''
    print(f'{host:20} {name:20} {src:15} {ip_decl:15} {tcp:6} {count:6} {last_ago}s atras{flag}')
print()
print(f'Total de peers unicos: {len(seen)}')
if any(i['src'] != i['pkt'].get('ip') for i in seen.values()):
    print('ATENCAO: ha PCs com MISMATCH (get_local_ip retornou IP errado)')
