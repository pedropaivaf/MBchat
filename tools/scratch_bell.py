import tkinter as tk

def op():
    print('open called')
    p = tk.Toplevel(root)
    p.overrideredirect(True)
    p.geometry('+100+100')
    tk.Label(p, text="POPUP", padx=50, pady=50).pack()
    
    def on_focus_out(e):
        print(f'focus out! {e.widget}')
        p.destroy()
        
    p.bind('<FocusOut>', on_focus_out)
    
    # simulate the delay
    p.focus_set()

root = tk.Tk()
root.geometry('300x300')
f = tk.Frame(root, bg='red', width=50, height=50)
f.pack(side='right')
l = tk.Label(f, text='bell')
l.pack()
l.bind('<Button-1>', lambda e: op() or 'break')

root.mainloop()
