# test_emoji_pinched_fingers.py
# 🤌 (U+1F90C, Unicode 13) nao existe na Segoe UI Emoji do Windows 10 e saia
# INVISIVEL (seletor, chat, campo de digitar, recado, lista de contatos).
# Fix: so para esse caractere, no Windows 10 (ou se a fonte nao o desenhar),
# usa a imagem assets/emoji/1f90c.png. Este teste trava:
#   1. a imagem e a licenca existem e carregam;
#   2. no Windows 10 (simulado) o 🤌 sai visivel nas 4 funcoes de desenho,
#      no tamanho e fundo certos;
#   3. NENHUM outro emoji muda: com a fonte real da maquina, cada emoji do
#      app sai byte a byte igual com e sem o modo Windows 10;
#   4. a lista de excecoes tem so o 🤌 (pedido: nao mexer em nenhum outro).
# Rodar: python tests/test_emoji_pinched_fingers.py

import os
import re
import sys

here = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(here) if os.path.basename(here) == 'tests' else here
sys.path.insert(0, root_dir)

# Rotulos com emoji: no console cp1252 do Windows (gate/CI) o print quebraria.
try:
    sys.stdout.reconfigure(errors='backslashreplace')
except Exception:
    pass

import database
import tempfile
database.get_db_path = lambda *a, **k: os.path.join(tempfile.mkdtemp(), 't.db')

PASS, FAIL = [], []


def ok(msg):
    PASS.append(msg)
    print(f'  PASS  {msg}')


def fail(msg, detail=''):
    FAIL.append(msg)
    print(f'  FAIL  {msg}' + (f': {detail}' if detail else ''))


def check(cond, msg, detail=''):
    ok(msg) if cond else fail(msg, detail)


HAND = '\U0001f90c'


