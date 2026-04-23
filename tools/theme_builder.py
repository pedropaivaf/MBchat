"""
MB Chat — Theme Builder (tkinter)
================================

Janela Toplevel para criar, editar e salvar temas personalizados.

Integração em gui.py
--------------------

No topo (imports)::

    from tools.theme_builder import (
        ThemeBuilderWindow,
        load_user_themes,
        THEME_BUILDER_VERSION,
    )

Após definir o dict `THEMES` e antes do seletor::

    # Merge aditivo — nunca sobrescreve os 3 temas fixos
    for name, tokens in load_user_themes().items():
        if name not in THEMES:
            THEMES[name] = tokens

Item de menu (Preferências → Criar tema personalizado…)::

    menu_pref.add_command(
        label="Criar tema personalizado…",
        command=lambda: ThemeBuilderWindow(self.root, app=self),
    )

Contrato com o app host (`app`)
-------------------------------

O builder chama apenas dois métodos no host, ambos opcionais::

    app.THEMES            # dict — se disponível, usado como fonte base
    app.apply_theme(name) # só chamado ao clicar "Salvar e Aplicar"
    app.root              # janela raiz do tkinter (para grab_set / transient)

Se algum não existir, o builder continua funcionando — só não re-aplica.

Formato do arquivo salvo
------------------------

``%APPDATA%\\.mbchat\\user_themes.json``::

    {
      "version": 1,
      "themes": {
        "Meu Tema Azul": {
          "bg_window": "#e8f0fe",
          "bg_header": "#0f2a5c",
          ...
        }
      }
    }

Restrições aplicadas
--------------------

- Não sobrescreve temas fixos (Clássico, Night Mode, MB Contabilidade).
- Chaves ausentes no tema custom herdam do MB Contabilidade (fallback).
- JSON corrompido não crasha — retorna dict vazio e mostra aviso.
- Campo ``version`` permite migração futura sem quebrar arquivos antigos.
- Aceita só ``#RRGGBB`` (regex). ``rgb(...)`` ou nomes são rejeitados.
- ``json.dumps(ensure_ascii=False)`` — nomes com acento OK.
- Preview só no mini-chat interno. ``apply_theme`` só no Salvar e Aplicar.
- Fonte / tamanho NÃO mexidos (ficam em Preferências → Aparência).
"""

import json
import os
import re
import tkinter as tk
from tkinter import colorchooser, messagebox, ttk

THEME_BUILDER_VERSION = 1

# Nomes protegidos — nunca podem ser sobrescritos nem usados como nome custom.
BUILTIN_THEMES = {"Clássico", "Night Mode", "MB Contabilidade"}

# Fallback completo (tema MB Contabilidade) — usado quando chave falta no custom.
MB_DEFAULT = {
    "bg_window": "#f5f7fa",
    "bg_white": "#ffffff",
    "bg_header": "#0f2a5c",
    "bg_group": "#e2e2e2",
    "bg_select": "#e8f0fe",
    "bg_input": "#f7fafc",
    "bg_chat": "#f5f7fa",
    "fg_black": "#1a202c",
    "fg_gray": "#718096",
    "fg_white": "#ffffff",
    "fg_blue": "#0f2a5c",
    "fg_green": "#48bb78",
    "fg_red": "#cc2222",
    "fg_orange": "#ecc94b",
    "fg_group": "#4a5568",
    "fg_msg": "#1a202c",
    "fg_time": "#718096",
    "fg_my_name": "#0f2a5c",
    "fg_peer_name": "#cc2222",
    "btn_bg": "#0f2a5c",
    "btn_fg": "#ffffff",
    "btn_active": "#1a3f7a",
    "border": "#e2e8f0",
    "statusbar_bg": "#f5f7fa",
    "statusbar_fg": "#718096",
    "msg_my_bg": "#e8f0fe",
    "msg_peer_bg": "#f0f0f0",
    "hover": "#edf2f7",
    "accent": "#0f2a5c",
    "online": "#48bb78",
    "away": "#ecc94b",
    "busy": "#f56565",
    "offline_color": "#a0aec0",
    "btn_send_bg": "#0f2a5c",
    "btn_send_fg": "#ffffff",
    "btn_flat_fg": "#718096",
    "chat_header_bg": "#0f2a5c",
    "chat_header_fg": "#ffffff",
    "chat_header_sub": "#8aa0cc",
    "input_border": "#e2e8f0",
    "avatar_border": "#0f2a5c",
    "select_border": "#0f2a5c",
}

