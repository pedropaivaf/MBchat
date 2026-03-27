"""
MB Chat - Mensageiro de rede local
Interface idêntica ao LAN Messenger original
"""
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import threading
import time
import os
import sys
import platform
import socket
import shutil
import hashlib
from datetime import datetime
from pathlib import Path

from messenger import Messenger

# Pillow for JPG/PNG avatar support
try:
    from PIL import Image, ImageTk
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

# System tray support
try:
    import pystray
    HAS_TRAY = True
except ImportError:
    HAS_TRAY = False

# Windows toast notifications (clickable)
try:
    from winotify import Notification as WinNotification, audio as wn_audio
    HAS_WINOTIFY = True
except ImportError:
    HAS_WINOTIFY = False

APP_NAME = 'MB Chat'

# --- Idiomas ---
LANGS = {
    'Português': {
        'menu_messenger': 'Messenger',
        'menu_tools': 'Ferramentas',
        'menu_help': 'Ajuda',
        'menu_change_name': 'Alterar nome...',
        'menu_preferences': 'Preferências...',
        'menu_quit': 'Sair',
        'menu_history': 'Histórico de mensagens',
        'menu_transfers': 'Transferência de arquivos',
        'menu_broadcast': 'Mensagem para todos',
        'menu_about': 'Sobre o',
        'btn_send': 'Enviar',
        'btn_file': 'Arquivo',
        'btn_refresh': 'Atualizar',
        'status_available': 'Disponível',
        'status_away': 'Ausente',
        'status_busy': 'Ocupado',
        'status_offline': 'Offline',
        'note_placeholder': 'Digite uma nota',
        'group_general': '  Geral',
        'user_default': ' Usuário',
        'ctx_send_msg': 'Enviar mensagem',
        'ctx_send_file': 'Enviar arquivo',
        'ctx_info': 'Ver info',
        'typing': 'está digitando...',
        'broadcast_title': 'Mensagem para Todos',
        'broadcast_label': 'Mensagem:',
        'broadcast_send': 'Enviar para Todos',
        'file_select_contact': 'Selecione um contato primeiro.',
        'file_complete': 'Arquivo salvo em:',
        'file_error': 'Erro de Transferência',
        'clear_history': 'Limpar Histórico',
        'clear_history_confirm': 'Limpar histórico de mensagens com',
        'history_cleared': 'Histórico limpo.',
        'history_btn': 'Histórico',
        'send_btn': 'Enviar',
        'send_file_btn': 'Enviar Arquivo',
        'font_btn': 'Fonte',
        'prefs_language': 'Idioma',
    },
    'English': {
        'menu_messenger': 'Messenger',
        'menu_tools': 'Tools',
        'menu_help': 'Help',
        'menu_change_name': 'Change name...',
        'menu_preferences': 'Preferences...',
        'menu_quit': 'Quit',
        'menu_history': 'Message history',
        'menu_transfers': 'File transfers',
        'menu_broadcast': 'Message to all',
        'menu_about': 'About',
        'btn_send': 'Send',
        'btn_file': 'File',
        'btn_refresh': 'Refresh',
        'status_available': 'Available',
        'status_away': 'Away',
        'status_busy': 'Busy',
        'status_offline': 'Offline',
        'note_placeholder': 'Type a note',
        'group_general': '  General',
        'user_default': ' User',
        'ctx_send_msg': 'Send message',
        'ctx_send_file': 'Send file',
        'ctx_info': 'View info',
        'typing': 'is typing...',
        'broadcast_title': 'Message to All',
        'broadcast_label': 'Message:',
        'broadcast_send': 'Send to All',
        'file_select_contact': 'Select a contact first.',
        'file_complete': 'File saved to:',
        'file_error': 'Transfer Error',
        'clear_history': 'Clear History',
        'clear_history_confirm': 'Clear message history with',
        'history_cleared': 'History cleared.',
        'history_btn': 'History',
        'send_btn': 'Send',
        'send_file_btn': 'Send File',
        'font_btn': 'Font',
        'prefs_language': 'Language',
    },
}

def _t(key):
    """Get translated string for current language."""
    return _CURRENT_LANG.get(key, key)

_CURRENT_LANG = LANGS['Português']

# --- Fonts ---
FONT = ('Segoe UI', 9)
FONT_BOLD = ('Segoe UI', 9, 'bold')
FONT_SMALL = ('Segoe UI', 8)
FONT_CHAT = ('Segoe UI', 9)
FONT_SECTION = ('Segoe UI', 9, 'bold')

# --- Themes ---
THEMES = {
    'Clássico': {
        'bg_window': '#f0f0f0',
        'bg_white': '#ffffff',
        'bg_header': '#e8e8e8',
        'bg_group': '#3366aa',
        'bg_select': '#cce8ff',
        'bg_input': '#ffffff',
        'bg_chat': '#ffffff',
        'fg_black': '#000000',
        'fg_gray': '#666666',
        'fg_white': '#ffffff',
        'fg_blue': '#0066cc',
        'fg_green': '#008800',
        'fg_red': '#cc0000',
        'fg_orange': '#cc8800',
        'fg_msg': '#000000',
        'fg_time': '#666666',
        'fg_my_name': '#0066cc',
        'fg_peer_name': '#cc0000',
        'btn_bg': '#e8e8e8',
        'btn_fg': '#000000',
        'btn_active': '#d0d0d0',
        'border': '#bbbbbb',
        'statusbar_bg': '#e8e8e8',
        'statusbar_fg': '#666666',
    },
    'Night Mode': {
        'bg_window': '#1e1e1e',
        'bg_white': '#2d2d2d',
        'bg_header': '#333333',
        'bg_group': '#3a3a5c',
        'bg_select': '#3a5070',
        'bg_input': '#383838',
        'bg_chat': '#252525',
        'fg_black': '#e0e0e0',
        'fg_gray': '#888888',
        'fg_white': '#f0f0f0',
        'fg_blue': '#6ca8e0',
        'fg_green': '#5cb85c',
        'fg_red': '#e05555',
        'fg_orange': '#e0a030',
        'fg_msg': '#d0d0d0',
        'fg_time': '#707070',
        'fg_my_name': '#6ca8e0',
        'fg_peer_name': '#e08060',
        'btn_bg': '#383838',
        'btn_fg': '#d0d0d0',
        'btn_active': '#505050',
        'border': '#444444',
        'statusbar_bg': '#282828',
        'statusbar_fg': '#808080',
    },
    'MB Contabilidade': {
        'bg_window': '#0f2a5c',
        'bg_white': '#0f2a5c',
        'bg_header': '#152d5e',
        'bg_group': '#cc2222',
        'bg_select': '#2a4a8a',
        'bg_input': '#1a3a7a',
        'bg_chat': '#0d2450',
        'fg_black': '#ffffff',
        'fg_gray': '#8aa0cc',
        'fg_white': '#ffffff',
        'fg_blue': '#80bbff',
        'fg_green': '#66cc66',
        'fg_red': '#ff6666',
        'fg_orange': '#ffaa44',
        'fg_msg': '#e0e8f0',
        'fg_time': '#6688bb',
        'fg_my_name': '#ffffff',
        'fg_peer_name': '#ff8888',
        'btn_bg': '#152d5e',
        'btn_fg': '#ffffff',
        'btn_active': '#2a4a8a',
        'border': '#0f2a5c',
        'statusbar_bg': '#0f2a5c',
        'statusbar_fg': '#8aa0cc',
    },
}

# --- Default colors (used at startup, overridden by theme) ---
BG_WINDOW = '#f0f0f0'
BG_WHITE = '#ffffff'
BG_HEADER = '#e8e8e8'
BG_GROUP = '#3366aa'
BG_SELECT = '#cce8ff'
FG_BLACK = '#000000'
FG_GRAY = '#666666'
FG_WHITE = '#ffffff'
FG_BLUE = '#0066cc'
FG_GREEN = '#008800'
FG_RED = '#cc0000'
FG_ORANGE = '#cc8800'

# --- Avatar colors for defaults ---
AVATAR_COLORS = [
    ('#4488cc', 'U'), ('#44aa44', 'U'), ('#cc4444', 'U'),
    ('#aa44aa', 'U'), ('#cc8844', 'U'), ('#44aaaa', 'U'),
    ('#6666cc', 'U'), ('#88aa44', 'U'), ('#cc44aa', 'U'),
    ('#4488aa', 'U'), ('#aa8844', 'U'), ('#44aa88', 'U'),
]


def _get_icon_path():
    """Retorna o caminho do icone, compativel com PyInstaller."""
    if getattr(sys, 'frozen', False):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    ico = os.path.join(base, 'mbchat.ico')
    if os.path.exists(ico):
        return ico
    return None


def _center_window(win, w, h):
    """Centraliza uma janela na tela."""
    win.update_idletasks()
    sx = win.winfo_screenwidth()
    sy = win.winfo_screenheight()
    x = (sx - w) // 2
    y = (sy - h) // 2
    win.geometry(f'{w}x{h}+{x}+{y}')


def _get_data_dir():
    if os.name == 'nt':
        base = os.environ.get('APPDATA', os.path.expanduser('~'))
    else:
        base = os.path.expanduser('~')
    d = os.path.join(base, '.mbchat')
    os.makedirs(d, exist_ok=True)
    return d


def _get_avatars_dir():
    d = os.path.join(_get_data_dir(), 'avatars')
    os.makedirs(d, exist_ok=True)
    return d


class SoundPlayer:
    @staticmethod
    def play_notification():
        try:
            if platform.system() == 'Windows':
                import winsound
                winsound.MessageBeep(winsound.MB_ICONINFORMATION)
            elif platform.system() == 'Darwin':
                os.system('afplay /System/Library/Sounds/Ping.aiff &')
            else:
                os.system('paplay /usr/share/sounds/freedesktop/stereo/'
                          'message-new-instant.oga 2>/dev/null &')
        except Exception:
            pass

    @staticmethod
    def play_connect():
        try:
            if platform.system() == 'Windows':
                import winsound
                winsound.MessageBeep(winsound.MB_OK)
        except Exception:
            pass


