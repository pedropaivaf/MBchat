# test_diagnostics.py
# Ferramentas > Diagnostico de rede: o app aponta QUAL problema e e o que fazer.
#
# Cobre:
#   1. diagnostics.build_findings: cada problema conhecido vira um achado claro
#      (ID repetido, mesma conta em 2 PCs, mensagem com o meu ID, quem manda
#      mensagem mas nao aparece, status Offline, placa de rede errada, porta,
#      firewall, VPN, nomes repetidos, historico de ID antigo, versoes antigas)
#   2. ordem de gravidade e qual achado vai para a faixa da janela principal
#      (inclusive o bug antigo: a faixa VERMELHA da porta ocupada sumia no
#      mesmo ciclo porque o "else" da cadeia de avisos escondia a faixa)
#   3. build_report: o texto da janela
#   4. Messenger real: evidencias coletadas de verdade (TCP de quem nao esta
#      na lista, TCP com o meu ID, conflito vindo da rede, historico juntado)
#   5. GUI real (Tk): janela abre com a verificacao no topo, faixa troca de cor
#
# Rodar: python tests/test_diagnostics.py

import os
import sys
import json
import time
import shutil
import tempfile
import threading
from types import SimpleNamespace

try:
    sys.stdout.reconfigure(errors='backslashreplace')
except Exception:
    pass

here = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(here) if os.path.basename(here) == 'tests' else here
sys.path.insert(0, root_dir)

# Nunca abrir o banco de producao
import database
_TMP_DIR = tempfile.mkdtemp(prefix='mbchat_test_diag_')
_DB_PATH = {'path': os.path.join(_TMP_DIR, 'default.db')}
database.get_db_path = lambda *a, **k: _DB_PATH['path']

import diagnostics
from diagnostics import build_findings, banner_finding, build_report
import network
import messenger

PASS = []
FAIL = []

DAY = 86400
PEDRO = 'd09466b1646a_026DKT071_pedro.paiva'
GUS_OLD = 'b1b1b1b1b1b1_026DKT050_gustavo.barra'
GUS_NEW = 'c2c2c2c2c2c2_026DKT099_gustavo.barra'


def ok(msg):
    PASS.append(msg)
    print(f'  PASS  {msg}')


def fail(msg, detail=''):
    FAIL.append(msg)
    print(f'  FAIL  {msg}' + (f': {detail}' if detail else ''))


def check(cond, msg, detail=''):
    if cond:
        ok(msg)
    else:
        fail(msg, detail)


def peer(name, ip, host, login, ver='1.8.39', scope='domain', uid=None):
    uid = uid or f'aaaaaaaaaaaa_{host}_{login}'
    return uid, {'display_name': name, 'ip': ip, 'hostname': host, 'winuser': login,
                 'version': ver, 'login_scope': scope, 'status': 'online'}


def healthy(**over):
    now = time.time()
    peers = dict([peer('Ana', '192.168.0.30', '026DKT030', 'ana.raquel'),
                  peer('Joao', '192.168.0.31', '026DKT031', 'joao.vitor'),
                  peer('Iuri', '192.168.0.32', '026DKT032', 'iuri')])
    s = {
        'now': now, 'version': '1.8.39', 'user_id': PEDRO, 'display_name': 'Pedro Paiva',
        'status': 'online', 'login': 'pedro.paiva', 'login_scope': 'domain',
        'hostname': '026DKT071', 'instance': None, 'local_ip': '192.168.0.4',
        'local_ips': ['192.168.0.4'], 'vpn_enabled': False, 'manual_peers': [],
        'health': {'bound_port': 50100, 'bind_fallback': False, 'multicast_joined': True,
                   'uptime': 600, 'packets_sent': 80, 'packets_received': 5000,
                   'sendto_errors': 0, 'peers_count': len(peers), 'uid_conflicts': 0,
                   'uid_conflict_last': None, 'uid_conflict_sources': {}, 'bind_errors': []},
        'peers': peers, 'contacts': [], 'identity_previous_uid': '',
        'identity_changed_at': None, 'tracking_since': now - 30 * DAY,
        'own_uid_tcp': {'count': 0, 'last_ip': '', 'last_at': 0},
        'tcp_recent': {}, 'merges': [],
    }
    for k, v in over.items():
        if k == 'health':
            s['health'].update(v)
        else:
            s[k] = v
    return s