def main():
    import gui
    from PIL import Image, ImageTk

    # Captura a imagem PIL que iria para o Tk (sem precisar de janela)
    rec = []

    def _recorder(img, *a, **k):
        rec.append(img.copy())
        return len(rec) - 1
    ImageTk.PhotoImage = _recorder
    gui.ImageTk.PhotoImage = _recorder

    def pil(photo):
        return None if photo is None else rec[photo]

    def visible(img, bg=None):
        if img is None:
            return False
        img = img.convert('RGBA')
        if bg:
            return img.tobytes() != Image.new('RGBA', img.size, bg).tobytes()
        return img.getchannel('A').getbbox() is not None

    def same(a, b):
        if a is None or b is None:
            return a is b
        return a.size == b.size and a.convert('RGBA').tobytes() == b.convert('RGBA').tobytes()

    cw = gui.ChatWindow.__new__(gui.ChatWindow)
    gw = gui.GroupChatWindow.__new__(gui.GroupChatWindow)
    app = gui.LanMessengerApp.__new__(gui.LanMessengerApp)
    app._contact_avatar_pil = {}
    app._row_images = {}

    # ───────────── 1. imagem e licenca ─────────────
    print('\n[1] Imagem embutida')
    png = os.path.join(root_dir, 'assets', 'emoji', '1f90c.png')
    lic = os.path.join(root_dir, 'assets', 'emoji', 'LICENSE-fluentui-emoji.txt')
    check(os.path.isfile(png), 'assets/emoji/1f90c.png existe (build empacota a pasta assets inteira)')
    check(os.path.isfile(lic), 'licenca MIT do desenho junto da imagem')
    try:
        im = Image.open(png).convert('RGBA')
        check(im.size == (128, 128) and im.getchannel('A').getbbox() is not None,
              'PNG 128x128 com transparencia e conteudo', str(im.size))
    except Exception as e:
        fail('PNG carrega', str(e))
    check(set(gui._EMOJI_IMAGE_FALLBACK) == {HAND},
          'excecao vale so para o U+1F90C (nenhum outro emoji)', repr(gui._EMOJI_IMAGE_FALLBACK))

    # ───────────── 2. Windows 10: 🤌 visivel nas 4 funcoes ─────────────
    print('\n[2] Windows 10 (simulado): U+1F90C visivel')
    gui._IS_WIN10 = True
    for size in (14, 18, 20):
        img = pil(gui._render_color_emoji(HAND, size))
        check(visible(img) and img.size == (size + 4, size + 4),
              f'_render_color_emoji {size}px (recado, reacoes, seletor do recado)',
              str(img and img.size))
    img = pil(gui._render_color_emoji(HAND + '️', 20))
    check(visible(img), 'variante com FE0F tambem')
    for name, cls, obj in (('chat', gui.ChatWindow, cw), ('grupo', gui.GroupChatWindow, gw)):
        for size, bg in ((34, None), (20, '#dcf8c6'), (18, None), (34, '#ffffff')):
            img = pil(cls._render_emoji_image(obj, HAND, size, bg_color=bg))
            bgt = tuple(int(bg[i:i + 2], 16) for i in (1, 3, 5)) + (255,) if bg else None
            good = (visible(img, bgt) and img.size == (size + 4, size + 4)
                    and (bgt is None or img.getpixel((0, 0)) == bgt))
            check(good, f'{name}: _render_emoji_image {size}px fundo {bg or "transparente"}',
                  str(img and img.size))
    calls = []
    orig_fb = gui._emoji_fallback_image

    def _spy(ch, *a, **k):
        r = orig_fb(ch, *a, **k)
        if r is not None:
            calls.append(ch)
        return r
    gui._emoji_fallback_image = _spy
    try:
        row = app._render_contact_display('u1', 'Ana', f'bom dia {HAND}', 'online')
        if row is None or not gui._get_emoji_font_paths():
            # Sem fonte de emoji nenhuma a lista desenha TODOS os emojis como
            # texto; no Windows a Segoe UI Emoji sempre existe.
            ok('lista de contatos: maquina sem fonte de emoji (so roda no Windows) -- pulado')
        else:
            check(calls == [HAND], 'lista de contatos: recado com U+1F90C usa a imagem', repr(calls))
    finally:
        gui._emoji_fallback_image = orig_fb

    # ───────────── 3. nenhum outro emoji muda ─────────────
    print('\n[3] Outros emojis: identicos com e sem o modo Windows 10')
    with open(os.path.join(root_dir, 'gui.py'), encoding='utf-8') as f:
        src = f.read()
    cps = sorted({int(h, 16) for h in re.findall(r'\\U000([0-9a-fA-F]{5})', src)} |
                 {int(h, 16) for h in re.findall(r'\\u(2[0-9a-fA-F]{3})', src)})
    others = [chr(c) for c in cps if c >= 0x2300 and chr(c) != HAND] + ['❤️']
    check(all(gui._emoji_fallback_image(ch, 20, 24) is None for ch in others),
          f'imagem embutida nunca usada para os outros {len(others)} emojis do app')

    def render_all(flag):
        gui._IS_WIN10 = flag
        out = []
        for ch in others:
            out.append(pil(gui._render_color_emoji(ch, 20)))
            out.append(pil(gui.ChatWindow._render_emoji_image(cw, ch, 34)))
            out.append(pil(gui.ChatWindow._render_emoji_image(cw, ch, 20, bg_color='#dcf8c6')))
            out.append(pil(gui.GroupChatWindow._render_emoji_image(gw, ch, 18)))
        for ch in others[:40]:
            out.append(pil(app._render_contact_display('u2', 'Bruno', f'oi {ch}', 'online')))
        return out
    a = render_all(False)
    b = render_all(True)
    diff = sum(1 for x, y in zip(a, b) if not same(x, y))
    drawn = sum(1 for x in a if x is not None)
    check(diff == 0, f'{len(a)} desenhos de outros emojis identicos byte a byte '
                     f'({drawn} desenhados pela fonte desta maquina)', f'{diff} diferentes')
    gui._IS_WIN10 = None

    # ───────────── 4. busca no seletor ─────────────
    print('\n[4] Busca no seletor (chat e recado) acha o U+1F90C por "italia"')
    # busca do seletor: query.lower() in nome -> nome precisa conter as grafias
    nomes = [n for n in re.findall(r"'\\U0001f90c': '([^']*)'", src)
             if not n.endswith('.png')]  # ignora o mapa da imagem embutida
    check(len(nomes) == 2, 'nome cadastrado nos 2 seletores (chat e recado)', str(len(nomes)))
    for q in ('italia', 'itália', 'Itália', 'ITALIA', 'mão', 'mao', 'coxinha'):
        check(all(q.lower() in n for n in nomes), f'busca "{q}" acha o U+1F90C nos 2 seletores')


if __name__ == '__main__':
    main()
    print(f'\n{len(PASS)} PASS, {len(FAIL)} FAIL')
    print(f'{len(PASS)} passou {len(FAIL)} falhou')  # resumo lido pelo gate
    sys.exit(0 if not FAIL else 1)