# =============================================================
#  PREFERENCES WINDOW — Idêntica ao original
# =============================================================
class PreferencesWindow(tk.Toplevel):
    """Tela de Preferências completa com abas laterais."""

    def __init__(self, app, initial_tab=0):
        super().__init__(app.root)
        self.app = app
        self.messenger = app.messenger
        self.title('Preferências')
        self.resizable(False, False)
        self.transient(app.root)
        self.grab_set()
        self.configure(bg=BG_WINDOW)

        _center_window(self, 580, 450)

        # --- Main layout: top area (left+right) and bottom buttons ---
        top = tk.Frame(self, bg=BG_WINDOW)
        top.pack(fill='both', expand=True, padx=6, pady=(6, 0))

        # Left sidebar
        left = tk.Frame(top, bg=BG_WHITE, width=160, bd=1, relief='sunken')
        left.pack(side='left', fill='y')
        left.pack_propagate(False)

        # Right content area
        self.right = tk.Frame(top, bg=BG_WINDOW)
        self.right.pack(side='left', fill='both', expand=True, padx=(6, 0))

        # Category items
        self.categories = [
            ('Geral', self._build_geral),
            ('Conta', self._build_conta),
            ('Mensagens', self._build_mensagens),
            ('Histórico', self._build_historico),
            ('Alertas', self._build_alertas),
            ('Rede', self._build_rede),
            ('Transferência de arq.', self._build_transferencia),
            ('Aparência', self._build_aparencia),
            ('Teclas de atalho', self._build_atalhos),
        ]

        self.cat_buttons = []
        self.current_frame = None

        for i, (name, builder) in enumerate(self.categories):
            btn = tk.Button(left, text=f'  {name}', font=FONT, anchor='w',
                            bg=BG_WHITE, fg=FG_BLACK, relief='flat', bd=0,
                            padx=8, pady=6, cursor='hand2',
                            activebackground=BG_SELECT,
                            command=lambda idx=i: self._select_category(idx))
            btn.pack(fill='x')
            self.cat_buttons.append(btn)

        # --- Bottom buttons (outside top, guaranteed visible) ---
        bottom = tk.Frame(self, bg=BG_WINDOW)
        bottom.pack(fill='x', padx=10, pady=8)

        tk.Button(bottom, text='Cancelar', font=FONT, width=10,
                  command=self.destroy).pack(side='right', padx=4)
        tk.Button(bottom, text='OK', font=FONT, width=10,
                  command=self._save_all).pack(side='right', padx=4)
        tk.Button(bottom, text='Redefinir Preferências', font=FONT_SMALL,
                  command=self._reset_defaults).pack(side='left', padx=4)

        # Settings vars
        self._init_vars()

        # Select initial tab
        self._select_category(initial_tab)

    def _init_vars(self):
        db = self.messenger.db
        self.var_autostart = tk.BooleanVar(
            value=db.get_setting('autostart', '0') == '1')
        self.var_show_main = tk.BooleanVar(
            value=db.get_setting('show_main_on_start', '1') == '1')
        self.var_tray_icon = tk.BooleanVar(
            value=db.get_setting('tray_icon', '1') == '1')
        self.var_minimize_tray = tk.BooleanVar(
            value=db.get_setting('minimize_to_tray', '0') == '1')
        self.var_single_click_tray = tk.BooleanVar(
            value=db.get_setting('single_click_tray', '0') == '1')
        self.var_balloon = tk.BooleanVar(
            value=db.get_setting('balloon_notify', '1') == '1')
        self.var_minimize_close = tk.BooleanVar(
            value=db.get_setting('minimize_on_close', '0') == '1')
        self.var_language = tk.StringVar(
            value=db.get_setting('language', 'Português'))
        self.var_sound = tk.BooleanVar(
            value=db.get_setting('sound', '1') == '1')
        self.var_sound_msg = tk.BooleanVar(
            value=db.get_setting('sound_message', '1') == '1')
        self.var_sound_online = tk.BooleanVar(
            value=db.get_setting('sound_online', '1') == '1')
        self.var_flash_taskbar = tk.BooleanVar(
            value=db.get_setting('flash_taskbar', '1') == '1')
        self.var_save_history = tk.BooleanVar(
            value=db.get_setting('save_history', '1') == '1')
        self.var_history_path = tk.StringVar(
            value=db.get_setting('history_path',
                                 os.path.join(_get_data_dir(), 'history')))
        self.var_download_dir = tk.StringVar(
            value=db.get_setting('download_dir',
                                 os.path.join(os.path.expanduser('~'),
                                              'MB_Chat_Files')))
        self.var_auto_accept = tk.BooleanVar(
            value=db.get_setting('auto_accept_files', '0') == '1')
        self.var_udp_port = tk.StringVar(
            value=db.get_setting('udp_port', '50000'))
        self.var_tcp_port = tk.StringVar(
            value=db.get_setting('tcp_port', '50001'))
        self.var_multicast = tk.StringVar(
            value=db.get_setting('multicast', '239.255.100.100'))
        self.var_font_size = tk.StringVar(
            value=db.get_setting('font_size', '9'))
        saved_theme = db.get_setting('theme', 'MB Contabilidade')
        if saved_theme not in THEMES:
            saved_theme = 'MB Contabilidade'
        self.var_theme = tk.StringVar(value=saved_theme)
        self.var_enter_send = tk.BooleanVar(
            value=db.get_setting('enter_to_send', '1') == '1')
        self.var_show_timestamp = tk.BooleanVar(
            value=db.get_setting('show_timestamp', '1') == '1')
        self.var_avatar_index = tk.IntVar(
            value=int(db.get_setting('avatar_index', '0')))
        self.var_custom_avatar = tk.StringVar(
            value=db.get_setting('custom_avatar', ''))
        self.var_display_name = tk.StringVar(
            value=self.messenger.display_name)

    def _select_category(self, idx):
        # Highlight selected
        for i, btn in enumerate(self.cat_buttons):
            if i == idx:
                btn.configure(bg=BG_SELECT, relief='flat')
            else:
                btn.configure(bg=BG_WHITE, relief='flat')

        # Clear right panel
        if self.current_frame:
            self.current_frame.destroy()

        self.current_frame = tk.Frame(self.right, bg=BG_WINDOW)
        self.current_frame.pack(fill='both', expand=True)

        # Build content
        self.categories[idx][1](self.current_frame)

    # ----- GERAL -----
    def _build_geral(self, parent):
        tk.Label(parent, text='Geral', font=FONT_SECTION,
                 bg=BG_WINDOW).pack(anchor='w', padx=10, pady=(5, 10))

        # Sistema
        lf = tk.LabelFrame(parent, text='Sistema', font=FONT,
                            bg=BG_WINDOW, padx=10, pady=5)
        lf.pack(fill='x', padx=10, pady=(0, 8))

        tk.Checkbutton(lf, text=f'Abrir o {APP_NAME} ao iniciar o sistema',
                       variable=self.var_autostart, font=FONT,
                       bg=BG_WINDOW).pack(anchor='w')
        tk.Checkbutton(lf, text=f'Mostrar a tela principal quando o {APP_NAME} iniciar',
                       variable=self.var_show_main, font=FONT,
                       bg=BG_WINDOW).pack(anchor='w')

        # Bandeja
        lf2 = tk.LabelFrame(parent, text='Bandeja do Sistema', font=FONT,
                             bg=BG_WINDOW, padx=10, pady=5)
        lf2.pack(fill='x', padx=10, pady=(0, 8))

        tk.Checkbutton(lf2, text='Mostrar ícone na bandeja do sistema',
                       variable=self.var_tray_icon, font=FONT,
                       bg=BG_WINDOW).pack(anchor='w')
        tk.Checkbutton(lf2, text='Minimizar janela principal para a bandeja do sistema',
                       variable=self.var_minimize_tray, font=FONT,
                       bg=BG_WINDOW).pack(anchor='w')
        tk.Checkbutton(lf2, text='Um clique no ícone da bandeja para abrir',
                       variable=self.var_single_click_tray, font=FONT,
                       bg=BG_WINDOW).pack(anchor='w')
        tk.Checkbutton(lf2, text='Mostrar balões de notificações na bandeja',
                       variable=self.var_balloon, font=FONT,
                       bg=BG_WINDOW).pack(anchor='w')
        tk.Checkbutton(lf2, text='Minimizar janela principal usando o ícone da bandeja',
                       variable=self.var_minimize_close, font=FONT,
                       bg=BG_WINDOW).pack(anchor='w')

        # Idioma
        lf3 = tk.LabelFrame(parent, text='Idioma', font=FONT,
                             bg=BG_WINDOW, padx=10, pady=5)
        lf3.pack(fill='x', padx=10, pady=(0, 8))

        row = tk.Frame(lf3, bg=BG_WINDOW)
        row.pack(fill='x')
        tk.Label(row, text='Selecionar idioma:', font=FONT,
                 bg=BG_WINDOW).pack(side='left')
        ttk.Combobox(row, textvariable=self.var_language,
                     values=list(LANGS.keys()),
                     state='readonly', font=FONT_SMALL,
                     width=15).pack(side='right')

    # ----- CONTA -----
    def _build_conta(self, parent):
        tk.Label(parent, text='Conta', font=FONT_SECTION,
                 bg=BG_WINDOW).pack(anchor='w', padx=10, pady=(5, 10))

        # Nome
        lf = tk.LabelFrame(parent, text='Perfil', font=FONT,
                            bg=BG_WINDOW, padx=10, pady=8)
        lf.pack(fill='x', padx=10, pady=(0, 8))

        row = tk.Frame(lf, bg=BG_WINDOW)
        row.pack(fill='x', pady=4)
        tk.Label(row, text='Nome de exibição:', font=FONT,
                 bg=BG_WINDOW).pack(side='left')
        tk.Entry(row, font=FONT, width=20,
                 textvariable=self.var_display_name).pack(side='right')

        # Foto de perfil
        lf2 = tk.LabelFrame(parent, text='Foto de Perfil', font=FONT,
                             bg=BG_WINDOW, padx=10, pady=8)
        lf2.pack(fill='x', padx=10, pady=(0, 8))

        tk.Label(lf2, text='Escolha um avatar ou envie uma foto:',
                 font=FONT_SMALL, bg=BG_WINDOW).pack(anchor='w', pady=(0, 6))

        # Avatar grid (pre-built colored avatars)
        grid = tk.Frame(lf2, bg=BG_WINDOW)
        grid.pack(anchor='w', pady=(0, 8))

        self._avatar_canvases = []
        for i, (color, letter) in enumerate(AVATAR_COLORS):
            c = tk.Canvas(grid, width=36, height=36, bg=BG_WINDOW,
                          highlightthickness=0, cursor='hand2')
            r = i // 6
            col = i % 6
            c.grid(row=r, column=col, padx=2, pady=2)

            # Draw avatar
            c.create_rectangle(2, 2, 34, 34, fill=color, outline='#999999')
            initial = self.messenger.display_name[0].upper() if self.messenger.display_name else 'U'
            c.create_text(18, 18, text=initial, fill='white',
                          font=('Segoe UI', 11, 'bold'))

            # Selection border
            if i == self.var_avatar_index.get() and not self.var_custom_avatar.get():
                c.create_rectangle(1, 1, 35, 35, outline='#0066cc', width=2)

            c.bind('<Button-1>', lambda e, idx=i: self._select_avatar(idx))
            self._avatar_canvases.append(c)

        # Custom photo preview + buttons
        photo_row = tk.Frame(lf2, bg=BG_WINDOW)
        photo_row.pack(fill='x', pady=4)

        self._custom_preview = tk.Canvas(photo_row, width=36, height=36,
                                         bg=BG_WINDOW, highlightthickness=0)
        self._custom_preview.pack(side='left', padx=(0, 8))

        custom = self.var_custom_avatar.get()
        self._show_preview(custom)

        btn_frame = tk.Frame(photo_row, bg=BG_WINDOW)
        btn_frame.pack(side='left')

        tk.Button(btn_frame, text='Enviar foto...', font=FONT_SMALL,
                  command=self._upload_avatar).pack(anchor='w')

        self._lbl_custom_path = tk.Label(
            btn_frame,
            text=os.path.basename(custom) if custom else 'Nenhuma foto',
            font=FONT_SMALL, bg=BG_WINDOW, fg=FG_GRAY)
        self._lbl_custom_path.pack(anchor='w')

        if custom:
            tk.Button(btn_frame, text='Remover foto', font=FONT_SMALL,
                      fg=FG_RED, command=self._remove_custom_avatar
                      ).pack(anchor='w', pady=2)

    def _show_preview(self, path):
        """Show image preview in the custom_preview canvas."""
        self._custom_preview.delete('all')
        if path and os.path.exists(path):
            try:
                if HAS_PIL:
                    img = Image.open(path)
                    img = img.resize((32, 32), Image.LANCZOS)
                    self._preview_img = ImageTk.PhotoImage(img)
                    self._custom_preview.create_image(18, 18,
                                                      image=self._preview_img)
                    return
            except Exception:
                pass
            # Fallback: green check
            self._custom_preview.create_rectangle(2, 2, 34, 34,
                                                  fill='#228822', outline='#999')
            self._custom_preview.create_text(18, 18, text='✓', fill='white',
                                             font=('Segoe UI', 14, 'bold'))
        else:
            self._custom_preview.create_rectangle(2, 2, 34, 34,
                                                  fill='#dddddd', outline='#999')
            self._custom_preview.create_text(18, 18, text='?', fill='#999',
                                             font=('Segoe UI', 12))

    def _select_avatar(self, idx):
        self.var_avatar_index.set(idx)
        self.var_custom_avatar.set('')
        for i, c in enumerate(self._avatar_canvases):
            c.delete('selection')
            if i == idx:
                c.create_rectangle(1, 1, 35, 35, outline='#0066cc',
                                   width=2, tags='selection')

    def _upload_avatar(self):
        path = filedialog.askopenfilename(
            parent=self,
            title='Selecionar foto de perfil',
            filetypes=[('Imagens', '*.png *.jpg *.jpeg *.gif *.bmp'),
                       ('Todos', '*.*')])
        if not path:
            return
        ext = os.path.splitext(path)[1]
        dest = os.path.join(_get_avatars_dir(), f'custom_avatar{ext}')
        shutil.copy2(path, dest)
        self.var_custom_avatar.set(dest)
        self._lbl_custom_path.config(text=os.path.basename(path))
        for c in self._avatar_canvases:
            c.delete('selection')
        self._show_preview(dest)

    def _remove_custom_avatar(self):
        self.var_custom_avatar.set('')
        self._lbl_custom_path.config(text='Nenhuma foto')
        self._show_preview('')

    # ----- MENSAGENS -----
    def _build_mensagens(self, parent):
        tk.Label(parent, text='Mensagens', font=FONT_SECTION,
                 bg=BG_WINDOW).pack(anchor='w', padx=10, pady=(5, 10))

        lf = tk.LabelFrame(parent, text='Comportamento', font=FONT,
                            bg=BG_WINDOW, padx=10, pady=5)
        lf.pack(fill='x', padx=10, pady=(0, 8))

        tk.Checkbutton(lf, text='Enter para enviar mensagem',
                       variable=self.var_enter_send, font=FONT,
                       bg=BG_WINDOW).pack(anchor='w')
        tk.Checkbutton(lf, text='Mostrar horário nas mensagens',
                       variable=self.var_show_timestamp, font=FONT,
                       bg=BG_WINDOW).pack(anchor='w')

    # ----- HISTÓRICO -----
    def _build_historico(self, parent):
        tk.Label(parent, text='Histórico', font=FONT_SECTION,
                 bg=BG_WINDOW).pack(anchor='w', padx=10, pady=(5, 10))

        lf = tk.LabelFrame(parent, text='Salvar Histórico', font=FONT,
                            bg=BG_WINDOW, padx=10, pady=5)
        lf.pack(fill='x', padx=10, pady=(0, 8))

        tk.Checkbutton(lf, text='Salvar histórico de mensagens',
                       variable=self.var_save_history, font=FONT,
                       bg=BG_WINDOW).pack(anchor='w')

        row = tk.Frame(lf, bg=BG_WINDOW)
        row.pack(fill='x', pady=4)
        tk.Label(row, text='Pasta:', font=FONT, bg=BG_WINDOW).pack(
            side='left')
        tk.Entry(row, textvariable=self.var_history_path, font=FONT_SMALL,
                 width=25).pack(side='left', padx=4, fill='x', expand=True)
        tk.Button(row, text='...', width=3,
                  command=lambda: self.var_history_path.set(
                      filedialog.askdirectory(parent=self) or
                      self.var_history_path.get())
                  ).pack(side='right')

        tk.Button(lf, text='Limpar todo o histórico', font=FONT_SMALL,
                  fg=FG_RED,
                  command=self._clear_history).pack(anchor='w', pady=4)

    def _clear_history(self):
        if messagebox.askyesno('Limpar Histórico',
                               'Tem certeza? Todas as mensagens serão apagadas.',
                               parent=self):
            self.messenger.db.conn.execute("DELETE FROM messages")
            self.messenger.db.conn.commit()
            messagebox.showinfo('Histórico', 'Histórico limpo.', parent=self)

    # ----- ALERTAS -----
    def _build_alertas(self, parent):
        tk.Label(parent, text='Alertas', font=FONT_SECTION,
                 bg=BG_WINDOW).pack(anchor='w', padx=10, pady=(5, 10))

        lf = tk.LabelFrame(parent, text='Sons', font=FONT,
                            bg=BG_WINDOW, padx=10, pady=5)
        lf.pack(fill='x', padx=10, pady=(0, 8))

        tk.Checkbutton(lf, text='Ativar sons de notificação',
                       variable=self.var_sound, font=FONT,
                       bg=BG_WINDOW).pack(anchor='w')
        tk.Checkbutton(lf, text='Som ao receber mensagem',
                       variable=self.var_sound_msg, font=FONT,
                       bg=BG_WINDOW).pack(anchor='w')
        tk.Checkbutton(lf, text='Som quando alguém ficar online',
                       variable=self.var_sound_online, font=FONT,
                       bg=BG_WINDOW).pack(anchor='w')

        lf2 = tk.LabelFrame(parent, text='Visual', font=FONT,
                             bg=BG_WINDOW, padx=10, pady=5)
        lf2.pack(fill='x', padx=10, pady=(0, 8))

        tk.Checkbutton(lf2, text='Piscar barra de tarefas ao receber mensagem',
                       variable=self.var_flash_taskbar, font=FONT,
                       bg=BG_WINDOW).pack(anchor='w')

    # ----- REDE -----
    def _build_rede(self, parent):
        tk.Label(parent, text='Rede', font=FONT_SECTION,
                 bg=BG_WINDOW).pack(anchor='w', padx=10, pady=(5, 10))

        lf = tk.LabelFrame(parent, text='Portas de Comunicação', font=FONT,
                            bg=BG_WINDOW, padx=10, pady=5)
        lf.pack(fill='x', padx=10, pady=(0, 8))

        r1 = tk.Frame(lf, bg=BG_WINDOW)
        r1.pack(fill='x', pady=2)
        tk.Label(r1, text='Porta UDP:', font=FONT, bg=BG_WINDOW,
                 width=14, anchor='w').pack(side='left')
        tk.Entry(r1, textvariable=self.var_udp_port, font=FONT,
                 width=8).pack(side='left')

        r2 = tk.Frame(lf, bg=BG_WINDOW)
        r2.pack(fill='x', pady=2)
        tk.Label(r2, text='Porta TCP:', font=FONT, bg=BG_WINDOW,
                 width=14, anchor='w').pack(side='left')
        tk.Entry(r2, textvariable=self.var_tcp_port, font=FONT,
                 width=8).pack(side='left')

        r3 = tk.Frame(lf, bg=BG_WINDOW)
        r3.pack(fill='x', pady=2)
        tk.Label(r3, text='Multicast:', font=FONT, bg=BG_WINDOW,
                 width=14, anchor='w').pack(side='left')
        tk.Entry(r3, textvariable=self.var_multicast, font=FONT,
                 width=16).pack(side='left')

        tk.Label(lf, text='(Reinicie o app para aplicar mudanças de rede)',
                 font=FONT_SMALL, fg=FG_GRAY, bg=BG_WINDOW).pack(
                     anchor='w', pady=4)

    # ----- TRANSFERÊNCIA -----
    def _build_transferencia(self, parent):
        tk.Label(parent, text='Transferência de Arquivos', font=FONT_SECTION,
                 bg=BG_WINDOW).pack(anchor='w', padx=10, pady=(5, 10))

        lf = tk.LabelFrame(parent, text='Recebimento', font=FONT,
                            bg=BG_WINDOW, padx=10, pady=5)
        lf.pack(fill='x', padx=10, pady=(0, 8))

        row = tk.Frame(lf, bg=BG_WINDOW)
        row.pack(fill='x', pady=4)
        tk.Label(row, text='Salvar arquivos em:', font=FONT,
                 bg=BG_WINDOW).pack(anchor='w')

        dir_row = tk.Frame(lf, bg=BG_WINDOW)
        dir_row.pack(fill='x', pady=2)
        tk.Entry(dir_row, textvariable=self.var_download_dir, font=FONT_SMALL
                 ).pack(side='left', fill='x', expand=True)
        tk.Button(dir_row, text='Procurar...', font=FONT_SMALL,
                  command=lambda: self.var_download_dir.set(
                      filedialog.askdirectory(parent=self) or
                      self.var_download_dir.get())
                  ).pack(side='right', padx=4)

        tk.Checkbutton(lf, text='Aceitar arquivos automaticamente',
                       variable=self.var_auto_accept, font=FONT,
                       bg=BG_WINDOW).pack(anchor='w', pady=4)

    # ----- APARÊNCIA -----
    def _build_aparencia(self, parent):
        tk.Label(parent, text='Aparência', font=FONT_SECTION,
                 bg=BG_WINDOW).pack(anchor='w', padx=10, pady=(5, 10))

        lf = tk.LabelFrame(parent, text='Tema', font=FONT,
                            bg=BG_WINDOW, padx=10, pady=5)
        lf.pack(fill='x', padx=10, pady=(0, 8))

        row = tk.Frame(lf, bg=BG_WINDOW)
        row.pack(fill='x', pady=2)
        tk.Label(row, text='Tema:', font=FONT, bg=BG_WINDOW).pack(side='left')
        ttk.Combobox(row, textvariable=self.var_theme,
                     values=list(THEMES.keys()),
                     state='readonly', font=FONT_SMALL, width=16
                     ).pack(side='right')

        lf2 = tk.LabelFrame(parent, text='Fonte', font=FONT,
                             bg=BG_WINDOW, padx=10, pady=5)
        lf2.pack(fill='x', padx=10, pady=(0, 8))

        row2 = tk.Frame(lf2, bg=BG_WINDOW)
        row2.pack(fill='x', pady=2)
        tk.Label(row2, text='Tamanho da fonte:', font=FONT,
                 bg=BG_WINDOW).pack(side='left')
        ttk.Combobox(row2, textvariable=self.var_font_size,
                     values=['8', '9', '10', '11', '12', '14'],
                     state='readonly', font=FONT_SMALL, width=5
                     ).pack(side='right')

    # ----- ATALHOS -----
    def _build_atalhos(self, parent):
        tk.Label(parent, text='Teclas de Atalho', font=FONT_SECTION,
                 bg=BG_WINDOW).pack(anchor='w', padx=10, pady=(5, 10))

        lf = tk.LabelFrame(parent, text='Atalhos do Teclado', font=FONT,
                            bg=BG_WINDOW, padx=10, pady=5)
        lf.pack(fill='x', padx=10, pady=(0, 8))

        atalhos = [
            ('Enviar mensagem:', 'Enter'),
            ('Nova linha:', 'Shift + Enter'),
            ('Enviar arquivo:', 'Ctrl + F'),
            ('Histórico:', 'Ctrl + H'),
            ('Fechar janela:', 'Alt + F4'),
        ]
        for desc, key in atalhos:
            r = tk.Frame(lf, bg=BG_WINDOW)
            r.pack(fill='x', pady=1)
            tk.Label(r, text=desc, font=FONT, bg=BG_WINDOW,
                     width=20, anchor='w').pack(side='left')
            tk.Label(r, text=key, font=FONT_BOLD, bg=BG_WINDOW,
                     fg=FG_BLUE).pack(side='left')

    # ----- SAVE ALL -----
    def _save_all(self):
        db = self.messenger.db

        # Save all settings
        db.set_setting('autostart', '1' if self.var_autostart.get() else '0')
        db.set_setting('show_main_on_start',
                       '1' if self.var_show_main.get() else '0')
        db.set_setting('tray_icon',
                       '1' if self.var_tray_icon.get() else '0')
        db.set_setting('minimize_to_tray',
                       '1' if self.var_minimize_tray.get() else '0')
        db.set_setting('single_click_tray',
                       '1' if self.var_single_click_tray.get() else '0')
        db.set_setting('balloon_notify',
                       '1' if self.var_balloon.get() else '0')
        db.set_setting('minimize_on_close',
                       '1' if self.var_minimize_close.get() else '0')
        db.set_setting('language', self.var_language.get())
        db.set_setting('sound', '1' if self.var_sound.get() else '0')
        db.set_setting('sound_message',
                       '1' if self.var_sound_msg.get() else '0')
        db.set_setting('sound_online',
                       '1' if self.var_sound_online.get() else '0')
        db.set_setting('flash_taskbar',
                       '1' if self.var_flash_taskbar.get() else '0')
        db.set_setting('save_history',
                       '1' if self.var_save_history.get() else '0')
        db.set_setting('history_path', self.var_history_path.get())
        db.set_setting('download_dir', self.var_download_dir.get())
        db.set_setting('auto_accept_files',
                       '1' if self.var_auto_accept.get() else '0')
        db.set_setting('udp_port', self.var_udp_port.get())
        db.set_setting('tcp_port', self.var_tcp_port.get())
        db.set_setting('multicast', self.var_multicast.get())
        db.set_setting('font_size', self.var_font_size.get())
        db.set_setting('theme', self.var_theme.get())
        db.set_setting('enter_to_send',
                       '1' if self.var_enter_send.get() else '0')
        db.set_setting('show_timestamp',
                       '1' if self.var_show_timestamp.get() else '0')
        db.set_setting('avatar_index', str(self.var_avatar_index.get()))
        db.set_setting('custom_avatar', self.var_custom_avatar.get())

        # Apply name change (uses StringVar, safe even if Conta tab not visible)
        new_name = self.var_display_name.get().strip()
        if new_name and new_name != self.messenger.display_name:
            self.messenger.change_name(new_name)
            self.app.lbl_username.config(text=f' {new_name}')

        # Apply font size to open chat windows and update global
        new_size = int(self.var_font_size.get())
        chat_font = ('Segoe UI', new_size)
        chat_font_bold = ('Segoe UI', new_size, 'bold')
        # Update globals so new windows use updated font
        global FONT_CHAT
        FONT_CHAT = chat_font
        for cw in self.app.chat_windows.values():
            try:
                cw.chat_text.configure(font=chat_font)
                cw.chat_text.tag_configure('msg', font=chat_font)
                cw.chat_text.tag_configure('my_name', font=chat_font_bold)
                cw.chat_text.tag_configure('peer_name', font=chat_font_bold)
                cw.entry.configure(font=chat_font)
            except Exception:
                pass

        # Apply theme
        self.app.apply_theme(self.var_theme.get())

        # Apply auto-start
        if self.var_autostart.get():
            _setup_autostart()
        else:
            _remove_autostart()

        # Apply language
        lang = self.var_language.get()
        if lang in LANGS:
            global _CURRENT_LANG
            _CURRENT_LANG = LANGS[lang]
            self.app._rebuild_ui_language()

        # Update avatar in main window
        self.app._update_avatar()

        self.destroy()

    def _reset_defaults(self):
        if messagebox.askyesno('Redefinir', 'Restaurar todas as preferências?',
                               parent=self):
            self.var_autostart.set(False)
            self.var_show_main.set(True)
            self.var_sound.set(True)
            self.var_sound_msg.set(True)
            self.var_sound_online.set(True)
            self.var_flash_taskbar.set(True)
            self.var_tray_icon.set(True)
            self.var_balloon.set(True)
            self.var_save_history.set(True)
            self.var_download_dir.set(
                os.path.join(os.path.expanduser('~'), 'MB_Chat_Files'))
            self.var_avatar_index.set(0)
            self.var_custom_avatar.set('')


