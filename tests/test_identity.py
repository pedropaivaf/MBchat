# test_identity.py
# Identidade do usuario: quem e quem na rede e onde fica o historico.
#
# Caso real (set/2026): dois funcionarios usaram o mesmo PC; depois cada um foi
# para o seu, mas o MB Chat de um ficou com o banco (e o user_id) do outro. Os
# dois anunciavam o MESMO ID: cada PC descartava o outro como eco e, para o
# resto da rede, viravam um contato so -- um deles "sumia" da lista.
#
# Cobre:
#   1. helpers puros de identity.py (dono do ID, hostname/login dentro do ID)
#   2. boot: banco de outra conta do Windows ganha ID proprio, historico mantido
#   3. rede: pacote com o MEU ID vindo de outro PC/login e conflito, nao eco
#   4. mesma pessoa em PC novo: historico do ID antigo junta no novo (com travas)
#   5. troca de ID alcanca todas as tabelas (reacoes, lembretes, reunioes...)
#   6. historico nunca some: contato com nome repetido nao e apagado, limpeza
#      do boot nao apaga conversa de contato ausente, status sem nome nao
#      apaga o nome
#   7. cenario completo do caso real (Pedro x Gustavo)
#
# Rodar: python tests/test_identity.py

import os
import sys
import ast
import json
import time
import shutil
import socket
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

# Nunca abrir o banco de producao (%APPDATA%\.mbchat\mbchat.db): cada cenario
# aponta _DB_PATH para um arquivo temporario proprio
import database
_TMP_DIR = tempfile.mkdtemp(prefix='mbchat_test_identity_')
_DB_PATH = {'path': os.path.join(_TMP_DIR, 'default.db')}
database.get_db_path = lambda *a, **k: _DB_PATH['path']

import identity
import network
import messenger
from database import Database
from messenger import Messenger, IDENTITY_MERGE_MIN_OFFLINE_S

PASS = []
FAIL = []

DAY = 86400
PEDRO = 'd09466b1646a_026DKT071_pedro.paiva'
GUS_OLD = 'b1b1b1b1b1b1_026DKT050_gustavo.barra'   # ID antigo dele (PC antigo)
GUS_NEW = 'c2c2c2c2c2c2_026DKT099_gustavo.barra'   # ID novo (PC novo)
COLEGA = 'e3e3e3e3e3e3_026DKT030_ana.raquel'


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


def new_db(name):
    path = os.path.join(_TMP_DIR, name + '.db')
    for ext in ('', '-wal', '-shm'):
        try:
            os.remove(path + ext)
        except OSError:
            pass
    _DB_PATH['path'] = path
    return Database(path), path


# a = dono do banco ("eu"), b = o outro lado da conversa
def add_msgs(db, a, b, n, prefix):
    with db.conn:
        for i in range(n):
            db.conn.execute(
                "INSERT INTO messages (msg_id, from_user, to_user, content,"
                " msg_type, timestamp, is_sent) VALUES (?,?,?,?,?,?,?)",
                (f'{prefix}{i}', a if i % 2 == 0 else b,
                 b if i % 2 == 0 else a, f'{prefix} {i}', 'text',
                 time.time() - 1000 + i, 1 if i % 2 == 0 else 0))


def count_with(db, uid):
    return db.conn.execute(
        "SELECT COUNT(*) FROM messages WHERE from_user=? OR to_user=?",
        (uid, uid)).fetchone()[0]


class patched:
    # Usar como: with patched(messenger, get_windows_user=lambda: 'x'): ...
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


def boot(login, generated):
    # Sobe o Messenger REAL (sem iniciar rede) como se fosse o login informado
    with patched(messenger, get_windows_user=lambda: login,
                 generate_user_id=lambda: generated):
        m = Messenger()
    return m


