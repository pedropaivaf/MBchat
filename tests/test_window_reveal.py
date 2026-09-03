# test_window_reveal.py
# Valida que janelas secundarias nao "piscam" (mini janela branca no canto
# superior-esquerdo) antes de abrir: _center_window deixa a janela transparente
# durante a montagem e so revela quando o builder termina.
# Cobre tambem a regressao que a alternativa withdraw() causaria: 8 dialogos do
# app chamam grab_set() DEPOIS de _center_window, e grab_set em janela nao
# viewable levanta TclError.
# Rodar: python tests/test_window_reveal.py

import os
import sys
import time

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


def pump(root, seconds=0.4):
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        time.sleep(0.01)


def alpha(win):
    try:
        return float(win.attributes('-alpha'))
    except Exception:
        return None


def run():
    import gui

    root = tk.Tk()
    root.geometry('280x520+1620+250')
    root.update_idletasks()

    # ---------------------------------------------------------------
    # 1 - Durante a montagem a janela fica invisivel (alpha 0).
    # ---------------------------------------------------------------
    print('\n[1] Janela fica invisivel durante a montagem')
    w = tk.Toplevel(root)
    gui._center_window(w, 420, 300)
    a_build = alpha(w)
    if a_build == 0.0:
        ok('alpha=0.0 logo apos _center_window (nada visivel durante o build)')
    else:
        fail(f'alpha={a_build!r} apos _center_window, esperado 0.0')

    # simula o resto da montagem (widgets sendo empacotados)
    for i in range(5):
        tk.Label(w, text=f'linha {i}').pack()
    if alpha(w) == 0.0:
        ok('continua invisivel enquanto widgets sao empacotados')
    else:
        fail('revelou cedo demais, no meio da montagem')

    # ---------------------------------------------------------------
    # 2 - Assim que o controle volta ao event loop, revela.
    # ---------------------------------------------------------------
    print('\n[2] Revela ao terminar a montagem')
    pump(root)
    a_after = alpha(w)
    if a_after == 1.0:
        ok('alpha=1.0 apos o event loop rodar (janela visivel, ja pronta)')
    else:
        fail(f'alpha={a_after!r} apos event loop, esperado 1.0')
    w.destroy()

    # ---------------------------------------------------------------
    # 3 - update_idletasks no meio do build NAO revela cedo
    #     (after(0) e timer, nao idle task).
    # ---------------------------------------------------------------
    print('\n[3] update_idletasks no meio do build nao revela cedo')
    w = tk.Toplevel(root)
    gui._center_window(w, 400, 260)
    tk.Label(w, text='parcial').pack()
    w.update_idletasks()          # varios builders do app fazem isso
    if alpha(w) == 0.0:
        ok('update_idletasks nao disparou o reveal (segue invisivel)')
    else:
        fail('update_idletasks revelou a janela no meio da montagem')
    pump(root)
    if alpha(w) == 1.0:
        ok('revelou normalmente depois')
    else:
        fail('nao revelou apos o event loop')
    w.destroy()

    # ---------------------------------------------------------------
    # 4 - REGRESSAO CRITICA: grab_set() DEPOIS de _center_window.
    #     8 dialogos do app fazem isso. Com withdraw() daria TclError
    #     'grab failed: window not viewable' e o dialogo quebraria.
    # ---------------------------------------------------------------
    print('\n[4] grab_set() apos _center_window continua funcionando')
    w = tk.Toplevel(root)
    gui._center_window(w, 300, 120)
    w.transient(root)
    try:
        w.grab_set()
        ok('grab_set() nao levantou TclError (modalidade preservada)')
        try:
            if w.grab_current() is w:
                ok('grab realmente ativo na janela')
            else:
                fail(f'grab_current={w.grab_current()!r}, esperado a propria janela')
        except Exception as e:
            fail(f'grab_current falhou: {e}')
        w.grab_release()
    except tk.TclError as e:
        fail(f'grab_set levantou TclError: {e}')
    pump(root)
    w.destroy()

    # ---------------------------------------------------------------
    # 5 - Janela ja withdrawn pelo caller (padrao ChatWindow) e ignorada:
    #     nao mexe no alpha e nao faz deiconify por conta propria.
    # ---------------------------------------------------------------
    print('\n[5] Janela ja escondida pelo caller nao e tocada')
    w = tk.Toplevel(root)
    w.withdraw()
    gui._center_window(w, 420, 480)
    a = alpha(w)
    st = w.state()
    if a in (1.0, None) and st == 'withdrawn':
        ok(f'alpha intacto ({a}) e continua withdrawn (caller controla o deiconify)')
    else:
        fail(f'alpha={a!r} state={st!r}: _center_window mexeu numa janela que o caller escondeu')
    pump(root)
    if w.state() == 'withdrawn':
        ok('nao foi revelada sozinha depois do event loop')
    else:
        fail(f'foi revelada sozinha (state={w.state()}) — quebraria start_hidden do ChatWindow')
    w.destroy()

    # ---------------------------------------------------------------
    # 6 - REGRESSAO: se o alpha for aplicado ANTES da geometry, o Windows
    #     realiza o HWND cedo e joga a janela no cascade padrao (+156+156),
    #     perdendo a centralizacao. So aparece depois de algumas janelas
    #     criadas/destruidas antes -- por isso o "ruido" no comeco.
    # ---------------------------------------------------------------
    print('\n[6] Centralizacao sobrevive ao cascade do Windows')
    orig_bounds = gui._get_monitor_bounds
    gui._get_monitor_bounds = lambda win: (0, 0, 1920, 1080)
    for _ in range(4):  # ruido: janelas abertas e fechadas antes
        t = tk.Toplevel(root)
        gui._center_window(t, 400, 260)
        pump(root, 0.1)
        t.destroy()
    w = tk.Toplevel(root)
    gui._center_window(w, 420, 480)
    pump(root)
    g = w.geometry()
    x = int(g.split('+')[1])
    y = int(g.split('+')[2])
    exp_x, exp_y = (1920 - 420) // 2, (1080 - 480) // 2
    if abs(x - exp_x) <= 2 and abs(y - exp_y) <= 2:
        ok(f'geometria centralizada: {g}')
    else:
        fail(f'geometria {g}, esperado +{exp_x}+{exp_y} (caiu no cascade do WM)')

    # ---------------------------------------------------------------
    # 7 - REGRESSAO: sem update_idletasks o HWND nao existe, GetParent()
    #     retorna 0 e _apply_rounded_corners falha calado -> cantos quadrados.
    # ---------------------------------------------------------------
    print('\n[7] HWND real disponivel (cantos arredondados aplicam)')
    try:
        import ctypes
        hparent = ctypes.windll.user32.GetParent(w.winfo_id())
        if hparent:
            hr = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hparent, 33, ctypes.byref(ctypes.c_int(2)), 4)
            if hr == 0:
                ok(f'GetParent={hparent} e DwmSetWindowAttribute HRESULT=0')
            else:
                fail(f'DwmSetWindowAttribute HRESULT={hr} (cantos nao aplicam)')
        else:
            fail('GetParent=0: janela sem HWND real, _apply_rounded_corners falharia')
    except Exception as e:
        print(f'  SKIP  sem API DWM disponivel: {e}')
    w.destroy()
    gui._get_monitor_bounds = orig_bounds

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
