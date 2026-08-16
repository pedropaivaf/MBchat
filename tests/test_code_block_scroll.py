# test_code_block_scroll.py
# Valida o fix de scroll "pula/agarra" ao rolar por cima de um bloco de
# codigo grande. Causa raiz: um bloco de codigo embutido (window_create)
# ocupa milhares de pixels reais mas conta como poucas "linhas" pro Tk
# internamente -- rolar por 'units' faz 1 clique da roda pular o bloco
# inteiro de uma vez. Fix: rolar por 'pixels' em vez de 'units'.
# Rodar: python tests/test_code_block_scroll.py

import sys
import os

here = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(here) if os.path.basename(here) == 'tests' else here
sys.path.insert(0, root_dir)

import tkinter as tk

PASS = []
FAIL = []


def ok(msg):
    PASS.append(msg)
    print(f'  PASS  {msg}')


def fail(msg, detail=''):
    FAIL.append(msg)
    print(f'  FAIL  {msg}' + (f': {detail}' if detail else ''))


# ─────────────────────────────────────────────
# 1 — Analise de codigo: os 3 handlers usam 'pixels', nao 'units'
# ─────────────────────────────────────────────
def test_scroll_uses_pixels():
    print("\n[1] Handlers de scroll usam 'pixels' (analise de codigo)")
    with open(os.path.join(root_dir, 'gui.py'), encoding='utf-8') as f:
        src = f.read()

    checks = [
        ("self.chat_text.yview_scroll(-1 * (event.delta * 51 // 120), 'pixels')",
         "ChatWindow._on_mousewheel / GroupChatWindow._on_mousewheel / "
         "_wheel_to_chat (ChatWindow e GroupChatWindow) usam 'pixels'"),
    ]
    for needle, label in checks:
        n = src.count(needle)
        if n == 4:
            ok(f'{label} -- 4 ocorrencias encontradas')
        else:
            fail(f'{label} -- esperado 4 ocorrencias, achei {n}')

    if "def _on_mousewheel(self, event):\n        self.chat_text.yview_scroll(-1 * (event.delta * 51 // 120), 'pixels')\n        return 'break'" in src:
        ok('GroupChatWindow ganhou _on_mousewheel proprio (nao existia antes)')
    else:
        fail('GroupChatWindow._on_mousewheel nao encontrado no formato esperado')

    if "self.chat_text.bind('<MouseWheel>', self._on_mousewheel)" in src:
        ok('GroupChatWindow.chat_text agora tem bind explicito de MouseWheel')
    else:
        fail('Bind de MouseWheel no chat_text da GroupChatWindow nao encontrado')


# ─────────────────────────────────────────────
# 2 — Comportamental: rolar por cima de um bloco de codigo grande nao pula
# ─────────────────────────────────────────────
def test_no_big_jump_scrolling_through_code_block():
    print('\n[2] Scroll atraves de bloco de codigo grande (Tk real)')
    import gui

    root = tk.Tk()
    root.geometry('900x600+0+0')
    root.update_idletasks()
    root.update()

    def build_chat(window_cls):
        chat_text = tk.Text(root, wrap='word', font=('Segoe UI', 10), bg='#f5f7fa')
        chat_text.pack(fill='both', expand=True)
        for i in range(15):
            chat_text.insert('end', f'Mensagem normal numero {i}\n')

        class _Fake:
            pass
        fk = _Fake()
        fk.chat_text = chat_text
        fk._configure_code_tags_on = window_cls._configure_code_tags_on.__get__(fk)
        fk._highlight_json_into = window_cls._highlight_json_into.__get__(fk)
        fk._highlight_python_into = window_cls._highlight_python_into.__get__(fk)
        fk._highlight_generic_into = window_cls._highlight_generic_into.__get__(fk)
        fk._on_chat_resize_update_code = window_cls._on_chat_resize_update_code.__get__(fk)
        insert_code_block = window_cls._insert_code_block.__get__(fk)

        with open(os.path.join(root_dir, 'build.py'), encoding='utf-8') as f:
            code = ''.join(f.readlines()[:150])  # ~150 linhas, tamanho real testado pelo usuario
        insert_code_block(code, 'python')

        for i in range(15):
            chat_text.insert('end', f'Mensagem normal depois numero {i}\n')

        root.update_idletasks()
        root.update()
        return chat_text, fk

    def simulate_scroll(chat_text, on_mousewheel, n_clicks=60, delta=-120):
        class FakeEvent:
            pass
        ev = FakeEvent()
        ev.delta = delta
        chat_text.yview_moveto(0.0)
        root.update_idletasks()
        root.update()
        prev = chat_text.yview()[0]
        max_delta = 0.0
        for _ in range(n_clicks):
            on_mousewheel(ev)
            root.update_idletasks()
            root.update()
            now = chat_text.yview()[0]
            max_delta = max(max_delta, abs(now - prev))
            prev = now
            if now >= 0.999:
                break
        return max_delta

    # ChatWindow
    chat_text, fk = build_chat(gui.ChatWindow)
    fk._show_scrollbar = lambda: None
    fk._hide_scrollbar = lambda: None
    fk.after = lambda ms, cb: None
    on_mw = gui.ChatWindow._on_mousewheel.__get__(fk)
    max_d = simulate_scroll(chat_text, on_mw)
    if max_d < 0.05:
        ok(f'ChatWindow: maior salto em 60 cliques = {max_d:.4f} (sem pulo grande)')
    else:
        fail(f'ChatWindow: salto grande detectado = {max_d:.4f} '
             f'(bloco de codigo sendo pulado de uma vez)')
    chat_text.destroy()

    # GroupChatWindow
    chat_text2, fk2 = build_chat(gui.GroupChatWindow)
    on_mw2 = gui.GroupChatWindow._on_mousewheel.__get__(fk2)
    max_d2 = simulate_scroll(chat_text2, on_mw2)
    if max_d2 < 0.05:
        ok(f'GroupChatWindow: maior salto em 60 cliques = {max_d2:.4f} (sem pulo grande)')
    else:
        fail(f'GroupChatWindow: salto grande detectado = {max_d2:.4f} '
             f'(bloco de codigo sendo pulado de uma vez)')
    chat_text2.destroy()

    root.destroy()


if __name__ == '__main__':
    test_scroll_uses_pixels()
    test_no_big_jump_scrolling_through_code_block()

    print(f'\n{"="*50}')
    print(f'  {len(PASS)} passou   {len(FAIL)} falhou')
    print('='*50)
    sys.exit(0 if not FAIL else 1)
