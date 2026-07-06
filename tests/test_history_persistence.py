# Teste de persistencia TOTAL do historico — prova que nenhuma mensagem se
# perde, mesmo com dezenas de milhares de registros e com a limpeza de
# contatos desconhecidos rodando (a que apagava grupos/broadcast ate v1.8.27).
#
# Roda standalone, sem rede e sem GUI, num banco temporario:
#   python test_history_persistence.py
#
# Cobre:
#   1. 22.000+ mensagens: privadas (enviadas/recebidas), grupo temp, grupo
#      fixo, broadcast e lembretes
#   2. cleanup_unknown_contacts() NAO pode apagar nada legitimo
#   3. Queries de exibicao retornam TUDO (sem LIMIT oculto)
#   4. Grupos temporarios/fixos arquivados continuam resolviveis (nome+tipo)
#   5. Filtro por periodo (get_peers_with_match) integro em volume

import os
import sys
import time
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import Database

ME = 'pedro_TESTE123'


def main():
    tmp = tempfile.mkdtemp()
    db = Database(os.path.join(tmp, 'teste.db'))
    now = time.time()
    falhas = []

    def check(nome, cond, detalhe=''):
        status = 'OK  ' if cond else 'FALHA'
        print(f'[{status}] {nome}' + (f' — {detalhe}' if detalhe else ''))
        if not cond:
            falhas.append(nome)

    # ---------- carga ----------
    # Contatos legitimos (com nome) e 1 fantasma (sem nome — lixo de discovery)
    db.upsert_contact('iuri_uid', 'Iuri', '192.168.0.10')
    db.upsert_contact('ana_uid', 'ana.raquel', '192.168.0.11')
    db.upsert_contact('fantasma_uid', '', '192.168.0.99')  # sem display_name

    # Grupos: 1 temporario e 1 fixo (serao arquivados depois)
    db.save_group('gtmp1', 'Sala Vidro', 'temp', creator_uid=ME)
    db.save_group('gfix1', 'Equipe Fiscal', 'fixed', creator_uid=ME)
    db.save_group_member('gfix1', ME, 'pedro.paiva', '192.168.0.2', 1)
    db.save_group_member('gfix1', 'iuri_uid', 'Iuri', '192.168.0.10', 0)

    N_PRIV = 10000   # 5000 enviadas + 5000 recebidas com Iuri
    N_GRP = 8000     # 4000 por grupo (metade enviada, metade recebida)
    N_BCAST = 2000   # broadcasts enviados
    N_ANA = 2000     # conversa com ana (para filtro de periodo)

    t0 = time.time()
    c = db.conn
    with c:
        for i in range(N_PRIV // 2):
            ts = now - 86400 * 365 * 2 + i * 60  # espalha por ~2 anos
            c.execute(
                "INSERT INTO messages (msg_id, from_user, to_user, content,"
                " msg_type, timestamp, is_sent) VALUES (?,?,?,?,?,?,?)",
                (f'pe{i}', ME, 'iuri_uid', f'enviada {i}', 'text', ts, 1))
            c.execute(
                "INSERT INTO messages (msg_id, from_user, to_user, content,"
                " msg_type, timestamp, is_sent) VALUES (?,?,?,?,?,?,?)",
                (f'pr{i}', 'iuri_uid', ME, f'recebida {i}', 'text', ts + 1, 0))
        for gid, pref in (('gtmp1', 'gt'), ('gfix1', 'gf')):
            for i in range(N_GRP // 4):
                ts = now - 86400 * 180 + i * 30
                c.execute(
                    "INSERT INTO messages (msg_id, from_user, to_user,"
                    " content, msg_type, timestamp, is_sent, file_path)"
                    " VALUES (?,?,?,?,?,?,?,?)",
                    (f'{pref}e{i}', ME, f'group:{gid}', f'grupo env {i}',
                     'text', ts, 1, 'pedro.paiva'))
                c.execute(
                    "INSERT INTO messages (msg_id, from_user, to_user,"
                    " content, msg_type, timestamp, is_sent, file_path)"
                    " VALUES (?,?,?,?,?,?,?,?)",
                    (f'{pref}r{i}', 'iuri_uid', f'group:{gid}',
                     f'grupo rec {i}', 'text', ts + 1, 0, 'Iuri'))
        for i in range(N_BCAST):
            c.execute(
                "INSERT INTO messages (msg_id, from_user, to_user, content,"
                " msg_type, timestamp, is_sent) VALUES (?,?,?,?,?,?,?)",
                (f'bc{i}', ME, 'broadcast', f'aviso geral {i}', 'text',
                 now - 86400 * 90 + i * 120, 1))
        for i in range(N_ANA):
            c.execute(
                "INSERT INTO messages (msg_id, from_user, to_user, content,"
                " msg_type, timestamp, is_sent) VALUES (?,?,?,?,?,?,?)",
                (f'an{i}', 'ana_uid', ME, f'oi {i}', 'text',
                 now - 86400 * 30 + i * 600, 0))
        # 50 mensagens de peer FANTASMA (sem nome em lugar nenhum) — unico
        # conjunto que o cleanup DEVE apagar (lixo de bug de discovery)
        for i in range(50):
            c.execute(
                "INSERT INTO messages (msg_id, from_user, to_user, content,"
                " msg_type, timestamp, is_sent) VALUES (?,?,?,?,?,?,?)",
                (f'fz{i}', 'fantasma_uid', ME, f'lixo {i}', 'text', now, 0))

    total_inserido = N_PRIV + N_GRP + N_BCAST + N_ANA + 50
    print(f'Carga: {total_inserido} mensagens inseridas em '
          f'{time.time() - t0:.1f}s\n')

    cnt = lambda: c.execute('SELECT COUNT(*) FROM messages').fetchone()[0]
    antes = cnt()
    check('contagem pos-carga', antes == total_inserido,
          f'{antes}/{total_inserido}')

    # ---------- 1) a limpeza NAO pode comer nada legitimo ----------
    # (fantasma sem nome em contacts: o cleanup tambem o remove de contacts,
    #  entao as 50 dele somem — e APENAS elas)
    t0 = time.time()
    db.cleanup_unknown_contacts()
    depois = cnt()
    check('cleanup preserva tudo que e legitimo',
          depois == total_inserido - 50,
          f'{antes} -> {depois} (esperado {total_inserido - 50}, '
          f'{time.time() - t0:.2f}s)')
    # roda DE NOVO (simula varios boots) — nao pode comer mais nada
    db.cleanup_unknown_contacts()
    db.cleanup_unknown_contacts()
    check('cleanup idempotente (3 boots)', cnt() == depois)

    grp_env = c.execute("SELECT COUNT(*) FROM messages WHERE to_user LIKE"
                        " 'group:%' AND is_sent=1").fetchone()[0]
    check('grupo: enviadas intactas', grp_env == N_GRP // 2,
          f'{grp_env}/{N_GRP // 2}')
    bc = c.execute("SELECT COUNT(*) FROM messages WHERE to_user="
                   "'broadcast'").fetchone()[0]
    check('broadcast: intactos', bc == N_BCAST, f'{bc}/{N_BCAST}')

    # ---------- 2) exibicao retorna TUDO (sem LIMIT oculto) ----------
    t0 = time.time()
    msgs = db.get_messages_with_peer(ME, 'iuri_uid')
    check('conversa privada completa (10k)', len(msgs) == N_PRIV,
          f'{len(msgs)}/{N_PRIV} em {time.time() - t0:.2f}s')
    check('ordem cronologica ASC',
          msgs[0]['timestamp'] <= msgs[-1]['timestamp'])

    for gid, nome in (('gtmp1', 'grupo TEMP'), ('gfix1', 'grupo FIXO')):
        m = db.get_messages_with_peer(ME, f'group:{gid}')
        check(f'historico {nome} completo', len(m) == N_GRP // 2,
              f'{len(m)}/{N_GRP // 2}')

    hist = db.get_chat_history(ME, 'iuri_uid', limit=None)
    check('get_chat_history sem limite (janela de chat)',
          len(hist) == N_PRIV, f'{len(hist)}')

    contatos = db.get_history_contacts()
    peers = {x['peer'] for x in contatos}
    check('lista do historico cobre todos os peers',
          {'iuri_uid', 'ana_uid', 'broadcast', 'group:gtmp1',
           'group:gfix1'} <= peers, str(sorted(peers)))
    ord_ok = all(contatos[i]['last_ts'] >= contatos[i + 1]['last_ts']
                 for i in range(len(contatos) - 1))
    check('historico ordenado por recencia (DESC)', ord_ok)

    # ---------- 3) grupos arquivados continuam no historico ----------
    db.archive_group('gtmp1')
    db.archive_group('gfix1')
    ativos = db.get_groups('fixed')
    check('boot NAO reativa grupo arquivado', len(ativos) == 0)
    todos = {g['group_id']: g for g in db.get_groups(include_archived=True)}
    check('historico resolve nome+tipo do temp arquivado',
          todos.get('gtmp1', {}).get('name') == 'Sala Vidro'
          and todos.get('gtmp1', {}).get('group_type') == 'temp')
    check('historico resolve nome+tipo do fixo arquivado',
          todos.get('gfix1', {}).get('name') == 'Equipe Fiscal'
          and todos.get('gfix1', {}).get('group_type') == 'fixed')
    db.save_group('gtmp1', 'Sala Vidro', 'temp', creator_uid=ME)
    re = [g for g in db.get_groups(include_archived=False)
          if g['group_id'] == 'gtmp1']
    check('re-entrar no grupo reativa (archived=0)', len(re) == 1)

    # ---------- 4) filtro por periodo em volume ----------
    t0 = time.time()
    p = db.get_peers_with_match(date_from=now - 86400 * 31, date_to=now + 10)
    check('filtro De/Ate acha quem conversou no periodo',
          'ana_uid' in p and 'group:gtmp1' not in p,
          f'{len(p)} peers em {time.time() - t0:.2f}s')

    n = db.count_matching_messages(date_from=now - 86400 * 31,
                                   date_to=now + 10)
    check('contagem do periodo bate', n == N_ANA + 50 - 50 or n == N_ANA,
          f'{n}')

    print()
    if falhas:
        print(f'>>> {len(falhas)} FALHA(S): {falhas}')
        sys.exit(1)
    total = cnt()
    print(f'>>> TODOS OS CHECKS PASSARAM — {total} mensagens persistidas, '
          'zero perda alem do lixo de discovery.')


if __name__ == '__main__':
    main()
