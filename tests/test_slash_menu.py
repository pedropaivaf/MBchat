# test_slash_menu.py
# Valida o menu de formatacao "/" (estilo Notion) sem precisar testar visualmente.
# Rodar: python tests/test_slash_menu.py

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
# 1 — Logica pura do gatilho (sem Tk): so abre no inicio da linha
# ─────────────────────────────────────────────
def test_should_open_slash_menu():
    print('\n[1] _should_open_slash_menu (gatilho puro)')
    import gui

    cases = [
        ('', True, 'campo/linha vazia'),
        ('texto', False, 'meio de uma palavra'),
        ('10', False, 'simula data "10/12" -- nao pode disparar'),
        ('CNPJ ', False, 'meio de frase com espaco'),
        (' ', False, 'espaco antes do / -- gatilho estrito (so vazio conta)'),
        ('\t', False, 'tab antes do / -- gatilho estrito'),
    ]
    for text_before, expected, desc in cases:
        got = gui._should_open_slash_menu(text_before)
        if got == expected:
            ok(f'{desc!r} -> {got} (esperado {expected})')
        else:
            fail(f'{desc!r} -> {got}, esperado {expected}')


# ─────────────────────────────────────────────
# 2 — Barra de ferramentas: botoes pouco usados removidos, essenciais mantidos
# ─────────────────────────────────────────────
def test_toolbar_trimmed():
    print('\n[2] Barra de formatacao (analise de codigo)')
    with open(os.path.join(root_dir, 'gui.py'), encoding='utf-8') as f:
        src = f.read()

    # Os handlers continuam existindo (usados pelo menu /)
    if 'def _wrap_selection_fmt' in src and 'def _change_font' in src:
        ok('Handlers _wrap_selection_fmt/_change_font preservados (usados pelo menu /)')
    else:
        fail('Handlers de formatacao sumiram do codigo')

    # As duas janelas tem o novo metodo _on_slash_key
    count_on_slash = src.count('def _on_slash_key(self, event):')
    if count_on_slash == 2:
        ok('_on_slash_key definido em ChatWindow e GroupChatWindow (2 ocorrencias)')
    else:
        fail(f'_on_slash_key encontrado {count_on_slash}x, esperado 2 (ChatWindow + GroupChatWindow)')

    # Bind do KeyRelease-slash nas duas janelas
    count_bind = src.count("bind('<KeyRelease-slash>', self._on_slash_key)")
    if count_bind == 2:
        ok('Bind <KeyRelease-slash> presente 2x')
    else:
        fail(f'Bind <KeyRelease-slash> encontrado {count_bind}x, esperado 2')

    # O loop que criava os botoes B/I/U/S nao existe mais
    if "_letter, _font, _cmd, _tip in [" not in src:
        ok('Loop de criacao dos botoes B/I/U/S removido da barra')
    else:
        fail('Loop de criacao dos botoes B/I/U/S ainda presente')

    # Emoji, Codigo e Anexar continuam sendo criados (ficam visiveis)
    for needle, label in [
        ("command=self._show_emoji_picker", 'botao Emoji'),
        ("command=self._wrap_selection_code", 'botao Bloco de Codigo'),
        ("command=self._send_file", 'botao Anexar arquivo'),
    ]:
        n = src.count(needle)
        if n >= 2:
            ok(f'{label} continua presente nas duas janelas ({n}x)')
        else:
            fail(f'{label} encontrado so {n}x, esperado >=2 (ChatWindow + GroupChatWindow)')