def codes(s):
    return [f['code'] for f in build_findings(s)]


def get(s, code):
    return next((f for f in build_findings(s) if f['code'] == code), None)


# ─────────────────────────────────────────────
# 1 — cada problema vira um achado
# ─────────────────────────────────────────────
def test_findings():
    print('\n[1] Achados')
    s = healthy()
    fs = build_findings(s)
    check(fs[0]['code'] == 'OK' and not any(f['level'] in ('erro', 'aviso') for f in fs),
          'PC saudavel: so "nenhum problema encontrado"', codes(s))
    check(banner_finding(fs) is None, 'PC saudavel: faixa nunca aparece')

    # Caso real: o PC do Gustavo usando o ID do Pedro
    conf = {'hostname': '026DKT099', 'winuser': 'gustavo.barra', 'ip': '192.168.0.99',
            'display_name': 'gustavo.barra', 'version': '1.8.38', 'at': time.time()}
    s = healthy(health={'uid_conflicts': 12, 'uid_conflict_last': conf,
                        'uid_conflict_sources': {'026dkt099|gustavo.barra': conf}},
                own_uid_tcp={'count': 3, 'last_ip': '192.168.0.99', 'last_at': time.time()})
    f = get(s, 'UID_CONFLICT_OTHER')
    check(f and f['level'] == 'erro', 'outro PC com o meu ID -> PROBLEMA')
    check(f and '026DKT099' in f['title'] and 'gustavo.barra' in f['title'],
          'diz QUAL PC e QUAL login', f and f['title'])
    check(f and any('026DKT099' in a for a in f['action'])
          and any('1.8.39' in a for a in f['action']),
          'diz quem precisa agir e o que fazer', f and f['action'])
    check(f and any('1.8.38' in d for d in f['detail']), 'mostra a versao do outro PC')
    check(f and f['banner'] and '026DKT099' in f['banner'], 'vira faixa na janela principal')
    check(get(s, 'OWN_UID_TCP') is not None, 'mensagens com o meu ID descartadas -> PROBLEMA')

    same = dict(conf, winuser='pedro.paiva', hostname='NOTEBOOK-PEDRO')
    s = healthy(health={'uid_conflicts': 2, 'uid_conflict_last': same,
                        'uid_conflict_sources': {'notebook-pedro|pedro.paiva': same}})
    f = get(s, 'UID_CONFLICT_SAME_LOGIN')
    check(f and f['level'] == 'aviso' and 'NOTEBOOK-PEDRO' in f['title'],
          'minha conta em outro PC com o mesmo ID -> ATENCAO')
    check(get(s, 'UID_CONFLICT_OTHER') is None, 'mesma conta nao e tratada como outra pessoa')

    # Quem manda mensagem mas nao aparece na lista (sintoma do caso original)
    now = time.time()
    s = healthy(tcp_recent={GUS_NEW: {'at': now - 120, 'ip': '192.168.0.99', 'name': 'gustavo.barra'},
                            'aaaaaaaaaaaa_026DKT030_ana.raquel': {'at': now - 60, 'ip': '192.168.0.30',
                                                                  'name': 'Ana'},
                            'velho_uid': {'at': now - 2 * 3600, 'ip': '1.1.1.1', 'name': 'Velho'}})
    f = get(s, 'TCP_BUT_NOT_LISTED')
    tcp = [x for x in build_findings(s) if x['code'] == 'TCP_BUT_NOT_LISTED']
    check(len(tcp) == 1 and 'gustavo.barra' in tcp[0]['title'],
          'manda mensagem mas nao esta na lista -> ATENCAO com o nome', [x['title'] for x in tcp])
    check(f and any('192.168.0.99' in d for d in f['detail']), 'mostra o IP de onde veio')
    check(f and any('antivirus' in a.lower() or 'placa' in a.lower() for a in f['action']),
          'aponta as causas provaveis no PC dele')

    s = healthy(status='invisible')
    check(get(s, 'STATUS_INVISIBLE') is not None, 'status Offline (invisivel) -> ATENCAO')

    s = healthy(local_ip='10.8.0.5', local_ips=['10.8.0.5', '192.168.0.4'])
    f = get(s, 'WRONG_ADAPTER')
    check(f and '10.8.0.5' in f['title'] and '192.168.0' in f['title'],
          'IP usado fora da rede dos colegas -> placa errada')
    check(f and any('ncpa.cpl' in a for a in f['action']), 'diz como corrigir a placa')
    s = healthy(local_ip='10.8.0.5', local_ips=['10.8.0.5'], vpn_enabled=True,
                manual_peers=['192.168.0.216'])
    check(get(s, 'WRONG_ADAPTER') is None, 'com VPN ligada, rede diferente e normal')
    s = healthy(local_ips=['192.168.0.4', '172.20.0.1'])
    check(get(s, 'MULTI_ADAPTER') is not None and get(s, 'WRONG_ADAPTER') is None,
          'duas placas mas a certa em uso -> so INFO')

    s = healthy(health={'bind_fallback': True, 'bound_port': 61234})
    f = get(s, 'BIND_FALLBACK')
    check(f and f['level'] == 'erro' and f['banner_severity'] == 'critical', 'porta ocupada -> faixa vermelha')

    s = healthy(health={'packets_received': 0, 'peers_count': 0, 'uptime': 90}, peers={})
    check(get(s, 'NO_PACKETS_IN') is not None, 'envia mas nao recebe -> firewall de entrada')
    s = healthy(health={'packets_received': 0, 'peers_count': 0, 'uptime': 200}, peers={},
                vpn_enabled=True, manual_peers=['192.168.0.216'])
    check(get(s, 'VPN_STUCK') is not None and get(s, 'NO_PACKETS_IN') is None,
          'VPN sem resposta tem achado proprio')
    s = healthy(health={'multicast_joined': False, 'peers_count': 0, 'uptime': 90,
                        'packets_sent': 0, 'packets_received': 0}, peers={})
    check(get(s, 'MULTICAST_NO_PEERS') is not None, 'multicast bloqueado sem colegas')
    s = healthy(health={'sendto_errors': 7})
    check(get(s, 'SENDTO_ERRORS') is not None, 'erros de envio do aviso -> ATENCAO')

    peers = dict([peer('Ana', '192.168.0.30', 'PC1', 'ana.raquel'),
                  peer('Ana', '192.168.0.40', 'PC2', 'ana.silva'),
                  peer('Joao', '192.168.0.31', 'PC3', 'joao.vitor'),
                  peer('Joao', '192.168.0.41', 'PC4', 'joao.vitor')])
    s = healthy(peers=peers, health={'peers_count': 4})
    check(get(s, 'SAME_NAME') is not None and 'Ana' in get(s, 'SAME_NAME')['title'],
          'duas pessoas com o mesmo nome -> ATENCAO')
    f = get(s, 'SAME_PERSON_TWO_PCS')
    check(f and 'Joao' in f['title'], 'mesma conta em 2 PCs (IDs diferentes) -> INFO')

    gus_peer = {GUS_NEW: {'display_name': 'gustavo.barra', 'ip': '192.168.0.99',
                          'hostname': '026DKT099', 'winuser': 'gustavo.barra',
                          'version': '1.8.39', 'login_scope': 'domain'}}
    old_c = {'user_id': GUS_OLD, 'display_name': 'gustavo.barra', 'hostname': '026DKT050',
             'last_announce_at': now - 2 * DAY}
    s = healthy(peers=dict(healthy()['peers'], **gus_peer), contacts=[old_c])
    f = get(s, 'OLD_ID_PENDING')
    check(f and '~5 dia' in f['title'], 'ID antigo da mesma pessoa: diz em quantos dias junta',
          f and f['title'])
    s = healthy(peers=dict(healthy()['peers'], **gus_peer),
                contacts=[dict(old_c, last_announce_at=now - 9 * DAY)])
    f = get(s, 'OLD_ID_PENDING')
    check(f and 'proxima checagem' in f['title'], 'prazo vencido: junta na proxima checagem')
    local_peer = {GUS_NEW: dict(gus_peer[GUS_NEW], login_scope='local')}
    s = healthy(peers=dict(healthy()['peers'], **local_peer), contacts=[old_c])
    check(get(s, 'OLD_ID_NO_MERGE') is not None and get(s, 'OLD_ID_PENDING') is None,
          'conta local em outro PC: avisa que NAO junta')
    s = healthy(peers=dict(healthy()['peers'], **gus_peer),
                contacts=[{'user_id': PEDRO, 'display_name': 'Pedro', 'last_announce_at': now - 30 * DAY}])
    check(get(s, 'OLD_ID_PENDING') is None, 'ID de OUTRA pessoa nunca aparece como "vai juntar"')

    s = healthy(merges=[{'old': GUS_OLD, 'new': GUS_NEW, 'login': 'gustavo.barra',
                         'at': now, 'name': 'gustavo.barra'}])
    f = get(s, 'MERGED')
    check(f and '026DKT050' in f['title'], 'historico juntado nesta sessao -> INFO com o PC antigo')

    s = healthy(peers=dict([peer('Ana', '192.168.0.30', 'PC1', 'ana.raquel', ver='1.8.37'),
                            peer('Joao', '192.168.0.31', 'PC3', 'joao.vitor', ver='1.8.39')]))
    f = get(s, 'OLD_VERSIONS')
    check(f and 'Ana' in f['detail'][0] and 'Joao' not in f['detail'][0], 'lista quem esta em versao antiga')

    s = healthy(identity_previous_uid=PEDRO, identity_changed_at=now, user_id=GUS_NEW,
                login='gustavo.barra')
    f = get(s, 'ID_CHANGED')
    check(f and 'pedro.paiva' in f['title'], 'PC que trocou de ID explica de quem era o banco')
    s = healthy(user_id=PEDRO, login='gustavo.barra')
    check(get(s, 'UID_NOT_MINE') is not None, 'ID que nao e deste login -> PROBLEMA')
    s = healthy(user_id=PEDRO + '_bot', login='pedro.paiva', instance='bot')
    check(get(s, 'UID_NOT_MINE') is None, '--instance (teste local) nao e acusado')

    check(diagnostics.MERGE_MIN_OFFLINE_S == messenger.IDENTITY_MERGE_MIN_OFFLINE_S,
          'prazo de 7 dias igual no diagnostico e no messenger')