# Agrupamento das chaves para UI mais legível.
TOKEN_GROUPS = [
    ("Janela / superfícies",
        ["bg_window", "bg_white", "bg_input", "bg_chat", "bg_group", "hover"]),
    ("Header navy do chat",
        ["chat_header_bg", "chat_header_fg", "chat_header_sub", "bg_header"]),
    ("Mensagens",
        ["msg_my_bg", "msg_peer_bg", "fg_msg", "fg_my_name", "fg_peer_name", "fg_time"]),
    ("Texto",
        ["fg_black", "fg_gray", "fg_white", "fg_group"]),
    ("Acento & seleção",
        ["accent", "bg_select", "select_border", "avatar_border", "input_border", "border"]),
    ("Botões",
        ["btn_bg", "btn_fg", "btn_active", "btn_send_bg", "btn_send_fg", "btn_flat_fg"]),
    ("Status",
        ["online", "away", "busy", "offline_color", "fg_red", "fg_green", "fg_blue", "fg_orange"]),
    ("Statusbar",
        ["statusbar_bg", "statusbar_fg"]),
]

TOKEN_LABELS = {
    "bg_window": "Fundo da janela",
    "bg_white": "Superfície (card / input)",
    "bg_header": "Fundo do header (lista)",
    "bg_group": "Fundo de grupo",
    "bg_select": "Seleção / minha bolha",
    "bg_input": "Fundo do input",
    "bg_chat": "Fundo da área de mensagens",
    "fg_black": "Texto primário",
    "fg_gray": "Texto secundário / muted",
    "fg_white": "Texto sobre fundo escuro",
    "fg_blue": "Texto de link / destaque azul",
    "fg_green": "Texto verde (sucesso)",
    "fg_red": "Texto vermelho (erro)",
    "fg_orange": "Texto amarelo / aviso",
    "fg_group": "Texto do grupo",
    "fg_msg": "Texto da mensagem",
    "fg_time": "Texto do timestamp",
    "fg_my_name": "Cor do meu nome",
    "fg_peer_name": "Cor do nome do peer",
    "btn_bg": "Botão — fundo",
    "btn_fg": "Botão — texto",
    "btn_active": "Botão — hover/press",
    "border": "Borda padrão",
    "statusbar_bg": "Statusbar — fundo",
    "statusbar_fg": "Statusbar — texto",
    "msg_my_bg": "Bolha (minha)",
    "msg_peer_bg": "Bolha (peer)",
    "hover": "Hover de linha",
    "accent": "Acento (primário)",
    "online": "Status online",
    "away": "Status ausente",
    "busy": "Status ocupado",
    "offline_color": "Status offline",
    "btn_send_bg": "Enviar — fundo",
    "btn_send_fg": "Enviar — texto",
    "btn_flat_fg": "Botão flat — texto",
    "chat_header_bg": "Header do chat — fundo",
    "chat_header_fg": "Header do chat — texto",
    "chat_header_sub": "Header do chat — subtítulo",
    "input_border": "Borda de input",
    "avatar_border": "Borda do avatar",
    "select_border": "Borda de seleção",
}

HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


# ----------------------------------------------------------------------------- 
# Persistência
# ----------------------------------------------------------------------------- 

def _appdata_dir():
    """Retorna %APPDATA%\\.mbchat, criando se necessário."""
    appdata = os.environ.get("APPDATA") or os.path.expanduser("~")
    path = os.path.join(appdata, ".mbchat")
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        pass
    return path


def _themes_path():
    return os.path.join(_appdata_dir(), "user_themes.json")


