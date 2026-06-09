# Teste visual standalone do AvatarCropDialog — NAO abre o app inteiro,
# nao inicia rede nem banco. Apenas a janela de ajuste de foto.
#
# Uso:
#   python tools\test_avatar_crop.py                  -> usa imagem de teste gerada
#   python tools\test_avatar_crop.py C:\foto.jpg      -> usa sua propria foto
#
# O que validar:
#   1. A janela de crop APARECE centralizada, na frente, modal
#   2. Arrastar reposiciona a imagem dentro do circulo
#   3. Scroll do mouse da zoom in/out
#   4. Salvar foto -> abre o PNG 256x256 resultante no visualizador
#   5. Cancelar / X -> fecha sem salvar e o host volta a responder

import os
import sys
import tempfile
import tkinter as tk

# Permite importar gui.py a partir da raiz do projeto
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# Gera imagem de teste 1200x800 (gradiente + alvo central) para avaliar
# nitidez e enquadramento sem depender de uma foto real
def _make_test_image(path):
    from PIL import Image, ImageDraw
    w, h = 1200, 800
    img = Image.new('RGB', (w, h))
    d = ImageDraw.Draw(img)
    for y in range(h):
        d.line([(0, y), (w, y)],
               fill=(int(255 * y / h), 90, 255 - int(255 * y / h)))
    cx, cy = w // 2, h // 2
    for r in range(60, 361, 60):
        d.ellipse([cx - r, cy - r, cx + r, cy + r],
                  outline=(255, 255, 255), width=4)
    d.rectangle([cx - 40, cy - 40, cx + 40, cy + 40], fill=(255, 215, 0))
    d.text((cx - 30, cy - 8), 'CENTRO', fill=(0, 0, 0))
    img.save(path, 'JPEG', quality=92)


def main():
    import gui

    src = sys.argv[1] if len(sys.argv) > 1 else ''
    if not src:
        src = os.path.join(tempfile.gettempdir(), 'mbchat_test_avatar_src.jpg')
        _make_test_image(src)
    if not os.path.exists(src):
        print(f'Imagem nao encontrada: {src}')
        return

    dest = os.path.join(tempfile.gettempdir(), 'mbchat_test_avatar_out.png')

    root = tk.Tk()
    root.title('Host de teste (simula Preferencias)')
    root.geometry('360x150+100+100')
    tk.Label(root, text='Janela host — o crop deve abrir NA FRENTE dela',
             font=('Segoe UI', 9)).pack(pady=(12, 4))
    lbl = tk.Label(root, text='aguardando...', font=('Segoe UI', 9), fg='#555')
    lbl.pack()

    def _open():
        def _cb(ok):
            if ok:
                lbl.config(text=f'SALVO: {dest}', fg='#0a7a2f')
                try:
                    os.startfile(dest)  # abre o resultado no visualizador
                except Exception:
                    pass
            else:
                lbl.config(text='CANCELADO (nada salvo)', fg='#b00020')
        gui.AvatarCropDialog(root, src, dest, _cb)

    tk.Button(root, text='Abrir editor de foto', font=('Segoe UI', 9, 'bold'),
              command=_open).pack(pady=8)
    root.after(400, _open)  # abre sozinho ao iniciar
    root.mainloop()


if __name__ == '__main__':
    main()