# ─────────────────────────────────────────────
# 2 — gravidade e faixa
# ─────────────────────────────────────────────
def test_order_and_banner():
    print('\n[2] Ordem de gravidade e faixa da janela principal')
    conf = {'hostname': 'X', 'winuser': 'outro', 'ip': '1.2.3.4', 'version': '1.8.38', 'at': time.time()}
    s = healthy(status='invisible', local_ips=['192.168.0.4', '172.20.0.1'],
                health={'uid_conflicts': 1, 'uid_conflict_sources': {'x|outro': conf},
                        'bind_fallback': True})
    fs = build_findings(s)
    levels = [f['level'] for f in fs]
    check(levels == sorted(levels, key=lambda l: {'erro': 0, 'aviso': 1, 'info': 2, 'ok': 3}[l]),
          'PROBLEMA antes de ATENCAO antes de INFO', levels)
    b = banner_finding(fs)
    check(b and b['code'] == 'BIND_FALLBACK', 'faixa vermelha (porta) ganha de qualquer outra')
    s = healthy(health={'bind_fallback': True})
    b = banner_finding(build_findings(s))
    check(b and b['banner_severity'] == 'critical',
          'porta ocupada SEM outros avisos continua com faixa (antes sumia no mesmo ciclo)')
    s = healthy(health={'uid_conflicts': 1, 'uid_conflict_sources': {'x|outro': conf}})
    b = banner_finding(build_findings(s))
    check(b and b['code'] == 'UID_CONFLICT_OTHER', 'ID repetido aparece na faixa')
    amarela = {'code': 'A', 'level': 'erro', 'banner': 'a', 'banner_severity': 'warning'}
    vermelha = {'code': 'V', 'level': 'erro', 'banner': 'v', 'banner_severity': 'critical'}
    check(banner_finding([amarela, vermelha])['code'] == 'V',
          'vermelha ganha mesmo vindo depois na lista')
    s = healthy(status='invisible', tcp_recent={GUS_NEW: {'at': time.time(), 'ip': '1.1.1.1', 'name': 'G'}})
    check(banner_finding(build_findings(s)) is None,
          'status Offline / colega sem aviso nao poluem a faixa (so a janela)')