# =============================================================
#  ACCOUNT WINDOW — Janela pequena só com opções de Conta
# =============================================================
class AccountWindow(tk.Toplevel):
    """Janelinha compacta de perfil (nome + avatar)."""

    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.messenger = app.messenger
        self.title('Conta')
        self.resizable(False, False)
        self.transient(app.root)
        self.grab_set()
        self.configure(bg=BG_WINDOW)

        _center_window(self, 340, 420)

        db = self.messenger.db
        self.var_display_name = tk.StringVar(value=self.messenger.display_name)
        self.var_avatar_index = tk.IntVar(
            value=int(db.get_setting('avatar_index', '0')))
        self.var_custom_avatar = tk.StringVar(
            value=db.get_setting('custom_avatar', ''))

        content = tk.Frame(self, bg=BG_WINDOW)
        content.pack(fill='both', expand=True, padx=10, pady=(10, 0))

        # Nome
        lf = tk.LabelFrame(content, text='Perfil', font=FONT,
                            bg=BG_WINDOW, padx=10, pady=8)
        lf.pack(fill='x', pady=(0, 8))

        row = tk.Frame(lf, bg=BG_WINDOW)
        row.pack(fill='x', pady=4)
        tk.Label(row, text='Nome de exibição:', font=FONT,
                 bg=BG_WINDOW).pack(side='left')
        tk.Entry(row, font=FONT, width=18,
                 textvariable=self.var_display_name).pack(side='right')

        # Foto de perfil
        lf2 = tk.LabelFrame(content, text='Foto de Perfil', font=FONT,
                             bg=BG_WINDOW, padx=10, pady=8)
        lf2.pack(fill='x', pady=(0, 8))

        tk.Label(lf2, text='Escolha um avatar ou envie uma foto:',
                 font=FONT_SMALL, bg=BG_WINDOW).pack(anchor='w', pady=(0, 6))

        grid = tk.Frame(lf2, bg=BG_WINDOW)
        grid.pack(anchor='w', pady=(0, 8))

        self._avatar_canvases = []
        for i, (color, letter) in enumerate(AVATAR_COLORS):
            c = tk.Canvas(grid, width=36, height=36, bg=BG_WINDOW,
                          highlightthickness=0, cursor='hand2')
            r = i // 6
            col = i % 6
            c.grid(row=r, column=col, padx=2, pady=2)
            c.create_rectangle(2, 2, 34, 34, fill=color, outline='#999999')
            initial = self.messenger.display_name[0].upper() if self.messenger.display_name else 'U'
            c.create_text(18, 18, text=initial, fill='white',
                          font=('Segoe UI', 11, 'bold'))
            if i == self.var_avatar_index.get() and not self.var_custom_avatar.get():
                c.create_rectangle(1, 1, 35, 35, outline='#0066cc', width=2)
            c.bind('<Button-1>', lambda e, idx=i: self._select_avatar(idx))
            self._avatar_canvases.append(c)

        photo_row = tk.Frame(lf2, bg=BG_WINDOW)
        photo_row.pack(fill='x', pady=4)

        self._custom_preview = tk.Canvas(photo_row, width=36, height=36,
                                         bg=BG_WINDOW, highlightthickness=0)
        self._custom_preview.pack(side='left', padx=(0, 8))

        custom = self.var_custom_avatar.get()
        self._show_preview(custom)

        btn_frame = tk.Frame(photo_row, bg=BG_WINDOW)
        btn_frame.pack(side='left')

        tk.Button(btn_frame, text='Enviar foto...', font=FONT_SMALL,
                  command=self._upload_avatar).pack(anchor='w')

        self._lbl_custom_path = tk.Label(
            btn_frame,
            text=os.path.basename(custom) if custom else 'Nenhuma foto',
            font=FONT_SMALL, bg=BG_WINDOW, fg=FG_GRAY)
        self._lbl_custom_path.pack(anchor='w')

        if custom:
            tk.Button(btn_frame, text='Remover foto', font=FONT_SMALL,
                      fg=FG_RED, command=self._remove_custom_avatar
                      ).pack(anchor='w', pady=2)

        # Bottom buttons
        bottom = tk.Frame(self, bg=BG_WINDOW)
        bottom.pack(fill='x', padx=10, pady=8)
        tk.Button(bottom, text='Cancelar', font=FONT, width=10,
                  command=self.destroy).pack(side='right', padx=4)
        tk.Button(bottom, text='OK', font=FONT, width=10,
                  command=self._save).pack(side='right', padx=4)

    def _show_preview(self, path):
        self._custom_preview.delete('all')
        if path and os.path.exists(path):
            try:
                if HAS_PIL:
                    img = Image.open(path)
                    img = img.resize((32, 32), Image.LANCZOS)
                    self._preview_img = ImageTk.PhotoImage(img)
                    self._custom_preview.create_image(18, 18,
                                                      image=self._preview_img)
                    return
            except Exception:
                pass
            self._custom_preview.create_rectangle(2, 2, 34, 34,
                                                  fill='#228822', outline='#999')
            self._custom_preview.create_text(18, 18, text='✓', fill='white',
                                             font=('Segoe UI', 14, 'bold'))
        else:
            self._custom_preview.create_rectangle(2, 2, 34, 34,
                                                  fill='#dddddd', outline='#999')
            self._custom_preview.create_text(18, 18, text='?', fill='#999',
                                             font=('Segoe UI', 12))

    def _select_avatar(self, idx):
        self.var_avatar_index.set(idx)
        self.var_custom_avatar.set('')
        for i, c in enumerate(self._avatar_canvases):
            c.delete('selection')
            if i == idx:
                c.create_rectangle(1, 1, 35, 35, outline='#0066cc',
                                   width=2, tags='selection')

    def _upload_avatar(self):
        path = filedialog.askopenfilename(
            parent=self, title='Selecionar foto de perfil',
            filetypes=[('Imagens', '*.png *.jpg *.jpeg *.gif *.bmp'),
                       ('Todos', '*.*')])
        if not path:
            return
        ext = os.path.splitext(path)[1]
        dest = os.path.join(_get_avatars_dir(), f'custom_avatar{ext}')
        shutil.copy2(path, dest)
        self.var_custom_avatar.set(dest)
        self._lbl_custom_path.config(text=os.path.basename(path))
        for c in self._avatar_canvases:
            c.delete('selection')
        self._show_preview(dest)

    def _remove_custom_avatar(self):
        self.var_custom_avatar.set('')
        self._lbl_custom_path.config(text='Nenhuma foto')
        self._show_preview('')

    def _save(self):
        db = self.messenger.db
        # Save name
        new_name = self.var_display_name.get().strip()
        if new_name and new_name != self.messenger.display_name:
            self.messenger.change_name(new_name)
            self.app.lbl_username.config(text=f' {new_name}')
        # Save avatar
        db.set_setting('avatar_index', str(self.var_avatar_index.get()))
        db.set_setting('custom_avatar', self.var_custom_avatar.get())
        self.app._update_avatar()
        self.destroy()