# ─────────────────────────────────────────────
# 3 — Integracao real com Tk: o popup abre/nao abre conforme a posicao do "/"
# ─────────────────────────────────────────────
def test_slash_menu_live():
    print('\n[3] Integracao real com Tk (_open_slash_format_menu / _handle_slash_keyrelease)')
    import gui

    root = tk.Tk()
    root.geometry('500x300+0+0')
    root.update_idletasks()
    root.update()

    win = tk.Toplevel(root)
    win.geometry('400x250+0+0')
    entry = tk.Text(win, font=('Segoe UI', 10), wrap='word', padx=14, pady=10,
                     height=4, width=30)
    entry.pack(fill='both', expand=True)
    root.update_idletasks()
    root.update()

    triggered = {'count': 0}

    def build_items():
        triggered['count'] += 1
        return [
            ('Negrito', lambda: entry.insert('insert', '<<NEGRITO>>')),
            ('Italico', lambda: entry.insert('insert', '<<ITALICO>>')),
        ]

    def fire_slash():
        # Simula o <KeyRelease-slash>: a barra ja foi inserida pelo Tk antes
        # do handler rodar de verdade (mesma ordem do evento real).
        gui._handle_slash_keyrelease(win, entry, build_items)
        root.update_idletasks()
        root.update()

    # --- Caso A: campo vazio, digita "/" -> deve abrir ---
    entry.delete('1.0', 'end')
    entry.insert('1.0', '/')
    fire_slash()
    opened = bool(getattr(win, '_slash_menu', None)) and win._slash_menu.winfo_exists()
    if opened:
        ok('Campo vazio + "/" -> menu abriu')
    else:
        fail('Campo vazio + "/" -> menu NAO abriu (deveria)')
    if getattr(win, '_slash_menu', None):
        win._slash_menu.destroy()

    # --- Caso B: "/" no meio de texto (simula data "10/12") -> NAO deve abrir ---
    entry.delete('1.0', 'end')
    entry.insert('1.0', '10/')
    before = triggered['count']
    fire_slash()
    opened = bool(getattr(win, '_slash_menu', None)) and win._slash_menu.winfo_exists()
    if not opened and triggered['count'] == before:
        ok('"10/" (simulando data) -> menu NAO abriu')
    else:
        fail('"10/" (simulando data) -> menu abriu incorretamente')
    if getattr(win, '_slash_menu', None):
        try:
            win._slash_menu.destroy()
        except Exception:
            pass

    # --- Caso C: segunda linha vazia (apos Enter) + "/" -> deve abrir ---
    entry.delete('1.0', 'end')
    entry.insert('1.0', 'primeira linha\n/')
    fire_slash()
    opened = bool(getattr(win, '_slash_menu', None)) and win._slash_menu.winfo_exists()
    if opened:
        ok('Nova linha vazia + "/" -> menu abriu')
    else:
        fail('Nova linha vazia + "/" -> menu NAO abriu (deveria)')

    # --- Caso D: clicar num item aplica o callback e apaga o "/" ---
    entry.delete('1.0', 'end')
    entry.insert('1.0', '/')
    fire_slash()
    popup = getattr(win, '_slash_menu', None)
    if popup and popup.winfo_exists():
        # Acha a primeira linha clicavel (Negrito) e simula o clique.
        def find_rows(widget):
            found = []
            for child in widget.winfo_children():
                if isinstance(child, tk.Frame) and child.cget('cursor') == 'hand2':
                    found.append(child)
                found.extend(find_rows(child))
            return found
        rows = find_rows(popup)
        if rows:
            rows[0].event_generate('<Button-1>', x=5, y=5)
            root.update_idletasks()
            root.update()
            # _apply usa win.after(10, cb) -- drena a fila de eventos/timers.
            import time
            end = time.time() + 0.5
            while time.time() < end:
                root.update()
                time.sleep(0.01)
            content = entry.get('1.0', 'end-1c')
            if '/' not in content and '<<NEGRITO>>' in content:
                ok(f'Clique em "Negrito" -> "/" removido e callback aplicado ({content!r})')
            else:
                fail(f'Conteudo apos clique inesperado: {content!r}')
        else:
            fail('Nao encontrou nenhuma linha clicavel no popup')
    else:
        fail('Popup nao abriu para o teste de clique')

    # --- Caso E: Escape fecha sem aplicar nada (o "/" continua no texto) ---
    entry.delete('1.0', 'end')
    entry.insert('1.0', '/')
    fire_slash()
    popup = getattr(win, '_slash_menu', None)
    if popup and popup.winfo_exists():
        # Espera o _arm_focus (delay de 120ms) rodar de verdade e dar foco
        # real ao popup, igual aconteceria com um usuario de verdade -- sem
        # foco real o <Escape> sintetico nao roteia pro binding do popup.
        import time
        end = time.time() + 0.3
        while time.time() < end:
            root.update()
            time.sleep(0.01)
        popup.event_generate('<Escape>')
        root.update_idletasks()
        root.update()
        still_open = popup.winfo_exists()
        content = entry.get('1.0', 'end-1c')
        if not still_open and content == '/':
            ok('Esc fecha o menu sem alterar o conteudo (\"/\" permanece)')
        else:
            fail(f'Esc nao funcionou como esperado (still_open={still_open}, content={content!r})')
    else:
        fail('Popup nao abriu para o teste de Esc')

    root.destroy()


# ─────────────────────────────────────────────
# Resultado final
# ─────────────────────────────────────────────
if __name__ == '__main__':
    test_should_open_slash_menu()
    test_toolbar_trimmed()
    test_slash_menu_live()

    print(f'\n{"="*50}')
    print(f'  {len(PASS)} passou   {len(FAIL)} falhou')
    print('='*50)
    sys.exit(0 if not FAIL else 1)