# ─────────────────────────────────────────────
# 3 — texto da janela
# ─────────────────────────────────────────────
def test_report():
    print('\n[3] Relatorio da janela')
    conf = {'hostname': '026DKT099', 'winuser': 'gustavo.barra', 'ip': '192.168.0.99',
            'version': '1.8.38', 'at': time.time()}
    peers = dict(healthy()['peers'])
    peers.update(dict([peer('Ana', '192.168.0.40', 'PC9', 'ana.silva')]))
    s = healthy(status='invisible', peers=peers,
                health={'uid_conflicts': 1, 'uid_conflict_sources': {'k': conf}})
    rows = build_report(s, build_findings(s), ['linha 1\n', '[ID] CONFLITO ...\n'])
    text = '\n'.join(r[0] for r in rows)
    check('=== VERIFICACAO AUTOMATICA ===' in text.split('=== IDENTIDADE ===')[0],
          'verificacao automatica vem antes dos dados crus')
    check(any(t == 'erro' and '026DKT099' in l for l, t in rows), 'achado grave com cor de PROBLEMA')
    check('O que fazer:' in text, 'cada achado diz o que fazer')
    check('ID e deste login: sim' in text, 'identidade: ID e deste login')
    check('Offline (invisivel' in text, 'status Offline explicado')
    check('<-- nome repetido' in text, 'tabela de colegas marca nome repetido')
    check('Versao' in text and '1.8.39' in text, 'tabela de colegas com versao')
    check('[ID] CONFLITO' in text, 'final do network.log incluido')
    check(all(isinstance(l, str) for l, _ in rows), 'so texto (Copiar tudo funciona)')


