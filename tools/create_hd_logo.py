import os
from PIL import Image, ImageDraw, ImageFont

def draw_logo(draw, s, tx, ty, w, scale=1.0):
    """
    Draws the main MB logo at position tx, ty with width w.
    """
    # Colors
    white = '#ffffff'
    red = '#e62429'
    bg_navy = '#182b5d' # matching the background

    # 1. Rounded rectangle outline
    box_w = w
    box_h = w * 0.55
    margin = w * 0.05
    radius = w * 0.08
    line_w = max(2, int(w * 0.03))
    
    # Draw outline
    draw.rounded_rectangle(
        [tx, ty, tx + box_w, ty + box_h],
        radius=radius, fill=None, outline=white, width=line_w
    )

    # 2. 'MB' Text inside
    font_size = int(w * 0.5)
    font = None
    # Try finding an italic/bold font
    for fp in [
        'C:/Windows/Fonts/segoeuib.ttf',
        'C:/Windows/Fonts/arialbd.ttf',
        'C:/Windows/Fonts/calibrib.ttf',
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
    
    txt_x = tx + (box_w - tw) / 2
    txt_y = ty + (box_h - th) / 2 - (w * 0.05) # adjust vertical center
    draw.text((txt_x, txt_y), text, fill=white, font=font)

    # 3. Dynamic red chart line 
    # Starts bottom left, goes diagonal up right, horizontal, diagonal up right
    red_w = max(3, int(w * 0.04))
    
    # points relative to tx, ty
    # bottom left out of box a bit
    p1 = (tx + box_w * 0.08, ty + box_h * 1.05)
    # diagonal up right
    p2 = (tx + box_w * 0.35, ty + box_h * 0.6)
    # diagonal up right more
    p3 = (tx + box_w * 0.65, ty + box_h * 0.6)
    # further up right out of box
    p4 = (tx + box_w * 1.05, ty - box_h * 0.1)

    # Let's just make a single dynamic diagonal red line over the M, and maybe a horizontal under B
    # Let's follow reference: diagonal up across M
    r1 = (tx + box_w * 0.1, ty + box_h * 0.85)
    r2 = (tx + box_w * 0.5, ty + box_h * 0.4)
    # horizontal under B
    r3 = (tx + box_w * 0.4, ty + box_h * 0.85)
    r4 = (tx + box_w * 0.9, ty + box_h * 0.85)
    # diagonal up right after B (optional)
    r5 = (tx + box_w * 0.8, ty + box_h * 0.85)
    r6 = (tx + box_w * 0.95, ty + box_h * 0.5)

    # It looks like one continuous line in the real logo:
    p1 = (tx + box_w * 0.1, ty + box_h * 1.1)
    p2 = (tx + box_w * 0.5, ty + box_h * 0.4)
    p3 = (tx + box_w * 0.95, ty - box_h * 0.1)
    
    # Actually just a thick red line across
    draw.line([p1, p3], fill=red, width=red_w)


def create_hd_image():
    W, H = 1920, 1080
    # SS = Supersampling
    SS = 4
    w, h = W * SS, H * SS
    
    img = Image.new('RGBA', (w, h), (0, 0, 0, 255))
    draw = ImageDraw.Draw(img)
    
    bg_color = (24, 43, 93) # #182b5d
    draw.rectangle([0, 0, w, h], fill=bg_color)
    
    # Add subtle left/right gradient or shapes if we want, but flat is cleaner
    
    logo_w = w * 0.35
    logo_tx = (w - logo_w) / 2
    logo_ty = h * 0.25
    
    draw_logo(draw, w, logo_tx, logo_ty, logo_w)
    
    # Add text "CONTABILIDADE"
    font_size_main = int(w * 0.045)
    font_main = None
    for fp in ['C:/Windows/Fonts/Montserrat-Bold.ttf', 'C:/Windows/Fonts/segoeuib.ttf', 'C:/Windows/Fonts/arialbd.ttf']:
        if os.path.exists(fp):
            font_main = ImageFont.truetype(fp, font_size_main)
            break
            
    if font_main is None:
        font_main = ImageFont.load_default()

    text_main = "CONTABILIDADE"
    bbox = draw.textbbox((0, 0), text_main, font=font_main)
    tw = bbox[2] - bbox[0]
    draw.text(((w - tw) / 2, logo_ty + logo_w * 0.65), text_main, fill="white", font=font_main)
    
    # Add text "A UNIÃO GERA RESULTADOS. E DE RESULTADOS NÓS ENTENDEMOS!!"
    font_size_sub = int(w * 0.018)
    font_sub = None
    for fp in ['C:/Windows/Fonts/Montserrat-Medium.ttf', 'C:/Windows/Fonts/segoeui.ttf', 'C:/Windows/Fonts/arial.ttf']:
        if os.path.exists(fp):
            font_sub = ImageFont.truetype(fp, font_size_sub)
            break
            
    if font_sub is None:
        font_sub = ImageFont.load_default()

    text_sub = "A UNIÃO GERA RESULTADOS. E DE RESULTADOS NÓS ENTENDEMOS!!"
    bbox = draw.textbbox((0, 0), text_sub, font=font_sub)
    tw2 = bbox[2] - bbox[0]
    draw.text(((w - tw2) / 2, logo_ty + logo_w * 0.65 + font_size_main * 1.3), text_sub, fill="white", font=font_sub)
    
    # Resize back for antialiasing
    final_img = img.resize((W, H), Image.LANCZOS)
    final_img.save("mbchat_hd_logo.png")
    print("Saved 1920x1080 to mbchat_hd_logo.png")

if __name__ == "__main__":
    create_hd_image()