# =============================================================
#  FILE TRANSFER DIALOG  (estilo LAN Messenger)
# =============================================================
class FileTransferDialog(tk.Toplevel):
    """Dialogo de progresso de transferencia de arquivo."""

    def __init__(self, parent, file_id, filename, peer_name,
                 direction='send', filesize=0, on_cancel=None):
        super().__init__(parent)
        self.file_id = file_id
        self._on_cancel = on_cancel

        self.title('Transferência de Arquivo')
        self.resizable(False, False)
        _center_window(self, 370, 120)
        self.configure(bg='#ffffff')
        self.transient(parent)

        if direction == 'send':
            txt = f"Enviando '{filename}' para {peer_name}."
        else:
            txt = f"Recebendo '{filename}' de {peer_name}."

        tk.Label(self, text=txt, font=FONT, bg='#ffffff', fg='#000000',
                 wraplength=340, anchor='w', justify='left'
                 ).pack(padx=15, pady=(15, 8), anchor='w')

        self.progress = ttk.Progressbar(self, length=335, mode='determinate',
                                         maximum=max(filesize, 1))
        self.progress.pack(padx=15, pady=(0, 6))

        cancel_lbl = tk.Label(self, text='Cancelar', font=('Segoe UI', 8, 'underline'),
                              fg='#0066cc', bg='#ffffff', cursor='hand2')
        cancel_lbl.pack(anchor='w', padx=15, pady=(0, 10))
        cancel_lbl.bind('<Button-1>', lambda e: self._cancel())

        self.protocol('WM_DELETE_WINDOW', self._cancel)

        ico = _get_icon_path()
        if ico:
            try:
                self.iconbitmap(ico)
            except Exception:
                pass

    def update_progress(self, transferred, total):
        try:
            self.progress['maximum'] = max(total, 1)
            self.progress['value'] = transferred
        except tk.TclError:
            pass

    def finish(self):
        try:
            self.destroy()
        except tk.TclError:
            pass

    def _cancel(self):
        if self._on_cancel:
            self._on_cancel(self.file_id)
        self.finish()


# =============================================================
#  CHAT WINDOW
# =============================================================
class ChatWindow(tk.Toplevel):
    def __init__(self, parent_app, peer_id, peer_name, **kw):
        super().__init__(parent_app.root)
        self.app = parent_app
        self.messenger = parent_app.messenger
        self.peer_id = peer_id
        self.peer_name = peer_name
        self._typing_timer = None
        self._was_typing = False

        self.title(f'{peer_name} - {APP_NAME}')
        self.minsize(350, 300)
        _center_window(self, 450, 400)
        self.configure(bg=BG_WINDOW)
        ico = _get_icon_path()
        if ico:
            try:
                self.iconbitmap(ico)
            except Exception:
                pass

        # Toolbar
        toolbar = tk.Frame(self, bg=BG_HEADER, height=30, bd=1,
                           relief='raised')
        toolbar.pack(fill='x')
        toolbar.pack_propagate(False)

        for text, cmd in [(_t('font_btn'), None),
                          (_t('send_file_btn'), self._send_file),
                          (_t('history_btn'), self._show_history)]:
            tk.Button(toolbar, text=text, font=FONT_SMALL, bg=BG_HEADER,
                      relief='flat', bd=0, padx=6, command=cmd,
                      cursor='hand2').pack(side='left', padx=1, pady=2)

        # Header
        header = tk.Frame(self, bg=BG_WHITE, bd=1, relief='sunken')
        header.pack(fill='x', padx=4, pady=(4, 0))

        self.lbl_peer = tk.Label(header, text=f'  {peer_name}',
                                 font=FONT_BOLD, bg=BG_WHITE, fg=FG_BLACK,
                                 anchor='w')
        self.lbl_peer.pack(fill='x', padx=4, pady=2)

        self.lbl_typing = tk.Label(header, text='', font=FONT_SMALL,
                                   bg=BG_WHITE, fg=FG_GRAY, anchor='w')
        self.lbl_typing.pack(fill='x', padx=8)

        # Send button row (pack before text areas so it's at bottom)
        btn_frame = tk.Frame(self, bg=BG_WINDOW)
        btn_frame.pack(fill='x', side='bottom', padx=4)
        tk.Button(btn_frame, text='Send', font=FONT, width=8,
                  command=self._send_message).pack(side='right', pady=2)

        # Input area
        input_frame = tk.Frame(self, bg=BG_WINDOW)
        input_frame.pack(fill='x', side='bottom', padx=4, pady=4)

        self.entry = tk.Text(input_frame, font=FONT_CHAT, bg=BG_WHITE,
                             fg=FG_BLACK, relief='sunken', bd=1, height=3,
                             wrap='word', padx=4, pady=4)
        entry_scroll = ttk.Scrollbar(input_frame, command=self.entry.yview)
        self.entry.configure(yscrollcommand=entry_scroll.set)
        entry_scroll.pack(side='right', fill='y')
        self.entry.pack(fill='both', expand=True)
        self.entry.bind('<Return>', self._on_enter)
        self.entry.bind('<Shift-Return>', lambda e: None)
        self.entry.bind('<KeyRelease>', self._on_key)
        self.entry.focus_set()

        # Chat display
        self.chat_text = tk.Text(self, font=FONT_CHAT, bg=BG_WHITE,
                                 fg=FG_BLACK, relief='sunken', bd=1,
                                 wrap='word', state='disabled', padx=6,
                                 pady=4, cursor='arrow')
        chat_scroll = ttk.Scrollbar(self, command=self.chat_text.yview)
        self.chat_text.configure(yscrollcommand=chat_scroll.set)
        chat_scroll.pack(side='right', fill='y', padx=(0, 4), pady=4)
        self.chat_text.pack(fill='both', expand=True, padx=(4, 0), pady=4)

        self.chat_text.tag_configure('time', foreground=FG_GRAY,
                                     font=FONT_SMALL)
        self.chat_text.tag_configure('my_name', foreground=FG_BLUE,
                                     font=FONT_BOLD)
        self.chat_text.tag_configure('peer_name', foreground=FG_RED,
                                     font=FONT_BOLD)
        self.chat_text.tag_configure('msg', font=FONT_CHAT)
        self.chat_text.tag_configure('system',
                                     foreground=FG_GRAY,
                                     font=('Segoe UI', 8, 'italic'))

        self._load_history()
        self.protocol('WM_DELETE_WINDOW', self._on_close)

    def _load_history(self):
        # Carrega mensagens nao-lidas ao abrir o chat
        unreads = self.messenger.get_unread_messages(self.peer_id)
        for msg in unreads:
            is_mine = msg['from_user'] != self.peer_id
            sender = self.app.messenger.display_name if is_mine else self.peer_name
            self._append_message(sender, msg['content'], is_mine,
                                 timestamp=msg['timestamp'])
        self.messenger.mark_as_read(self.peer_id)

    def _append_message(self, sender, text, is_mine, timestamp=None):
        ts = datetime.fromtimestamp(timestamp or time.time()).strftime('%H:%M:%S')
        self.chat_text.configure(state='normal')
        tag = 'my_name' if is_mine else 'peer_name'
        self.chat_text.insert('end', f'[{ts}] ', 'time')
        self.chat_text.insert('end', f'{sender}: ', tag)
        self.chat_text.insert('end', f'{text}\n', 'msg')
        self.chat_text.configure(state='disabled')
        self.chat_text.see('end')

    def receive_message(self, content, timestamp=None):
        self._append_message(self.peer_name, content, False, timestamp=timestamp)
        self.messenger.mark_as_read(self.peer_id)
        if self.focus_get() is None:
            self.bell()

    def set_typing(self, is_typing):
        self.lbl_typing.config(
            text=f'{self.peer_name} {_t("typing")}' if is_typing else '')

    def _on_enter(self, event):
        if not (event.state & 0x1):
            self._send_message()
            return 'break'

    def _on_key(self, event):
        if not self._was_typing:
            self._was_typing = True
            self.messenger.send_typing(self.peer_id, True)
        if self._typing_timer:
            self.after_cancel(self._typing_timer)
        self._typing_timer = self.after(2000, self._stop_typing)

    def _stop_typing(self):
        self._was_typing = False
        self.messenger.send_typing(self.peer_id, False)

    def _send_message(self):
        content = self.entry.get('1.0', 'end').strip()
        if not content:
            return
        self.entry.delete('1.0', 'end')
        self._append_message(self.messenger.display_name, content, True)
        threading.Thread(target=self.messenger.send_message,
                         args=(self.peer_id, content), daemon=True).start()

    def _send_file(self):
        filepath = filedialog.askopenfilename(parent=self, title='Enviar arquivo')
        if filepath:
            self.app._start_file_send(self.peer_id, filepath)

    def _show_history(self):
        history = self.messenger.get_chat_history(self.peer_id, limit=500)
        win = tk.Toplevel(self)
        win.title(f'Histórico - {self.peer_name}')
        _center_window(win, 500, 400)
        txt = tk.Text(win, font=FONT_SMALL, wrap='word', bg=BG_WHITE)
        scr = ttk.Scrollbar(win, command=txt.yview)
        txt.configure(yscrollcommand=scr.set)
        scr.pack(side='right', fill='y')
        txt.pack(fill='both', expand=True)
        for m in history:
            ts = datetime.fromtimestamp(m['timestamp']).strftime('%Y-%m-%d %H:%M:%S')
            who = 'Você' if m['is_sent'] else self.peer_name
            txt.insert('end', f'[{ts}] {who}: {m["content"]}\n')
        txt.configure(state='disabled')

    def _on_close(self):
        if self.peer_id in self.app.chat_windows:
            del self.app.chat_windows[self.peer_id]
        self.destroy()


