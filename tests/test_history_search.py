# test_history_search.py
# Historico ponta a ponta com 500 mensagens: grava tudo no banco (caminho
# real de envio e de recebimento), exibe tudo e a busca por palavra acha
# exatamente as mensagens certas nas DUAS janelas:
#   - "Historico" da janela de chat (ChatWindow._show_history)
#   - Ferramentas > Historico de Mensagens (LanMessengerApp._show_all_history)
#
# Bugs que este teste trava (todos reproduzidos antes do fix):
#   1. Ferramentas > Historico: "atenção" nao achava "ATENÇÃO" (LIKE do
#      SQLite so ignora maiusculas em A-Z, sem acento).
#   2. "%" e "_" digitados viravam curinga do LIKE: "50%" achava "50 reais",
#      "arquivo_final" achava "arquivoXfinal".
#   3. Destaque amarelo so na 1a linha de mensagem com quebra de linha, e
#      pegando a data/hora (buscar "2026" pintava a data de toda mensagem).
#   4. Historico do chat carregava so as 5000 mensagens mais recentes (as
#      antigas sumiam da janela, continuavam no banco).
#   5. text.search(nocase=True) do Tk derruba o processo com emoji no texto
#      (guarda estatica: o destaque nao pode usar isso).
# Rodar: python tests/test_history_search.py

import os
import re
import sys
import json
import time
import struct
import socket
import tempfile
import threading
from datetime import datetime

here = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(here) if os.path.basename(here) == 'tests' else here
sys.path.insert(0, root_dir)

# Nunca abrir o banco de producao (%APPDATA%\.mbchat\mbchat.db)
import database
_TMP_DIR = tempfile.mkdtemp(prefix='mbchat_test_hist_')
database.get_db_path = lambda *a, **k: os.path.join(_TMP_DIR, 'hist.db')

import tkinter as tk
from tkinter import ttk

PASS, FAIL = [], []


def ok(msg):
    PASS.append(msg)
    print(f'  PASS  {msg}')


def fail(msg, detail=''):
    FAIL.append(msg)
    print(f'  FAIL  {msg}' + (f': {detail}' if detail else ''))


def check(cond, msg, detail=''):
    ok(msg) if cond else fail(msg, detail)


# ─────────────────────────────────────────────
# Receptor TCP local: faz o papel do PC do contato (recebe o que enviamos e
# os ACKs). Nada sai da maquina.
# ─────────────────────────────────────────────
_sink = {'messages': []}


def _start_sink():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(('127.0.0.1', 0))
    srv.listen(64)

    def loop():
        while True:
            try:
                c, _ = srv.accept()
            except OSError:
                return
            try:
                c.settimeout(5)
                hdr = b''
                while len(hdr) < 4:
                    ch = c.recv(4 - len(hdr))
                    if not ch:
                        break
                    hdr += ch
                if len(hdr) == 4:
                    n = struct.unpack('!I', hdr)[0]
                    data = b''
                    while len(data) < n:
                        ch = c.recv(n - len(data))
                        if not ch:
                            break
                        data += ch
                    p = json.loads(data.decode('utf-8'))
                    if p.get('type') == 'message':
                        _sink['messages'].append(p)
            except Exception:
                pass
            finally:
                c.close()
    threading.Thread(target=loop, daemon=True).start()
    return srv.getsockname()[1]


N = 500
PEER = 'f1e2d3c4b5a6_PC-ANA_ana.paula'
PEER_NAME = 'Ana Paula'
PEER2 = 'a9b8c7d6e5f4_PC-BRUNO_bruno'
BASE_TS = datetime(2026, 6, 1, 9, 0).timestamp()

SPECIAL = {
    3: 'ATENÇÃO: o relatório fiscal vence amanhã',
    4: 'enviei o Relatório de novo',
    7: 'atenção pessoal, reunião às 15h',
    11: 'Atenção com o prazo do DCTF',
    12: 'Linha A\n\nLinha C com relatorio e relatorio de novo',
    15: 'Linha um sem nada\nsegunda linha fala do relatorio mensal\nterceira linha',
    19: 'desconto de 50% no plano',
    23: 'o arquivo_final.xlsx esta na pasta',
    27: 'arquivoXfinal nao deveria aparecer na busca por underline',
    31: 'meta de 50 reais por pessoa',
    35: "caixa d'água e \"aspas\" e barra \\ invertida",
    39: 'emoji no meio 😀 do relatorio 👍 ok',
    43: 'link https://mbcontabilidade.com.br/relatorio?id=10 aqui',
    47: 'RELATORIO em maiusculas sem acento',
    51: 'x' * 1500 + ' relatorio no fim de um texto longo',
    55: 'balanco de 2026 fechado',
}