# ─────────────────────────────────────────────
# 1 — helpers puros
# ─────────────────────────────────────────────
def test_helpers():
    print('\n[1] identity.py')
    check(identity.uid_belongs_to(PEDRO, 'pedro.paiva'), 'ID e do login que o criou')
    check(identity.uid_belongs_to(PEDRO, 'Pedro.Paiva'), 'login sem diferenciar maiusculas')
    check(not identity.uid_belongs_to(PEDRO, 'gustavo.barra'), 'ID nao e de outro login')
    check(not identity.uid_belongs_to(PEDRO, 'paiva'), 'pedaco do login nao conta')
    check(not identity.uid_belongs_to(PEDRO, ''), 'login vazio nunca e dono')
    check(identity.uid_hostname(PEDRO, 'pedro.paiva') == '026DKT071', 'hostname de dentro do ID')
    check(identity.uid_hostname(PEDRO, 'gustavo.barra') == '', 'hostname so para o dono')
    check(identity.uid_login(PEDRO) == 'pedro.paiva', 'login de dentro do ID')
    check(identity.uid_login('d09466b1646a_PC_pedro_paiva') == 'pedro_paiva', 'login com underscore')
    check(identity.uid_login('d09466b1646a_026DKT071') == '', 'formato antigo (sem login)')
    check(identity.uid_login('broadcast') == '', 'ID que nao e de usuario')
    check(identity.login_scope({'USERDOMAIN': 'MBCONTAB', 'COMPUTERNAME': '026DKT071'}) == 'domain',
          'conta de dominio')
    check(identity.login_scope({'USERDOMAIN': '026DKT071', 'COMPUTERNAME': '026dkt071'}) == 'local',
          'conta local do PC')
    check(identity.login_scope({}) == '', 'sem Windows: desconhecido')


# ─────────────────────────────────────────────
# 2 — boot: o ID precisa ser deste login
# ─────────────────────────────────────────────
def test_boot_owner():
    print('\n[2] Boot: ID gravado precisa ser do login do Windows')

    # Banco do Pedro aberto pelo login do Gustavo (pasta .mbchat copiada)
    db, path = new_db('copia')
    db.set_local_user(PEDRO, 'gustavo.barra')
    add_msgs(db, PEDRO, COLEGA, 40, 'cp')
    db.conn.execute("INSERT INTO reactions VALUES ('cp0', '👍', ?, ?)", (PEDRO, time.time()))
    db.conn.commit()
    db.close() if hasattr(db, 'close') else None
    m = boot('gustavo.barra', GUS_NEW)
    check(m.user_id == GUS_NEW, 'banco de outra conta -> ID novo deste login', m.user_id)
    check(m.db.get_local_user()['user_id'] == GUS_NEW, 'local_user gravado com o ID novo')
    check(count_with(m.db, PEDRO) == 0, 'nenhuma mensagem ficou no ID do Pedro neste banco')
    hist = m.db.get_chat_history(GUS_NEW, COLEGA)
    check(len(hist) == 40, 'historico local continua aparecendo inteiro', len(hist))
    check(m.db.get_setting('identity_previous_uid') == PEDRO, 'ID anterior registrado')
    r = m.db.conn.execute("SELECT from_user FROM reactions WHERE msg_id='cp0'").fetchone()
    check(r and r[0] == GUS_NEW, 'reacao acompanhou o ID novo')
    check(m.discovery.user_id == GUS_NEW, 'anuncio na rede ja sai com o ID novo')

    # Dono do ID: nada muda
    db, path = new_db('dono')
    db.set_local_user(PEDRO, 'Pedro Paiva')
    add_msgs(db, PEDRO, COLEGA, 10, 'dn')
    m = boot('pedro.paiva', 'ffffffffffff_OUTRO_pedro.paiva')
    check(m.user_id == PEDRO, 'dono do ID continua com ele', m.user_id)
    check(count_with(m.db, PEDRO) == 10, 'historico do dono intocado')

    m = boot('Pedro.Paiva', 'ffffffffffff_OUTRO_pedro.paiva')
    check(m.user_id == PEDRO, 'login com outra caixa nao troca o ID')

    # Mesmo login em PC novo com a pasta levada junto: ID mantido (historico
    # de todo mundo com ele continua o mesmo)
    m = boot('pedro.paiva', 'aaaaaaaaaaaa_PCNOVO_pedro.paiva')
    check(m.user_id == PEDRO, 'mesmo login em outro PC mantem o ID')

    # Formato antigo (sem login no ID): ganha o login
    db, path = new_db('antigo')
    db.set_local_user('d09466b1646a_026DKT071', 'Pedro')
    add_msgs(db, 'd09466b1646a_026DKT071', COLEGA, 6, 'an')
    m = boot('pedro.paiva', PEDRO)
    check(m.user_id == PEDRO, 'ID antigo sem login -> formato com login')
    check(count_with(m.db, PEDRO) == 6, 'historico do formato antigo acompanhou')

    # Sem login disponivel: nao mexe
    db, path = new_db('semlogin')
    db.set_local_user(PEDRO, 'Pedro')
    m = boot('', GUS_NEW)
    check(m.user_id == PEDRO, 'sem login do Windows nao mexe no ID')

    # --instance (testes locais): nao mexe
    db, path = new_db('instancia')
    db.set_local_user(PEDRO, 'Pedro')
    argv = sys.argv[:]
    sys.argv = argv + ['--instance', 'bot']
    try:
        m = boot('gustavo.barra', GUS_NEW)
    finally:
        sys.argv = argv
    check(m.user_id == PEDRO + '_bot', '--instance nao passa pela checagem', m.user_id)