# =============================================================
#  MAIN WINDOW
# =============================================================
class LanMessengerApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title(APP_NAME)
        self.root.minsize(240, 350)
        self.root.geometry('280x500')
        self.root.configure(bg=BG_WINDOW)

        # Icone da janela (iconphoto para nitidez na taskbar)
        self._icon_path = _get_icon_path()
        if self._icon_path:
            try:
                self.root.iconbitmap(self._icon_path)
                if HAS_PIL:
                    _ico_img = Image.open(self._icon_path)
                    _ico_img = _ico_img.resize((48, 48), Image.LANCZOS)
                    self._icon_photo = ImageTk.PhotoImage(_ico_img)
                    self.root.iconphoto(True, self._icon_photo)
            except Exception:
                pass

        # Posiciona no canto direito após a janela estar visível
        self.root.after(10, self._position_right)

        self.chat_windows = {}
        self.peer_items = {}
        self.peer_info = {}
        self._file_dialogs = {}  # file_id -> FileTransferDialog
        self._tray_icon = None
        self._last_notif_peer = None

        self._build_ui()
        self.root.protocol('WM_DELETE_WINDOW', self._on_close)

        # Init pesado deferido: janela aparece rapido, depois carrega rede/DB/tray
        self.root.after_idle(self._deferred_init)

    def _deferred_init(self):
        """Inicializacao deferida - roda apos a janela aparecer."""
        self._init_messenger()

        # Aplica idioma salvo
        saved_lang = self.messenger.db.get_setting('language', 'Português')
        if saved_lang in LANGS:
            global _CURRENT_LANG
            _CURRENT_LANG = LANGS[saved_lang]
            self._rebuild_ui_language()

        # Aplica tema salvo
        saved_theme = self.messenger.db.get_setting('theme', 'MB Contabilidade')
        self.apply_theme(saved_theme)

        # Carrega contatos offline salvos no DB
        self._load_saved_contacts()

        # Inicia tray icon para notificacoes
        if HAS_TRAY and HAS_PIL:
            self.root.after(50, self._start_tray)

    def _position_right(self):
        """Posiciona a janela no canto direito da tela, centralizada na vertical."""
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        x = sw - w - 20
        y = (sh - h) // 2 - 30
        self.root.geometry(f'+{x}+{y}')

    def _init_messenger(self):
        self.messenger = Messenger(
            on_user_found=self._safe(self._on_user_found),
            on_user_lost=self._safe(self._on_user_lost),
            on_message=self._safe(self._on_message),
            on_typing=self._safe(self._on_typing),
            on_file_incoming=self._safe(self._on_file_incoming),
            on_file_progress=self._safe(self._on_file_progress),
            on_file_complete=self._safe(self._on_file_complete),
            on_file_error=self._safe(self._on_file_error),
        )
        self.messenger.start()
        self.lbl_username.config(text=f' {self.messenger.display_name}')
        self.root.title(APP_NAME)
        self._update_avatar()

    def _safe(self, func):
        def wrapper(*args, **kwargs):
            self.root.after(0, func, *args, **kwargs)
        return wrapper

    def _rebuild_ui_language(self):
        """Atualiza textos da UI apos mudanca de idioma."""
        # Rebuild menu bar
        menubar = tk.Menu(self.root, font=FONT)

        m1 = tk.Menu(menubar, tearoff=0, font=FONT)
        m1.add_command(label=_t('menu_change_name'), command=self._change_name)
        m1.add_separator()
        m1.add_command(label=_t('menu_preferences'),
                       command=self._show_preferences)
        m1.add_separator()
        m1.add_command(label=_t('menu_quit'), command=self._quit)
        menubar.add_cascade(label=_t('menu_messenger'), menu=m1)

        m2 = tk.Menu(menubar, tearoff=0, font=FONT)
        m2.add_command(label=_t('menu_history'),
                       command=self._show_all_history)
        m2.add_command(label=_t('menu_transfers'),
                       command=self._show_transfers)
        m2.add_separator()
        m2.add_command(label=_t('menu_broadcast'),
                       command=self._send_broadcast)
        menubar.add_cascade(label=_t('menu_tools'), menu=m2)

        m3 = tk.Menu(menubar, tearoff=0, font=FONT)
        m3.add_command(label=f'{_t("menu_about")} {APP_NAME}',
                       command=self._show_about)
        menubar.add_cascade(label=_t('menu_help'), menu=m3)

        self.root.config(menu=menubar)

        # Update status combo
        self.status_combo['values'] = [
            _t('status_available'), _t('status_away'),
            _t('status_busy'), _t('status_offline')]
        # Map current internal status to new language
        rev = {'online': 'status_available', 'away': 'status_away',
               'busy': 'status_busy', 'invisible': 'status_offline'}
        current = self.messenger.status
        self.status_var.set(_t(rev.get(current, 'status_available')))

        # Update note placeholder
        if not self.note_entry.get().strip() or \
           self.note_entry.get() in ('Digite uma nota', 'Type a note'):
            self.note_entry.delete(0, 'end')
            self.note_entry.insert(0, _t('note_placeholder'))

        # Update group label
        self.tree.item(self.group_general, text=_t('group_general'))

        # Update context menu
        self.ctx_menu.entryconfigure(0, label=_t('ctx_send_msg'))
        self.ctx_menu.entryconfigure(1, label=_t('ctx_send_file'))
        self.ctx_menu.entryconfigure(3, label=_t('ctx_info'))

    def apply_theme(self, theme_name):
        """Aplica um tema em toda a interface."""
        t = THEMES.get(theme_name, THEMES['MB Contabilidade'])
        self._theme = t

        # --- Main window ---
        self.root.configure(bg=t['bg_window'])

        # Recursivo: todos os frames e labels da janela principal
        self._apply_theme_recursive(self.root, t)

        # --- Treeview style ---
        style = ttk.Style()
        style.configure('Contacts.Treeview',
                        background=t['bg_white'],
                        foreground=t['fg_black'],
                        fieldbackground=t['bg_white'],
                        rowheight=28)
        style.configure('Contacts.Treeview.Heading',
                        background=t['bg_group'],
                        foreground=t['fg_white'])
        style.map('Contacts.Treeview',
                  background=[('selected', t['bg_select'])],
                  foreground=[('selected', t['fg_black'])])

        # Custom scrollbar canvas
        if hasattr(self, '_scroll_canvas'):
            self._scroll_canvas.configure(bg=t['bg_white'])
            self._scroll_redraw()

        # Tags do treeview
        if hasattr(self, 'tree'):
            self.tree.tag_configure('group', background=t['bg_group'],
                                    foreground=t['fg_white'], font=FONT_BOLD)
            self.tree.tag_configure('online', foreground=t['fg_black'])
            self.tree.tag_configure('away', foreground=t['fg_orange'])
            self.tree.tag_configure('busy', foreground=t['fg_red'])
            self.tree.tag_configure('offline', foreground=t['fg_gray'])


        # --- User info panel ---
        if hasattr(self, 'lbl_username'):
            self.lbl_username.configure(bg=t['bg_white'], fg=t['fg_black'])
        if hasattr(self, 'avatar_canvas'):
            self.avatar_canvas.configure(bg=t['bg_white'])
        if hasattr(self, 'note_entry'):
            self.note_entry.configure(bg=t['bg_white'], fg=t['fg_gray'],
                                      insertbackground=t['fg_gray'])

        # --- Chat windows abertas ---
        for cw in self.chat_windows.values():
            self._apply_theme_to_chat(cw, t)

    def _apply_theme_recursive(self, widget, t):
        """Aplica cores basicas em frames e labels recursivamente."""
        wtype = widget.winfo_class()
        try:
            if wtype in ('Frame', 'Labelframe'):
                widget.configure(bg=t['bg_window'])
            elif wtype == 'Label':
                cur_bg = str(widget.cget('bg'))
                if cur_bg in (BG_WHITE, '#ffffff',
                              *[th['bg_white'] for th in THEMES.values()]):
                    widget.configure(bg=t['bg_white'], fg=t['fg_black'])
                elif cur_bg in (BG_HEADER, '#e8e8e8',
                                *[th['bg_header'] for th in THEMES.values()],
                                *[th['statusbar_bg'] for th in THEMES.values()]):
                    widget.configure(bg=t['bg_header'], fg=t['fg_gray'])
                else:
                    widget.configure(bg=t['bg_window'])
            elif wtype == 'Button':
                widget.configure(bg=t['btn_bg'], fg=t['btn_fg'],
                                 activebackground=t['btn_active'],
                                 activeforeground=t['btn_fg'])
        except Exception:
            pass
        for child in widget.winfo_children():
            self._apply_theme_recursive(child, t)

    def _apply_theme_to_chat(self, cw, t):
        """Aplica tema em uma ChatWindow."""
        try:
            cw.configure(bg=t['bg_window'])
            cw.chat_text.configure(bg=t['bg_chat'], fg=t['fg_msg'],
                                   insertbackground=t['fg_black'])
            cw.chat_text.tag_configure('time', foreground=t['fg_time'])
            cw.chat_text.tag_configure('my_name', foreground=t['fg_my_name'])
            cw.chat_text.tag_configure('peer_name',
                                       foreground=t['fg_peer_name'])
            cw.chat_text.tag_configure('msg', foreground=t['fg_msg'])
            cw.entry.configure(bg=t['bg_input'], fg=t['fg_black'],
                               insertbackground=t['fg_black'])
            cw.lbl_peer.configure(bg=t['bg_white'], fg=t['fg_black'])
            cw.lbl_typing.configure(bg=t['bg_white'], fg=t['fg_gray'])
            self._apply_theme_recursive(cw, t)
        except Exception:
            pass

    def _build_ui(self):
        # Menu Bar
        menubar = tk.Menu(self.root, font=FONT)

        m1 = tk.Menu(menubar, tearoff=0, font=FONT)
        m1.add_command(label=_t('menu_change_name'), command=self._change_name)
        m1.add_separator()
        m1.add_command(label=_t('menu_preferences'), command=self._show_preferences)
        m1.add_separator()
        m1.add_command(label=_t('menu_quit'), command=self._quit)
        menubar.add_cascade(label=_t('menu_messenger'), menu=m1)

        m2 = tk.Menu(menubar, tearoff=0, font=FONT)
        m2.add_command(label=_t('menu_history'), command=self._show_all_history)
        m2.add_command(label=_t('menu_transfers'), command=self._show_transfers)
        m2.add_separator()
        m2.add_command(label=_t('menu_broadcast'), command=self._send_broadcast)
        menubar.add_cascade(label=_t('menu_tools'), menu=m2)

        m3 = tk.Menu(menubar, tearoff=0, font=FONT)
        m3.add_command(label=f'{_t("menu_about")} {APP_NAME}', command=self._show_about)
        menubar.add_cascade(label=_t('menu_help'), menu=m3)

        self.root.config(menu=menubar)

        # User Info Panel
        user_frame = tk.Frame(self.root, bg=BG_WHITE, bd=0, relief='flat')
        user_frame.pack(fill='x', padx=3, pady=(3, 0))

        row1 = tk.Frame(user_frame, bg=BG_WHITE)
        row1.pack(fill='x', padx=4, pady=(6, 2))

        # Avatar
        self.avatar_canvas = tk.Canvas(row1, width=32, height=32,
                                       bg=BG_WHITE, highlightthickness=0,
                                       cursor='hand2')
        self.avatar_canvas.pack(side='left', padx=(0, 6))
        self.avatar_canvas.bind('<Button-1>',
                                lambda e: self._show_account())
        self._draw_default_avatar(0)

        name_status = tk.Frame(row1, bg=BG_WHITE)
        name_status.pack(side='left', fill='x', expand=True)

        self.lbl_username = tk.Label(name_status, text=_t('user_default'),
                                     font=FONT_BOLD, bg=BG_WHITE,
                                     fg=FG_BLACK, anchor='w')
        self.lbl_username.pack(fill='x')

        status_row = tk.Frame(name_status, bg=BG_WHITE)
        status_row.pack(fill='x')

        self.status_var = tk.StringVar(value=_t('status_available'))
        self.status_combo = ttk.Combobox(
            status_row, textvariable=self.status_var,
            values=[_t('status_available'), _t('status_away'),
                    _t('status_busy'), _t('status_offline')],
            state='readonly', font=FONT_SMALL, width=12)
        self.status_combo.pack(side='left')
        self.status_combo.bind('<<ComboboxSelected>>',
                               self._on_status_change)

        row2 = tk.Frame(user_frame, bg=BG_WHITE)
        row2.pack(fill='x', padx=8, pady=(2, 6))

        # Wrapper para dar borda sutil ao campo de nota
        note_border = tk.Frame(row2, bg='#aaaaaa', bd=0)
        note_border.pack(fill='x')

        self.note_entry = tk.Entry(note_border, font=FONT, bg=BG_WHITE,
                                   fg=FG_GRAY, relief='flat', bd=2,
                                   insertbackground=FG_GRAY)
        self.note_entry.pack(fill='x', ipady=2)
        self.note_entry.insert(0, _t('note_placeholder'))
        self.note_entry.bind('<FocusIn>', self._note_focus_in)
        self.note_entry.bind('<FocusOut>', self._note_focus_out)

        # Toolbar
        toolbar = tk.Frame(self.root, bg=BG_HEADER, height=30, bd=0,
                           relief='flat')
        toolbar.pack(fill='x', padx=3)
        toolbar.pack_propagate(False)

        for text, cmd in [(_t('btn_send'), self._send_broadcast),
                          (_t('btn_file'), self._send_file_toolbar),
                          (_t('btn_refresh'), self._refresh_peers)]:
            tk.Button(toolbar, text=text, font=FONT_SMALL,
                      bg=BG_HEADER, relief='flat', bd=0, padx=8,
                      pady=2, command=cmd, cursor='hand2',
                      activebackground='#d0d0d0'
                      ).pack(side='left', padx=2, pady=2)

        # Contact Treeview
        tree_frame = tk.Frame(self.root, bg=BG_WHITE, bd=0,
                              highlightthickness=0)
        tree_frame.pack(fill='both', expand=True, padx=3, pady=(0, 3))

        style = ttk.Style()
        style.theme_use('clam')
        style.configure('Contacts.Treeview', background=BG_WHITE,
                         foreground=FG_BLACK, fieldbackground=BG_WHITE,
                         font=FONT, rowheight=28, borderwidth=0)
        style.configure('Contacts.Treeview.Heading', background=BG_GROUP,
                         foreground=FG_WHITE, font=FONT_BOLD)
        style.map('Contacts.Treeview',
                   background=[('selected', BG_SELECT)],
                   foreground=[('selected', FG_BLACK)])
        style.layout('Contacts.Treeview',
                      [('Treeview.treearea', {'sticky': 'nswe'})])

        self.tree = ttk.Treeview(tree_frame, style='Contacts.Treeview',
                                 show='tree', selectmode='browse')

        # Custom thin scrollbar (LAN Messenger style)
        self._scroll_canvas = tk.Canvas(tree_frame, width=6,
                                        highlightthickness=0, bd=0,
                                        bg=BG_WHITE)
        self._scroll_thumb = None
        self._scroll_dragging = False
        self._scroll_drag_y = 0
        self._scroll_wide = False
        self._scroll_lo = 0.0
        self._scroll_hi = 1.0
        self._THIN = 6
        self._WIDE = 12

        def _scroll_set(lo, hi):
            self._scroll_lo, self._scroll_hi = float(lo), float(hi)
            if float(lo) <= 0.0 and float(hi) >= 1.0:
                self._scroll_canvas.pack_forget()
            else:
                if not self._scroll_canvas.winfo_ismapped():
                    self._scroll_canvas.pack(side='right', fill='y')
                _scroll_redraw()

        def _scroll_redraw():
            c = self._scroll_canvas
            c.delete('all')
            h = c.winfo_height()
            if h < 2:
                return
            w = c.winfo_width()
            y1 = max(int(self._scroll_lo * h), 0)
            y2 = min(int(self._scroll_hi * h), h)
            if y2 - y1 < 20:
                mid = (y1 + y2) // 2
                y1, y2 = max(mid - 10, 0), min(mid + 10, h)
            pad = 1 if w <= self._THIN else 2
            t = self._theme if hasattr(self, '_theme') else THEMES.get('MB Contabilidade')
            thumb_color = t.get('fg_gray', '#888888')
            c.create_rectangle(pad, y1 + 2, w - pad, y2 - 2,
                               fill=thumb_color, outline='', width=0)

        def _scroll_enter(e):
            self._scroll_wide = True
            self._scroll_canvas.configure(width=self._WIDE)
            _scroll_redraw()

        def _scroll_leave(e):
            if not self._scroll_dragging:
                self._scroll_wide = False
                self._scroll_canvas.configure(width=self._THIN)
                _scroll_redraw()

        def _scroll_press(e):
            self._scroll_dragging = True
            self._scroll_drag_y = e.y
            h = self._scroll_canvas.winfo_height()
            click_frac = e.y / h if h > 0 else 0
            if click_frac < self._scroll_lo or click_frac > self._scroll_hi:
                self.tree.yview_moveto(max(click_frac - (self._scroll_hi - self._scroll_lo) / 2, 0))

        def _scroll_drag(e):
            if not self._scroll_dragging:
                return
            h = self._scroll_canvas.winfo_height()
            if h < 1:
                return
            dy = (e.y - self._scroll_drag_y) / h
            self._scroll_drag_y = e.y
            new_lo = self._scroll_lo + dy
            self.tree.yview_moveto(max(0.0, min(1.0, new_lo)))

        def _scroll_release(e):
            self._scroll_dragging = False
            if not self._scroll_wide:
                self._scroll_canvas.configure(width=self._THIN)
                _scroll_redraw()

        self._scroll_canvas.bind('<Enter>', _scroll_enter)
        self._scroll_canvas.bind('<Leave>', _scroll_leave)
        self._scroll_canvas.bind('<Button-1>', _scroll_press)
        self._scroll_canvas.bind('<B1-Motion>', _scroll_drag)
        self._scroll_canvas.bind('<ButtonRelease-1>', _scroll_release)
        self._scroll_canvas.bind('<Configure>', lambda e: _scroll_redraw())
        self._scroll_redraw = _scroll_redraw

        self.tree.configure(yscrollcommand=_scroll_set)
        self._scroll_canvas.pack(side='right', fill='y')
        self.tree.pack(fill='both', expand=True)

        # Status dot images (10x10 colored circles)
        self._status_dots = {}
        self._create_status_dots()

        self.group_general = self.tree.insert('', 'end', text=_t('group_general'),
                                              open=True, tags=('group',))
        self.tree.tag_configure('group', background=BG_GROUP,
                                foreground=FG_WHITE, font=FONT_BOLD)
        self.tree.tag_configure('online', foreground=FG_BLACK)
        self.tree.tag_configure('away', foreground=FG_ORANGE)
        self.tree.tag_configure('busy', foreground=FG_RED)
        self.tree.tag_configure('offline', foreground=FG_GRAY)
        self.tree.tag_configure('unread', font=FONT_BOLD)

        self.tree.bind('<Double-1>', self._on_tree_dbl)
        self.tree.bind('<Button-3>', self._on_tree_right)

        self.ctx_menu = tk.Menu(self.root, tearoff=0, font=FONT)
        self.ctx_menu.add_command(label=_t('ctx_send_msg'),
                                  command=self._ctx_chat)
        self.ctx_menu.add_command(label=_t('ctx_send_file'),
                                  command=self._ctx_file)
        self.ctx_menu.add_separator()
        self.ctx_menu.add_command(label=_t('ctx_info'), command=self._ctx_info)


    def _create_status_dots(self):
        """Cria imagens de bolinha colorida para cada status."""
        dot_colors = {
            'online': '#00cc44',
            'away': '#ccaa00',
            'busy': '#cc2222',
            'offline': '#888888',
        }
        size = 10
        for status, color in dot_colors.items():
            img = tk.PhotoImage(width=size, height=size)
            # Draw filled circle using pixel-by-pixel
            cx, cy, r = size // 2, size // 2, size // 2 - 1
            for y in range(size):
                for x in range(size):
                    dx, dy = x - cx, y - cy
                    if dx * dx + dy * dy <= r * r:
                        img.put(color, (x, y))
            self._status_dots[status] = img

    def _load_saved_contacts(self):
        """Carrega contatos offline do DB no treeview ao iniciar."""
        contacts = self.messenger.db.get_contacts(online_only=False)
        for c in contacts:
            uid = c['user_id']
            if uid == self.messenger.user_id:
                continue
            if uid in self.peer_items:
                continue
            status = c.get('status', 'offline')
            tag = status if status in ('online', 'away', 'busy') else 'offline'
            name = c.get('display_name', 'Unknown')
            suffix = ' (offline)' if tag == 'offline' else ''
            display = f'  {name}{suffix}'
            dot = self._status_dots.get(tag)
            iid = self.tree.insert(self.group_general, 'end',
                                   text=display, tags=(tag,),
                                   image=dot if dot else '')
            self.peer_items[uid] = iid
            self.peer_info[uid] = {
                'display_name': name,
                'ip': c.get('ip_address', ''),
                'hostname': c.get('hostname', ''),
                'status': status,
            }

    # --- Avatar ---
    def _draw_default_avatar(self, idx):
        self.avatar_canvas.delete('all')
        color, _ = AVATAR_COLORS[idx % len(AVATAR_COLORS)]
        self.avatar_canvas.create_rectangle(2, 2, 30, 30, fill=color,
                                            outline='#336699')
        self.avatar_canvas.create_text(16, 16, text='U', fill='white',
                                       font=('Segoe UI', 12, 'bold'))

    def _update_avatar(self):
        db = self.messenger.db
        idx = int(db.get_setting('avatar_index', '0'))
        custom = db.get_setting('custom_avatar', '')
        self.avatar_canvas.delete('all')

        if custom and os.path.exists(custom):
            try:
                if HAS_PIL:
                    img = Image.open(custom)
                    img = img.resize((28, 28), Image.LANCZOS)
                    self._avatar_img = ImageTk.PhotoImage(img)
                else:
                    self._avatar_img = tk.PhotoImage(file=custom)
                    w = self._avatar_img.width()
                    h = self._avatar_img.height()
                    if w > 0 and h > 0:
                        factor = max(w // 28, h // 28, 1)
                        self._avatar_img = self._avatar_img.subsample(factor)
                self.avatar_canvas.create_image(16, 16,
                                                image=self._avatar_img)
                return
            except Exception:
                pass

        # Default colored avatar
        color, _ = AVATAR_COLORS[idx % len(AVATAR_COLORS)]
        initial = self.messenger.display_name[0].upper() if self.messenger.display_name else 'U'
        self.avatar_canvas.create_rectangle(2, 2, 30, 30, fill=color,
                                            outline='#336699')
        self.avatar_canvas.create_text(16, 16, text=initial, fill='white',
                                       font=('Segoe UI', 12, 'bold'))

    # --- Note ---
    def _note_focus_in(self, e):
        if self.note_entry.get() in ('Digite uma nota', 'Type a note',
                                        _t('note_placeholder')):
            self.note_entry.delete(0, 'end')
            self.note_entry.config(fg=FG_BLACK)

    def _note_focus_out(self, e):
        if not self.note_entry.get().strip():
            self.note_entry.insert(0, _t('note_placeholder'))
            self.note_entry.config(fg=FG_GRAY)

    def _on_status_change(self, e=None):
        m = {_t('status_available'): 'online',
             _t('status_away'): 'away',
             _t('status_busy'): 'busy',
             _t('status_offline'): 'invisible'}
        self.messenger.change_status(m.get(self.status_var.get(), 'online'))

    # --- Tree ---
    def _get_selected_peer(self):
        sel = self.tree.selection()
        if not sel:
            return None
        item = sel[0]
        if item == self.group_general:
            return None
        for uid, iid in self.peer_items.items():
            if iid == item:
                return uid
        return None

    def _add_contact(self, uid, info):
        status = info.get('status', 'online')
        tag = status if status in ('online', 'away', 'busy') else 'offline'
        name = info.get('display_name', 'Unknown')
        suffix = ' (offline)' if tag == 'offline' else ''
        display = f'  {name}{suffix}'
        dot = self._status_dots.get(tag)
        if uid in self.peer_items:
            self.tree.item(self.peer_items[uid], text=display,
                           tags=(tag,), image=dot if dot else '')
        else:
            iid = self.tree.insert(self.group_general, 'end',
                                   text=display, tags=(tag,),
                                   image=dot if dot else '')
            self.peer_items[uid] = iid
        self.peer_info[uid] = info

    def _remove_contact(self, uid):
        """Marca peer como offline no treeview (nao remove)."""
        if uid in self.peer_items:
            name = self.peer_info.get(uid, {}).get('display_name', 'Unknown')
            dot = self._status_dots.get('offline')
            self.tree.item(self.peer_items[uid],
                           text=f'  {name} (offline)',
                           tags=('offline',),
                           image=dot if dot else '')

    def _mark_unread(self, uid):
        if uid in self.peer_items:
            item = self.peer_items[uid]
            tags = list(self.tree.item(item, 'tags'))
            if 'unread' not in tags:
                tags.append('unread')
                self.tree.item(item, tags=tuple(tags))
            name = self.peer_info.get(uid, {}).get('display_name', '')
            unread = self.messenger.get_unread_count(uid)
            status_tag = [t for t in tags if t in ('online','away','busy','offline')]
            status = status_tag[0] if status_tag else 'online'
            dot = self._status_dots.get(status)
            self.tree.item(item, text=f'  {name} ({unread})',
                           image=dot if dot else '')

    def _clear_unread(self, uid):
        if uid in self.peer_items:
            item = self.peer_items[uid]
            tags = [t for t in self.tree.item(item, 'tags') if t != 'unread']
            self.tree.item(item, tags=tuple(tags) if tags else ())
            name = self.peer_info.get(uid, {}).get('display_name', '')
            status = tags[0] if tags and tags[0] != 'group' else 'online'
            dot = self._status_dots.get(status)
            self.tree.item(item, text=f'  {name}',
                           image=dot if dot else '')

    def _on_tree_dbl(self, e):
        uid = self._get_selected_peer()
        if uid:
            self._open_chat(uid)

    def _on_tree_right(self, e):
        item = self.tree.identify_row(e.y)
        if item and item != self.group_general:
            self.tree.selection_set(item)
            self.ctx_menu.tk_popup(e.x_root, e.y_root)

    def _ctx_chat(self):
        uid = self._get_selected_peer()
        if uid:
            self._open_chat(uid)

    def _ctx_file(self):
        uid = self._get_selected_peer()
        if uid:
            fp = filedialog.askopenfilename(title='Enviar arquivo')
            if fp:
                self.messenger.send_file(uid, fp)

    def _ctx_info(self):
        uid = self._get_selected_peer()
        if uid and uid in self.peer_info:
            i = self.peer_info[uid]
            messagebox.showinfo('Info do Usuário',
                f"Nome: {i.get('display_name','?')}\n"
                f"IP: {i.get('ip','?')}\n"
                f"Host: {i.get('hostname','?')}\n"
                f"OS: {i.get('os','?')}\n"
                f"Status: {i.get('status','?')}")

    def _open_chat(self, peer_id):
        if peer_id in self.chat_windows:
            self.chat_windows[peer_id].lift()
            self.chat_windows[peer_id].focus_force()
            return
        name = self.peer_info.get(peer_id, {}).get('display_name', 'Unknown')
        cw = ChatWindow(self, peer_id, name)
        self.chat_windows[peer_id] = cw
        if hasattr(self, '_theme'):
            self._apply_theme_to_chat(cw, self._theme)
        self._clear_unread(peer_id)

    # --- Menu commands ---
    def _change_name(self):
        win = tk.Toplevel(self.root)
        win.title('Alterar Nome')
        win.resizable(False, False)
        _center_window(win, 300, 120)
        win.transient(self.root)
        win.grab_set()

        tk.Label(win, text='Novo nome:', font=FONT).pack(padx=15, pady=(15, 5), anchor='w')
        var = tk.StringVar(value=self.messenger.display_name)
        e = tk.Entry(win, textvariable=var, font=FONT)
        e.pack(fill='x', padx=15)
        e.select_range(0, 'end')
        e.focus_set()

        def save():
            n = var.get().strip()
            if n:
                self.messenger.change_name(n)
                self.lbl_username.config(text=f' {n}')
                self._update_avatar()
            win.destroy()

        tk.Button(win, text='OK', font=FONT, width=8, command=save).pack(pady=10)
        e.bind('<Return>', lambda ev: save())

    def _show_preferences(self):
        PreferencesWindow(self)

    def _show_account(self):
        AccountWindow(self)

    def _show_all_history(self):
        win = tk.Toplevel(self.root)
        win.title('Histórico de Mensagens')
        win.configure(bg=BG_WINDOW)
        _center_window(win, 700, 480)

        db = self.messenger.db
        user_id = self.messenger.user_id

        # --- Top filter bar ---
        filter_bar = tk.Frame(win, bg=BG_WINDOW)
        filter_bar.pack(fill='x', padx=6, pady=(6, 2))

        tk.Label(filter_bar, text='Pesquisar:', font=FONT_SMALL,
                 bg=BG_WINDOW).pack(side='left')
        search_var = tk.StringVar()
        search_entry = tk.Entry(filter_bar, textvariable=search_var,
                                font=FONT_SMALL, width=18)
        search_entry.pack(side='left', padx=(4, 10))

        tk.Label(filter_bar, text='De:', font=FONT_SMALL,
                 bg=BG_WINDOW).pack(side='left')
        date_from_var = tk.StringVar()
        tk.Entry(filter_bar, textvariable=date_from_var,
                 font=FONT_SMALL, width=10).pack(side='left', padx=2)

        tk.Label(filter_bar, text='Até:', font=FONT_SMALL,
                 bg=BG_WINDOW).pack(side='left')
        date_to_var = tk.StringVar()
        tk.Entry(filter_bar, textvariable=date_to_var,
                 font=FONT_SMALL, width=10).pack(side='left', padx=2)

        tk.Label(filter_bar, text='(dd/mm/aaaa)', font=FONT_SMALL,
                 fg=FG_GRAY, bg=BG_WINDOW).pack(side='left', padx=4)

        # --- Main split: left contacts | right messages ---
        main = tk.Frame(win, bg=BG_WINDOW)
        main.pack(fill='both', expand=True, padx=6, pady=2)

        # Left: contact list with Treeview (Name + Date)
        left = tk.Frame(main, bg=BG_WHITE, bd=1, relief='sunken')
        left.pack(side='left', fill='y', padx=(0, 4))

        cols = ('nome', 'data')
        contact_tree = ttk.Treeview(left, columns=cols, show='headings',
                                     height=18, selectmode='browse')
        contact_tree.heading('nome', text='Nome')
        contact_tree.heading('data', text='Data')
        contact_tree.column('nome', width=120, minwidth=80)
        contact_tree.column('data', width=110, minwidth=80)
        ct_scroll = ttk.Scrollbar(left, orient='vertical',
                                   command=contact_tree.yview)
        contact_tree.configure(yscrollcommand=ct_scroll.set)
        ct_scroll.pack(side='right', fill='y')
        contact_tree.pack(fill='both', expand=True)

        # Right: message display
        right = tk.Frame(main, bg=BG_WHITE, bd=1, relief='sunken')
        right.pack(side='left', fill='both', expand=True)

        msg_text = tk.Text(right, font=FONT, wrap='word', bg=BG_WHITE,
                           fg=FG_BLACK, state='disabled', padx=6, pady=4)
        msg_scroll = ttk.Scrollbar(right, command=msg_text.yview)
        msg_text.configure(yscrollcommand=msg_scroll.set)
        msg_scroll.pack(side='right', fill='y')
        msg_text.pack(fill='both', expand=True)

        msg_text.tag_configure('name_bold', font=FONT_BOLD)
        msg_text.tag_configure('time_tag', foreground=FG_GRAY,
                               font=FONT_SMALL)
        msg_text.tag_configure('highlight', background='#ffff00')

        # --- Bottom buttons ---
        bottom = tk.Frame(win, bg=BG_WINDOW)
        bottom.pack(fill='x', padx=6, pady=(2, 6))

        def clear_history():
            if messagebox.askyesno('Limpar Histórico',
                    'Tem certeza? Todas as mensagens serão apagadas.',
                    parent=win):
                db.conn.execute("DELETE FROM messages")
                db.conn.commit()
                contact_tree.delete(*contact_tree.get_children())
                msg_text.configure(state='normal')
                msg_text.delete('1.0', 'end')
                msg_text.configure(state='disabled')

        tk.Button(bottom, text='Limpar histórico', font=FONT_SMALL,
                  command=clear_history).pack(side='left')
        tk.Button(bottom, text='Fechar', font=FONT_SMALL,
                  command=win.destroy).pack(side='right')

        # --- Data ---
        contacts_data = db.get_history_contacts()
        # Resolve display names
        contact_names = {}
        for c in contacts_data:
            peer = c['peer']
            info = self.peer_info.get(peer, {})
            name = info.get('display_name', '')
            if not name:
                row = db.get_contact(peer)
                name = row['display_name'] if row else peer[:20]
            contact_names[peer] = name

        for c in contacts_data:
            peer = c['peer']
            name = contact_names[peer]
            ts = datetime.fromtimestamp(c['last_ts']).strftime('%d/%m/%Y %H:%M')
            contact_tree.insert('', 'end', iid=peer, values=(name, ts))

        def show_messages(event=None):
            sel = contact_tree.selection()
            if not sel:
                return
            peer = sel[0]
            # Parse date filters
            d_from = None
            d_to = None
            try:
                df = date_from_var.get().strip()
                if df:
                    d_from = datetime.strptime(df, '%d/%m/%Y').timestamp()
            except ValueError:
                pass
            try:
                dt = date_to_var.get().strip()
                if dt:
                    d_to = datetime.strptime(dt, '%d/%m/%Y').replace(
                        hour=23, minute=59, second=59).timestamp()
            except ValueError:
                pass
            stxt = search_var.get().strip() or None

            msgs = db.get_messages_with_peer(user_id, peer,
                                              date_from=d_from,
                                              date_to=d_to,
                                              search_text=stxt)
            peer_name = contact_names.get(peer, peer[:20])
            my_name = self.messenger.display_name

            msg_text.configure(state='normal')
            msg_text.delete('1.0', 'end')
            for m in msgs:
                who = my_name if m['is_sent'] else peer_name
                ts = datetime.fromtimestamp(
                    m['timestamp']).strftime('%H:%M')
                msg_text.insert('end', f'{who}:', 'name_bold')
                msg_text.insert('end', f'{ts}', 'time_tag')
                content = m['content']
                msg_text.insert('end', f'{content}\n')
                # Highlight search matches
                if stxt:
                    start = msg_text.index('end-1c linestart')
                    # Search backwards in last inserted line
            msg_text.configure(state='disabled')

        contact_tree.bind('<<TreeviewSelect>>', show_messages)

        def apply_filter(event=None):
            show_messages()
        search_entry.bind('<Return>', apply_filter)

        # Filter button
        tk.Button(filter_bar, text='Filtrar', font=FONT_SMALL,
                  command=apply_filter).pack(side='left', padx=4)

        # Ctrl+F focus search
        win.bind('<Control-f>', lambda e: search_entry.focus_set())

        # Select first contact if any
        children = contact_tree.get_children()
        if children:
            contact_tree.selection_set(children[0])
            show_messages()

    def _show_transfers(self):
        download_dir = self.messenger.db.get_setting(
            'download_dir',
            os.path.join(os.path.expanduser('~'), 'MB_Chat_Files'))
        os.makedirs(download_dir, exist_ok=True)
        if os.name == 'nt':
            os.startfile(download_dir)
        else:
            import subprocess
            subprocess.Popen(['xdg-open', download_dir])

    def _send_broadcast(self):
        win = tk.Toplevel(self.root)
        win.title(_t('broadcast_title'))
        win.transient(self.root)
        _center_window(win, 400, 200)

        tk.Label(win, text=f'{_t("broadcast_label")}', font=FONT).pack(padx=10, pady=10, anchor='w')
        txt = tk.Text(win, font=FONT, height=4)
        txt.pack(fill='both', expand=True, padx=10)

        def send():
            c = txt.get('1.0', 'end').strip()
            if c:
                for uid in self.peer_items:
                    self.messenger.send_message(uid, c)
                win.destroy()

        tk.Button(win, text=_t('broadcast_send'), font=FONT,
                  command=send).pack(pady=10)

    def _send_file_toolbar(self):
        uid = self._get_selected_peer()
        if not uid:
            messagebox.showinfo(_t('send_file_btn'), _t('file_select_contact'))
            return
        fp = filedialog.askopenfilename(title='Enviar arquivo')
        if fp:
            self._start_file_send(uid, fp)

    def _start_file_send(self, peer_id, filepath):
        """Inicia envio de arquivo com dialogo de progresso."""
        fid = self.messenger.send_file(peer_id, filepath)
        if fid:
            name = self.peer_info.get(peer_id, {}).get('display_name', 'Unknown')
            dlg = FileTransferDialog(
                self.root, fid, os.path.basename(filepath), name,
                direction='send', filesize=os.path.getsize(filepath),
                on_cancel=self.messenger.cancel_file
            )
            self._file_dialogs[fid] = dlg

    def _refresh_peers(self):
        self.messenger.discovery._send_announce()

    def _show_about(self):
        messagebox.showinfo(f'Sobre o {APP_NAME}',
            f'{APP_NAME}\n\n'
            'Mensageiro de rede local\n\n'
            'Funcionalidades:\n'
            '- Descoberta automática de rede\n'
            '- Mensagens instantâneas\n'
            '- Transferência de arquivos\n'
            '- Histórico (SQLite)\n'
            '- Auto-start com o sistema\n\n'
            'Python + tkinter')

    # --- Network callbacks ---
    def _on_user_found(self, uid, info):
        is_new = uid not in self.peer_items
        self._add_contact(uid, info)
        if is_new:
            SoundPlayer.play_connect()

    def _on_user_lost(self, uid, info):
        self._remove_contact(uid)

    def _on_message(self, from_user, content, msg_id, timestamp):
        SoundPlayer.play_notification()
        if from_user in self.chat_windows:
            cw = self.chat_windows[from_user]
            cw.receive_message(content, timestamp)
            # Notifica se a janela de chat nao esta em foco
            try:
                if not cw.focus_displayof():
                    self._show_toast(from_user, content)
            except Exception:
                pass
        else:
            self._mark_unread(from_user)
            self._show_toast(from_user, content)
            try:
                self.root.bell()
            except Exception:
                pass

    def _on_typing(self, from_user, is_typing):
        if from_user in self.chat_windows:
            self.chat_windows[from_user].set_typing(is_typing)

    def _on_file_incoming(self, file_id, from_user, display_name,
                          filename, filesize):
        # Auto-aceitar (como LAN Messenger)
        self.messenger.accept_file(file_id)
        dlg = FileTransferDialog(
            self.root, file_id, filename, display_name,
            direction='receive', filesize=filesize,
            on_cancel=lambda fid: self.messenger.decline_file(fid)
        )
        self._file_dialogs[file_id] = dlg

    def _on_file_progress(self, file_id, transferred, total):
        if file_id in self._file_dialogs:
            self._file_dialogs[file_id].update_progress(transferred, total)

    def _on_file_complete(self, file_id, filepath):
        if file_id in self._file_dialogs:
            self._file_dialogs[file_id].finish()
            del self._file_dialogs[file_id]
        if filepath:
            messagebox.showinfo('OK', f'{_t("file_complete")}\n{filepath}')

    def _on_file_error(self, file_id, error):
        if file_id in self._file_dialogs:
            self._file_dialogs[file_id].finish()
            del self._file_dialogs[file_id]
        messagebox.showerror(_t('file_error'), error)

    def _show_toast(self, from_user, content):
        """Mostra notificacao toast nativa do Windows (clicavel via winotify)."""
        self._last_notif_peer = from_user
        name = self.peer_info.get(from_user, {}).get('display_name', 'Mensagem')
        preview = content[:120] + '...' if len(content) > 120 else content

        # Tenta winotify primeiro (toast clicavel do Windows 10/11)
        if HAS_WINOTIFY:
            try:
                notif = WinNotification(
                    app_id='MB Chat',
                    title=name,
                    msg=preview,
                    icon=self._icon_path or '',
                )
                notif.launch = f'mbchat://open/{from_user}'
                notif.set_audio(wn_audio.Default, loop=False)
                notif.show()
                return
            except Exception:
                pass

        # Fallback: pystray balloon tip
        if self._tray_icon is not None:
            try:
                self._tray_icon.notify(preview, title=name)
                return
            except Exception:
                pass
        if HAS_TRAY and HAS_PIL:
            try:
                self._start_tray()
                if self._tray_icon is not None:
                    self._tray_icon.notify(preview, title=name)
            except Exception:
                pass

    def _on_close(self):
        """Minimiza para o system tray ao fechar (se disponivel)."""
        if HAS_TRAY and HAS_PIL:
            self.root.withdraw()
            self._start_tray()
        else:
            self._quit()

    def _quit(self):
        """Encerra o aplicativo completamente."""
        self._stop_tray()
        for w in list(self.chat_windows.values()):
            try:
                w.destroy()
            except Exception:
                pass
        self.messenger.stop()
        self.root.destroy()

    # --- System Tray ---
    def _start_tray(self):
        """Inicia o icone no system tray."""
        if self._tray_icon is not None:
            return
        if not HAS_TRAY or not HAS_PIL:
            return

        if self._icon_path:
            icon_image = Image.open(self._icon_path)
        else:
            icon_image = Image.new('RGBA', (64, 64), '#1a3a7a')

        menu = pystray.Menu(
            pystray.MenuItem('Abrir MB Chat', self._tray_show,
                             default=True),
            pystray.MenuItem('Sair', self._tray_quit),
        )
        self._tray_icon = pystray.Icon('mbchat', icon_image,
                                        APP_NAME, menu)
        threading.Thread(target=self._tray_icon.run, daemon=True).start()

    def _stop_tray(self):
        """Remove o icone do system tray."""
        if self._tray_icon is not None:
            try:
                self._tray_icon.stop()
            except Exception:
                pass
            self._tray_icon = None

    def _tray_show(self, icon=None, item=None):
        """Restaura a janela a partir do tray e abre chat da ultima notificacao."""
        peer = self._last_notif_peer
        self._last_notif_peer = None
        self.root.after(0, lambda: self._restore_and_open(peer))

    def _restore_and_open(self, peer=None):
        self.root.deiconify()
        self.root.state('normal')
        self.root.lift()
        self.root.focus_force()
        self.root.attributes('-topmost', True)
        self.root.after(200, lambda: self.root.attributes('-topmost', False))
        if peer and peer in self.peer_info and hasattr(self, 'messenger'):
            self._open_chat(peer)

    def _tray_quit(self, icon=None, item=None):
        """Encerra via menu do tray."""
        self.root.after(0, self._quit)

    def run(self):
        self.root.mainloop()


# =============================================================
def _format_size(size):
    if size < 1024:
        return f'{size} B'
    elif size < 1024**2:
        return f'{size/1024:.1f} KB'
    elif size < 1024**3:
        return f'{size/1024**2:.1f} MB'
    return f'{size/1024**3:.1f} GB'


def _setup_autostart():
    script = os.path.abspath(sys.argv[0])
    python = sys.executable
    if platform.system() == 'Windows':
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                r'Software\\Microsoft\\Windows\\CurrentVersion\\Run',
                0, winreg.KEY_SET_VALUE)
            winreg.SetValueEx(key, 'MBChat', 0, winreg.REG_SZ,
                              f'"{python}" "{script}" --silent')
            winreg.CloseKey(key)
        except Exception:
            pass
    elif platform.system() == 'Linux':
        d = os.path.expanduser('~/.config/autostart')
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, 'mbchat.desktop'), 'w') as f:
            f.write(f"[Desktop Entry]\nType=Application\nName={APP_NAME}\n"
                    f"Exec={python} {script} --silent\nHidden=false\n"
                    f"X-GNOME-Autostart-enabled=true\n")
    elif platform.system() == 'Darwin':
        d = os.path.expanduser('~/Library/LaunchAgents')
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, 'com.mbchat.plist'), 'w') as f:
            f.write(f'<?xml version="1.0" encoding="UTF-8"?>\n'
                    f'<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
                    f'"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
                    f'<plist version="1.0"><dict>'
                    f'<key>Label</key><string>com.mbchat</string>'
                    f'<key>ProgramArguments</key><array>'
                    f'<string>{python}</string><string>{script}</string>'
                    f'<string>--silent</string></array>'
                    f'<key>RunAtLoad</key><true/></dict></plist>')