# ─────────────────────────────────────────────
# 4 — Messenger real coleta as evidencias
# ─────────────────────────────────────────────
class patched:
    def __init__(self, mod, **attrs):
        self.mod, self.attrs, self.orig = mod, attrs, {}

    def __enter__(self):
        for k, v in self.attrs.items():
            self.orig[k] = getattr(self.mod, k)
            setattr(self.mod, k, v)
        return self

    def __exit__(self, *exc):
        for k, v in self.orig.items():
            setattr(self.mod, k, v)


def make_messenger():
    _DB_PATH['path'] = os.path.join(_TMP_DIR, f'm{len(PASS)}{len(FAIL)}.db')
    with patched(messenger, get_windows_user=lambda: 'pedro.paiva',
                 generate_user_id=lambda: PEDRO):
        return messenger.Messenger()


def test_messenger_evidence():
    print('\n[4] Messenger real: evidencias')
    with patched(messenger, get_local_ip=lambda *a, **k: '192.168.0.4',
                 get_local_ipv4s=lambda: ['192.168.0.4'], get_windows_user=lambda: 'pedro.paiva'), \
            patched(network, get_local_ip=lambda *a, **k: '192.168.0.4',
                    get_windows_user=lambda: 'pedro.paiva'):
        m = make_messenger()
        check(m.user_id == PEDRO, 'messenger de teste com o ID do Pedro')

        # Mensagem de quem NAO esta na lista
        m._on_tcp_message({'type': network.MT_TYPING, 'from_user': GUS_NEW,
                           'display_name': 'gustavo.barra', 'is_typing': True},
                          ('192.168.0.99', 50101))
        s = m.get_diagnostic_snapshot()
        check(GUS_NEW in s['tcp_recent'] and s['tcp_recent'][GUS_NEW]['ip'] == '192.168.0.99',
              'TCP de quem nao esta na lista e registrado')
        check(any(f['code'] == 'TCP_BUT_NOT_LISTED' and 'gustavo.barra' in f['title']
                  for f in build_findings(s)), 'e vira achado com o nome dele')

        # Mensagem com o MEU ID (outro PC usando meu ID)
        m._on_tcp_message({'type': network.MT_MESSAGE, 'from_user': PEDRO, 'to_user': PEDRO,
                           'content': 'oi'}, ('192.168.0.99', 50101))
        m._on_tcp_message({'type': network.MT_MESSAGE, 'from_user': PEDRO, 'content': 'eco'},
                          ('127.0.0.1', 50101))
        s = m.get_diagnostic_snapshot()
        check(s['own_uid_tcp']['count'] == 1 and s['own_uid_tcp']['last_ip'] == '192.168.0.99',
              'TCP com o meu ID de outro IP e contado (loopback nao)', s['own_uid_tcp'])
        check(m.db.conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0,
              'mensagem com o meu ID continua descartada (nao grava)')

        # Conflito vindo da rede (announce com o meu ID de outro PC)
        pkt = json.dumps({'app': 'mbchat', 'type': 'announce', 'user_id': PEDRO,
                          'display_name': 'gustavo.barra', 'hostname': '026DKT099',
                          'winuser': 'gustavo.barra', 'ip': '192.168.0.99',
                          'version': '1.8.38'}).encode()
        m.discovery._handle_packet(pkt, ('192.168.0.99', 50100))
        s = m.get_diagnostic_snapshot()
        check('026dkt099|gustavo.barra' in s['health']['uid_conflict_sources'],
              'conflito guardado por PC de origem')
        f = next((f for f in build_findings(s) if f['code'] == 'UID_CONFLICT_OTHER'), None)
        check(f and '026DKT099' in f['title'], 'diagnostico do PC do Pedro aponta o PC do Gustavo')

        light = m.get_diagnostic_snapshot(full=False)
        check(light['contacts'] == [] and light['local_ips'] == [],
              'foto leve (faixa a cada 30s) nao le contatos nem placas')
        check(light['health']['uid_conflicts'] >= 1, 'foto leve ainda ve o conflito')

        # Historico juntado aparece no diagnostico
        now = time.time()
        m.db.upsert_contact(GUS_OLD, 'gustavo.barra', '192.168.0.50', hostname='026DKT050')
        m.db.conn.execute("UPDATE contacts SET last_announce_at=? WHERE user_id=?",
                          (now - 10 * DAY, GUS_OLD))
        m.db.conn.commit()
        info = {'display_name': 'gustavo.barra', 'ip': '192.168.0.99', 'status': 'online',
                'hostname': '026DKT099', 'winuser': 'gustavo.barra', 'login_scope': 'domain'}
        m._persist_announced_contact(GUS_NEW, info)
        m._merge_previous_identities(GUS_NEW, info)
        s = m.get_diagnostic_snapshot()
        check(any(x['old'] == GUS_OLD for x in s['merges']), 'historico juntado registrado')
        check(any(f['code'] == 'MERGED' for f in build_findings(s)), 'e aparece no diagnostico')
    return m


