# test_reply_hittest.py
# Valida o fix que permite responder a uma mensagem que JA E uma resposta
# (estilo WhatsApp): o hit-test do clique direito passa a incluir a area da
# citacao (topo do balao), em chat individual E grupo.
#
# Sem GUI (tkinter nao existe no CI headless) — analise estrutural de gui.py
# garantindo que bubble_start e capturado ANTES da citacao, que _msg_hit_idx
# e populado/consultado e que a tag da mensagem cobre a citacao.
#
# Rodar: python tests/test_reply_hittest.py

import os
import re
import sys

here = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(here) if os.path.basename(here) == 'tests' else here

PASS, FAIL = [], []
def ok(m): PASS.append(m); print(f'  PASS  {m}')
def bad(m, d=''): FAIL.append(m); print(f'  FAIL  {m}' + (f': {d}' if d else ''))

with open(os.path.join(root_dir, 'gui.py'), encoding='utf-8') as f:
    SRC = f.read()


def func_body(name_marker_after):
    # Extrai um _append_message: do 'def _append_message' ate o proximo 'def '
    # no mesmo nivel. name_marker_after distingue individual (mstart_) de grupo (gmstart_).
    spans = [m.start() for m in re.finditer(r'\n    def _append_message\(', SRC)]
    for s in spans:
        nxt = SRC.find('\n    def ', s + 10)
        body = SRC[s:nxt]
        if name_marker_after in body:
            return body
    return ''


def test_counts_globais():
    print('\n[Wiring] listas e consultas de hit-test')
    pairs = [
        ('_msg_hit_idx = []', 2, 'init de _msg_hit_idx nas duas janelas'),
        ('self._msg_hit_idx.append((hit_mark, end_mark))', 2, 'append do hit-test nas duas janelas'),
        ('enumerate(self._msg_hit_idx)', 2, 'hit-test itera _msg_hit_idx (individual+grupo)'),
    ]
    for token, n, desc in pairs:
        c = SRC.count(token)
        if c == n: ok(f'{desc} (x{c})')
        else: bad(f'{desc}', f'achou {c}, esperado {n}')

    # Nenhum _find_msg_idx_at_index pode mais iterar a lista antiga
    leftover = SRC.count('enumerate(self._msg_ranges_idx)')
    if leftover == 0:
        ok('Nenhum hit-test usa mais _msg_ranges_idx (so _msg_hit_idx)')
    else:
        bad('hit-test ainda usa _msg_ranges_idx', f'{leftover} ocorrencia(s)')

    for mark in ("hit_mark = f'hstart_{n}'", "hit_mark = f'ghstart_{n}'"):
        if mark in SRC: ok(f'mark de hit-test criado: {mark}')
        else: bad(f'mark de hit-test ausente: {mark}')


def test_ordem_individual():
    print('\n[ChatWindow] bubble_start antes da citacao + tag cobre a citacao')
    b = func_body('mstart_')
    if not b:
        bad('nao localizou _append_message individual'); return
    p_bubble = b.find("bubble_start = self.chat_text.index('end-1c')")
    p_quote = b.find('get_message_by_id(reply_to)')
    p_tag = b.find('tag_add(msg_tag_name')
    if 0 <= p_bubble < p_quote:
        ok('bubble_start capturado ANTES de renderizar a citacao')
    else:
        bad('bubble_start nao vem antes da citacao', f'bubble={p_bubble} quote={p_quote}')
    if 0 <= p_bubble < p_tag and 'self.chat_text.index(bubble_start)' in b:
        ok('tag da mensagem comeca em bubble_start (cobre a citacao)')
    else:
        bad('tag nao usa bubble_start')
    if 'self._msg_hit_idx.append((hit_mark, end_mark))' in b:
        ok('append no _msg_hit_idx presente no individual')
    else:
        bad('sem append de hit-test no individual')


def test_ordem_grupo():
    print('\n[GroupChatWindow] bubble_start antes da citacao + tag cobre a citacao')
    b = func_body('gmstart_')
    if not b:
        bad('nao localizou _append_message de grupo'); return
    p_bubble = b.find("bubble_start = self.chat_text.index('end-1c')")
    p_quote = b.find('get_message_by_id(reply_to)')
    p_tag = b.find('tag_add(msg_tag_name')
    if 0 <= p_bubble < p_quote:
        ok('bubble_start capturado ANTES da citacao (grupo)')
    else:
        bad('bubble_start nao vem antes da citacao (grupo)', f'bubble={p_bubble} quote={p_quote}')
    if 0 <= p_bubble < p_tag and 'self.chat_text.index(bubble_start)' in b:
        ok('tag da mensagem comeca em bubble_start (grupo)')
    else:
        bad('tag nao usa bubble_start (grupo)')
    if 'self._msg_hit_idx.append((hit_mark, end_mark))' in b:
        ok('append no _msg_hit_idx presente no grupo')
    else:
        bad('sem append de hit-test no grupo')


def test_menu_incondicional():
    print('\n[Menu] "Responder" continua habilitado por msg_id (sem bloqueio por reply)')
    # has_id depende so de msg_id — nenhuma condicao por reply_to_id
    if "('\\uE97A', 'Responder', self._ctx_reply, has_id)" in SRC:
        ok('Item Responder usa has_id (existencia de msg_id)')
    else:
        bad('assinatura do item Responder mudou inesperadamente')
    if re.search(r"has_id = \(0 <= msg_idx < len\(self\._msg_data\)\s*\n\s*and bool\(self\._msg_data\[msg_idx\]\.get\('msg_id'\)\)\)", SRC):
        ok('has_id checa apenas msg_id (sem filtro de reply)')
    else:
        bad('logica de has_id nao encontrada como esperado')


def test_sintaxe():
    print('\n[Sanidade] gui.py compila')
    import ast
    try:
        ast.parse(SRC); ok('gui.py ast.parse OK')
    except SyntaxError as e:
        bad('SyntaxError', str(e))


if __name__ == '__main__':
    test_counts_globais()
    test_ordem_individual()
    test_ordem_grupo()
    test_menu_incondicional()
    test_sintaxe()
    print(f'\n{"="*52}\n  {len(PASS)} passou   {len(FAIL)} falhou\n{"="*52}')
    sys.exit(0 if not FAIL else 1)
