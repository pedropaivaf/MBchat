# -*- coding: utf-8 -*-
import tkinter as tk
import time
import threading

def run_mock_update():
    root = tk.Tk()
    root.withdraw()

    win = tk.Toplevel(root)
    win.title('MB Chat - Atualização')
    
    win.overrideredirect(True)
    win.configure(bg='#ffffff', highlightbackground='#e2e8f0', highlightcolor='#e2e8f0', highlightthickness=1)
    
    w, h = 360, 190
    ws = root.winfo_screenwidth()
    hs = root.winfo_screenheight()
    x = (ws/2) - (w/2)
    y = (hs/2) - (h/2)
    win.geometry('%dx%d+%d+%d' % (w, h, x, y))
    
    win.attributes('-topmost', True)
    win.grab_set()

    tk.Label(win, text='🚀 Atualizando o MB Chat', font=('Segoe UI', 12, 'bold'), bg='#ffffff', fg='#0f172a').pack(pady=(20, 5))
    lbl_sub = tk.Label(win, text='Baixando versão 1.8.23...', font=('Segoe UI', 9), bg='#ffffff', fg='#64748b')
    lbl_sub.pack(pady=(0, 10))
    
    canvas = tk.Canvas(win, width=280, height=8, bg='#f1f5f9', bd=0, highlightthickness=0)
    canvas.pack(pady=5)
    bar_id = canvas.create_rectangle(0, 0, 0, 8, fill='#3b82f6', outline='')
    
    lbl_pct = tk.Label(win, text='Iniciando...', font=('Segoe UI', 8, 'bold'), bg='#ffffff', fg='#3b82f6')
    lbl_pct.pack(pady=(5, 0))

    lbl_warn = tk.Label(win, text='💡 A instalação está sendo preparada,\naguarde o carregamento...', 
                        font=('Segoe UI', 8), bg='#ffffff', fg='#94a3b8', justify='center')
    lbl_warn.pack(pady=(10, 10))

    def _on_ok_click():
        lbl_pct.config(text='Reiniciando... O app fechará em breve.')
        btn_ok.config(state='disabled')
        root.after(1000, root.destroy)

    btn_ok = tk.Button(win, text='OK', font=('Segoe UI', 9, 'bold'), bg='#10b981', fg='white', 
                       relief='flat', bd=0, padx=20, pady=5, cursor='hand2', command=_on_ok_click)

    def _simulate():
        total = 20 * 1024 * 1024
        copied = 0
        chunk = 256 * 1024
        while copied < total:
            time.sleep(0.04)
            copied += chunk
            if copied > total: copied = total
            
            pct = int((copied / total) * 100)
            fill_width = int((copied / total) * 280)
            
            root.after(0, lambda fw=fill_width: canvas.coords(bar_id, 0, 0, fw, 8))
            root.after(0, lambda p=pct, c=copied, t=total: lbl_pct.config(text=f'{p}%  -  {c//1024} KB / {t//1024} KB'))
            
        root.after(0, lambda: lbl_sub.config(text='Download concluído!'))
        root.after(0, lambda: lbl_pct.config(text='Pronto para instalar.', fg='#10b981'))
        root.after(0, lambda: canvas.itemconfig(bar_id, fill='#10b981'))
        root.after(0, lambda: lbl_warn.pack_forget())
        root.after(0, lambda: btn_ok.pack(pady=(5, 10)))

    threading.Thread(target=_simulate, daemon=True).start()
    
    root.mainloop()

if __name__ == '__main__':
    run_mock_update()