def load_user_themes():
    """Carrega temas customizados do disco. Nunca crasha — retorna {} em erro.

    Aplica fallback por chave: qualquer token ausente no tema custom herda de
    MB_DEFAULT, garantindo que o tema é sempre válido mesmo se usuário salvou
    um JSON incompleto à mão.
    """
    path = _themes_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"[theme_builder] user_themes.json corrompido ou ilegível: {e}")
        return {}

    if not isinstance(data, dict):
        return {}

    # Migration hook — hoje só existe v1.
    version = data.get("version", 1)
    themes = data.get("themes") or {}
    if not isinstance(themes, dict):
        return {}

    result = {}
    for name, tokens in themes.items():
        if name in BUILTIN_THEMES:
            continue  # nunca sobrescreve builtin
        if not isinstance(tokens, dict):
            continue
        # Fallback por chave
        merged = dict(MB_DEFAULT)
        for k, v in tokens.items():
            if isinstance(v, str) and HEX_RE.match(v):
                merged[k] = v
        result[str(name)] = merged

    _ = version  # reservado pra migrações futuras
    return result


def save_user_themes(themes_dict):
    """Persiste o dict {nome: {tokens}} em user_themes.json."""
    path = _themes_path()
    payload = {
        "version": THEME_BUILDER_VERSION,
        "themes": {k: v for k, v in themes_dict.items() if k not in BUILTIN_THEMES},
    }
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except OSError as e:
        messagebox.showerror("Erro ao salvar", f"Não foi possível gravar\n{path}\n\n{e}")
        return False
    return True


# ----------------------------------------------------------------------------- 
# UI
# ----------------------------------------------------------------------------- 

