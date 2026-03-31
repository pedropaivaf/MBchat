"""
Gera mbchat.ico a partir do mbchat_icon.png (icone profissional 1024x1024).
Uso: python create_icon.py
"""
import os
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ICON_PNG = os.path.join(HERE, 'assets', 'mbchat_icon.png')


def save_icon(output_path=None):
    if output_path is None:
        output_path = os.path.join(HERE, 'assets', 'mbchat.ico')

    if not os.path.exists(ICON_PNG):
        print(f'ERRO: Icone PNG nao encontrado em {ICON_PNG}')
        return

    img = Image.open(ICON_PNG).convert('RGBA')

    sizes = [16, 24, 32, 48, 64, 128, 256]
    images = [img.resize((sz, sz), Image.LANCZOS) for sz in sizes]

    images[-1].save(
        output_path,
        format='ICO',
        sizes=[(sz, sz) for sz in sizes],
        append_images=images[:-1]
    )
    print(f'Icone HD salvo em: {output_path}')


if __name__ == '__main__':
    save_icon()