# ─────────────────────────────────────────────
# 3 — rede: conflito de ID e diferente de eco
# ─────────────────────────────────────────────
def test_conflict_detection():
    print('\n[3] Rede: pacote com o MEU ID vindo de outro PC')
    my_host = socket.gethostname()
    got = []
    with patched(network, get_windows_user=lambda: 'pedro.paiva',
                 get_local_ip=lambda *a, **k: '192.168.0.4'):
        d = network.UDPDiscovery(PEDRO, 'Pedro Paiva')
        d.on_uid_conflict = got.append

        def pkt(uid, host, login, name='x'):
            return json.dumps({'app': 'mbchat', 'type': 'announce', 'user_id': uid,
                               'display_name': name, 'hostname': host,
                               'winuser': login, 'ip': '192.168.0.50',
                               'version': '1.8.38'}).encode()

        d._handle_packet(pkt(PEDRO, my_host, 'pedro.paiva'), ('192.168.0.4', 50100))
        check(d.health['uid_conflicts'] == 0 and not got, 'eco do proprio announce nao e conflito')
        d._handle_packet(pkt(PEDRO, my_host.upper(), 'Pedro.Paiva'), ('192.168.0.4', 50100))
        check(d.health['uid_conflicts'] == 0, 'eco com outra caixa nao e conflito')

        d._handle_packet(pkt(PEDRO, '026DKT050', 'gustavo.barra', 'gustavo.barra'),
                         ('192.168.0.50', 50100))
        check(d.health['uid_conflicts'] == 1, 'outro PC com o meu ID -> conflito contado')
        check(len(got) == 1 and got[0]['hostname'] == '026DKT050'
              and got[0]['winuser'] == 'gustavo.barra' and got[0]['ip'] == '192.168.0.50',
              'callback recebe PC, login e IP de quem usa o ID', got)
        check(PEDRO not in d.peers, 'conflito nunca vira contato')
        last = d.health['uid_conflict_last'] or {}
        check(last.get('version') == '1.8.38', 'diagnostico guarda a versao do outro PC')

        for _ in range(5):
            d._handle_packet(pkt(PEDRO, '026DKT050', 'gustavo.barra'), ('192.168.0.50', 50100))
        check(d.health['uid_conflicts'] == 6 and len(got) == 1,
              'contador sobe a cada pacote, aviso so 1x a cada 10 min')

        d._handle_packet(pkt(PEDRO, my_host, 'gustavo.barra'), ('192.168.0.4', 50100))
        check(len(got) == 2, 'mesmo PC com OUTRO login do Windows tambem e conflito')

        d._handle_packet(pkt(COLEGA, '026DKT030', 'ana.raquel', 'Ana'), ('192.168.0.30', 50100))
        check(COLEGA in d.peers, 'peer normal continua entrando na lista')
        check(d.peers[COLEGA].get('display_name') == 'Ana', 'peer normal com o nome certo')

        raw = json.loads(d._make_packet(network.MT_ANNOUNCE).decode())
        check('login_scope' in raw, 'announce leva o tipo de conta (dominio/local)')


# ─────────────────────────────────────────────
# 4 — mesma pessoa em PC novo: junta historico
# ─────────────────────────────────────────────
def make_receiver(db, me=COLEGA, online=(), since=None):
    m = Messenger.__new__(Messenger)
    m.db = db
    m.user_id = me
    m._groups = {}
    m._identity_check_at = {}
    m.merged = []
    m.on_contact_merged = lambda o, n: m.merged.append((o, n))
    m.discovery = SimpleNamespace(_lock=threading.Lock(),
                                  peers={u: {} for u in online})
    db.set_setting('identity_tracking_since', str(since if since else time.time() - 30 * DAY))
    return m