class ThemeBuilderWindow(tk.Toplevel):
    """Janela Toplevel para criar/editar temas personalizados."""

    def __init__(self, parent, app=None):
        super().__init__(parent)
        self.app = app
        # Esconde antes de posicionar pra evitar flash no canto superior esquerdo.
        self.withdraw()
        self.title("Criar tema personalizado — MB Chat")
        # Centraliza no monitor
        w, h = 880, 620
        try:
            self.update_idletasks()
            sx = self.winfo_screenwidth()
            sy = self.winfo_screenheight()
            x = (sx - w) // 2
            y = (sy - h) // 2
            self.geometry(f"{w}x{h}+{x}+{y}")
        except Exception:
            self.geometry(f"{w}x{h}")
        self.minsize(800, 560)
        self.transient(parent)
        try:
            self.grab_set()
        except tk.TclError:
            pass

        # Lê tema atual do host para colorir a UI do builder. O preview
        # continua usando self.tokens (tema sendo construído).
        host_theme = None
        if app is not None and hasattr(app, "_theme"):
            host_theme = app._theme
        host_theme = host_theme or MB_DEFAULT
        self.ui = {
            "panel": host_theme.get("bg_white", "#ffffff"),
            "window": host_theme.get("bg_window", "#f5f7fa"),
            "border": host_theme.get("border", "#e2e8f0"),
            "text": host_theme.get("fg_black", "#1a202c"),
            "muted": host_theme.get("fg_gray", "#718096"),
            "accent": host_theme.get("accent", "#0f2a5c"),
            "accent_active": host_theme.get("btn_active", "#1a3f7a"),
            "btn_secondary_bg": host_theme.get("btn_bg", "#e2e8f0"),
            "btn_secondary_fg": host_theme.get("btn_fg", "#4a5568"),
            "hover": host_theme.get("hover", "#edf2f7"),
            "chip_bg": host_theme.get("bg_select", "#e8f0fe"),
            "chip_fg": host_theme.get("fg_blue", "#0f2a5c"),
            "input_bg": host_theme.get("bg_input", "#f7fafc"),
        }

        # State
        self.user_themes = load_user_themes()  # dict nome -> tokens
        self.current_name = tk.StringVar(value="Meu Tema")
        self.tokens = dict(MB_DEFAULT)  # sempre começa completo
        self.color_vars = {k: tk.StringVar(value=self.tokens[k]) for k in MB_DEFAULT}
        self._swatch_widgets = {}  # k -> Frame (pro recolorir)

        self._build_ui()
        self._refresh_preview()

        # Mostra agora (ja centralizada e com layout pronto)
        try:
            self.update_idletasks()
            self.deiconify()
        except Exception:
            pass

    # ------------------------------------------------------------------ 
    # Layout
    # ------------------------------------------------------------------ 

    def _build_ui(self):
        u = self.ui
        self.configure(bg=u["window"])

        # Toolbar superior: base + nome
        top = tk.Frame(self, bg=u["panel"], padx=14, pady=10,
                       highlightbackground=u["border"], highlightthickness=0)
        top.pack(side="top", fill="x")

        tk.Label(top, text="Base:", bg=u["panel"], fg=u["muted"],
                 font=("Segoe UI", 9)).pack(side="left")

        base_options = ["MB Contabilidade (default)"] + list(self.user_themes.keys())
        self.base_var = tk.StringVar(value=base_options[0])
        self.base_combo = ttk.Combobox(top, textvariable=self.base_var,
                                        values=base_options, state="readonly", width=28)
        self.base_combo.pack(side="left", padx=(6, 14))
        self.base_combo.bind("<<ComboboxSelected>>", self._on_base_change)

        tk.Label(top, text="Nome:", bg=u["panel"], fg=u["muted"],
                 font=("Segoe UI", 9)).pack(side="left")
        tk.Entry(top, textvariable=self.current_name, width=28,
                 font=("Segoe UI", 10), relief="solid", bd=1,
                 bg=u["input_bg"], fg=u["text"],
                 insertbackground=u["text"]).pack(side="left", padx=6)

        # Separador
        tk.Frame(self, height=1, bg=u["border"]).pack(side="top", fill="x")

        # Corpo: editor esquerda, preview direita
        body = tk.Frame(self, bg=u["window"])
        body.pack(side="top", fill="both", expand=True)

        # LEFT — scrollable editor
        left_wrap = tk.Frame(body, bg=u["panel"], width=490)
        left_wrap.pack(side="left", fill="both", expand=True)
        left_wrap.pack_propagate(False)

        canvas = tk.Canvas(left_wrap, bg=u["panel"], highlightthickness=0)
        scrollbar = tk.Scrollbar(left_wrap, orient="vertical", command=canvas.yview)
        self.editor = tk.Frame(canvas, bg=u["panel"])
        self.editor.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.create_window((0, 0), window=self.editor, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self._build_editor()

        # Scroll do mouse funciona em QUALQUER widget do painel esquerdo
        # (swatches, labels, canvas). Sem isso, so rolava com o mouse sobre
        # a barra de scroll.
        def _on_wheel(e):
            try:
                canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
            except Exception:
                pass
            return "break"

        def _bind_wheel_recursive(widget):
            try:
                widget.bind("<MouseWheel>", _on_wheel)
                # Linux
                widget.bind("<Button-4>",
                            lambda e: canvas.yview_scroll(-1, "units"))
                widget.bind("<Button-5>",
                            lambda e: canvas.yview_scroll(1, "units"))
            except Exception:
                pass
            for child in widget.winfo_children():
                _bind_wheel_recursive(child)

        _bind_wheel_recursive(left_wrap)

        # Separador vertical
        tk.Frame(body, width=1, bg=u["border"]).pack(side="left", fill="y")

        # RIGHT — preview
        right_wrap = tk.Frame(body, bg=u["window"], width=370)
        right_wrap.pack(side="left", fill="both")
        right_wrap.pack_propagate(False)
        tk.Label(right_wrap, text="PREVIEW", bg=u["window"], fg=u["muted"],
                 font=("Segoe UI", 8, "bold")).pack(anchor="w", padx=14, pady=(12, 6))
        self.preview_frame = tk.Frame(right_wrap, bg=u["window"])
        self.preview_frame.pack(fill="both", expand=True, padx=14, pady=(0, 14))

        # Footer
        footer = tk.Frame(self, bg=u["panel"], padx=14, pady=10)
        footer.pack(side="bottom", fill="x")
        tk.Frame(self, height=1, bg=u["border"]).pack(side="bottom", fill="x")

        self._build_saved_strip(footer)

        tk.Button(footer, text="Cancelar", command=self.destroy,
                  bg=u["btn_secondary_bg"], fg=u["btn_secondary_fg"], relief="flat",
                  font=("Segoe UI", 9), padx=14, pady=6,
                  activebackground=u["hover"]).pack(side="right", padx=(6, 0))

        tk.Button(footer, text="Salvar e Aplicar", command=self._save_and_apply,
                  bg=u["accent"], fg="#ffffff", relief="flat",
                  font=("Segoe UI", 9, "bold"), padx=14, pady=6,
                  activebackground=u["accent_active"]).pack(side="right")

        tk.Button(footer, text="Salvar", command=self._save_only,
                  bg=u["panel"], fg=u["accent"], relief="solid", bd=1,
                  font=("Segoe UI", 9), padx=14, pady=5,
                  activebackground=u["hover"]).pack(side="right", padx=(0, 6))

    def _build_editor(self):
        u = self.ui
        for g_title, keys in TOKEN_GROUPS:
            # section header
            sec = tk.Frame(self.editor, bg=u["panel"])
            sec.pack(fill="x", padx=14, pady=(12, 4))
            tk.Label(sec, text=g_title.upper(), bg=u["panel"], fg=u["muted"],
                     font=("Segoe UI", 8, "bold")).pack(anchor="w")

            grid = tk.Frame(self.editor, bg=u["panel"])
            grid.pack(fill="x", padx=14)
            for i, k in enumerate(keys):
                if k not in MB_DEFAULT:
                    continue
                row = i // 2
                col = i % 2
                cell = tk.Frame(grid, bg=u["panel"])
                cell.grid(row=row, column=col, sticky="ew", padx=(0, 10), pady=3)
                grid.columnconfigure(col, weight=1)
                self._build_token_row(cell, k)

    def _build_token_row(self, parent, key):
        u = self.ui
        sw = tk.Frame(parent, width=26, height=26, bg=self.tokens[key],
                      highlightbackground=u["border"], highlightthickness=1,
                      cursor="hand2")
        sw.pack_propagate(False)
        sw.pack(side="left")
        sw.bind("<Button-1>", lambda e, k=key: self._pick_color(k))
        self._swatch_widgets[key] = sw

        body = tk.Frame(parent, bg=u["panel"])
        body.pack(side="left", fill="x", expand=True, padx=(8, 0))

        tk.Label(body, text=TOKEN_LABELS.get(key, key), bg=u["panel"],
                 fg=u["text"], font=("Segoe UI", 9), anchor="w").pack(fill="x")

        entry = tk.Entry(body, textvariable=self.color_vars[key],
                         font=("Consolas", 8), relief="flat",
                         bg=u["panel"], fg=u["muted"], bd=0,
                         insertbackground=u["text"])
        entry.pack(fill="x")
        entry.bind("<FocusOut>", lambda e, k=key: self._on_hex_typed(k))
        entry.bind("<Return>", lambda e, k=key: self._on_hex_typed(k))

    def _build_saved_strip(self, parent):
        if not self.user_themes:
            return
        u = self.ui
        strip = tk.Frame(parent, bg=u["panel"])
        strip.pack(side="left", fill="x", expand=True)
        tk.Label(strip, text="Salvos:", bg=u["panel"], fg=u["muted"],
                 font=("Segoe UI", 8)).pack(side="left", padx=(0, 4))
        for name in list(self.user_themes.keys()):
            chip = tk.Frame(strip, bg=u["chip_bg"], padx=6, pady=2)
            chip.pack(side="left", padx=2)
            tk.Label(chip, text=name, bg=u["chip_bg"], fg=u["chip_fg"],
                     font=("Segoe UI", 8, "bold")).pack(side="left")
            tk.Label(chip, text="×", bg=u["chip_bg"], fg=u["chip_fg"],
                     font=("Segoe UI", 9), cursor="hand2").pack(side="left", padx=(4, 0))
            # Delete on click
            for w in chip.winfo_children():
                w.bind("<Button-1>", lambda e, n=name: self._delete_saved(n))

    # ------------------------------------------------------------------ 
    # Interações
    # ------------------------------------------------------------------ 

    def _on_base_change(self, event=None):
        choice = self.base_var.get()
        if choice.startswith("MB Contabilidade"):
            tokens = MB_DEFAULT
        else:
            tokens = self.user_themes.get(choice, MB_DEFAULT)
        for k, v in tokens.items():
            self.tokens[k] = v
            self.color_vars[k].set(v)
            sw = self._swatch_widgets.get(k)
            if sw:
                sw.configure(bg=v)
        self._refresh_preview()

    def _pick_color(self, key):
        rgb, hx = colorchooser.askcolor(
            color=self.tokens[key], parent=self,
            title=f"Escolher cor — {TOKEN_LABELS.get(key, key)}",
        )
        if hx:
            self._set_token(key, hx)

    def _on_hex_typed(self, key):
        value = self.color_vars[key].get().strip()
        if not HEX_RE.match(value):
            messagebox.showwarning(
                "Cor inválida",
                f"'{value}' não é uma cor hex válida.\n\n"
                "Use o formato #RRGGBB (ex: #0f2a5c).\n"
                "rgb(...) ou nomes de cor não são aceitos.",
                parent=self,
            )
            self.color_vars[key].set(self.tokens[key])
            return
        self._set_token(key, value.lower())

    def _set_token(self, key, hex_value):
        self.tokens[key] = hex_value
        self.color_vars[key].set(hex_value)
        sw = self._swatch_widgets.get(key)
        if sw:
            sw.configure(bg=hex_value)
        self._refresh_preview()

    # ------------------------------------------------------------------ 
    # Save flows
    # ------------------------------------------------------------------ 

    def _validate_name(self):
        name = self.current_name.get().strip()
        if not name:
            messagebox.showwarning("Nome vazio", "Dê um nome ao tema.", parent=self)
            return None
        if name in BUILTIN_THEMES:
            messagebox.showwarning(
                "Nome reservado",
                f"'{name}' é um tema padrão do MB Chat.\n"
                "Escolha outro nome para seu tema personalizado.",
                parent=self,
            )
            return None
        if len(name) > 60:
            messagebox.showwarning("Nome muito longo",
                                   "Use até 60 caracteres.", parent=self)
            return None
        return name

    def _save_only(self):
        name = self._validate_name()
        if not name:
            return
        self.user_themes[name] = dict(self.tokens)
        if save_user_themes(self.user_themes):
            messagebox.showinfo("Salvo", f"Tema '{name}' salvo.", parent=self)

    def _save_and_apply(self):
        name = self._validate_name()
        if not name:
            return
        self.user_themes[name] = dict(self.tokens)
        if not save_user_themes(self.user_themes):
            return
        # Propagar pro host
        if self.app is not None:
            try:
                if hasattr(self.app, "THEMES"):
                    self.app.THEMES[name] = dict(self.tokens)
                if hasattr(self.app, "apply_theme"):
                    self.app.apply_theme(name)
            except Exception as e:
                messagebox.showwarning(
                    "Tema salvo, mas não aplicado",
                    f"Salvou em user_themes.json, mas houve erro ao aplicar:\n{e}\n\n"
                    "Reinicie o MB Chat e selecione o tema manualmente.",
                    parent=self,
                )
                return
        self.destroy()

    def _delete_saved(self, name):
        if not messagebox.askyesno("Remover tema",
                                   f"Remover '{name}' permanentemente?",
                                   parent=self):
            return
        self.user_themes.pop(name, None)
        save_user_themes(self.user_themes)
        # Rebuild footer quick: simplest é fechar e pedir reabrir.
        messagebox.showinfo("Removido",
                            "Feche e reabra o builder para ver a lista atualizada.",
                            parent=self)

    # ------------------------------------------------------------------ 
    # Preview mini-chat
    # ------------------------------------------------------------------ 

    def _refresh_preview(self):
        for w in self.preview_frame.winfo_children():
            w.destroy()
        t = self.tokens

        box = tk.Frame(self.preview_frame, bg=t["bg_window"],
                       highlightbackground=t["border"], highlightthickness=1)
        box.pack(fill="both", expand=True)

        # Header
        hdr = tk.Frame(box, bg=t["chat_header_bg"], pady=8, padx=12)
        hdr.pack(fill="x")
        av = tk.Frame(hdr, bg=t["accent"], width=28, height=28,
                      highlightbackground=t["chat_header_fg"], highlightthickness=2)
        av.pack_propagate(False)
        av.pack(side="left")
        tk.Label(av, text="MA", bg=t["accent"], fg=t["chat_header_fg"],
                 font=("Segoe UI", 9, "bold")).pack(expand=True)
        meta = tk.Frame(hdr, bg=t["chat_header_bg"])
        meta.pack(side="left", padx=10, fill="x", expand=True)
        tk.Label(meta, text="Marina Alves", bg=t["chat_header_bg"],
                 fg=t["chat_header_fg"], font=("Segoe UI", 10, "bold"),
                 anchor="w").pack(fill="x")
        tk.Label(meta, text="digitando…", bg=t["chat_header_bg"],
                 fg=t["chat_header_sub"], font=("Segoe UI", 8),
                 anchor="w").pack(fill="x")

        # Messages
        msgs = tk.Frame(box, bg=t["bg_chat"], padx=10, pady=10)
        msgs.pack(fill="both", expand=True)

        peer = tk.Frame(msgs, bg=t["msg_peer_bg"], padx=10, pady=5)
        peer.pack(anchor="w", pady=2)
        tk.Label(peer, text="Bom dia!", bg=t["msg_peer_bg"],
                 fg=t["fg_msg"], font=("Segoe UI", 9)).pack(anchor="w")

        me = tk.Frame(msgs, bg=t["msg_my_bg"], padx=10, pady=5)
        me.pack(anchor="e", pady=2)
        tk.Label(me, text="Oi, como vai?", bg=t["msg_my_bg"],
                 fg=t["fg_msg"], font=("Segoe UI", 9)).pack(anchor="e")

        # Input row
        inp = tk.Frame(box, bg=t["bg_white"], padx=8, pady=8,
                       highlightbackground=t["border"], highlightthickness=0)
        inp.pack(fill="x")
        tk.Frame(box, height=1, bg=t["border"]).pack(fill="x", before=inp)

        fake = tk.Frame(inp, bg=t["bg_input"],
                        highlightbackground=t["input_border"], highlightthickness=1)
        fake.pack(side="left", fill="x", expand=True, ipady=4, ipadx=6)
        tk.Label(fake, text="Digite uma mensagem…", bg=t["bg_input"],
                 fg=t["fg_gray"], font=("Segoe UI", 9)).pack(side="left")

        tk.Button(inp, text="Enviar", bg=t["btn_send_bg"], fg=t["btn_send_fg"],
                  relief="flat", font=("Segoe UI", 9, "bold"), padx=14,
                  activebackground=t["btn_active"]).pack(side="right", padx=(6, 0))

        # Status bar
        sb = tk.Frame(box, bg=t["statusbar_bg"], padx=10, pady=3)
        sb.pack(fill="x")
        tk.Frame(box, height=1, bg=t["border"]).pack(fill="x", before=sb)
        dot = tk.Frame(sb, bg=t["online"], width=7, height=7)
        dot.pack_propagate(False)
        dot.pack(side="left", pady=3)
        tk.Label(sb, text=f"  {self.current_name.get() or 'Sem nome'}",
                 bg=t["statusbar_bg"], fg=t["statusbar_fg"],
                 font=("Segoe UI", 8)).pack(side="left")


# ----------------------------------------------------------------------------- 
# Standalone test — `python tools/theme_builder.py`
# ----------------------------------------------------------------------------- 

if __name__ == "__main__":
    root = tk.Tk()
    root.withdraw()
    ThemeBuilderWindow(root)
    root.mainloop()