# ─────────────────────────────────────────────
# 5 — GUI real
# ─────────────────────────────────────────────
def test_gui(m):
    print('\n[5] GUI real (Tk)')
    try:
        import tkinter as tk
        import gui
        root = tk.Tk()
        root.withdraw()
    except Exception as e:
        print(f'  SKIP  sem Tk/display: {e}')
        return

    shown = []
    fake = SimpleNamespace(root=root, messenger=m)
    fake._show_health_banner = lambda severity='warning', text='': shown.append((severity, text))
    fake._hide_health_banner = lambda: shown.append(('hide', ''))
    gui.LanMessengerApp._update_health_banner(fake)
    check(shown and shown[-1][0] == 'warning' and '026DKT099' in shown[-1][1],
          'faixa da janela principal mostra o ID repetido', shown)

    # Bug antigo: porta ocupada SEM outro aviso -> a faixa vermelha era
    # mostrada e escondida no mesmo ciclo (o "else" da cadeia de avisos)
    shown.clear()
    snap_bind = healthy(health={'bind_fallback': True, 'bound_port': 61234})
    fake2 = SimpleNamespace(root=root, messenger=SimpleNamespace(
        discovery=object(), get_diagnostic_snapshot=lambda full=True: snap_bind))
    fake2._show_health_banner = fake._show_health_banner
    fake2._hide_health_banner = fake._hide_health_banner
    gui.LanMessengerApp._update_health_banner(fake2)
    check(shown == [('critical', shown[0][1])] if shown else False,
          'porta ocupada: faixa vermelha fica (nao e escondida em seguida)', shown)

    # faixa existente com outra gravidade e recriada (antes so trocava o texto)
    real = SimpleNamespace(root=root, _open_network_diag=lambda: None)
    real._hide_health_banner = lambda: gui.LanMessengerApp._hide_health_banner(real)
    gui.LanMessengerApp._show_health_banner(real, 'warning', 'amarela')
    bar1 = real._health_bar
    bg1 = bar1.cget('bg')
    gui.LanMessengerApp._show_health_banner(real, 'critical', 'vermelha')
    root.update_idletasks()
    check(not bar1.winfo_exists() and real._health_bar.cget('bg') != bg1
          and real._health_bar_label.cget('text') == 'vermelha',
          'faixa troca de amarela para vermelha')
    gui.LanMessengerApp._show_health_banner(real, 'critical', 'outro texto')
    check(real._health_bar_label.cget('text') == 'outro texto', 'mesma gravidade so troca o texto')

    # janela de diagnostico de verdade
    before = set(root.winfo_children())
    gui.LanMessengerApp._open_network_diag(SimpleNamespace(root=root, messenger=m))
    root.update()
    dlg = next((w for w in root.winfo_children()
                if w not in before and isinstance(w, tk.Toplevel)), None)
    check(dlg is not None, 'janela de diagnostico abre')
    texts = []

    def walk(w):
        for c in w.winfo_children():
            if isinstance(c, tk.Text):
                texts.append(c)
            walk(c)
    if dlg is not None:
        walk(dlg)
    body = texts[0].get('1.0', 'end') if texts else ''
    check(body.lstrip().startswith('MB Chat v') and '=== VERIFICACAO AUTOMATICA ===' in body,
          'verificacao automatica no topo da janela')
    check('[PROBLEMA] O PC 026DKT099 (login gustavo.barra) esta usando o SEU ID' in body,
          'janela diz qual PC usa o meu ID')
    check(texts and texts[0].tag_ranges('erro'), 'linha do problema pintada de vermelho')
    try:
        root.destroy()
    except Exception:
        pass


def main():
    for t in (test_findings, test_order_and_banner, test_report):
        try:
            t()
        except Exception as e:
            import traceback
            traceback.print_exc()
            fail(f'{t.__name__} quebrou', repr(e))
    m = None
    try:
        m = test_messenger_evidence()
    except Exception as e:
        import traceback
        traceback.print_exc()
        fail('test_messenger_evidence quebrou', repr(e))
    if m is not None:
        try:
            test_gui(m)
        except Exception as e:
            import traceback
            traceback.print_exc()
            fail('test_gui quebrou', repr(e))
    print(f'\n{len(PASS)} passou, {len(FAIL)} falhou')
    shutil.rmtree(_TMP_DIR, ignore_errors=True)
    sys.exit(0 if not FAIL else 1)


if __name__ == '__main__':
    main()