def contact(db, uid, name, host, last_announce):
    db.upsert_contact(uid, name, '192.168.0.9', hostname=host,
                      winuser=identity.uid_login(uid))
    db.conn.execute("UPDATE contacts SET last_announce_at=? WHERE user_id=?",
                    (last_announce, uid))
    db.conn.commit()


def announce_info(uid, scope='domain', host=None, login=None, name='gustavo.barra'):
    return {'display_name': name, 'ip': '192.168.0.99', 'status': 'online',
            'hostname': host or identity.uid_hostname(uid, identity.uid_login(uid)),
            'winuser': login if login is not None else identity.uid_login(uid),
            'login_scope': scope}


def test_merge_same_person():
    print('\n[4] Mesma pessoa com ID novo: historico do ID antigo junta no novo')
    now = time.time()

    db, _ = new_db('merge_ok')
    contact(db, GUS_OLD, 'gustavo.barra', '026DKT050', now - 10 * DAY)
    add_msgs(db, COLEGA, GUS_OLD, 30, 'old')
    db.save_group('g1', 'Fiscal', 'fixed', creator_uid=GUS_OLD)
    db.save_group_member('g1', GUS_OLD, 'gustavo.barra', '192.168.0.9', 1)
    m = make_receiver(db)
    m._groups['g1'] = {'name': 'Fiscal', 'creator_uid': GUS_OLD, 'admins': [GUS_OLD],
                       'members': [{'uid': GUS_OLD, 'display_name': 'gustavo.barra', 'ip': ''}]}
    m._persist_announced_contact(GUS_NEW, announce_info(GUS_NEW))
    m._merge_previous_identities(GUS_NEW, announce_info(GUS_NEW))
    check(count_with(db, GUS_NEW) == 30 and count_with(db, GUS_OLD) == 0,
          'as 30 mensagens agora estao no ID novo')
    check(len(db.get_chat_history(COLEGA, GUS_NEW)) == 30, 'chat com ele mostra o historico todo')
    check(db.get_contact(GUS_OLD) is None and db.get_contact(GUS_NEW),
          'um contato so (o antigo sai, o novo fica)')
    check(m.merged == [(GUS_OLD, GUS_NEW)], 'GUI avisada para tirar o ID antigo da lista')
    g = m._groups['g1']
    check(g['members'][0]['uid'] == GUS_NEW and g['admins'] == [GUS_NEW]
          and g['creator_uid'] == GUS_NEW, 'grupo em memoria passou para o ID novo')
    gm = db.conn.execute("SELECT uid FROM group_members WHERE group_id='g1'").fetchall()
    check([r[0] for r in gm] == [GUS_NEW], 'grupo no banco passou para o ID novo')
    check(db.find_user_name(GUS_NEW) == 'gustavo.barra', 'nome da pessoa no historico')

    def scenario(name, setup, info, expect_merge, uid=GUS_NEW, **recv):
        db, _ = new_db('merge_' + name)
        setup(db)
        add_msgs(db, COLEGA, GUS_OLD, 4, 'x')
        m = make_receiver(db, **recv)
        m._persist_announced_contact(uid, info)
        m._merge_previous_identities(uid, info)
        merged = count_with(db, GUS_OLD) == 0
        check(merged == expect_merge, name,
              f'esperado {"juntar" if expect_merge else "NAO juntar"}')

    old10 = lambda db: contact(db, GUS_OLD, 'gustavo.barra', '026DKT050', now - 10 * DAY)
    scenario('ID antigo ONLINE agora nao junta (duas maquinas em uso)',
             old10, announce_info(GUS_NEW), False, online=(GUS_OLD,))
    scenario('ID antigo visto ha 2 dias nao junta (PC dele so desligado)',
             lambda db: contact(db, GUS_OLD, 'gustavo.barra', '026DKT050', now - 2 * DAY),
             announce_info(GUS_NEW), False)
    scenario('conta LOCAL em outro PC nao junta (pode ser outra pessoa)',
             old10, announce_info(GUS_NEW, scope='local'), False)
    scenario('conta LOCAL no mesmo PC junta',
             old10, announce_info(GUS_NEW, scope='local', host='026DKT050'), True)
    scenario('versao antiga (sem tipo de conta) em outro PC nao junta',
             old10, announce_info(GUS_NEW, scope=''), False)
    scenario('ID antigo sem registro + rastreio recente nao junta',
             lambda db: contact(db, GUS_OLD, 'gustavo.barra', '026DKT050', None),
             announce_info(GUS_NEW), False, since=now - 1 * DAY)
    scenario('ID antigo sem registro + rastreio ha 8 dias junta',
             lambda db: contact(db, GUS_OLD, 'gustavo.barra', '026DKT050', None),
             announce_info(GUS_NEW), True, since=now - 8 * DAY)
    scenario('ID copiado de outra pessoa nao puxa historico de ninguem',
             old10, announce_info(PEDRO, login='gustavo.barra'), False, uid=PEDRO)
    scenario('meu proprio ID nunca e juntado em outro',
             old10, announce_info(GUS_NEW), False, me=GUS_OLD)

    # Contato do Pedro com o campo winuser "contaminado" pelo conflito:
    # o login que vale e o de DENTRO do ID, entao o Pedro nunca vai para o Gustavo
    db, _ = new_db('merge_contaminado')
    contact(db, PEDRO, 'Pedro Paiva', '026DKT071', now - 10 * DAY)
    db.conn.execute("UPDATE contacts SET winuser='gustavo.barra' WHERE user_id=?", (PEDRO,))
    db.conn.commit()
    add_msgs(db, COLEGA, PEDRO, 12, 'pp')
    m = make_receiver(db)
    m._persist_announced_contact(GUS_NEW, announce_info(GUS_NEW))
    m._merge_previous_identities(GUS_NEW, announce_info(GUS_NEW))
    check(count_with(db, PEDRO) == 12 and db.get_contact(PEDRO),
          'historico do Pedro NUNCA vai para o Gustavo (mesmo com winuser trocado)')

    # Prazo: o merge espera IDENTITY_MERGE_MIN_OFFLINE_S
    check(IDENTITY_MERGE_MIN_OFFLINE_S >= 7 * DAY, 'prazo minimo de 7 dias sem se anunciar')

    # Volta para o PC antigo depois de largar o novo: a mesma regra devolve
    db, _ = new_db('merge_volta')
    contact(db, GUS_NEW, 'gustavo.barra', '026DKT099', now - 9 * DAY)
    add_msgs(db, COLEGA, GUS_NEW, 8, 'vt')
    m = make_receiver(db)
    m._persist_announced_contact(GUS_OLD, announce_info(GUS_OLD))
    m._merge_previous_identities(GUS_OLD, announce_info(GUS_OLD))
    check(count_with(db, GUS_OLD) == 8, 'voltou ao PC antigo: historico acompanha a pessoa')


