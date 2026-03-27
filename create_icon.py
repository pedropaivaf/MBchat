"""
Gera o icone do MB Chat (ICO com multiplas resolucoes).
Reproduz o logo corporativo MB Contabilidade:
- Fundo azul escuro
- "MB" branco estilizado em fonte bold
- Faixa vermelha diagonal cruzando as letras
- Faixa azul diagonal paralela (acento corporativo)
Renderiza em alta resolucao com supersampling LANCZOS.
"""
from PIL import Image, ImageDraw, ImageFont
import os


def create_icon(size=256):
    """Cria o icone reproduzindo o logo corporativo MB Contabilidade."""
    # Supersampling agressivo para nitidez maxima em todos os tamanhos
    if size <= 24:
        ss = 20
    elif size <= 32:
        ss = 16
    elif size <= 48:
        ss = 10
    elif size <= 64:
        ss = 8
    else:
        ss = 4
    s = size * ss
    img = Image.new('RGBA', (s, s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Cores do logo corporativo MB Contabilidade
    bg_navy = '#0c1a3d'
    white = '#ffffff'
    red = '#cc2222'
    accent_blue = '#2244aa'

    # --- Fundo: retangulo azul escuro com cantos arredondados ---
    margin = s * 0.02
    radius = s * 0.13
    draw.rounded_rectangle(
        [margin, margin, s - margin, s - margin],
        radius=radius, fill=bg_navy
    )

    # --- Texto "MB" centralizado, bold, grande ---
    font = None
    font_size = int(s * 0.56)
    # Prioriza fontes bold pesadas para maxima legibilidade
    for fp in [
        'C:/Windows/Fonts/arialbd.ttf',
        'C:/Windows/Fonts/ariblk.ttf',
        'C:/Windows/Fonts/impact.ttf',
        'C:/Windows/Fonts/calibrib.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
        '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
    ]:
        if os.path.exists(fp):
            try:
                font = ImageFont.truetype(fp, font_size)
                break
            except Exception:
                continue
    if font is None:
        font = ImageFont.load_default()

    text = "MB"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx = (s - tw) / 2
    ty = (s - th) / 2 - s * 0.015
    draw.text((tx, ty), text, fill=white, font=font)

    # --- Faixa azul diagonal (acento corporativo, atras da vermelha) ---
    # Diagonal do canto superior-direito para inferior-esquerdo
    blue_w = max(3, int(s * 0.038))
    offset = s * 0.065  # deslocamento para direita da faixa vermelha
    bx1 = s * 0.73 + offset
    by1 = s * 0.08
    bx2 = s * 0.23 + offset
    by2 = s * 0.88
    draw.line([(bx1, by1), (bx2, by2)], fill=accent_blue, width=blue_w)
    # Pontas arredondadas
    bcr = blue_w // 2
    draw.ellipse([bx1 - bcr, by1 - bcr, bx1 + bcr, by1 + bcr], fill=accent_blue)
    draw.ellipse([bx2 - bcr, by2 - bcr, bx2 + bcr, by2 + bcr], fill=accent_blue)

    # --- Faixa vermelha diagonal (marca principal) ---
    red_w = max(4, int(s * 0.052))
    rx1 = s * 0.73
    ry1 = s * 0.08
    rx2 = s * 0.23
    ry2 = s * 0.88
    draw.line([(rx1, ry1), (rx2, ry2)], fill=red, width=red_w)
    # Pontas arredondadas
    rcr = red_w // 2
    draw.ellipse([rx1 - rcr, ry1 - rcr, rx1 + rcr, ry1 + rcr], fill=red)
    draw.ellipse([rx2 - rcr, ry2 - rcr, rx2 + rcr, ry2 + rcr], fill=red)

    # Reduz para tamanho final com LANCZOS (alta qualidade)
    img = img.resize((size, size), Image.LANCZOS)
    return img


def save_icon(output_path='mbchat.ico'):
    """Salva o ICO com cada resolucao renderizada individualmente."""
    sizes = [16, 24, 32, 48, 64, 128, 256]
    images = []
    for sz in sizes:
        images.append(create_icon(sz))

    images[-1].save(
        output_path,
        format='ICO',
        sizes=[(sz, sz) for sz in sizes],
        append_images=images[:-1]
    )
    print(f'Icone salvo em: {output_path}')
    return output_path


if __name__ == '__main__':
    save_icon()