def _remove_autostart():
    if platform.system() == 'Windows':
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                r'Software\\Microsoft\\Windows\\CurrentVersion\\Run',
                0, winreg.KEY_SET_VALUE)
            winreg.DeleteValue(key, 'MBChat')
            winreg.CloseKey(key)
        except Exception:
            pass
    elif platform.system() == 'Linux':
        p = os.path.expanduser('~/.config/autostart/mbchat.desktop')
        if os.path.exists(p):
            os.remove(p)
    elif platform.system() == 'Darwin':
        p = os.path.expanduser('~/Library/LaunchAgents/com.mbchat.plist')
        if os.path.exists(p):
            os.remove(p)


SINGLE_INSTANCE_PORT = 50199


def _register_url_protocol():
    """Registra o protocolo mbchat:// no Windows para notificacoes clicaveis."""
    if platform.system() != 'Windows':
        return
    try:
        import winreg
        if getattr(sys, 'frozen', False):
            exe_path = sys.executable
        else:
            exe_path = sys.executable
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                               r'Software\Classes\mbchat')
        winreg.SetValueEx(key, '', 0, winreg.REG_SZ, 'URL:MB Chat Protocol')
        winreg.SetValueEx(key, 'URL Protocol', 0, winreg.REG_SZ, '')
        icon_key = winreg.CreateKey(key, r'DefaultIcon')
        winreg.SetValueEx(icon_key, '', 0, winreg.REG_SZ, f'{exe_path},0')
        winreg.CloseKey(icon_key)
        cmd_key = winreg.CreateKey(key, r'shell\open\command')
        winreg.SetValueEx(cmd_key, '', 0, winreg.REG_SZ,
                          f'"{exe_path}" "%1"')
        winreg.CloseKey(cmd_key)
        winreg.CloseKey(key)
    except Exception:
        pass