# ─────────────────────────────────────────────
# 5 — troca de ID em todas as tabelas
# ─────────────────────────────────────────────
def test_rename_everywhere():
    print('\n[5] Troca de ID alcanca todas as tabelas')
    db, _ = new_db('rename')
    old, new, other = 'aaaaaaaaaaaa_PC1_x', 'bbbbbbbbbbbb_PC2_x', 'aaaaaaaaaaaa_PC1_xy'
    now = time.time()
    c = db.conn
    c.execute("INSERT INTO reactions VALUES ('m1', '👍', ?, ?)", (old, now))
    c.execute("INSERT INTO reactions VALUES ('m2', '❤', ?, ?)", (old, now))
    c.execute("INSERT INTO reactions VALUES ('m2', '❤', ?, ?)", (new, now))
    c.execute("INSERT INTO reminders (text, remind_at, created_at, creator_uid, invited_uids,"
              " accepted_uids, completed_by_uids) VALUES ('r', ?, ?, ?, ?, ?, ?)",
              (now, now, old, json.dumps([old, other]), json.dumps([other, old]), json.dumps([old])))
    db.save_group('g9', 'G', 'fixed', creator_uid=old)
    c.execute("INSERT INTO bookings (booking_id, room_id, title, creator_uid, creator_name,"
              " start_ts, end_ts, created_at, updated_at) VALUES ('b1', 1, 't', ?, 'X', ?, ?, ?, ?)",
              (old, now, now + 60, now, now))
    c.execute("INSERT INTO booking_participants (booking_id, uid, display_name) VALUES ('b1', ?, 'X')",
              (old,))
    c.execute("INSERT INTO block_list (user_id, display_name, blocked_at) VALUES (?, 'X', ?)", (old, now))
    c.commit()
    db._rename_user_id_everywhere(old, new)

    def one(sql, *a):
        return c.execute(sql, a).fetchall()
    check(one("SELECT COUNT(*) FROM reactions WHERE from_user=?", old)[0][0] == 0
          and one("SELECT COUNT(*) FROM reactions WHERE from_user=?", new)[0][0] == 2,
          'reacoes (duplicata da mesma reacao vira uma so)')
    r = one("SELECT creator_uid, invited_uids, accepted_uids, completed_by_uids FROM reminders")[0]
    check(r[0] == new, 'lembrete: criador')
    check(json.loads(r[1]) == [new, other] and json.loads(r[2]) == [other, new]
          and json.loads(r[3]) == [new],
          'lembrete: convidados/aceitos/concluidos (ID parecido intocado)', r)
    check(one("SELECT creator_uid FROM groups WHERE group_id='g9'")[0][0] == new, 'grupo: criador')
    check(one("SELECT creator_uid FROM bookings")[0][0] == new, 'reuniao: criador')
    check(one("SELECT uid FROM booking_participants")[0][0] == new, 'reuniao: participante')
    check(db.is_blocked(new) and not db.is_blocked(old), 'bloqueio continua valendo no ID novo')


