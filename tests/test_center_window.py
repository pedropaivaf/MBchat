# test_center_window.py
# Valida que _center_window centraliza janelas secundarias na WORK AREA do
# monitor ativo (nao ancorada no retangulo da janela principal, que vive no
# canto direito da tela via _position_right).
# Regressao coberta: v1.8.37 passou a ancorar no pai -> filhas coladas na root.
# Rodar: python tests/test_center_window.py

import os
import sys

here = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(here) if os.path.basename(here) == 'tests' else here
sys.path.insert(0, root_dir)

import tkinter as tk

PASS, FAIL = [], []


def ok(msg):
    PASS.append(msg)
    print(f'  PASS  {msg}')


def fail(msg, detail=''):
    FAIL.append(msg)
    print(f'  FAIL  {msg}' + (f': {detail}' if detail else ''))


def _geom(win):
    # '{w}x{h}+{x}+{y}' -> (w, h, x, y)
    win.update_idletasks()
    g = win.geometry()
    size, x, y = g.split('+')[0], g.split('+')[1], g.split('+')[2]
    w, h = size.split('x')
    return int(w), int(h), int(x), int(y)


def run():
    import gui

    root = tk.Tk()
    # Simula _position_right: janela principal pequena, colada na borda direita
    # de um monitor primario de 1920x1080.
    PRIMARY = (0, 0, 1920, 1080)
    SECONDARY = (1920, 0, 1920 + 1600, 900)  # segundo monitor a direita, menor
    root.geometry('280x520+1620+250')
    root.update_idletasks()

    orig_bounds = gui._get_monitor_bounds

    # ---------------------------------------------------------------
    # 1 - Monitor primario: filha deve nascer no CENTRO da tela,
    #     nao colada na root (que esta em x=1620).
    # ---------------------------------------------------------------
    print('\n[1] Centraliza no monitor primario (ignora posicao da root)')
    gui._get_monitor_bounds = lambda win: PRIMARY
    child = tk.Toplevel(root)
    gui._center_window(child, 420, 480)
    w, h, x, y = _geom(child)
    exp_x = (1920 - 420) // 2
    exp_y = (1080 - 480) // 2
    if abs(x - exp_x) <= 2 and abs(y - exp_y) <= 2:
        ok(f'filha em ({x},{y}) ~ centro da tela ({exp_x},{exp_y})')
    else:
        fail(f'filha em ({x},{y}), esperado centro ({exp_x},{exp_y}) - ancorou na root?')
    if x < 1620:
        ok('filha NAO ficou colada na root (x < posicao da root)')
    else:
        fail(f'filha colada na root: x={x} >= root.x=1620 (REGRESSAO v1.8.37)')
    child.destroy()

    # ---------------------------------------------------------------
    # 2 - Monitor secundario: filha centraliza DENTRO do 2o monitor.
    # ---------------------------------------------------------------
    print('\n[2] Centraliza dentro do monitor secundario')
    gui._get_monitor_bounds = lambda win: SECONDARY
    child = tk.Toplevel(root)
    gui._center_window(child, 420, 480)
    w, h, x, y = _geom(child)
    l, t, r, b = SECONDARY
    exp_x = l + (r - l - 420) // 2
    exp_y = t + (b - t - 480) // 2
    if abs(x - exp_x) <= 2 and abs(y - exp_y) <= 2:
        ok(f'filha em ({x},{y}) ~ centro do 2o monitor ({exp_x},{exp_y})')
    else:
        fail(f'filha em ({x},{y}), esperado ({exp_x},{exp_y})')
    if l <= x and x + w <= r and t <= y and y + h <= b:
        ok('filha totalmente contida no monitor secundario')
    else:
        fail(f'filha vazou do monitor secundario: ({x},{y},{x+w},{y+h}) vs {SECONDARY}')
    child.destroy()

    # ---------------------------------------------------------------
    # 3 - Janela maior que o monitor: clamp mantem dentro (x,y >= left,top).
    # ---------------------------------------------------------------
    print('\n[3] Janela maior que o monitor -> clamp')
    gui._get_monitor_bounds = lambda win: PRIMARY
    child = tk.Toplevel(root)
    gui._center_window(child, 3000, 2000)
    w, h, x, y = _geom(child)
    if x == 0 and y == 0:
        ok(f'janela superdimensionada travada em (0,0)')
    else:
        fail(f'esperado (0,0) apos clamp, veio ({x},{y})')
    child.destroy()

    # ---------------------------------------------------------------
    # 4 - Sem w/h: usa winfo_reqwidth/reqheight, sem TypeError.
    # ---------------------------------------------------------------
    print('\n[4] _center_window(win) sem w/h -> reqwidth/reqheight (era TypeError)')
    gui._get_monitor_bounds = lambda win: PRIMARY
    child = tk.Toplevel(root)
    tk.Label(child, text='x' * 40, font=('Segoe UI', 12)).pack(padx=20, pady=20)
    try:
        gui._center_window(child)
        w, h, x, y = _geom(child)
        if w > 1 and h > 1 and 0 <= x <= 1920 and 0 <= y <= 1080:
            ok(f'sem w/h ok: {w}x{h}+{x}+{y}')
        else:
            fail(f'geometria suspeita sem w/h: {w}x{h}+{x}+{y}')
    except TypeError as e:
        fail(f'TypeError com w/h ausente: {e}')
    child.destroy()

    # ---------------------------------------------------------------
    # 5 - _get_monitor_bounds nao foi alterado (assinatura/uso leitura).
    # ---------------------------------------------------------------
    print('\n[5] _get_monitor_bounds intacto')
    gui._get_monitor_bounds = orig_bounds
    b = gui._get_monitor_bounds(root)
    if isinstance(b, tuple) and len(b) == 4:
        ok(f'_get_monitor_bounds(root) -> {b}')
    else:
        fail(f'_get_monitor_bounds retornou {b!r}')

    root.destroy()


if __name__ == '__main__':
    try:
        run()
    except tk.TclError as e:
        print(f'  SKIP  sem display disponivel: {e}')
        sys.exit(0)
    print(f'\n{"="*52}')
    print(f'  {len(PASS)} passou   {len(FAIL)} falhou')
    print('=' * 52)
    sys.exit(0 if not FAIL else 1)