def _check_single_instance():
    """Verifica se ja existe uma instancia rodando.
    Retorna True se esta e a unica instancia, False se ja existe outra."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.3)  # loopback e rapido, 300ms basta
        sock.connect(('127.0.0.1', SINGLE_INSTANCE_PORT))
        sock.sendall(b'SHOW')
        sock.close()
        return False  # Outra instancia ja existe
    except (ConnectionRefusedError, OSError, socket.timeout):
        return True  # Somos a primeira instancia


def _start_instance_listener(app):
    """Escuta por comandos de novas instancias."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        srv.bind(('127.0.0.1', SINGLE_INSTANCE_PORT))
    except OSError:
        return
    srv.listen(5)
    srv.settimeout(0.2)  # ciclo rapido para responder notificacoes

    def listen():
        while True:
            try:
                client, _ = srv.accept()
                data = client.recv(256).decode('utf-8', errors='ignore')
                client.close()
                if data.startswith('OPEN:'):
                    peer_id = data[5:].strip()
                    app.root.after(0, lambda p=peer_id: app._restore_and_open(p))
                elif data == 'SHOW':
                    app.root.after(0, app._restore_and_open)
            except socket.timeout:
                continue
            except OSError:
                break

    t = threading.Thread(target=listen, daemon=True)
    t.start()


def main():
    # Handle protocol activation: mbchat://open/PEER_ID
    for arg in sys.argv[1:]:
        if arg.startswith('mbchat://'):
            peer_id = ''
            if '/open/' in arg:
                peer_id = arg.split('/open/')[-1].strip('/')
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(0.5)  # loopback rapido
                sock.connect(('127.0.0.1', SINGLE_INSTANCE_PORT))
                cmd = f'OPEN:{peer_id}' if peer_id else 'SHOW'
                sock.sendall(cmd.encode())
                sock.close()
            except Exception:
                pass
            sys.exit(0)

    if not _check_single_instance():
        sys.exit(0)

    _register_url_protocol()

    silent = '--silent' in sys.argv or '--minimized' in sys.argv
    app = LanMessengerApp()
    _start_instance_listener(app)
    if silent:
        app.root.withdraw()
    app.run()


if __name__ == '__main__':
    main()