# ─────────────────────────────────────────────
# 6 — historico nunca some
# ─────────────────────────────────────────────
def test_history_never_lost():
    print('\n[6] Historico permanente')
    import gui

    # 6a: dois contatos com o MESMO nome (mesma pessoa com 2 IDs, ou 2 "Ana")
    db, _ = new_db('nomes_iguais')
    a1, a2 = 'aaaaaaaaaaaa_PCA_ana', 'bbbbbbbbbbbb_PCB_ana.silva'
    db.upsert_contact(a1, 'Ana', '192.168.0.1')
    db.upsert_contact(a2, 'Ana', '192.168.0.2')
    db.set_all_contacts_offline()
    add_msgs(db, PEDRO, a1, 20, 'a1')
    add_msgs(db, PEDRO, a2, 20, 'a2')
    fake = SimpleNamespace(
        messenger=SimpleNamespace(db=db, user_id=PEDRO),
        peer_items={}, peer_info={}, group_general='geral',
        tree=SimpleNamespace(insert=lambda *a, **k: 'iid'),
        _create_contact_avatar=lambda *a, **k: None,
        _render_contact_display=lambda *a, **k: None,
        _sort_tree_children=lambda *a, **k: None)
    gui.LanMessengerApp._load_saved_contacts(fake)
    for _ in range(3):  # tres boots
        db.cleanup_unknown_contacts()
    check(db.get_contact(a1) and db.get_contact(a2), 'contatos com o mesmo nome nao sao apagados')
    check(count_with(db, a1) == 20 and count_with(db, a2) == 20,
          'conversas das duas "Ana" intactas apos 3 boots')
    check(a1 in fake.peer_info and a2 in fake.peer_info, 'nomes das duas disponiveis para o historico')

    src = open(os.path.join(root_dir, 'gui.py'), encoding='utf-8').read()
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == '_load_saved_contacts')
    check('delete_contact' not in ast.get_source_segment(src, fn),
          'guarda: _load_saved_contacts nunca apaga contato')

    # 6b: conversa com peer que NAO esta em contacts (contato sumiu) fica
    db, _ = new_db('sem_contato')
    add_msgs(db, PEDRO, 'cccccccccccc_PCC_joao', 15, 'jo')
    db.upsert_contact('fantasma_uid', '', '192.168.0.66')
    add_msgs(db, PEDRO, 'fantasma_uid', 5, 'fz')
    db.cleanup_unknown_contacts()
    check(count_with(db, 'cccccccccccc_PCC_joao') == 15, 'limpeza nao apaga conversa de contato ausente')
    check(count_with(db, 'fantasma_uid') == 0, 'fantasma explicito (nome vazio) continua limpo')
    check(db.find_user_name('cccccccccccc_PCC_joao') == 'joao',
          'sem contato, o nome vem do login dentro do ID (nao "[Desconhecido]")')

    # 6c: status sem nome nao apaga o nome do contato
    db, _ = new_db('status')
    db.upsert_contact('ana_uid', 'Ana Raquel', '192.168.0.11')
    add_msgs(db, PEDRO, 'ana_uid', 6, 'st')
    m = Messenger.__new__(Messenger)
    m.db, m.user_id, m.on_status = db, PEDRO, None
    m._on_tcp_message({'type': network.MT_STATUS, 'from_user': 'ana_uid', 'status': 'away'},
                      ('192.168.0.11', 50101))
    c = db.get_contact('ana_uid')
    check(c['display_name'] == 'Ana Raquel' and c['status'] == 'away',
          'status sem nome mantem o nome e atualiza o status')
    db.cleanup_unknown_contacts()
    check(count_with(db, 'ana_uid') == 6, 'historico da Ana sobrevive ao boot seguinte')