def content_of(i):
    return f'[MSG-{i:04d}] ' + SPECIAL.get(i, f'mensagem numero {i} conversa normal')


def expected(q):
    ql = q.lower()
    return sorted(i for i in range(1, N + 1) if ql in content_of(i).lower())


def occurrences(q, ids):
    return sum(content_of(i).lower().count(q.lower()) for i in ids)


def walk(w):
    yield w
    for ch in w.winfo_children():
        yield from walk(ch)


def pump(root, sec=0.3):
    end = time.time() + sec
    while time.time() < end:
        root.update()
        time.sleep(0.005)


def hl_texts(tw):
    rs = tw.tag_ranges('highlight')
    return [tw.get(rs[k], rs[k + 1]) for k in range(0, len(rs), 2)]


def hl_in_timestamp(tw):
    rs = tw.tag_ranges('highlight')
    return sum(1 for k in range(0, len(rs), 2) if 'ts' in tw.tag_names(rs[k]))


def type_into(root, entry, value, wait=0.3):
    # igual digitar/colar: o proprio Entry muda o texto e dispara o trace
    entry.delete(0, 'end')
    if value:
        entry.insert(0, value)
    pump(root, wait)


def main():
    import messenger
    import gui

    sink_port = _start_sink()
    # Envio e ACK vao para o receptor local (a porta do contato nao e conhecida
    # pelo discovery aqui, entao cai no TCP_PORT do modulo)
    messenger.TCP_PORT = sink_port

    m = messenger.Messenger(display_name='Pedro Teste')
    db = m.db
    ME = m.user_id
    db.upsert_contact(PEER, PEER_NAME, '127.0.0.1')
    db.upsert_contact(PEER2, 'Bruno Lima', '127.0.0.1')

    # ───────────── 1. gravacao pelos caminhos reais ─────────────
    print(f'\n[1] {N} mensagens: recebidas (_on_tcp_message) + enviadas (send_message)')
    recv_ts = {}
    for i in range(1, N + 1):
        c = content_of(i)
        if i % 2:
            ts = BASE_TS + i * 3 * 3600  # espalhadas por ~62 dias
            recv_ts[i] = ts
            m._on_tcp_message({'type': 'message', 'from_user': PEER, 'to_user': ME,
                               'display_name': PEER_NAME, 'msg_id': f'peer-{i}',
                               'content': c, 'timestamp': ts}, ('127.0.0.1', 50000))
        else:
            m.send_message(PEER, c)
    for k in range(10):
        m._on_tcp_message({'type': 'message', 'from_user': PEER2, 'to_user': ME,
                           'display_name': 'Bruno Lima', 'msg_id': f'b-{k}',
                           'content': f'[B-{k}] ' + ('bruno manda o relatorio' if k in (2, 5) else 'oi tudo bem'),
                           'timestamp': time.time() - 100 + k}, ('127.0.0.1', 50000))

    rows = db.get_chat_history(ME, PEER)
    ids = [int(re.match(r'\[MSG-(\d{4})\]', r['content']).group(1)) for r in rows]
    check(len(rows) == N and sorted(ids) == list(range(1, N + 1)),
          f'as {N} mensagens estao no banco, sem faltar nem duplicar', f'{len(rows)}')
    by_id = {i: r for i, r in zip(ids, rows)}
    bad = [i for i in ids if by_id[i]['content'] != content_of(i)]
    check(not bad, 'conteudo identico (multi-linha, emoji, aspas, %, _, 1500 chars)', f'{bad[:8]}')
    bad = [i for i in ids if bool(by_id[i]['is_sent']) != (i % 2 == 0)]
    check(not bad, 'direcao correta (enviada/recebida)', f'{bad[:8]}')
    bad = [i for i in recv_ts if abs(by_id[i]['timestamp'] - recv_ts[i]) > 0.001]
    check(not bad, 'data/hora original das recebidas preservada', f'{bad[:8]}')
    deadline = time.time() + 20
    while len(_sink['messages']) < N // 2 and time.time() < deadline:
        time.sleep(0.05)
    check(len(_sink['messages']) == N // 2, f'as {N // 2} enviadas sairam pela rede',
          f'{len(_sink["messages"])}')

    # busca no banco (usada por Ferramentas > Historico)
    for q in ('atenção', 'ATENÇÃO', 'relatorio', '50%', 'arquivo_final', '😀'):
        got = sorted(int(re.match(r'\[MSG-(\d{4})\]', r['content']).group(1))
                     for r in db.get_messages_with_peer(ME, PEER, search_text=q))
        check(got == expected(q), f'banco: busca "{q}" retorna as {len(expected(q))} certas',
              f'extras={sorted(set(got) - set(expected(q)))[:6]} faltando={sorted(set(expected(q)) - set(got))[:6]}')

    root = tk.Tk()
    root.withdraw()

    # ───────────── 2. janela Historico do chat ─────────────
    print('\n[2] Janela "Historico" do chat')

    class _App:
        _current_theme = 'MB Contabilidade'

    class _FakeChat(tk.Toplevel):
        pass
    fc = _FakeChat(root)
    fc.withdraw()
    fc.messenger = m
    fc.peer_id = PEER
    fc.peer_name = PEER_NAME
    fc.app = _App()
    gui.ChatWindow._show_history(fc)
    pump(root)
    hw = [w for w in fc.winfo_children() if isinstance(w, tk.Toplevel)][-1]
    ws = list(walk(hw))
    htxt = [w for w in ws if isinstance(w, tk.Text)][0]
    search_e, from_e, to_e = [w for w in ws if isinstance(w, tk.Entry)][:3]
    count_lbl = [w for w in ws if isinstance(w, tk.Label) and 'mensag' in str(w.cget('text'))][0]

    def shown():
        return [int(x) for x in re.findall(r'\[MSG-(\d{4})\]', htxt.get('1.0', 'end-1c'))]

    check(sorted(shown()) == list(range(1, N + 1)), f'exibe as {N} mensagens', f'{len(shown())}')
    check(shown() == ids[::-1], 'mais recente no topo')
    check(count_lbl.cget('text') == f'{N} mensagens', f'contador "{N} mensagens"', count_lbl.cget('text'))

    for q in ('relatorio', 'atenção', 'ATENÇÃO', '50%', 'arquivo_final', '😀', "d'água"):
        type_into(root, search_e, q)
        exp = expected(q)
        check(sorted(shown()) == exp, f'busca "{q}": mostra as {len(exp)} mensagens certas',
              f'mostrou {sorted(shown())[:10]}')
        occ = occurrences(q, exp)
        hls = hl_texts(htxt)
        check(len(hls) == occ and all(h.lower() == q.lower() for h in hls),
              f'busca "{q}": destaca as {occ} ocorrencias (todas as linhas)', f'{hls[:6]}')
    type_into(root, search_e, '2026')
    check(sorted(shown()) == [55] and hl_texts(htxt) == ['2026'] and not hl_in_timestamp(htxt),
          'busca "2026": acha so a mensagem e nao destaca a data/hora',
          f'{shown()} {hl_texts(htxt)}')
    check(count_lbl.cget('text') == '1 ocorrências em 1 mensagens',
          'contador nao conta a data/hora como ocorrencia', count_lbl.cget('text'))
    type_into(root, search_e, '')
    check(len(shown()) == N, 'limpar a busca volta a mostrar todas')

    exp_day = sorted(i for i, ts in recv_ts.items()
                     if datetime.fromtimestamp(ts).date() == datetime(2026, 6, 5).date())
    type_into(root, from_e, '05/06/2026')
    type_into(root, to_e, '05/06/2026')
    check(sorted(shown()) == exp_day, f'filtro De/Ate 05/06/2026: {len(exp_day)} mensagens do dia',
          f'{sorted(shown())[:10]}')
    hw.destroy()

    # ───────────── 3. Ferramentas > Historico de Mensagens ─────────────
    print('\n[3] Ferramentas > Historico de Mensagens')
    app = gui.LanMessengerApp.__new__(gui.LanMessengerApp)
    app.root = root
    app.messenger = m
    app.peer_info = {}
    app._current_theme = 'MB Contabilidade'
    before = set(root.winfo_children())
    app._show_all_history()
    pump(root, 0.5)
    gw = [w for w in root.winfo_children() if w not in before and isinstance(w, tk.Toplevel)][-1]
    ws = list(walk(gw))
    tree = [w for w in ws if isinstance(w, ttk.Treeview)][0]
    mtxt = [w for w in ws if isinstance(w, tk.Text)][0]
    g_search, g_from, g_to = [w for w in ws if isinstance(w, tk.Entry)][:3]
    g_count = [w for w in ws if isinstance(w, tk.Label) and 'conversa' in str(w.cget('text'))][0]
    right_hdr = [w for w in ws if isinstance(w, tk.Label) and 'Selecione' in str(w.cget('text'))][0]

    def g_select(peer):
        tree.selection_set(peer)
        pump(root, 0.4)

    def g_shown():
        return [int(x) for x in re.findall(r'\[MSG-(\d{4})\]', mtxt.get('1.0', 'end-1c'))]

    check(set(tree.get_children()) == {PEER, PEER2}, 'lista as 2 conversas')
    g_select(PEER)
    check(g_shown() == ids, f'painel exibe as {N} mensagens em ordem cronologica', f'{len(g_shown())}')
    check(f'({N} mensagens)' in right_hdr.cget('text'), 'cabecalho com o total', right_hdr.cget('text'))

    for q in ('relatorio', 'atenção', 'ATENÇÃO', 'Atenção', '50%', 'arquivo_final', '😀'):
        type_into(root, g_search, q, wait=0.6)
        exp = expected(q)
        in_b = q.lower() in 'bruno manda o relatorio'
        exp_peers = ({PEER} if exp else set()) | ({PEER2} if in_b else set())
        check(set(tree.get_children()) == exp_peers, f'busca "{q}": lista so as conversas com o termo',
              f'{tree.get_children()}')
        g_select(PEER)
        check(sorted(g_shown()) == exp, f'busca "{q}": painel mostra as {len(exp)} mensagens certas',
              f'extras={sorted(set(g_shown()) - set(exp))[:6]} faltando={sorted(set(exp) - set(g_shown()))[:6]}')
        occ = occurrences(q, exp)
        hls = hl_texts(mtxt)
        check(len(hls) == occ and all(h.lower() == q.lower() for h in hls),
              f'busca "{q}": destaca as {occ} ocorrencias (todas as linhas)', f'{hls[:6]}')
        total = len(exp) + (2 if in_b else 0)
        check(f'{total} mensagens' in g_count.cget('text'), f'busca "{q}": contador = {total}',
              g_count.cget('text'))
    type_into(root, g_search, '2026', wait=0.6)
    g_select(PEER)
    check(sorted(g_shown()) == [55] and hl_texts(mtxt) == ['2026'] and not hl_in_timestamp(mtxt),
          'busca "2026": acha so a mensagem e nao destaca a data/hora', f'{hl_texts(mtxt)}')
    type_into(root, g_search, '', wait=0.6)

    for e in (g_from, g_to):
        type_into(root, e, '05/06/2026', wait=0.05)
    app._history_refresh_cb()
    pump(root, 0.3)
    g_select(PEER)
    check(sorted(g_shown()) == exp_day and set(tree.get_children()) == {PEER},
          f'filtro De/Ate 05/06/2026: {len(exp_day)} mensagens e so a conversa do dia',
          f'{sorted(g_shown())}')
    gw.destroy()

    # ───────────── 4. volume: mais de 5000 com um contato ─────────────
    print('\n[4] Historico do chat com 6000 mensagens (antes sumiam as mais antigas)')
    BIG = 'c0ffee000000_PC-VOL_volume'
    db.upsert_contact(BIG, 'Volume', '127.0.0.1')
    base = time.time() - 6000 * 60
    db.conn.executemany(
        "INSERT INTO messages (msg_id, from_user, to_user, content, msg_type, timestamp, is_sent) "
        "VALUES (?,?,?,?,?,?,?)",
        [(f'v{i}', ME if i % 2 else BIG, BIG if i % 2 else ME, f'[VOL-{i:05d}] texto',
          'text', base + i * 60, i % 2) for i in range(1, 6001)])
    db.conn.commit()
    fc.peer_id, fc.peer_name = BIG, 'Volume'
    gui.ChatWindow._show_history(fc)
    pump(root)
    hw = [w for w in fc.winfo_children() if isinstance(w, tk.Toplevel)][-1]
    vtxt = [w for w in walk(hw) if isinstance(w, tk.Text)][0]
    vol = re.findall(r'\[VOL-(\d{5})\]', vtxt.get('1.0', 'end-1c'))
    check(len(vol) == 6000 and '00001' in vol, 'exibe as 6000, inclusive a mais antiga', f'{len(vol)}')
    hw.destroy()

    # ───────────── 5. guardas estaticas ─────────────
    print('\n[5] Guardas estaticas')
    with open(os.path.join(root_dir, 'gui.py'), encoding='utf-8') as f:
        src = f.read()
    code = '\n'.join(l for l in src.splitlines() if not l.strip().startswith('#'))
    check(not re.search(r'\.search\([^)]*nocase\s*=\s*(True|1)', code),
          'destaque nao usa text.search(nocase=True) (segfault do Tk 8.6 com emoji)')
    check('get_chat_history(self.peer_id, limit=5000)' not in src,
          'Historico do chat sem o limite de 5000')
    with open(os.path.join(root_dir, 'database.py'), encoding='utf-8') as f:
        dsrc = f.read()
    check('content LIKE' not in dsrc, 'busca de mensagens nao usa LIKE (curinga % e _)')

    root.destroy()


if __name__ == '__main__':
    main()
    print(f'\n{len(PASS)} PASS, {len(FAIL)} FAIL')
    sys.exit(0 if not FAIL else 1)