# ─────────────────────────────────────────────
# 7 — caso real completo
# ─────────────────────────────────────────────
def test_real_case():
    print('\n[7] Caso real: Pedro e Gustavo com o mesmo ID')
    # Banco do Pedro (dono) com historico
    db_p, path_p = new_db('real_pedro')
    db_p.set_local_user(PEDRO, 'Pedro Paiva')
    add_msgs(db_p, PEDRO, COLEGA, 50, 'pd')
    db_p.conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    path_g = os.path.join(_TMP_DIR, 'real_gustavo.db')
    shutil.copy(path_p, path_g)  # a pasta do Pedro foi parar no perfil do Gustavo

    _DB_PATH['path'] = path_p
    pedro = boot('pedro.paiva', 'ffffffffffff_X_pedro.paiva')
    _DB_PATH['path'] = path_g
    gustavo = boot('gustavo.barra', GUS_NEW)
    check(pedro.user_id == PEDRO, 'Pedro (dono) continua com o ID dele')
    check(gustavo.user_id == GUS_NEW, 'Gustavo ganha ID proprio ao abrir a versao nova')
    check(pedro.user_id != gustavo.user_id, 'os dois deixam de colidir na rede')
    check(count_with(pedro.db, PEDRO) == 50, 'historico do Pedro intacto no PC dele')
    check(len(gustavo.db.get_chat_history(GUS_NEW, COLEGA)) == 50,
          'Gustavo continua vendo o historico que ja via')

    # Colega: conhece o Pedro e o ID antigo do Gustavo (parado ha 30 dias)
    db_c, _ = new_db('real_colega')
    now = time.time()
    contact(db_c, PEDRO, 'Pedro Paiva', '026DKT071', now - 60)
    contact(db_c, GUS_OLD, 'gustavo.barra', '026DKT050', now - 30 * DAY)
    add_msgs(db_c, COLEGA, PEDRO, 25, 'cp')
    add_msgs(db_c, COLEGA, GUS_OLD, 18, 'cg')
    col = make_receiver(db_c, online=(PEDRO,))
    for uid, info in ((PEDRO, announce_info(PEDRO, name='Pedro Paiva')),
                      (GUS_NEW, announce_info(GUS_NEW))):
        col._persist_announced_contact(uid, info)
        col._merge_previous_identities(uid, info)
    check(count_with(db_c, PEDRO) == 25, 'colega: conversas com o Pedro continuam com o Pedro')
    check(count_with(db_c, GUS_NEW) == 18 and count_with(db_c, GUS_OLD) == 0,
          'colega: conversas antigas com o Gustavo voltam para ele')
    check(db_c.get_contact(PEDRO)['display_name'] == 'Pedro Paiva'
          and db_c.get_contact(GUS_NEW)['display_name'] == 'gustavo.barra',
          'colega: cada um com o proprio nome')


def main():
    tests = [test_helpers, test_boot_owner, test_conflict_detection,
             test_merge_same_person, test_rename_everywhere,
             test_history_never_lost, test_real_case]
    for t in tests:
        try:
            t()
        except Exception as e:
            import traceback
            traceback.print_exc()
            fail(f'{t.__name__} quebrou', repr(e))
    print(f'\n{len(PASS)} passou, {len(FAIL)} falhou')
    shutil.rmtree(_TMP_DIR, ignore_errors=True)
    sys.exit(0 if not FAIL else 1)


if __name__ == '__main__':
    main()
