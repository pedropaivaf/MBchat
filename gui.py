# MB Chat - Mensageiro de rede local
# Interface idêntica ao LAN Messenger original
#
# Este módulo é a camada de apresentação (View) do MB Chat.
# Responsável por todas as janelas, widgets, temas visuais, animações
# e interações com o usuário. Nunca acessa o banco de dados ou a rede
# diretamente — sempre passa pelo messenger.py (Controller).
#
# Fluxo: gui.py -> messenger.py -> network.py / database.py
import tkinter as tk                            # Biblioteca principal de GUI do Python
from tkinter import ttk, messagebox, filedialog, colorchooser  # Widgets avançados e diálogos
import tkinter.font as tkfont                   # Manipulação de fontes (diálogo de escolha de fonte)
import threading                                # Threads para envio de mensagens/arquivos sem travar a UI
import time                                     # Timestamps e cálculo de velocidade de transferência
import uuid                                     # Geração de IDs únicos
import os                                       # Operações de arquivo/diretório e variáveis de ambiente
import sys                                      # Para detectar se está rodando como .exe (PyInstaller)
import platform                                 # Para detectar Windows/Mac/Linux (sons de notificação)
import socket                                   # Suporte de rede (usado pelo messenger)
import shutil                                   # Copiar arquivo de avatar para pasta local
import hashlib                                  # Hash de arquivos
from datetime import datetime, timedelta        # Formatar timestamps das mensagens
import calendar as cal_mod                      # Gerar o grid de dias no mini-calendário popup
import logging                                  # Registrar erros em arquivo de log
import re                                       # Detectar emojis Unicode via expressão regular
import io                                       # BytesIO para compressao de imagens em memoria
import webbrowser                                # Abrir links clicaveis no browser padrao
from pathlib import Path                        # Manipulação de caminhos de forma moderna

# --- Logging ---
# Arquivo de log em %APPDATA%\MBChat\mbchat.log (Windows) ou ~/MBChat/mbchat.log
_log_path = os.path.join(
    os.environ.get('APPDATA', os.path.expanduser('~')),
    'MBChat', 'mbchat.log')
os.makedirs(os.path.dirname(_log_path), exist_ok=True)  # Cria a pasta se não existir
log = logging.getLogger('mbchat')                        # Logger nomeado deste módulo
log.setLevel(logging.DEBUG)                              # Captura DEBUG, INFO, WARNING, ERROR
_fh = logging.FileHandler(_log_path, encoding='utf-8')  # Grava em arquivo UTF-8
_fh.setLevel(logging.DEBUG)
_fh.setFormatter(logging.Formatter(
    '%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'))                        # Ex: "2024-01-15 09:30:00 [ERROR] ..."
log.addHandler(_fh)

# Camada de controle: orquestra rede, banco de dados e callbacks para a GUI
from messenger import Messenger
from version import APP_VERSION
import updater

# Pillow (PIL): suporte a avatares JPG/PNG e renderização de emojis coloridos.
# Sem PIL: avatares usam canvas simples (texto sobre círculo colorido) e emojis ficam como texto.
try:
    from PIL import Image, ImageTk, ImageGrab  # Image: manipulação; ImageTk: exibir no tkinter; ImageGrab: clipboard
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

# pystray: ícone e menu de contexto na bandeja do sistema (system tray do Windows)
try:
    import pystray
    HAS_TRAY = True
except ImportError:
    HAS_TRAY = False                        # Sem pystray: app roda sem ícone na bandeja

# winotify: notificações toast clicáveis do Windows 10/11.
# Clicar na notificação abre a janela de chat correspondente.
try:
    from winotify import Notification as WinNotification, audio as wn_audio
    HAS_WINOTIFY = True
except ImportError:
    HAS_WINOTIFY = False                    # Sem winotify: sem notificações nativas do Windows

# windnd: drag-and-drop de arquivos no Windows (arrastar arquivo para a janela)
try:
    import windnd
    HAS_WINDND = True
except ImportError:
    HAS_WINDND = False

APP_NAME = 'MB Chat'                        # Nome do aplicativo exibido nos títulos de janela

# Expressão regular para detectar emojis Unicode no texto das mensagens.
# Usada em _insert_text_with_emojis() para substituir cada emoji por uma imagem colorida
# renderizada via PIL com a fonte seguiemj.ttf (Segoe UI Emoji da Microsoft).
_EMOJI_RE = re.compile(
    r'(?:'
    r'[\U0001f600-\U0001f64f]'  # emoticons (rostos, pessoas, gestos)
    r'|[\U0001f300-\U0001f5ff]' # símbolos e pictogramas
    r'|[\U0001f680-\U0001f6ff]' # transporte e mapas
    r'|[\U0001f900-\U0001f9ff]' # símbolos suplementares
    r'|[\U0001fa00-\U0001faff]' # símbolos estendidos (chess, icons)
    r'|[\u2600-\u26ff]'          # símbolos miscelâneos (sol, lua, nuvem, etc.)
    r'|[\u2700-\u27bf]'          # dingbats (setas, tesouras, marcadores)
    r'|[\u231a-\u231b\u23e9-\u23ec\u23f0-\u23f3\u25fd\u25fe\u2614\u2615\u263a\u2648-\u2653\u2660\u2663\u2665\u2666\u2668\u267b\u267f\u2692-\u2694\u2696\u2697\u2699\u269b\u269c\u26a0\u26a1\u26aa\u26ab\u26b0\u26b1\u26bd\u26be\u26c4\u26c5\u26c8\u26ce\u26cf\u26d1\u26d3\u26d4\u26e9\u26ea\u26f0-\u26f5\u26f7-\u26fa\u26fd]'
    r')[\ufe00-\ufe0f\U0001f3fb-\U0001f3ff]?' # seletor de variação e tons de pele
)

# Detecta URLs em mensagens (http(s)://, www.)
_URL_RE = re.compile(
    r'(https?://[^\s<>"\'`]+|www\.[^\s<>"\'`]+)',
    re.IGNORECASE
)


# Abre uma URL no browser; normaliza www. para http://www.
def _open_url(url):
    # Remove pontuacao trailing (., ,, ), ], !, ?)
    while url and url[-1] in '.,);]!?':
        url = url[:-1]
    if not url:
        return
    if url.lower().startswith('www.'):
        url = 'http://' + url
    try:
        webbrowser.open(url, new=2)
    except Exception:
        log.exception('Erro ao abrir URL')

# --- Idiomas ---
# Dicionário de traduções para suporte a múltiplos idiomas.
# Cada chave é um ID de string; o valor é o texto traduzido para aquele idioma.
# Para adicionar um novo idioma: copie o bloco 'Português' e traduza os valores.
# Uso: _t('send_btn') retorna 'Enviar' em português ou 'Send' em inglês.
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
        'menu_check_update': 'Verificar atualizações',
        'update_available': 'Atualização v{ver} disponível',
        'update_btn': 'Atualizar',
        'update_later': 'Depois',
        'update_downloading': 'Baixando atualização...',
        'update_restarting': 'Atualização aplicada!\nReabra o MB Chat.',
        'update_failed': 'Falha ao baixar atualização.',
        'update_none': 'Você já está na versão mais recente.',
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
        'menu_check_update': 'Check for updates',
        'update_available': 'Update v{ver} available',
        'update_btn': 'Update',
        'update_later': 'Later',
        'update_downloading': 'Downloading update...',
        'update_restarting': 'Update applied!\\nPlease reopen MB Chat.',
        'update_failed': 'Failed to download update.',
        'update_none': 'You are on the latest version.',
    },
}

# Retorna a string traduzida para o idioma atual.
# Se a chave não existir no dicionário do idioma atual, retorna a própria chave
# como fallback (útil durante desenvolvimento para detectar chaves ausentes).
def _t(key):
    return _CURRENT_LANG.get(key, key)

# Idioma ativo no momento — alterado em PreferencesWindow._save_all()
_CURRENT_LANG = LANGS['Português']

# --- Fontes padrão do app ---
# Usadas em todos os widgets para manter consistência visual
FONT = ('Segoe UI', 9)             # Fonte padrão para labels e menus
FONT_BOLD = ('Segoe UI', 9, 'bold')  # Negrito para nomes e cabeçalhos
FONT_SMALL = ('Segoe UI', 8)       # Fonte menor para informações secundárias
FONT_CHAT = ('Segoe UI', 9)        # Fonte do chat (pode ser alterada pelo usuário em Fonte...)
FONT_SECTION = ('Segoe UI', 9, 'bold')  # Títulos de seção nas preferências

# --- Temas visuais ---
# Cada tema é um dicionário de cores nomeadas. A GUI consulta essas chaves para
# estilizar cada elemento. Trocar de tema chama app.apply_theme() que re-aplica
# as cores em todos os widgets abertos.
THEMES = {
    'Clássico': {
        'bg_window': '#f0f0f0',
        'bg_white': '#ffffff',
        'bg_header': '#e8e8e8',
        'bg_group': '#e0e0e0',
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
        'fg_group': '#555555',
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
        'chat_header_bg': '#e8e8e8',
        'chat_header_fg': '#000000',
        'chat_header_sub': '#666666',
        'btn_send_bg': '#3366aa',
        'btn_send_fg': '#ffffff',
        'btn_flat_fg': '#666666',
        'input_border': '#bbbbbb',
        'avatar_border': '#3366aa',
    },
    'Night Mode': {
        'bg_window': '#1e1e1e',
        'bg_white': '#2d2d2d',
        'bg_header': '#333333',
        'bg_group': '#3a3a3a',
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
        'fg_group': '#c0c0c0',
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
        'chat_header_bg': '#333333',
        'chat_header_fg': '#e0e0e0',
        'chat_header_sub': '#888888',
        'btn_send_bg': '#3a5070',
        'btn_send_fg': '#f0f0f0',
        'btn_flat_fg': '#888888',
        'input_border': '#444444',
        'avatar_border': '#6ca8e0',
    },
    'MB Contabilidade': {
        'bg_window': '#f5f7fa',
        'bg_white': '#ffffff',
        'bg_header': '#0f2a5c',
        'bg_group': '#e2e2e2',
        'bg_select': '#e8f0fe',
        'bg_input': '#f7fafc',
        'bg_chat': '#f5f7fa',
        'fg_black': '#1a202c',
        'fg_gray': '#718096',
        'fg_white': '#ffffff',
        'fg_blue': '#0f2a5c',
        'fg_green': '#48bb78',
        'fg_red': '#cc2222',
        'fg_orange': '#ecc94b',
        'fg_group': '#4a5568',
        'fg_msg': '#1a202c',
        'fg_time': '#718096',
        'fg_my_name': '#0f2a5c',
        'fg_peer_name': '#cc2222',
        'btn_bg': '#0f2a5c',
        'btn_fg': '#ffffff',
        'btn_active': '#1a3f7a',
        'border': '#e2e8f0',
        'statusbar_bg': '#f5f7fa',
        'statusbar_fg': '#718096',
        # Novas chaves do redesign
        'msg_my_bg': '#e8f0fe',
        'msg_peer_bg': '#f0f0f0',
        'hover': '#edf2f7',
        'accent': '#0f2a5c',
        'online': '#48bb78',
        'away': '#ecc94b',
        'busy': '#f56565',
        'offline_color': '#a0aec0',
        'btn_send_bg': '#0f2a5c',
        'btn_send_fg': '#ffffff',
        'btn_flat_fg': '#718096',
        'chat_header_bg': '#0f2a5c',
        'chat_header_fg': '#ffffff',
        'chat_header_sub': '#8aa0cc',
        'input_border': '#e2e8f0',
        'avatar_border': '#0f2a5c',
        'select_border': '#0f2a5c',
    },
}

# --- Cores padrão globais ---
# Usadas como fallback quando nenhum tema está ativo (ex: na inicialização).
# O método app.apply_theme() sobrescreve essas variáveis globais com as cores do tema escolhido.
BG_WINDOW = '#f0f0f0'   # Fundo da janela principal
BG_WHITE = '#ffffff'    # Fundo de áreas de conteúdo (chat, listas)
BG_HEADER = '#e8e8e8'   # Fundo do cabeçalho/toolbar
BG_GROUP = '#3366aa'    # Cor de fundo dos grupos no TreeView (azul navy)
BG_SELECT = '#cce8ff'   # Cor de seleção no TreeView (azul claro)
FG_BLACK = '#000000'    # Texto principal
FG_GRAY = '#666666'     # Texto secundário/dicas
FG_WHITE = '#ffffff'    # Texto sobre fundo escuro
FG_BLUE = '#0066cc'     # Links e destaque azul
FG_GREEN = '#008800'    # Indicador online / confirmação
FG_RED = '#cc0000'      # Alertas de erro / nome do peer no chat
FG_ORANGE = '#cc8800'   # Avisos (status "ausente", aguardando, etc.)

# Tooltip minimalista (balão de dica) exibido ao passar o mouse sobre um widget.
# Cria uma janela Toplevel sem decoração, posicionada acima do widget.
# Destruída automaticamente quando o mouse sai.
class _Tooltip:
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        # _tip guarda a referência à janela; None = tooltip oculto
        self._tip = None
        # Vincula os eventos de entrar/sair do mouse
        widget.bind('<Enter>', self._show, add='+')
        widget.bind('<Leave>', self._hide, add='+')

    # Cria e exibe a janela do tooltip acima do widget.
    def _show(self, event=None):
        if self._tip:
            # Evita criar duplicata se já está visível
            return
        # Calcula posição: centro horizontal do widget, 28px acima do topo
        x = self.widget.winfo_rootx() + self.widget.winfo_width() // 2
        y = self.widget.winfo_rooty() - 28
        self._tip = tw = tk.Toplevel(self.widget)
        # Remove barra de título e bordas da janela (aparência de popup flutuante)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f'+{x}+{y}')
        tw.configure(bg='#1a202c')
        tk.Label(tw, text=self.text, font=('Segoe UI', 8),
                 bg='#1a202c', fg='#ffffff', padx=6, pady=3).pack()

    # Destrói a janela do tooltip ao sair com o mouse.
    def _hide(self, event=None):
        if self._tip:
            self._tip.destroy()
            self._tip = None


# Configura o estilo visual das scrollbars ttk para todo o app.
# Cria dois estilos personalizados ('Clean.Vertical.TScrollbar' e
# 'Clean.Horizontal.TScrollbar') com aparência minimalista: sem setas,
# thumb fino de 6px, cores suaves que combinam com todos os temas.
# Chamado uma única vez na inicialização antes de criar qualquer janela.
def _setup_scrollbar_style():
    style = ttk.Style()
    # --- Scrollbar vertical minimalista (sem setas, thumb de 6px) ---
    style.configure('Clean.Vertical.TScrollbar',
                    background='#cbd5e0', troughcolor='#f5f7fa',
                    borderwidth=0, relief='flat', width=6,
                    arrowsize=0)
    # Muda a cor do thumb ao passar o mouse (active) e ao clicar (pressed)
    style.map('Clean.Vertical.TScrollbar',
              background=[('active', '#a0aec0'), ('pressed', '#718096')])
    # Remove completamente as setas — layout contém apenas o trilho e o thumb
    style.layout('Clean.Vertical.TScrollbar',
                 [('Vertical.Scrollbar.trough',
                   {'children': [('Vertical.Scrollbar.thumb',
                                  {'expand': '1', 'sticky': 'nswe'})],
                    'sticky': 'ns'})])
    # --- Scrollbar horizontal (mesmo estilo, direção diferente) ---
    style.configure('Clean.Horizontal.TScrollbar',
                    background='#cbd5e0', troughcolor='#f5f7fa',
                    borderwidth=0, relief='flat', width=6,
                    arrowsize=0)
    style.map('Clean.Horizontal.TScrollbar',
              background=[('active', '#a0aec0'), ('pressed', '#718096')])
    style.layout('Clean.Horizontal.TScrollbar',
                 [('Horizontal.Scrollbar.trough',
                   {'children': [('Horizontal.Scrollbar.thumb',
                                  {'expand': '1', 'sticky': 'nswe'})],
                    'sticky': 'we'})])


# Recorta uma imagem para formato circular com anti-aliasing de alta qualidade.
# Técnica de superamostragem: renderiza em resolução 2x (antialias=2) e depois
# reduz — produz bordas suaves sem serrilhamento. O resultado é RGBA com fundo
# transparente; os pixels fora do círculo são completamente transparentes.
# Args:
#     img_or_path: Caminho (str) para arquivo de imagem OU objeto PIL.Image já aberto.
# Captura imagem do clipboard com fallback robusto para Win10.
# PIL ImageGrab.grabclipboard() pode falhar no Win10 (retorna None ou lista de paths).
# Fallback: acessa CF_DIB via ctypes (win32 API) para capturar screenshots.
def _grab_clipboard_image():
    if not HAS_PIL:
        return None
    # Tentativa 1: PIL ImageGrab (funciona na maioria dos casos)
    try:
        clip = ImageGrab.grabclipboard()
        if clip is not None:
            if isinstance(clip, Image.Image):
                log.debug('Clipboard: PIL ImageGrab retornou Image %s', clip.size)
                return clip
            # Win10: pode retornar lista de file paths
            if isinstance(clip, list):
                for p in clip:
                    if isinstance(p, str) and os.path.isfile(p):
                        try:
                            img = Image.open(p)
                            log.debug('Clipboard: PIL abriu arquivo %s', p)
                            return img
                        except Exception:
                            continue
        log.debug('Clipboard: PIL ImageGrab retornou %s', type(clip))
    except Exception as e:
        log.debug('Clipboard: PIL ImageGrab falhou: %s', e)
    # Tentativa 2: win32 clipboard via ctypes
    try:
        import ctypes, struct
        u32 = ctypes.windll.user32
        k32 = ctypes.windll.kernel32
        # Tenta CF_DIBV5 primeiro (mais completo), depois CF_DIB
        for cf_fmt in (17, 8):
            if not u32.OpenClipboard(0):
                log.debug('Clipboard: OpenClipboard falhou')
                return None
            try:
                if not u32.IsClipboardFormatAvailable(cf_fmt):
                    continue
                h = u32.GetClipboardData(cf_fmt)
                if not h:
                    continue
                k32.GlobalLock.restype = ctypes.c_void_p
                ptr = k32.GlobalLock(h)
                if not ptr:
                    continue
                try:
                    size = k32.GlobalSize(h)
                    if size < 40:
                        continue
                    dib_data = ctypes.string_at(ptr, size)
                    hdr_size = struct.unpack_from('<I', dib_data, 0)[0]
                    bpp = struct.unpack_from('<H', dib_data, 14)[0]
                    if bpp <= 8:
                        clr_used = struct.unpack_from('<I', dib_data, 32)[0]
                        if clr_used == 0:
                            clr_used = 1 << bpp
                        palette_size = clr_used * 4
                    else:
                        palette_size = 0
                    pixel_offset = 14 + hdr_size + palette_size
                    file_size = 14 + size
                    bmp_header = struct.pack('<2sIHHI', b'BM', file_size, 0, 0, pixel_offset)
                    bmp_data = bmp_header + dib_data
                    img = Image.open(io.BytesIO(bmp_data))
                    log.debug('Clipboard: ctypes CF_%d ok, size=%s', cf_fmt, img.size)
                    return img
                finally:
                    k32.GlobalUnlock(h)
            finally:
                u32.CloseClipboard()
    except Exception as e:
        log.debug('Clipboard: ctypes falhou: %s', e)
    log.debug('Clipboard: nenhuma imagem encontrada')
    return None

#     size: Tamanho final do avatar em pixels (quadrado NxN).
#     antialias: Fator de superamostragem (2 = dobro da resolução final).
# Returns:
#     PIL.Image RGBA com o avatar circular, ou None se PIL não estiver disponível.
def _make_circular_avatar(img_or_path, size=36, antialias=2):
    if not HAS_PIL:
        return None
    from PIL import ImageDraw
    if isinstance(img_or_path, str):
        img = Image.open(img_or_path)
    else:
        img = img_or_path
    img = img.convert('RGBA')
    w, h = img.size
    # Recorta para quadrado centralizado usando o menor lado
    s = min(w, h)
    left = (w - s) // 2
    top = (h - s) // 2
    img = img.crop((left, top, left + s, top + s))
    # Redimensiona para resolução 2x antes de aplicar a máscara circular
    big = size * antialias
    img = img.resize((big, big), Image.LANCZOS)
    # Cria máscara circular: branco (255) dentro do círculo, preto (0) fora
    mask = Image.new('L', (big, big), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, big - 1, big - 1], fill=255)
    # Aplica máscara como canal alpha — área fora do círculo = transparente
    img.putalpha(mask)
    # Reduz para o tamanho final com LANCZOS (melhor algoritmo para redução)
    img = img.resize((size, size), Image.LANCZOS)
    return img


# Cria um ícone da fonte Segoe MDL2 Assets como PhotoImage tkinter.
# Versão module-level (sem self) usada fora de classes, por exemplo na janela
# principal. Para uso dentro de classes, use o método _create_mdl2_icon() da classe.
# A fonte segmdl2.ttf contém ícones vetoriais nativos do Windows (codepoints Unicode
# especiais). O ícone é renderizado em 4x a resolução final e depois reduzido com
# LANCZOS para garantir nitidez em qualquer DPI.
# Args:
#     char: Caractere Unicode do ícone (ex: '\uE81C' = Histórico, '\uE723' = Clipe).
#     size: Tamanho final em pixels (quadrado NxN).
#     color: Cor do ícone em formato hex '#rrggbb'.
# Returns:
#     ImageTk.PhotoImage pronto para uso em Button/Label, ou None em caso de erro.
def _create_mdl2_icon_static(char, size=18, color='#718096'):
    try:
        from PIL import ImageDraw, ImageFont
        # Tenta a fonte MDL2 padrão; fallback para SegoeIcons se não encontrar
        font_path = 'C:/Windows/Fonts/segmdl2.ttf'
        if not os.path.exists(font_path):
            font_path = 'C:/Windows/Fonts/SegoeIcons.ttf'
        if not os.path.exists(font_path):
            return None
        # Superamostragem 4x para bordas nítidas
        s = size * 4
        font = ImageFont.truetype(font_path, s - 4)
        img = Image.new('RGBA', (s, s), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        # Calcula bounding box do glifo para centralizar perfeitamente
        bbox = draw.textbbox((0, 0), char, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        x = (s - tw) // 2 - bbox[0]
        y = (s - th) // 2 - bbox[1]
        # Converte cor hex para tupla RGB
        r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
        draw.text((x, y), char, font=font, fill=(r, g, b, 255))
        img = img.resize((size, size), Image.LANCZOS)
        return ImageTk.PhotoImage(img)
    except Exception:
        return None


# --- Cores padrão para avatares gerados automaticamente ---
# Lista de 12 cores distintas usadas quando o contato não tem foto personalizada.
# Cada tupla é (cor_hex, letra_padrão). A letra inicial do nome é desenhada sobre
# um círculo colorido (a segunda string 'U' é legado — não é mais usada diretamente).
AVATAR_COLORS = [
    ('#4488cc', 'U'), ('#44aa44', 'U'), ('#cc4444', 'U'),
    ('#aa44aa', 'U'), ('#cc8844', 'U'), ('#44aaaa', 'U'),
    ('#6666cc', 'U'), ('#88aa44', 'U'), ('#cc44aa', 'U'),
    ('#4488aa', 'U'), ('#aa8844', 'U'), ('#44aa88', 'U'),
]


# Retorna o caminho absoluto do arquivo mbchat.ico, compatível com PyInstaller.
# Quando o app é empacotado como .exe pelo PyInstaller, os assets ficam em
# sys._MEIPASS (pasta temporária). Em desenvolvimento, ficam em assets/ ao
# lado do script. Tenta ambos os caminhos para garantir compatibilidade.
def _get_icon_path():
    if getattr(sys, 'frozen', False):
        # Rodando como executável PyInstaller — assets em pasta temporária
        base = sys._MEIPASS
    else:
        # Rodando em desenvolvimento — assets na mesma pasta do script
        base = os.path.dirname(os.path.abspath(__file__))
    ico = os.path.join(base, 'assets', 'mbchat.ico')
    if os.path.exists(ico):
        return ico
    ico = os.path.join(base, 'mbchat.ico')
    if os.path.exists(ico):
        return ico
    return None


# Adiciona efeito hover (mudança de cor ao passar o mouse) a qualquer widget.
# Os botões tk.Button não têm hover nativo como os ttk.Button. Esta função
# simula o efeito vinculando os eventos <Enter> e <Leave> para trocar as cores.
# Args:
#     widget: Qualquer widget tkinter (Button, Label, Frame, etc.).
#     normal_bg: Cor de fundo quando o mouse está fora.
#     hover_bg: Cor de fundo quando o mouse está sobre o widget.
#     normal_fg: Cor do texto normal (None = não altera texto).
#     hover_fg: Cor do texto no hover (None = não altera texto).
def _add_hover(widget, normal_bg, hover_bg, normal_fg=None, hover_fg=None):
    def on_enter(e):
        widget.config(bg=hover_bg)
        if hover_fg:
            widget.config(fg=hover_fg)

    def on_leave(e):
        widget.config(bg=normal_bg)
        if normal_fg:
            widget.config(fg=normal_fg)

    widget.bind('<Enter>', on_enter)
    widget.bind('<Leave>', on_leave)


# Renderiza um emoji Unicode como imagem colorida via PIL (versão module-level).
# Usa a fonte seguiemj.ttf (Segoe UI Emoji) do Windows com suporte a cores COLR/CPAL.
# O parâmetro embedded_color=True instrui o PIL a usar as camadas de cor do glifo.
# Versão de módulo para uso fora de classes. Dentro de ChatWindow/GroupChatWindow,
# use _render_emoji_image() (método de instância com cache automático por janela).
# Args:
#     emoji_char: Caractere emoji Unicode (ex: '😀', '❤️').
#     size: Tamanho da imagem em pixels.
# Returns:
#     ImageTk.PhotoImage pronto para uso em tkinter, ou None se não disponível.
def _render_color_emoji(emoji_char, size=28):
    if not HAS_PIL:
        return None
    try:
        from PIL import ImageFont, ImageDraw
        font_path = 'C:/Windows/Fonts/seguiemj.ttf'
        if not os.path.exists(font_path):
            return None
        # Strip variation selector para bbox consistente (renderiza igual sem ele)
        clean = emoji_char.replace('\ufe0f', '')
        font = ImageFont.truetype(font_path, size)
        # Canvas temporário maior para medir o tamanho real do glifo
        tmp = Image.new('RGBA', (size * 3, size * 3), (255, 255, 255, 0))
        d = ImageDraw.Draw(tmp)
        bbox = d.textbbox((0, 0), clean, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        # Canvas final quadrado baseado no tamanho desejado
        canvas_sz = size + 4
        img = Image.new('RGBA', (canvas_sz, canvas_sz), (255, 255, 255, 0))
        draw = ImageDraw.Draw(img)
        x = (canvas_sz - tw) // 2 - bbox[0]
        y = (canvas_sz - th) // 2 - bbox[1]
        # embedded_color=True ativa renderização colorida (COLR/CPAL da fonte)
        draw.text((x, y), clean, font=font, embedded_color=True)
        return ImageTk.PhotoImage(img)
    except Exception:
        return None


# Função utilitária: varre um widget tk.Text e substitui TODOS os emojis Unicode
# por imagens coloridas renderizadas via PIL. Usada em todas as janelas de entrada
# (ChatWindow, GroupChatWindow, Broadcast) para garantir que emojis digitados,
# colados ou inseridos por atalhos do Windows (Win+.) apareçam sempre coloridos.
#
# Usa text_widget.dump() para obter posições exatas de cada segmento de texto,
# ignorando imagens já embutidas. Processa de trás para frente (reversed) para
# que a substituição de um emoji não invalide os índices dos emojis anteriores.
#
# Args:
#     text_widget: Widget tk.Text a ser varrido.
#     emoji_cache: Dict para cache de imagens (evita re-renderizar).
#     img_map: Dict que mapeia img_name -> emoji_char para reconstrução do texto.
#     prefix: Prefixo do nome da imagem (para evitar colisão entre janelas).
#     size: Tamanho do emoji em pixels.
def _scan_entry_emojis(text_widget, emoji_cache, img_map, prefix='emoji', size=18):
    """Varre o widget Text e substitui caracteres emoji por imagens coloridas."""
    if not HAS_PIL:
        return

    # Coleta todas as posições de emojis a serem substituídos
    replacements = []  # [(tk_index, emoji_char), ...]

    try:
        # dump() retorna (tipo, valor, índice) para cada elemento do widget.
        # 'text' = segmento de texto puro com seu índice tkinter exato.
        # Imagens já embutidas são retornadas como 'image' e são ignoradas.
        for item_type, value, index in text_widget.dump('1.0', 'end', text=True):
            if item_type != 'text' or not value:
                continue
            # Procura emojis dentro deste segmento de texto
            for match in _EMOJI_RE.finditer(value):
                emoji_char = match.group()
                char_offset = match.start()
                # Índice tkinter exato: posição do segmento + offset do match
                emoji_idx = f'{index}+{char_offset}c'
                replacements.append((emoji_idx, emoji_char))
    except Exception:
        return

    if not replacements:
        return

    # Processa de trás para frente para manter os índices válidos
    for idx, emoji_char in reversed(replacements):
        # Renderiza ou busca do cache
        if emoji_char in emoji_cache:
            img = emoji_cache[emoji_char]
        else:
            img = _render_color_emoji(emoji_char, size)
            if img:
                emoji_cache[emoji_char] = img

        if img:
            try:
                end_idx = f'{idx}+{len(emoji_char)}c'
                text_widget.delete(idx, end_idx)
                img_name = f'{prefix}_{len(img_map)}'
                img_map[img_name] = emoji_char
                text_widget.image_create(idx, image=img, name=img_name, padx=1)
            except Exception:
                pass

# Centraliza uma janela na tela.
def _center_window(win, w, h):
    win.update_idletasks()
    sx = win.winfo_screenwidth()
    sy = win.winfo_screenheight()
    x = (sx - w) // 2
    y = (sy - h) // 2
    win.geometry(f'{w}x{h}+{x}+{y}')


# Aplica bordas levemente arredondadas em uma janela via API DWM do Windows 11+.
# Usa ctypes para chamar DwmSetWindowAttribute() com DWMWA_WINDOW_CORNER_PREFERENCE=2
# (DWMWCP_ROUND). No Windows 10 ou anterior, a API não existe e a exceção é silenciada.
# Deve ser chamado após _center_window() em toda janela Toplevel criada no app.
def _apply_rounded_corners(win):
    try:
        import ctypes
        DWMWA_WINDOW_CORNER_PREFERENCE = 33
        DWMWCP_ROUND = 2
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_WINDOW_CORNER_PREFERENCE,
            ctypes.byref(ctypes.c_int(DWMWCP_ROUND)), 4)
    except Exception:
        pass  # Windows 10 ou anterior — API não disponível, ignorar silenciosamente


# Libera WM_DROPFILES atraves do filtro UIPI para permitir drop do Explorer
# mesmo quando os integrity levels entre processos diferem (Win7+).
# Aplica tanto no HWND filho (winfo_id) quanto no top-level pai — Explorer
# envia WM_DROPFILES para o top-level e windnd pode subclassar o filho.
# Tambem garante DragAcceptFiles(TRUE) em ambos via shell32.
def _allow_uipi_drop(widget):
    if platform.system() != 'Windows':
        return
    try:
        import ctypes
        user32 = ctypes.windll.user32
        shell32 = ctypes.windll.shell32
        MSGFLT_ALLOW = 1
        child = widget.winfo_id()
        parent = user32.GetParent(child) or child
        ancestor = user32.GetAncestor(child, 2) or parent  # GA_ROOT
        seen = set()
        for hwnd in (child, parent, ancestor):
            if not hwnd or hwnd in seen:
                continue
            seen.add(hwnd)
            for msg in (0x0233, 0x004A, 0x0049):
                try:
                    user32.ChangeWindowMessageFilterEx(hwnd, msg, MSGFLT_ALLOW, None)
                except Exception:
                    pass
            try:
                shell32.DragAcceptFiles(hwnd, True)
            except Exception:
                pass
    except Exception:
        pass



# Formata automaticamente um campo de entrada como dd/mm/aaaa durante a digitação.
# Intercepta cada tecla liberada, extrai apenas os dígitos e reinsere o texto
# formatado com as barras nos lugares corretos. Teclas de navegação são ignoradas
# para não interferir com BackSpace, setas, etc.
def _bind_date_mask(entry, var):
    def on_key(event):
        if event.keysym in ('BackSpace', 'Delete', 'Left', 'Right',
                            'Home', 'End', 'Tab'):
            return
        val = var.get()
        digits = ''.join(c for c in val if c.isdigit())
        digits = digits[:8]  # máximo de 8 dígitos (ddmmaaaa)
        formatted = ''
        for i, d in enumerate(digits):
            if i == 2 or i == 4:
                formatted += '/'
            formatted += d
        if formatted != val:
            cursor = entry.index('insert')
            var.set(formatted)
            new_pos = min(cursor + (len(formatted) - len(val)), len(formatted))
            entry.icursor(new_pos)
    entry.bind('<KeyRelease>', on_key)


# Exibe um mini-calendário popup para seleção de data.
#
# Posicionado abaixo do campo de data (entry_widget). Permite navegar entre
# meses com botões < > e clicar em um dia para preencher date_var com dd/mm/aaaa.
# Fecha ao clicar em Escape ou ao perder o foco.
def _show_calendar(parent, date_var, entry_widget):
    popup = tk.Toplevel(parent)
    popup.overrideredirect(True)
    popup.configure(bg='#333333', bd=1, relief='solid')

    # Position below the entry
    x = entry_widget.winfo_rootx()
    y = entry_widget.winfo_rooty() + entry_widget.winfo_height() + 2
    popup.geometry(f'+{x}+{y}')

    # Current date or parse from entry
    try:
        d = datetime.strptime(date_var.get(), '%d/%m/%Y')
        cur_year, cur_month = d.year, d.month
    except (ValueError, AttributeError):
        now = datetime.now()
        cur_year, cur_month = now.year, now.month

    state = {'year': cur_year, 'month': cur_month}

    def draw_calendar():
        for w in cal_frame.winfo_children():
            w.destroy()
        yr, mn = state['year'], state['month']

        # Header: < Month Year >
        hdr = tk.Frame(cal_frame, bg='#333333')
        hdr.pack(fill='x')
        tk.Button(hdr, text='\u25c0', font=('Segoe UI', 8), bg='#333333',
                  fg='white', relief='flat', bd=0, cursor='hand2',
                  command=lambda: nav(-1)).pack(side='left', padx=4)
        months_pt = ['', 'Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun',
                     'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez']
        tk.Label(hdr, text=f'{months_pt[mn]} {yr}', font=('Segoe UI', 9, 'bold'),
                 bg='#333333', fg='white').pack(side='left', expand=True)
        tk.Button(hdr, text='\u25b6', font=('Segoe UI', 8), bg='#333333',
                  fg='white', relief='flat', bd=0, cursor='hand2',
                  command=lambda: nav(1)).pack(side='right', padx=4)

        # Day names
        days_row = tk.Frame(cal_frame, bg='#333333')
        days_row.pack(fill='x')
        for dn in ['Se', 'Te', 'Qu', 'Qu', 'Se', 'Sa', 'Do']:
            tk.Label(days_row, text=dn, font=('Segoe UI', 7), bg='#333333',
                     fg='#aaaaaa', width=3).pack(side='left')

        # Days grid
        today = datetime.now()
        matrix = cal_mod.monthcalendar(yr, mn)
        for week in matrix:
            row = tk.Frame(cal_frame, bg='#333333')
            row.pack(fill='x')
            for day in week:
                if day == 0:
                    tk.Label(row, text='', width=3, bg='#333333').pack(side='left')
                else:
                    is_today = (day == today.day and mn == today.month
                                and yr == today.year)
                    bg = '#0066cc' if is_today else '#333333'
                    fg = 'white'
                    btn = tk.Label(row, text=str(day), font=('Segoe UI', 8),
                                   bg=bg, fg=fg, width=3, cursor='hand2',
                                   relief='flat')
                    btn.pack(side='left')
                    btn.bind('<Button-1>',
                             lambda e, d=day: select(d))
                    btn.bind('<Enter>',
                             lambda e, b=btn: b.configure(bg='#0055aa'))
                    btn.bind('<Leave>',
                             lambda e, b=btn, bg_=bg: b.configure(bg=bg_))

    # Avança ou recua um mês no calendário e redesenha o grid.
    def nav(delta):
        state['month'] += delta
        if state['month'] > 12:
            state['month'] = 1
            state['year'] += 1
        elif state['month'] < 1:
            state['month'] = 12
            state['year'] -= 1
        draw_calendar()

    # Preenche o campo de data com o dia selecionado e fecha o popup.
    def select(day):
        date_var.set(f'{day:02d}/{state["month"]:02d}/{state["year"]}')
        popup.destroy()

    cal_frame = tk.Frame(popup, bg='#333333', padx=4, pady=4)
    cal_frame.pack()
    draw_calendar()

    popup.focus_set()
    popup.bind('<Escape>', lambda e: popup.destroy())
    # Fecha o calendário ao perder foco (aguarda 100ms para evitar falso positivo)
    popup.bind('<FocusOut>', lambda e: popup.after(100, lambda: (
        popup.destroy() if popup.winfo_exists() and
        popup.focus_get() not in (popup,) + tuple(
            popup.winfo_children()) else None)))


# Retorna o diretório de dados do app, criando-o se necessário.
# Windows: %APPDATA%\.mbchat
# Outros:  ~/.mbchat
def _get_data_dir():
    if os.name == 'nt':
        base = os.environ.get('APPDATA', os.path.expanduser('~'))
    else:
        base = os.path.expanduser('~')
    d = os.path.join(base, '.mbchat')
    os.makedirs(d, exist_ok=True)
    return d


# Retorna o diretório de avatares personalizados, dentro do diretório de dados.
def _get_avatars_dir():
    d = os.path.join(_get_data_dir(), 'avatars')
    os.makedirs(d, exist_ok=True)
    return d


# Reproduz sons de notificação usando a API nativa de cada sistema operacional.
# Usa winsound no Windows (sons do sistema), afplay no macOS e paplay no Linux.
# Todos os métodos são estáticos — não precisam de instância.
class SoundPlayer:
    # Referencia ao banco, setada pelo app no startup para ler settings
    db = None

    @staticmethod
    def _gate(key):
        # Master off bloqueia tudo; gate especifico bloqueia o som individual
        try:
            if SoundPlayer.db is None:
                return True  # fallback: toca se nao conectado ao db
            if SoundPlayer.db.get_setting('sound_master', '1') != '1':
                return False
            return SoundPlayer.db.get_setting(key, '1') == '1'
        except Exception:
            return True

    @staticmethod
    def _beep(tone='info'):
        try:
            if platform.system() == 'Windows':
                import winsound
                if tone == 'ok':
                    winsound.MessageBeep(winsound.MB_OK)
                else:
                    winsound.MessageBeep(winsound.MB_ICONINFORMATION)
            elif platform.system() == 'Darwin':
                os.system('afplay /System/Library/Sounds/Ping.aiff &')
            else:
                os.system('paplay /usr/share/sounds/freedesktop/stereo/'
                          'message-new-instant.oga 2>/dev/null &')
        except Exception:
            pass

    @staticmethod
    def play_msg_private():
        if SoundPlayer._gate('sound_msg_private'):
            SoundPlayer._beep('info')

    @staticmethod
    def play_msg_group():
        if SoundPlayer._gate('sound_msg_group'):
            SoundPlayer._beep('info')

    @staticmethod
    def play_msg_broadcast():
        if SoundPlayer._gate('sound_msg_broadcast'):
            SoundPlayer._beep('info')

    @staticmethod
    def play_file_start():
        if SoundPlayer._gate('sound_file_start'):
            SoundPlayer._beep('info')

    @staticmethod
    def play_file_done():
        if SoundPlayer._gate('sound_file_done'):
            SoundPlayer._beep('ok')

    @staticmethod
    def play_reminder():
        if SoundPlayer._gate('sound_reminder'):
            SoundPlayer._beep('info')

    # Compat: chamadas antigas ainda funcionam (mapeia pra msg_private)
    @staticmethod
    def play_notification():
        SoundPlayer.play_msg_private()

    @staticmethod
    def play_connect():
        try:
            if SoundPlayer.db is not None:
                if SoundPlayer.db.get_setting('sound_master', '1') != '1':
                    return
            if platform.system() == 'Windows':
                import winsound
                winsound.MessageBeep(winsound.MB_OK)
        except Exception:
            pass


# =============================================================
#  PREFERENCES WINDOW — Idêntica ao original
# =============================================================
# Janela de Preferências completa com navegação lateral por categorias.
# Layout: sidebar esquerda (lista de categorias) + área direita (conteúdo da
# categoria selecionada). Cada categoria é construída dinamicamente pelos métodos
# _build_*() quando o usuário clica nela. As configurações são salvas no banco
# de dados via messenger.db.set_setting() ao clicar em OK (_save_all).
# Categorias disponíveis: Geral, Conta, Mensagens, Histórico, Alertas,
# Rede, Transferência de arq., Aparência, Teclas de atalho.
class PreferencesWindow(tk.Toplevel):

    def __init__(self, app, initial_tab=0):
        super().__init__(app.root)
        self.app = app
        self.messenger = app.messenger
        self.title('Preferências')
        self.resizable(False, False)
        self.transient(app.root)    # Janela filho da janela principal
        self.grab_set()             # Modal: bloqueia interação com outras janelas
        self.configure(bg=BG_WINDOW)
        self.bind('<Escape>', lambda e: self.destroy())

        _center_window(self, 580, 450)
        _apply_rounded_corners(self)

        # --- Main layout: top area (left+right) and bottom buttons ---
        top = tk.Frame(self, bg=BG_WINDOW)
        top.pack(fill='both', expand=True, padx=6, pady=(6, 0))

        # Left sidebar
        left = tk.Frame(top, bg='#f8fafc', width=160, bd=0, relief='flat',
                        highlightthickness=1, highlightbackground='#e2e8f0')
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
                            bg='#f8fafc', fg='#334155', relief='flat', bd=0,
                            padx=8, pady=6, cursor='hand2',
                            activebackground='#e2e8f0',
                            command=lambda idx=i: self._select_category(idx))
            btn.pack(fill='x')
            _add_hover(btn, '#f8fafc', '#e2e8f0')
            self.cat_buttons.append(btn)

        # --- Bottom buttons (outside top, guaranteed visible) ---
        bottom = tk.Frame(self, bg=BG_WINDOW)
        bottom.pack(fill='x', padx=10, pady=8)

        btn_cancel = tk.Button(bottom, text='Cancelar',
                               font=('Segoe UI', 9),
                               bg='#e2e8f0', fg='#4a5568', relief='flat',
                               bd=0, padx=14, pady=4, cursor='hand2',
                               activebackground='#cbd5e0',
                               command=self.destroy)
        btn_cancel.pack(side='right', padx=4)
        _add_hover(btn_cancel, '#e2e8f0', '#cbd5e0')

        btn_ok = tk.Button(bottom, text='OK',
                           font=('Segoe UI', 9, 'bold'),
                           bg='#0f2a5c', fg='#ffffff', relief='flat',
                           bd=0, padx=14, pady=4, cursor='hand2',
                           activebackground='#1a3f7a',
                           activeforeground='#ffffff',
                           command=self._save_all)
        btn_ok.pack(side='right', padx=4)
        _add_hover(btn_ok, '#0f2a5c', '#1a3f7a')

        btn_reset = tk.Button(bottom, text='Redefinir Preferências',
                              font=('Segoe UI', 8),
                              bg='#f5f7fa', fg='#94a3b8', relief='flat',
                              bd=0, padx=8, pady=4, cursor='hand2',
                              activebackground='#e2e8f0',
                              command=self._reset_defaults)
        btn_reset.pack(side='left', padx=4)
        _add_hover(btn_reset, '#f5f7fa', '#e2e8f0')

        # Settings vars
        self._init_vars()

        # Select initial tab
        self._select_category(initial_tab)

    # Inicializa todas as variáveis tkinter com os valores salvos no banco de dados.
    # Cada var_* corresponde a uma configuração persistida em database.py via
    # set_setting()/get_setting(). Os valores padrão são passados como segundo
    # argumento de get_setting() caso a chave ainda não exista no banco.
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
        self.var_notif_msg_private = tk.BooleanVar(
            value=db.get_setting('notif_msg_private', '1') == '1')
        self.var_notif_msg_group = tk.BooleanVar(
            value=db.get_setting('notif_msg_group', '1') == '1')
        self.var_notif_msg_broadcast = tk.BooleanVar(
            value=db.get_setting('notif_msg_broadcast', '1') == '1')
        self.var_notif_file = tk.BooleanVar(
            value=db.get_setting('notif_file', '1') == '1')
        self.var_notif_reminder = tk.BooleanVar(
            value=db.get_setting('notif_reminder', '1') == '1')
        self.var_sound_master = tk.BooleanVar(
            value=db.get_setting('sound_master', '1') == '1')
        self.var_sound_msg_private = tk.BooleanVar(
            value=db.get_setting('sound_msg_private', '1') == '1')
        self.var_sound_msg_group = tk.BooleanVar(
            value=db.get_setting('sound_msg_group', '1') == '1')
        self.var_sound_msg_broadcast = tk.BooleanVar(
            value=db.get_setting('sound_msg_broadcast', '1') == '1')
        self.var_sound_file_start = tk.BooleanVar(
            value=db.get_setting('sound_file_start', '1') == '1')
        self.var_sound_file_done = tk.BooleanVar(
            value=db.get_setting('sound_file_done', '1') == '1')
        self.var_sound_reminder = tk.BooleanVar(
            value=db.get_setting('sound_reminder', '1') == '1')
        self.var_flash_taskbar_msg = tk.BooleanVar(
            value=db.get_setting('flash_taskbar_msg', '1') == '1')
        self.var_flash_taskbar_file = tk.BooleanVar(
            value=db.get_setting('flash_taskbar_file', '1') == '1')
        self.var_flash_reminder = tk.BooleanVar(
            value=db.get_setting('flash_reminder', '1') == '1')
        self.var_save_history = tk.BooleanVar(value=True)
        self.var_history_path = tk.StringVar(
            value=db.get_setting('history_path',
                                 os.path.join(_get_data_dir(), 'history')))
        self.var_download_dir = tk.StringVar(
            value=db.get_setting('download_dir',
                                 os.path.join(os.path.expanduser('~'),
                                              'MB_Chat_Files')))
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
        self.var_msg_style = tk.StringVar(
            value=db.get_setting('msg_style', 'bubble'))
        self.var_avatar_index = tk.IntVar(
            value=int(db.get_setting('avatar_index', '0')))
        self.var_custom_avatar = tk.StringVar(
            value=db.get_setting('custom_avatar', ''))
        self.var_display_name = tk.StringVar(
            value=self.messenger.display_name)

    # Seleciona uma categoria da sidebar e reconstrói o painel direito.
    # Atualiza o destaque visual dos botões da sidebar, destrói o frame anterior
    # e chama o método _build_*() da categoria selecionada para preencher o painel.
    def _select_category(self, idx):
        # Destaca o botão selecionado em azul e restaura os demais ao padrão
        for i, btn in enumerate(self.cat_buttons):
            if i == idx:
                btn.configure(bg='#dbeafe', fg='#1e3a5f', relief='flat')
                _add_hover(btn, '#dbeafe', '#dbeafe')
            else:
                btn.configure(bg='#f8fafc', fg='#334155', relief='flat')
                _add_hover(btn, '#f8fafc', '#e2e8f0')

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
    # Constrói o painel da aba 'Conta': nome de exibição e foto de perfil.
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

        # Departamento
        lf3 = tk.LabelFrame(parent, text='Departamento', font=FONT,
                             bg=BG_WINDOW, padx=10, pady=8)
        lf3.pack(fill='x', padx=10, pady=(0, 8))
        dept_row = tk.Frame(lf3, bg=BG_WINDOW)
        dept_row.pack(fill='x', pady=4)
        tk.Label(dept_row, text='Selecionar:', font=FONT,
                 bg=BG_WINDOW).pack(side='left')
        self._dept_combo = ttk.Combobox(dept_row, font=FONT, width=18,
                                         state='readonly',
                                         values=['(Nenhum)', 'Administrativo',
                                                 'CS', 'Comercial', 'Contábil',
                                                 'Fiscal', 'Marketing', 'Pessoal',
                                                 'Processos', 'Recepção', 'TI'])
        cur_dept = self.messenger.db.get_setting('department', '')
        self._dept_combo.set(cur_dept if cur_dept else '(Nenhum)')
        self._dept_combo.pack(side='right')
        self._dept_combo.bind('<<ComboboxSelected>>', self._on_dept_changed)
        tk.Label(lf3, text='Visivel para todos na lista de contatos.',
                 font=FONT_SMALL, bg=BG_WINDOW, fg=FG_GRAY).pack(anchor='w')

    # Aplica e propaga o departamento assim que o usuario seleciona no combobox.
    def _on_dept_changed(self, event=None):
        dept = self._dept_combo.get().strip()
        if dept == '(Nenhum)':
            dept = ''
        try:
            self.messenger.db.set_setting('department', dept)
            self.messenger.discovery.update_department(dept)
        except Exception:
            log.exception('Erro ao aplicar departamento')

    # Show image preview in the custom_preview canvas.
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

        # Estilo de mensagem
        lf2 = tk.LabelFrame(parent, text='Estilo de Mensagem', font=FONT,
                             bg=BG_WINDOW, padx=10, pady=5)
        lf2.pack(fill='x', padx=10, pady=(0, 8))

        tk.Radiobutton(lf2, text='Linear (mensagens em sequência)',
                       variable=self.var_msg_style, value='linear',
                       font=FONT, bg=BG_WINDOW).pack(anchor='w')
        tk.Radiobutton(lf2, text='Bolhas (estilo WhatsApp)',
                       variable=self.var_msg_style, value='bubble',
                       font=FONT, bg=BG_WINDOW).pack(anchor='w')

    # ----- HISTÓRICO -----
    # ----- ALERTAS -----
    def _build_alertas(self, parent):
        tk.Label(parent, text='Alertas', font=FONT_SECTION,
                 bg=BG_WINDOW).pack(anchor='w', padx=10, pady=(5, 10))

        # --- Notificacoes (toast Windows) ---
        lf = tk.LabelFrame(parent, text='Notificações', font=FONT,
                            bg=BG_WINDOW, padx=10, pady=5)
        lf.pack(fill='x', padx=10, pady=(0, 8))
        notif_items = [
            ('Mensagem privada', self.var_notif_msg_private),
            ('Mensagem de grupo', self.var_notif_msg_group),
            ('Transmissão', self.var_notif_msg_broadcast),
            ('Arquivo', self.var_notif_file),
            ('Lembrete', self.var_notif_reminder),
        ]
        for i, (label, var) in enumerate(notif_items):
            r = i // 2
            c = i % 2
            padx = (0, 20) if c == 0 else (0, 0)
            tk.Checkbutton(lf, text=label, variable=var, font=FONT,
                           bg=BG_WINDOW).grid(row=r, column=c, sticky='w',
                                              padx=padx)
        lf.grid_columnconfigure(0, weight=1)
        lf.grid_columnconfigure(1, weight=1)

        # --- Sons ---
        lf2 = tk.LabelFrame(parent, text='Sons', font=FONT,
                             bg=BG_WINDOW, padx=10, pady=5)
        lf2.pack(fill='x', padx=10, pady=(0, 8))
        tk.Checkbutton(lf2, text='Ativar sons (mestre)',
                       variable=self.var_sound_master, font=FONT,
                       bg=BG_WINDOW).grid(row=0, column=0, columnspan=2,
                                          sticky='w', pady=(0, 2))
        sound_items = [
            ('Mensagem privada', self.var_sound_msg_private),
            ('Mensagem de grupo', self.var_sound_msg_group),
            ('Transmissão', self.var_sound_msg_broadcast),
            ('Recebendo arquivo', self.var_sound_file_start),
            ('Transferência concluída', self.var_sound_file_done),
            ('Lembrete', self.var_sound_reminder),
        ]
        for i, (label, var) in enumerate(sound_items):
            r = 1 + (i // 2)
            c = i % 2
            padx = (20, 10) if c == 0 else (0, 0)
            tk.Checkbutton(lf2, text=label, variable=var, font=FONT,
                           bg=BG_WINDOW).grid(row=r, column=c, sticky='w',
                                              padx=padx)
        lf2.grid_columnconfigure(0, weight=1)
        lf2.grid_columnconfigure(1, weight=1)

        # --- Piscar barra de tarefas ---
        lf3 = tk.LabelFrame(parent, text='Piscar na barra de tarefas', font=FONT,
                             bg=BG_WINDOW, padx=10, pady=5)
        lf3.pack(fill='x', padx=10, pady=(0, 8))
        flash_items = [
            ('Mensagens', self.var_flash_taskbar_msg),
            ('Arquivos', self.var_flash_taskbar_file),
            ('Lembretes', self.var_flash_reminder),
        ]
        for i, (label, var) in enumerate(flash_items):
            r = i // 2
            c = i % 2
            padx = (0, 20) if c == 0 else (0, 0)
            tk.Checkbutton(lf3, text=label, variable=var, font=FONT,
                           bg=BG_WINDOW).grid(row=r, column=c, sticky='w',
                                              padx=padx)
        lf3.grid_columnconfigure(0, weight=1)
        lf3.grid_columnconfigure(1, weight=1)

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
            ('Desfazer:', 'Ctrl + Z'),
            ('Refazer:', 'Ctrl + Y'),
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
    # Salva todas as preferências no banco de dados e aplica as mudanças imediatamente.
    # Esta função é chamada ao clicar em 'OK'. Ordem de execução:
    # 1. Persiste todos os valores das variáveis no banco via set_setting()
    # 2. Atualiza avatar via messenger.change_avatar() (propaga para a rede)
    # 3. Atualiza nome de exibição se foi alterado (propaga para a rede)
    # 4. Aplica nova fonte em todas as janelas de chat abertas
    # 5. Aplica o tema selecionado (recria paleta de cores)
    # 6. Configura ou remove o auto-start do Windows (registro)
    # 7. Atualiza o idioma da interface se foi alterado
    # 8. Fecha a janela de preferências
    def _save_all(self):
        db = self.messenger.db

        # Persiste cada configuração individualmente no banco SQLite
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
        db.set_setting('notif_msg_private',
                       '1' if self.var_notif_msg_private.get() else '0')
        db.set_setting('notif_msg_group',
                       '1' if self.var_notif_msg_group.get() else '0')
        db.set_setting('notif_msg_broadcast',
                       '1' if self.var_notif_msg_broadcast.get() else '0')
        db.set_setting('notif_file',
                       '1' if self.var_notif_file.get() else '0')
        db.set_setting('sound_master',
                       '1' if self.var_sound_master.get() else '0')
        db.set_setting('sound_msg_private',
                       '1' if self.var_sound_msg_private.get() else '0')
        db.set_setting('sound_msg_group',
                       '1' if self.var_sound_msg_group.get() else '0')
        db.set_setting('sound_msg_broadcast',
                       '1' if self.var_sound_msg_broadcast.get() else '0')
        db.set_setting('sound_file_start',
                       '1' if self.var_sound_file_start.get() else '0')
        db.set_setting('sound_file_done',
                       '1' if self.var_sound_file_done.get() else '0')
        db.set_setting('flash_taskbar_msg',
                       '1' if self.var_flash_taskbar_msg.get() else '0')
        db.set_setting('flash_taskbar_file',
                       '1' if self.var_flash_taskbar_file.get() else '0')
        db.set_setting('sound_reminder',
                       '1' if self.var_sound_reminder.get() else '0')
        db.set_setting('notif_reminder',
                       '1' if self.var_notif_reminder.get() else '0')
        db.set_setting('flash_reminder',
                       '1' if self.var_flash_reminder.get() else '0')
        db.set_setting('save_history',
                       '1' if self.var_save_history.get() else '0')
        db.set_setting('history_path', self.var_history_path.get())
        db.set_setting('download_dir', self.var_download_dir.get())
        db.set_setting('udp_port', self.var_udp_port.get())
        db.set_setting('tcp_port', self.var_tcp_port.get())
        db.set_setting('multicast', self.var_multicast.get())
        db.set_setting('font_size', self.var_font_size.get())
        db.set_setting('theme', self.var_theme.get())
        db.set_setting('enter_to_send',
                       '1' if self.var_enter_send.get() else '0')
        db.set_setting('show_timestamp',
                       '1' if self.var_show_timestamp.get() else '0')
        db.set_setting('msg_style', self.var_msg_style.get())
        # Apply avatar change via messenger (syncs to network)
        self.messenger.change_avatar(
            self.var_avatar_index.get(),
            self.var_custom_avatar.get())

        # Departamento ja foi salvo e propagado via _on_dept_changed,
        # mas garante consistencia caso tenha sido alterado por outro meio.
        if hasattr(self, '_dept_combo'):
            dept = self._dept_combo.get().strip()
            if dept == '(Nenhum)':
                dept = ''
            cur = db.get_setting('department', '')
            if cur != dept:
                db.set_setting('department', dept)
                self.messenger.discovery.update_department(dept)

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
            self.var_notif_msg_private.set(True)
            self.var_notif_msg_group.set(True)
            self.var_notif_msg_broadcast.set(True)
            self.var_notif_file.set(True)
            self.var_notif_reminder.set(True)
            self.var_sound_master.set(True)
            self.var_sound_msg_private.set(True)
            self.var_sound_msg_group.set(True)
            self.var_sound_msg_broadcast.set(True)
            self.var_sound_file_start.set(True)
            self.var_sound_file_done.set(True)
            self.var_sound_reminder.set(True)
            self.var_flash_taskbar_msg.set(True)
            self.var_flash_taskbar_file.set(True)
            self.var_flash_reminder.set(True)
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
# Janelinha compacta de perfil (nome + avatar).
class AccountWindow(tk.Toplevel):

    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.messenger = app.messenger
        self.title('Conta')
        self.resizable(False, False)
        self.transient(app.root)
        self.grab_set()
        self.configure(bg=BG_WINDOW)
        self.bind('<Escape>', lambda e: self.destroy())

        _center_window(self, 340, 420)
        _apply_rounded_corners(self)

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
        # Save avatar (syncs to network)
        self.messenger.change_avatar(
            self.var_avatar_index.get(),
            self.var_custom_avatar.get())
        self.app._update_avatar()
        # Departamento ja foi salvo e propagado via _on_dept_changed,
        # mas garante consistencia caso tenha sido alterado por outro meio.
        if hasattr(self, '_dept_combo'):
            dept = self._dept_combo.get().strip()
            if dept == '(Nenhum)':
                dept = ''
            cur = db.get_setting('department', '')
            if cur != dept:
                db.set_setting('department', dept)
                self.messenger.discovery.update_department(dept)
        self.destroy()


# =============================================================
#  FILE TRANSFER DIALOG  (estilo LAN Messenger)
# =============================================================
def _format_size(bytes_val):
    if bytes_val < 1024:
        return f'{bytes_val} B'
    elif bytes_val < 1024 * 1024:
        return f'{bytes_val / 1024:.1f} KB'
    else:
        return f'{bytes_val / (1024 * 1024):.2f} MB'


# Diálogo de progresso de transferência de arquivo ponto-a-ponto.
# Exibe estado diferente para quem envia vs. quem recebe:
# - Sender: barra de progresso imediatamente + label 'Aguardando aceitação...'
# - Receiver: botões 'Aceitar' e 'Declinar'; barra aparece após aceitar
# Ao concluir com sucesso:
# - Sender vê: "arquivo enviado — Completo!"
# - Receiver vê: "arquivo recebido" + botão 'Abrir Pasta' para abrir o Explorer
# Callbacks injetados pelo app:
# - on_cancel: chamado quando o usuário cancela
# - on_accept: chamado quando o receiver aceita (inicia a transferência)
# - on_decline: chamado quando o receiver recusa
class FileTransferDialog(tk.Toplevel):

    def __init__(self, parent, file_id, filename, peer_name,
                 direction='send', filesize=0, on_cancel=None,
                 on_accept=None, on_decline=None):
        super().__init__(parent)
        self.file_id = file_id
        self.filename = filename
        self.peer_name = peer_name
        self.direction = direction
        self._on_cancel = on_cancel
        self._filesize = filesize
        self._start_time = time.time()
        self._last_transferred = 0
        self._last_speed_time = time.time()
        self._finished = False
        self._filepath = ''  # set on complete

        self.title('Transferência de Arquivo')
        self.resizable(False, False)
        _center_window(self, 420, 180)
        _apply_rounded_corners(self)
        self.configure(bg='#ffffff')
        self.transient(parent)

        # Status label — envio direto (sem aceitar/recusar)
        if direction == 'send':
            status = f"Enviando '{filename}' para {peer_name}..."
        else:
            status = f"Recebendo '{filename}' de {peer_name}..."
        self._lbl_status = tk.Label(self, text=status,
                                     font=FONT, bg='#ffffff', fg='#000000',
                                     wraplength=390, anchor='w', justify='left')
        self._lbl_status.pack(padx=15, pady=(12, 2), anchor='w')

        # File info
        size_txt = _format_size(filesize)
        self._lbl_file = tk.Label(self, text=f'{filename} ({size_txt})',
                                   font=('Segoe UI', 9, 'bold'),
                                   bg='#ffffff', fg='#1a202c',
                                   wraplength=390, anchor='w')
        self._lbl_file.pack(padx=15, anchor='w')

        # Progress bar — visivel imediatamente (envio direto)
        self._progress_frame = tk.Frame(self, bg='#ffffff')
        self.progress = ttk.Progressbar(self._progress_frame, length=385,
                                         mode='determinate',
                                         maximum=max(filesize, 1))
        self.progress.pack(padx=0, pady=(4, 2))

        self._lbl_info = tk.Label(self._progress_frame,
                                  text=f'0 B / {size_txt}',
                                  font=('Segoe UI', 8), bg='#ffffff',
                                  fg='#718096', anchor='w')
        self._lbl_info.pack(anchor='w')
        self._progress_frame.pack(padx=15, fill='x')

        # Action buttons frame
        self._btn_frame = tk.Frame(self, bg='#ffffff')
        self._btn_frame.pack(padx=15, pady=(6, 10), anchor='w')

        self._lbl_state = tk.Label(self._btn_frame,
                                    text='Transferindo...',
                                    font=('Segoe UI', 8, 'italic'),
                                    bg='#ffffff', fg='#2b8a3e')
        self._lbl_state.pack(side='left')
        cancel_lbl = tk.Label(self._btn_frame, text='Cancelar',
                              font=('Segoe UI', 8, 'underline'),
                              fg='#cc0000', bg='#ffffff', cursor='hand2')
        cancel_lbl.pack(side='left', padx=(12, 0))
        cancel_lbl.bind('<Button-1>', lambda e: self._cancel())
        self._cancel_lbl = cancel_lbl

        self.protocol('WM_DELETE_WINDOW', self._cancel)

        ico = _get_icon_path()
        if ico:
            try:
                self.iconbitmap(ico)
            except Exception:
                pass

    # Atualiza a barra de progresso e o label de velocidade/tamanho.
    #
    # Chamado periodicamente pelo app a partir de callbacks de rede.
    # A velocidade é calculada a cada 0.5s para suavizar variações.
    # Para o sender, também confirma visualmente que o receiver aceitou
    # (quando o primeiro byte chega, significa que foi aceito).
    def update_progress(self, transferred, total):
        if self._finished:
            return
        try:
            self.progress['maximum'] = max(total, 1)
            self.progress['value'] = transferred

            now = time.time()
            elapsed = now - self._last_speed_time
            if elapsed > 0.5:
                # Calcula velocidade em bytes/s e formata como KB/s ou MB/s
                speed = (transferred - self._last_transferred) / elapsed
                self._last_transferred = transferred
                self._last_speed_time = now
                speed_txt = f'{_format_size(int(speed))}/s'
            else:
                speed_txt = ''

            info = f'{_format_size(transferred)} / {_format_size(total)}'
            if speed_txt:
                info += f'  —  {speed_txt}'
            self._lbl_info.config(text=info)

            pass
        except tk.TclError:
            pass

    # Finaliza o diálogo de transferência com resultado de sucesso ou erro.
    #
    # Em caso de sucesso:
    # - Sender: exibe mensagem "enviado — Completo!"
    # - Receiver: exibe mensagem "recebido — Completo!" + botão 'Abrir Pasta'
    # Em caso de erro: fecha o diálogo silenciosamente.
    def finish(self, success=True, filepath=''):
        if self._finished:
            return
        self._finished = True
        self._filepath = filepath
        try:
            for w in self._btn_frame.winfo_children():
                w.destroy()
            if success:
                self._lbl_status.config(fg='#2b8a3e')
                if self.direction == 'send':
                    self._lbl_status.config(text=f"'{self.filename}' enviado com sucesso!")
                else:
                    self._lbl_status.config(text=f"'{self.filename}' recebido de {self.peer_name}")
                self.progress['value'] = self.progress['maximum']
                self.update_idletasks()
                self._lbl_info.config(text=_format_size(self._filesize))
                # "Abrir Pasta" só para receiver
                if self.direction == 'receive' and filepath:
                    btn_folder = tk.Label(self._btn_frame,
                                          text='Abrir Pasta',
                                          font=('Segoe UI', 9, 'underline'),
                                          fg='#0066cc', bg='#ffffff',
                                          cursor='hand2')
                    btn_folder.pack(side='left')
                    btn_folder.bind('<Button-1>',
                                    lambda e: (self._open_folder(filepath),
                                               self._safe_destroy()))
                close_lbl = tk.Label(self._btn_frame, text='Fechar',
                                     font=('Segoe UI', 8, 'underline'),
                                     fg='#718096', bg='#ffffff',
                                     cursor='hand2')
                close_lbl.pack(side='left', padx=(12, 0))
                close_lbl.bind('<Button-1>', lambda e: self._safe_destroy())
            else:
                self._safe_destroy()
        except tk.TclError:
            pass

    # Abre o explorador na pasta do arquivo.
    def _open_folder(self, filepath):
        try:
            import subprocess
            if os.path.exists(filepath):
                subprocess.Popen(['explorer', '/select,', filepath])
            else:
                folder = os.path.dirname(filepath)
                if os.path.isdir(folder):
                    subprocess.Popen(['explorer', folder])
        except Exception:
            log.exception('Erro ao abrir pasta')

    def _safe_destroy(self):
        try:
            self.destroy()
        except tk.TclError:
            pass

    def _cancel(self):
        if not self._finished and self._on_cancel:
            self._on_cancel(self.file_id)
        self._finished = True
        self._safe_destroy()


# =============================================================
#  FILE TRANSFERS WINDOW  (lista de todas as transferencias)
# =============================================================
# Janela com lista de todas as transferencias de arquivos.
class FileTransfersWindow(tk.Toplevel):

    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self._rows = {}  # file_id -> frame widget

        self.title('Transferências de Arquivos')
        self.minsize(400, 300)
        _center_window(self, 460, 420)
        _apply_rounded_corners(self)
        self.configure(bg='#f5f7fa')
        self.protocol('WM_DELETE_WINDOW', self._on_close)
        self.bind('<Escape>', lambda e: self._on_close())

        ico = _get_icon_path()
        if ico:
            try:
                self.iconbitmap(ico)
            except Exception:
                pass

        NAVY = '#0f2a5c'
        # Toolbar
        toolbar = tk.Frame(self, bg='#e8ecf1', bd=0)
        toolbar.pack(fill='x')
        tb_inner = tk.Frame(toolbar, bg='#e8ecf1')
        tb_inner.pack(fill='x', padx=6, pady=4)

        btn_folder = tk.Button(tb_inner, text='\U0001f4c2 Mostrar a Pasta',
                               font=('Segoe UI', 8), bg='#e8ecf1',
                               fg='#4a5568', relief='flat', bd=0,
                               cursor='hand2', padx=6,
                               command=self._open_folder_selected)
        btn_folder.pack(side='left', padx=(0, 4))

        btn_remove = tk.Button(tb_inner, text='\u2716 Remover da Lista',
                               font=('Segoe UI', 8), bg='#e8ecf1',
                               fg='#cc0000', relief='flat', bd=0,
                               cursor='hand2', padx=6,
                               command=self._remove_selected)
        btn_remove.pack(side='left')

        # Scrollable list
        list_frame = tk.Frame(self, bg='#ffffff')
        list_frame.pack(fill='both', expand=True, padx=0, pady=0)

        self._canvas = tk.Canvas(list_frame, bg='#ffffff',
                                  highlightthickness=0)
        scrollbar = ttk.Scrollbar(list_frame, orient='vertical',
                                   command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        self._canvas.pack(fill='both', expand=True)

        self._inner = tk.Frame(self._canvas, bg='#ffffff')
        self._win_id = self._canvas.create_window((0, 0), window=self._inner,
                                                    anchor='nw')
        self._canvas.bind('<Configure>',
                          lambda e: self._canvas.itemconfig(self._win_id,
                                                             width=e.width))
        self._inner.bind('<Configure>',
                         lambda e: self._canvas.configure(
                             scrollregion=self._canvas.bbox('all')))
        self._canvas.bind('<MouseWheel>',
                          lambda e: self._canvas.yview_scroll(
                              -1 * (e.delta // 120), 'units'))

        # Bottom bar
        bottom = tk.Frame(self, bg='#f5f7fa')
        bottom.pack(fill='x', padx=8, pady=6)
        btn_clear = tk.Button(bottom, text='Apagar Lista',
                              font=('Segoe UI', 8), bg='#f5f7fa',
                              fg='#cc0000', relief='flat', bd=0,
                              cursor='hand2', command=self._clear_all)
        btn_clear.pack(side='left')
        btn_close = tk.Button(bottom, text='  Fechar  ',
                              font=('Segoe UI', 9),
                              bg='#e2e8f0', fg='#4a5568', relief='flat',
                              bd=0, padx=12, pady=3, cursor='hand2',
                              command=self._on_close)
        btn_close.pack(side='right')

        # Load existing entries
        self._load_entries()

    # Carrega transferencias da lista do app.
    def _load_entries(self):
        for entry in self.app._transfer_history:
            self._add_entry_widget(entry)

    def _add_entry_widget(self, entry):
        fid = entry['file_id']
        if fid in self._rows:
            return

        row = tk.Frame(self._inner, bg='#ffffff', cursor='hand2')
        row.pack(fill='x', padx=0, pady=0)
        row._entry = entry
        row._selected = False
        self._rows[fid] = row

        # Separator
        tk.Frame(row, bg='#e8ecf1', height=1).pack(fill='x')

        content = tk.Frame(row, bg='#ffffff')
        content.pack(fill='x', padx=10, pady=8)

        # Direction + peer
        direction = entry.get('direction', 'send')
        peer = entry.get('peer_name', '?')
        if direction == 'send':
            header = f'Para:{peer}'
        else:
            header = f'De:{peer}'
        tk.Label(content, text=header, font=('Segoe UI', 9, 'bold'),
                 bg='#ffffff', fg='#1a202c', anchor='w').pack(anchor='w')

        # Filename + size
        fname = entry.get('filename', '?')
        fsize = _format_size(entry.get('filesize', 0))
        tk.Label(content, text=f'{fname} ({fsize})',
                 font=('Segoe UI', 8), bg='#ffffff',
                 fg='#4a5568', anchor='w').pack(anchor='w')

        # Status
        status = entry.get('status', 'pending')
        status_text = {'pending': 'Pendente', 'transferring': 'Transferindo...',
                       'completed': 'Completo', 'error': 'Erro',
                       'declined': 'Recusado', 'cancelled': 'Cancelado'
                       }.get(status, status)
        color = '#2b8a3e' if status == 'completed' else '#b07d10' if status == 'transferring' else '#cc0000' if status in ('error', 'cancelled') else '#718096'
        lbl_status = tk.Label(content, text=status_text,
                              font=('Segoe UI', 8, 'italic'),
                              bg='#ffffff', fg=color, anchor='w')
        lbl_status.pack(anchor='w')
        row._lbl_status = lbl_status

        # Click to select
        for w in [row, content] + list(content.winfo_children()):
            w.bind('<Button-1>', lambda e, r=row: self._select_row(r))

    def _select_row(self, row):
        # Deselect all
        for r in self._rows.values():
            r.configure(bg='#ffffff')
            r._selected = False
            for w in r.winfo_children():
                if hasattr(w, 'configure'):
                    try:
                        w.configure(bg='#ffffff')
                        for c in w.winfo_children():
                            try:
                                c.configure(bg='#ffffff')
                            except Exception:
                                pass
                    except Exception:
                        pass
        # Select this
        row._selected = True
        row.configure(bg='#cce0ff')
        for w in row.winfo_children():
            if hasattr(w, 'configure'):
                try:
                    w.configure(bg='#cce0ff')
                    for c in w.winfo_children():
                        try:
                            c.configure(bg='#cce0ff')
                        except Exception:
                            pass
                except Exception:
                    pass

    def _get_selected(self):
        for fid, row in self._rows.items():
            if row._selected:
                return fid, row
        return None, None

    def _open_folder_selected(self):
        fid, row = self._get_selected()
        if not fid:
            return
        fp = row._entry.get('filepath', '')
        if not fp:
            log.warning('Mostrar pasta: filepath vazio para %s', fid)
            return
        # Abre a pasta que contem o arquivo. os.startfile e o caminho mais
        # confiavel no Windows — evita o /select, do explorer que quebra
        # quando passado como arg separado via subprocess.
        folder = os.path.dirname(fp) if os.path.isfile(fp) else fp
        if not os.path.isdir(folder):
            log.warning('Mostrar pasta: diretorio nao existe: %s', folder)
            return
        try:
            os.startfile(folder)
        except Exception:
            log.exception('Erro ao abrir pasta')

    def _remove_selected(self):
        fid, row = self._get_selected()
        if fid:
            row.destroy()
            del self._rows[fid]
            self.app._transfer_history = [
                e for e in self.app._transfer_history
                if e['file_id'] != fid]

    def _clear_all(self):
        for row in self._rows.values():
            row.destroy()
        self._rows.clear()
        self.app._transfer_history.clear()

    # Adiciona ou atualiza uma entrada.
    def add_or_update(self, entry):
        fid = entry['file_id']
        # Update in history
        found = False
        for i, e in enumerate(self.app._transfer_history):
            if e['file_id'] == fid:
                self.app._transfer_history[i] = entry
                found = True
                break
        if not found:
            self.app._transfer_history.append(entry)

        if fid in self._rows:
            # Update status label
            row = self._rows[fid]
            row._entry = entry
            status = entry.get('status', 'pending')
            status_text = {'pending': 'Pendente', 'transferring': 'Transferindo...',
                           'completed': 'Completo', 'error': 'Erro',
                           'declined': 'Recusado', 'cancelled': 'Cancelado'
                           }.get(status, status)
            color = '#2b8a3e' if status == 'completed' else '#b07d10' if status == 'transferring' else '#cc0000' if status in ('error', 'cancelled') else '#718096'
            try:
                row._lbl_status.config(text=status_text, fg=color)
            except tk.TclError:
                pass
        else:
            self._add_entry_widget(entry)

    def _on_close(self):
        self.withdraw()


# =============================================================
#  CHAT WINDOW
# =============================================================
# Janela de conversa individual entre dois usuários.
#
# Layout (de baixo para cima, usando pack side='bottom' primeiro):
# 1. btn_frame   — toolbar inferior com botões Fonte, Emoji, Enviar Arquivo + botão Enviar
# 2. input_outer — campo de texto de entrada (3 linhas, suporta emojis coloridos)
# 3. chat_frame  — área de exibição de mensagens (tk.Text desabilitado para edição)
# 4. header      — cabeçalho navy com avatar do peer, nome, label de digitação e botão Histórico
#
# Funcionalidades principais:
# - Emojis coloridos: digitados ou escolhidos no picker são inseridos como imagens PIL
# - Cache de imagens: _chat_emoji_cache (chat) e _entry_emoji_cache (entrada)
# - Dois estilos: 'linear' (padrão LAN Messenger) e 'bubble' (estilo WhatsApp)
# - Indicador de digitação: envia MT_TYPING para o peer ao detectar keystrokes
# - Histórico: carrega mensagens não lidas ao abrir; botão abre janela de histórico completo
# - Scrollbar automática: aparece ao passar o mouse, some ao sair
class ChatWindow(tk.Toplevel):

    def __init__(self, parent_app, peer_id, peer_name, start_hidden=False, **kw):
        super().__init__(parent_app.root)
        if start_hidden:
            self.withdraw()
        self.app = parent_app
        self.messenger = parent_app.messenger
        self.peer_id = peer_id         # UUID do contato (chave primária na tabela contacts)
        self.peer_name = peer_name     # Nome de exibição do contato
        self._typing_timer = None       # Timer tkinter para parar o indicador de digitação após 2s de inatividade
        self._was_typing = False        # True enquanto o usuário está digitando (para não re-enviar MT_TYPING)
        self._msg_ranges = []           # Lista de textos das mensagens (para funcionalidade de copiar)
        self._chat_emoji_cache = {}     # Cache emoji_char -> PhotoImage para o chat (evita re-renderizar)
        self._entry_emoji_cache = {}    # Cache emoji_char -> PhotoImage para o campo de entrada
        self._entry_img_map = {}        # img_name -> emoji_char: mapeia imagens no entry de volta para texto

        # Obtém o tema atual (fallback para 'MB Contabilidade' se o tema não existir)
        t = THEMES.get(self.app._current_theme, THEMES.get('MB Contabilidade', {}))

        self.title(f'{peer_name} - {APP_NAME}')
        self.minsize(350, 350)
        _center_window(self, 420, 480)
        self.bind('<Escape>', lambda e: self._on_close())
        _apply_rounded_corners(self)
        # Cada chat tem entrada propria na taskbar (estilo LAN Messenger)
        try:
            self.app._force_taskbar_entry(self)
        except Exception:
            pass
        # Ao restaurar (clique na thumbnail), para o flash e limpa unread
        self.bind('<Map>', lambda e: self.app._on_chat_window_mapped(self))
        self.configure(bg=t.get('bg_window', '#f5f7fa'))
        ico = _get_icon_path()
        if ico:
            try:
                self.iconbitmap(ico)
            except Exception:
                pass

        # Header navy integrado (avatar + nome + histórico)
        header_bg = t.get('chat_header_bg', t.get('bg_header', '#0f2a5c'))
        header_fg = t.get('chat_header_fg', '#ffffff')
        header_sub = t.get('chat_header_sub', '#8aa0cc')

        header = tk.Frame(self, bg=header_bg)
        header.pack(fill='x')

        header_row = tk.Frame(header, bg=header_bg)
        header_row.pack(fill='x', padx=10, pady=8)

        # Peer avatar 40x40
        self._chat_avatar_canvas = tk.Canvas(header_row, width=40, height=40,
                                              bg=header_bg, highlightthickness=0)
        self._chat_avatar_canvas.pack(side='left', padx=(0, 10))
        self._draw_peer_avatar()

        name_frame = tk.Frame(header_row, bg=header_bg)
        name_frame.pack(side='left', fill='x', expand=True)

        self.lbl_peer = tk.Label(name_frame, text=peer_name,
                                 font=('Segoe UI', 12, 'bold'),
                                 bg=header_bg, fg=header_fg, anchor='w')
        self.lbl_peer.pack(fill='x')

        self.lbl_typing = tk.Label(name_frame, text='', font=('Segoe UI', 9),
                                   bg=header_bg, fg=header_sub, anchor='w')
        self.lbl_typing.pack(fill='x')

        # Botão Histórico no header (ícone MDL2 U+E81C)
        ico_hist = self._create_mdl2_icon('\uE81C', 20, header_fg) if HAS_PIL else None
        if ico_hist:
            self._hist_icon = ico_hist
            btn_hist = tk.Button(header_row, image=ico_hist,
                      bg=header_bg, relief='flat', bd=0,
                      command=self._show_history, cursor='hand2',
                      activebackground=t.get('btn_active', '#1a3f7a'))
        else:
            btn_hist = tk.Button(header_row, text='\u2630', font=('Segoe UI', 12),
                      bg=header_bg, fg=header_fg, relief='flat', bd=0,
                      command=self._show_history, cursor='hand2',
                      activebackground=t.get('btn_active', '#1a3f7a'))
        btn_hist.pack(side='right', padx=4)
        _Tooltip(btn_hist, _t('history_btn'))

        # Barra de ações (bottom - pack ANTES do input/chat para garantir posição fixa)
        # IMPORTANTE: btn_frame e input_outer devem ser empacotados com side='bottom'
        # antes do chat_frame (fill='both', expand=True) — padrão obrigatório do layout.
        btn_frame = tk.Frame(self, bg=t.get('bg_window', '#f5f7fa'))
        btn_frame.pack(fill='x', side='bottom', padx=8, pady=(0, 6))

        # Botão Enviar destacado na cor navy do tema, alinhado à direita
        send_bg = t.get('btn_send_bg', t.get('btn_bg', '#0f2a5c'))
        send_fg = t.get('btn_send_fg', '#ffffff')
        btn_send = tk.Button(btn_frame, text=f' {_t("send_btn")} ', font=('Segoe UI', 9, 'bold'),
                  bg=send_bg, fg=send_fg, relief='flat', bd=0,
                  command=self._send_message, cursor='hand2',
                  activebackground=t.get('btn_active', '#1a3f7a'),
                  activeforeground=send_fg, padx=12, pady=3)
        btn_send.pack(side='right', pady=2)
        _Tooltip(btn_send, _t('send_btn') + ' (Enter)')

        # Botões flat à esquerda com ícones MDL2 + tooltips
        flat_fg = t.get('btn_flat_fg', '#718096')
        win_bg = t.get('bg_window', '#f5f7fa')
        self._btn_icons = {}
        icon_size = 20

        # Ícone Fonte (U+E8D2)
        ico_font = self._create_mdl2_icon('\uE8D2', icon_size, flat_fg) if HAS_PIL else None
        if ico_font:
            self._btn_icons['font'] = ico_font
            btn_font = tk.Button(btn_frame, image=ico_font,
                      bg=win_bg, relief='flat', bd=0, padx=3, pady=2,
                      command=self._change_font, cursor='hand2')
        else:
            btn_font = tk.Button(btn_frame, text='A', font=('Segoe UI', 10, 'bold'),
                      bg=win_bg, fg=flat_fg, relief='flat', bd=0,
                      command=self._change_font, cursor='hand2')
        btn_font.pack(side='left', pady=2, padx=(0, 2))
        _Tooltip(btn_font, _t('font_btn'))

        # Ícone Emoji (U+E76E)
        ico_emoji = self._create_mdl2_icon('\uE76E', icon_size, flat_fg) if HAS_PIL else None
        if ico_emoji:
            self._btn_icons['emoji'] = ico_emoji
            btn_emoji = tk.Button(btn_frame, image=ico_emoji,
                      bg=win_bg, relief='flat', bd=0, padx=3, pady=2,
                      command=self._show_emoji_picker, cursor='hand2')
        else:
            btn_emoji = tk.Button(btn_frame, text='\U0001f600', font=('Segoe UI', 11),
                      bg=win_bg, fg=flat_fg, relief='flat', bd=0,
                      command=self._show_emoji_picker, cursor='hand2')
        btn_emoji.pack(side='left', pady=2, padx=(0, 2))
        _Tooltip(btn_emoji, 'Emojis')

        # Ícone Anexo/Clipe (U+E723)
        ico_attach = self._create_mdl2_icon('\uE723', icon_size, flat_fg) if HAS_PIL else None
        if ico_attach:
            self._btn_icons['attach'] = ico_attach
            btn_file = tk.Button(btn_frame, image=ico_attach,
                      bg=win_bg, relief='flat', bd=0, padx=3, pady=2,
                      command=self._send_file, cursor='hand2')
        else:
            btn_file = tk.Button(btn_frame, text='\u2736',
                      font=('Segoe UI', 11), bg=win_bg, fg=flat_fg,
                      relief='flat', bd=0,
                      command=self._send_file, cursor='hand2')
        btn_file.pack(side='left', pady=2, padx=(0, 2))
        _Tooltip(btn_file, _t('send_file_btn'))

        # Campo de entrada: Frame externo cria a borda sutil (bg = cor da borda)
        # O Text interno tem padx=1,pady=1 para revelar o Frame como borda de 1px
        self._input_outer = tk.Frame(self, bg=t.get('input_border', '#e2e8f0'))
        self._input_outer.pack(fill='x', side='bottom', padx=8, pady=(4, 2))
        input_outer = self._input_outer

        # tk.Text é usado (não tk.Entry) para suportar múltiplas linhas e imagens (emojis)
        self.entry = tk.Text(input_outer, font=('Segoe UI', 10),
                             bg=t.get('bg_input', '#f7fafc'),
                             fg=t.get('fg_black', '#1a202c'),
                             relief='flat', bd=0, height=3,
                             wrap='word', padx=8, pady=6,
                             insertbackground=t.get('fg_black', '#1a202c'),
                             undo=True, autoseparators=True, maxundo=-1)
        self.entry.pack(fill='both', expand=True, padx=1, pady=1)
        def _redo(e):
            try: self.entry.edit_redo()
            except tk.TclError: pass
            return 'break'
        self.entry.bind('<Control-y>', _redo)
        self.entry.bind('<Control-Y>', _redo)
        # Enter envia (verificado em _on_enter); Shift+Enter insere nova linha
        self.entry.bind('<Return>', self._on_enter)
        self.entry.bind('<Shift-Return>', lambda e: None)
        self.entry.bind('<Control-v>', self._on_paste)
        self.entry.bind('<Control-V>', self._on_paste)
        # <<Modified>> dispara SEMPRE que o conteúdo muda (teclado, IME, Win+., paste)
        # Este é o único evento confiável para detectar emojis inseridos pelo Windows Emoji Picker
        self.entry.bind('<<Modified>>', self._on_modified)
        # <KeyRelease> usado apenas para o indicador de digitação (não para emojis)
        self.entry.bind('<KeyRelease>', self._on_key_typing)
        self.entry.focus_set()

        self._image_cache = {}  # path -> PhotoImage para imagens no chat
        self._reply_to = None   # {msg_id, sender, text} — mensagem sendo respondida
        self._reply_bar = None  # Frame da barra de reply
        self._pending_image = None        # PIL Image aguardando envio (Ctrl+V preview)
        self._image_preview_bar = None    # Frame da barra de preview de imagem
        self._preview_thumb_ref = None    # referencia para evitar GC do thumbnail

        # Área de exibição das mensagens (chat_frame se expande para preencher o espaço restante)
        chat_frame = tk.Frame(self, bg=t.get('bg_window', '#f5f7fa'))
        chat_frame.pack(fill='both', expand=True, padx=0, pady=0)

        chat_bg = t.get('bg_chat', '#f5f7fa')
        # state='disabled' impede edição pelo usuário; liberado temporariamente ao inserir mensagens
        self.chat_text = tk.Text(chat_frame, font=('Segoe UI', 10),
                                 bg=chat_bg, fg=t.get('fg_msg', '#1a202c'),
                                 relief='flat', bd=0,
                                 wrap='word', state='disabled', padx=10,
                                 pady=8, cursor='arrow',
                                 selectbackground='#1e66d0',
                                 selectforeground='#ffffff',
                                 inactiveselectbackground='#1e66d0')

        # Scrollbar minimalista (4px, sem setas) — oculta por padrão, aparece no hover
        self._chat_scrollbar = tk.Scrollbar(chat_frame,
                                             command=self.chat_text.yview,
                                             width=4, relief='flat',
                                             troughcolor=chat_bg,
                                             bg='#cbd5e0', activebackground='#a0aec0')
        # Conecta o scroll da scrollbar ao método que controla visibilidade
        self.chat_text.configure(yscrollcommand=self._on_chat_scroll)
        self._chat_scrollbar.pack(side='right', fill='y')
        self._chat_scrollbar.pack_forget()  # Começa oculta
        self.chat_text.pack(fill='both', expand=True)

        # Controla visibilidade da scrollbar: aparece ao passar o mouse, some ao sair
        self._scroll_visible = False
        chat_frame.bind('<Enter>', self._show_scrollbar)
        chat_frame.bind('<Leave>', self._hide_scrollbar)
        self.chat_text.bind('<Enter>', self._show_scrollbar)
        self.chat_text.bind('<Leave>', self._hide_scrollbar)

        # Mouse wheel scroll
        self.chat_text.bind('<MouseWheel>', self._on_mousewheel)

        fg_time = t.get('fg_time', '#718096')
        fg_my = t.get('fg_my_name', '#0f2a5c')
        fg_peer = t.get('fg_peer_name', '#cc2222')
        fg_msg = t.get('fg_msg', '#1a202c')

        self.chat_text.tag_configure('time', foreground=fg_time,
                                     font=('Segoe UI', 7))
        self.chat_text.tag_configure('my_name', foreground=fg_my,
                                     font=('Segoe UI', 9, 'bold'))
        self.chat_text.tag_configure('peer_name', foreground=fg_peer,
                                     font=('Segoe UI', 9, 'bold'))
        self.chat_text.tag_configure('msg', foreground=fg_msg,
                                     font=('Segoe UI', 10))
        self.chat_text.tag_configure('system',
                                     foreground='#718096',
                                     font=('Segoe UI', 8, 'italic'))

        # Tags para modo bolha (WhatsApp style) — cada mensagem fica numa "bolha" colorida
        msg_my_bg = t.get('msg_my_bg', '#e8f0fe')   # cor de fundo das bolhas próprias (azul claro)
        msg_peer_bg = t.get('msg_peer_bg', '#f0f0f0')  # cor de fundo das bolhas do contato (cinza)
        # Bolha do próprio usuário: alinhada à direita, margem esquerda grande (empurra para direita)
        self.chat_text.tag_configure('my_bubble',
                                     background=msg_my_bg,
                                     justify='right', rmargin=8,
                                     lmargin1=80, lmargin2=80,
                                     spacing1=6, spacing3=2)
        # Nome do remetente dentro da bolha própria (negrito, alinhado à direita)
        self.chat_text.tag_configure('my_bubble_name',
                                     background=msg_my_bg,
                                     foreground=fg_my,
                                     font=('Segoe UI', 8, 'bold'),
                                     justify='right', rmargin=8,
                                     lmargin1=80, lmargin2=80,
                                     spacing1=6)
        # Horário da mensagem própria (menor, cor discreta, alinhado à direita)
        self.chat_text.tag_configure('my_bubble_time',
                                     background=msg_my_bg,
                                     foreground=fg_time,
                                     font=('Segoe UI', 7),
                                     justify='right', rmargin=8,
                                     lmargin1=80, lmargin2=80)
        # Bolha do contato: alinhada à esquerda, margem direita grande (empurra para esquerda)
        self.chat_text.tag_configure('peer_bubble',
                                     background=msg_peer_bg,
                                     justify='left', lmargin1=8,
                                     lmargin2=8, rmargin=80,
                                     spacing1=6, spacing3=2)
        # Nome do contato dentro da bolha (negrito, alinhado à esquerda)
        self.chat_text.tag_configure('peer_bubble_name',
                                     background=msg_peer_bg,
                                     foreground=fg_peer,
                                     font=('Segoe UI', 8, 'bold'),
                                     justify='left', lmargin1=8,
                                     lmargin2=8, rmargin=80,
                                     spacing1=6)
        # Horário da mensagem do contato (menor, cor discreta, alinhado à esquerda)
        self.chat_text.tag_configure('peer_bubble_time',
                                     background=msg_peer_bg,
                                     foreground=fg_time,
                                     font=('Segoe UI', 7),
                                     justify='left', lmargin1=8,
                                     lmargin2=8, rmargin=80)
        # Tag do link "copiar" que aparece ao lado de cada mensagem
        self.chat_text.tag_configure('copy_btn',
                                     foreground='#a0aec0',
                                     font=('Segoe UI', 8))
        # Clique na tag copia o texto; cursor muda para mão ao passar por cima
        self.chat_text.tag_bind('copy_btn', '<Button-1>', self._on_copy_click)
        self.chat_text.tag_bind('copy_btn', '<Enter>',
                                lambda e: self.chat_text.config(cursor='hand2'))
        self.chat_text.tag_bind('copy_btn', '<Leave>',
                                lambda e: self.chat_text.config(cursor='arrow'))

        # Tags para quote/reply (barra azul simulada via lmargin + background)
        self.chat_text.tag_configure('quote_name',
                                     background='#e2e8f0',
                                     foreground='#2451a0',
                                     font=('Segoe UI', 8, 'bold'),
                                     lmargin1=12, lmargin2=12,
                                     rmargin=40,
                                     spacing1=4, spacing3=0)
        self.chat_text.tag_configure('quote',
                                     background='#e2e8f0',
                                     foreground='#4a5568',
                                     font=('Segoe UI', 8),
                                     lmargin1=12, lmargin2=12,
                                     rmargin=40,
                                     spacing1=0, spacing3=4)

        try: self.chat_text.tag_raise('sel')
        except tk.TclError: pass

        # Dados de mensagens para reply (msg_id, sender, text_preview)
        self._msg_data = []  # [{msg_id, sender, text, is_mine}]
        self._msg_ranges_idx = []  # [(start_idx, end_idx)] por mensagem (para tag msg_N)
        self._img_click_handled = False
        self._link_counter = 0

        # Tag visual para mensagem selecionada em modo seleção multi-mensagem
        self.chat_text.tag_configure('selected_msg', background='#fff3b0')
        try:
            self.chat_text.tag_raise('sel')
        except tk.TclError:
            pass

        # Modo seleção (long-press ativa)
        self._selection_mode = False
        self._selection_set = set()
        self._selection_bar = None
        self._sel_count_lbl = None
        self._long_press_after = None
        self._long_press_origin = None
        self._long_press_msg_idx = None

        # Botao de copiar que aparece no hover da mensagem
        self._hover_copy_btn = tk.Label(
            self.chat_text, text='\uE8C8', font=('Segoe MDL2 Assets', 9),
            bg='#f0f0f0', fg='#666666', cursor='hand2', bd=0, relief='flat',
            padx=2, pady=0)
        self._hover_copy_btn.bind('<Button-1>', self._on_hover_copy_click)
        self._hover_copy_btn.bind('<Enter>', lambda e: self._cancel_hover_hide())
        self._hover_copy_btn.bind('<Leave>', lambda e: self._schedule_hover_hide())
        self._hover_copy_visible_idx = None
        self._hover_hide_after = None

        self.chat_text.bind('<ButtonPress-1>', self._on_chat_press, add='+')
        self.chat_text.bind('<B1-Motion>', self._on_chat_motion, add='+')
        self.chat_text.bind('<ButtonRelease-1>', self._on_chat_release, add='+')
        self.bind('<Escape>', self._on_escape_selection, add='+')

        # Menu de contexto no chat (Responder / Copiar / Selecionar)
        self._chat_ctx = tk.Menu(self, tearoff=0, font=('Segoe UI', 9))
        self._chat_ctx.add_command(label='Responder', command=self._ctx_reply)
        self._chat_ctx.add_command(label='Copiar', command=self._ctx_copy)
        self._chat_ctx.add_command(label='Selecionar', command=self._ctx_select)
        self.chat_text.bind('<Button-3>', self._on_chat_right_click)
        self._ctx_click_index = None

        self.protocol('WM_DELETE_WINDOW', self._on_close)  # trata fechamento da janela
        self.bind('<FocusIn>', lambda e: self.app._stop_flash(self))  # para o flash da taskbar ao focar

        # Drag & Drop de arquivos (windnd) — hook na janela E na caixa de entrada
        if HAS_WINDND:
            try:
                windnd.hook_dropfiles(self, func=self._on_drop_files)
                windnd.hook_dropfiles(self.entry, func=self._on_drop_files)
                windnd.hook_dropfiles(self.chat_text, func=self._on_drop_files)
                _allow_uipi_drop(self)
                _allow_uipi_drop(self.entry)
                _allow_uipi_drop(self.chat_text)
            except Exception:
                pass

    # Callback do windnd: arquivos arrastados para a janela
    def _on_drop_files(self, files):
        for f in files:
            path = f.decode('utf-8') if isinstance(f, bytes) else str(f)
            if os.path.isfile(path):
                self.app._start_file_send(self.peer_id, path)
                break  # envia apenas o primeiro arquivo

    # Carrega e exibe as mensagens não lidas acumuladas desde o último acesso.
    # Após exibir, marca todas como lidas no banco de dados.
    def _load_history(self):
        # Busca histórico recente (últimas 40 mensagens) para garantir que a janela nunca abra vazia
        history = self.messenger.db.get_chat_history(self.messenger.user_id, self.peer_id, limit=40)
        for msg in history:
            # Determina se a mensagem foi enviada por mim ou pelo contato
            is_mine = msg['from_user'] != self.peer_id
            sender = self.app.messenger.display_name if is_mine else self.peer_name
            # Adiciona a mensagem na área de chat com timestamp original
            self._append_message(sender, msg['content'], is_mine,
                                 timestamp=msg['timestamp'],
                                 msg_id=msg.get('msg_id', ''),
                                 reply_to=msg.get('reply_to_id', ''))
        # Marca todas as mensagens deste contato como lidas no banco
        self.messenger.mark_as_read(self.peer_id)

    # Desenha o avatar do contato no canvas do cabeçalho.
    # Prioridade: foto personalizada (base64 da rede) > círculo colorido com inicial.
    # Usa antialias 2x com PIL; fallback para oval tkinter sem PIL.
    def _draw_peer_avatar(self):
        # Busca dados do contato (índice de cor e foto personalizada em base64)
        contact = self.messenger.db.get_contact(self.peer_id)
        idx = contact.get('avatar_index', 0) if contact else 0  # índice da cor do avatar
        avatar_data_b64 = contact.get('avatar_data', '') if contact else ''  # foto base64
        color, _ = AVATAR_COLORS[idx % len(AVATAR_COLORS)]  # cor do avatar padrão
        initial = self.peer_name[0].upper() if self.peer_name else 'U'  # inicial do nome
        self._chat_avatar_canvas.delete('all')  # limpa o canvas antes de redesenhar

        # Tenta exibir foto personalizada sincronizada via rede (thumbnail JPEG em base64)
        if HAS_PIL and avatar_data_b64:
            try:
                import base64
                from io import BytesIO
                raw = base64.b64decode(avatar_data_b64)   # base64 → bytes brutos
                pil_img = Image.open(BytesIO(raw))         # abre como imagem PIL
                img = _make_circular_avatar(pil_img, 36)   # recorte circular 36x36px
                self._peer_avatar_img = ImageTk.PhotoImage(img)  # guarda referência (evita GC)
                self._chat_avatar_canvas.create_image(
                    20, 20, image=self._peer_avatar_img)   # desenha centralizado no canvas
                return  # foto ok — sai sem desenhar avatar padrão
            except Exception:
                pass  # imagem inválida/corrompida: usa avatar padrão como fallback

        # Avatar padrão com PIL: renderiza 2x e reduz para antialias suave
        if HAS_PIL:
            from PIL import ImageDraw, ImageFont
            big = 72  # tamanho interno 2x para super-sample (reduz para 36px depois)
            img_big = Image.new('RGBA', (big, big), (0, 0, 0, 0))  # fundo transparente
            draw_big = ImageDraw.Draw(img_big)
            draw_big.ellipse([0, 0, big - 1, big - 1], fill=color)  # círculo colorido
            try:
                font = ImageFont.truetype('segoeui.ttf', 28)  # tenta Segoe UI
            except Exception:
                font = ImageFont.load_default()  # fallback se fonte não disponível
            bbox = draw_big.textbbox((0, 0), initial, font=font)  # mede o texto
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]          # largura/altura do texto
            # Centraliza a inicial levando em conta o offset do bounding box
            draw_big.text(((big - tw) / 2 - bbox[0],
                           (big - th) / 2 - bbox[1]),
                          initial, fill='white', font=font)
            img = img_big.resize((36, 36), Image.LANCZOS)  # reduz 2x com antialias Lanczos
            self._peer_avatar_img = ImageTk.PhotoImage(img)
            self._chat_avatar_canvas.create_image(
                20, 20, image=self._peer_avatar_img)
        else:
            # Fallback sem PIL: oval simples do tkinter com letra da inicial em branco
            self._chat_avatar_canvas.create_oval(2, 2, 38, 38, fill=color,
                                                  outline='', width=0)
            self._chat_avatar_canvas.create_text(20, 20, text=initial,
                                                  fill='white',
                                                  font=('Segoe UI', 14, 'bold'))

    # Callback chamado pelo Text quando o conteúdo rola.
    # Atualiza a scrollbar e a esconde quando todo o conteúdo está visível.
    def _on_chat_scroll(self, first, last):
        self._chat_scrollbar.set(first, last)  # sincroniza posição da scrollbar
        # Se tudo cabe na tela (first=0, last=1), esconde a scrollbar
        if float(first) <= 0.0 and float(last) >= 1.0:
            if self._scroll_visible:
                self._chat_scrollbar.pack_forget()  # remove da tela sem destruir
                self._scroll_visible = False

    # Exibe a scrollbar se o conteúdo ultrapassar a altura visível.
    def _show_scrollbar(self, event=None):
        first, last = self.chat_text.yview()
        if first > 0.0 or last < 1.0:  # há conteúdo além do visível
            if not self._scroll_visible:
                self._chat_scrollbar.pack(side='right', fill='y')  # exibe a barra
                self.chat_text.pack_configure(padx=(0, 0))
                self._scroll_visible = True

    # Esconde a scrollbar se o mouse não estiver sobre a área de chat ou barra.
    def _hide_scrollbar(self, event=None):
        if self._scroll_visible:
            # Verifica se o ponteiro ainda está sobre o chat ou sobre a barra
            try:
                x, y = self.winfo_pointerxy()
                widget = self.winfo_containing(x, y)
                if widget and (widget == self.chat_text or
                               widget == self._chat_scrollbar):
                    return  # mouse ainda na área — não esconde
            except Exception:
                pass
            self._chat_scrollbar.pack_forget()  # esconde a scrollbar
            self._scroll_visible = False

    # Processa o scroll do mouse: rola o chat e agenda esconder a barra.
    def _on_mousewheel(self, event):
        self.chat_text.yview_scroll(-1 * (event.delta // 40), 'units')  # rola proporcionalmente
        self._show_scrollbar()  # exibe scrollbar temporariamente
        # Esconde automaticamente após 1,5 s se o mouse sair
        self.after(1500, self._hide_scrollbar)
        return 'break'  # consome o evento para não propagar

    # Retorna imagem do emoji do cache, ou renderiza e cacheia.
    def _get_chat_emoji(self, emoji_char, bg_color=None):
        cache_key = f'{emoji_char}_{bg_color}' if bg_color else emoji_char
        if cache_key in self._chat_emoji_cache:
            return self._chat_emoji_cache[cache_key]
        img = self._render_emoji_image(emoji_char, size=20, bg_color=bg_color)
        if img:
            self._chat_emoji_cache[cache_key] = img
        return img

    # Retorna imagem do emoji para o input (tamanho 18px), cacheada.
    def _get_entry_emoji(self, emoji_char):
        if emoji_char in self._entry_emoji_cache:
            return self._entry_emoji_cache[emoji_char]
        img = self._render_emoji_image(emoji_char, size=18)
        if img:
            self._entry_emoji_cache[emoji_char] = img
        return img

    # Insere emoji como imagem PIL colorida no campo de entrada de texto.
    # Cria nome único, registra no mapa interno para reconstrução do texto ao enviar.
    # Fallback: insere caractere unicode puro se PIL não disponível.
    def _entry_insert_emoji(self, emoji_char, pos='insert'):
        img = self._get_entry_emoji(emoji_char)  # obtém/gera imagem 18px do emoji
        if img:
            img_name = f'entry_emoji_{len(self._entry_img_map)}'  # nome único para a imagem
            self._entry_img_map[img_name] = emoji_char   # mapeia nome → caractere emoji
            self.entry.image_create(pos, image=img, name=img_name, padx=1)  # insere inline
        else:
            self.entry.insert(pos, emoji_char)  # fallback: texto unicode puro

    # Lê o conteúdo do campo de entrada reconstruindo emojis a partir das imagens.
    # Percorre todos os tokens do widget Text (texto puro e imagens embutidas).
    # Imagens são convertidas de volta ao caractere emoji via o mapa interno.
    # Retorna a string completa pronta para envio, sem espaços nas extremidades.
    def _get_entry_content(self):
        result = []
        # Itera sobre todos os elementos: textos e imagens embutidas no widget
        for key, value, index in self.entry.dump('1.0', 'end', image=True, text=True):
            if key == 'text':
                result.append(value)  # trecho de texto puro
            elif key == 'image':
                emoji = self._entry_img_map.get(value, '')  # imagem → emoji char
                result.append(emoji)
        return ''.join(result).strip()  # string completa sem espaços extras

    # Insere texto no chat substituindo emojis Unicode por imagens PIL coloridas.
    # Divide o texto com regex: partes textuais recebem 'tag'; emojis viram imagens inline.
    # Fallback para texto simples se PIL não disponível ou emoji não renderizável.
    def _insert_text_with_emojis(self, text, tag):
        bg = self.chat_text.tag_cget(tag, 'background') or self.chat_text.cget('bg')
        # Primeiro divide por URL; cada pedaco nao-URL passa pelo render de emoji
        last = 0
        for m in _URL_RE.finditer(text):
            if m.start() > last:
                self._insert_emoji_run(text[last:m.start()], tag, bg)
            url = m.group(0)
            self._insert_link(url, tag)
            last = m.end()
        if last < len(text):
            self._insert_emoji_run(text[last:], tag, bg)

    # Insere um pedaco de texto (sem URLs) aplicando emojis coloridos.
    def _insert_emoji_run(self, text, tag, bg):
        parts = _EMOJI_RE.split(text)
        emojis = _EMOJI_RE.findall(text)
        for i, part in enumerate(parts):
            if part:
                self.chat_text.insert('end', part, tag)
            if i < len(emojis):
                img = self._get_chat_emoji(emojis[i], bg_color=bg)
                if img:
                    mark = self.chat_text.index('end-1c')
                    self.chat_text.image_create('end', image=img, padx=1)
                    self.chat_text.tag_add(tag, mark, 'end-1c')
                else:
                    self.chat_text.insert('end', emojis[i], tag)

    # Insere uma URL clicavel com tag unica.
    def _insert_link(self, url, base_tag):
        n = getattr(self, '_link_counter', 0) + 1
        self._link_counter = n
        link_tag = f'link_{n}'
        bg = self.chat_text.tag_cget(base_tag, 'background') or self.chat_text.cget('bg')
        self.chat_text.tag_configure(link_tag, foreground='#0066cc',
                                     underline=True, background=bg)
        start = self.chat_text.index('end-1c')
        self.chat_text.insert('end', url, (base_tag, link_tag))
        self.chat_text.tag_bind(link_tag, '<Button-1>',
                                lambda e, u=url: _open_url(u))
        self.chat_text.tag_bind(link_tag, '<Enter>',
                                lambda e: self.chat_text.config(cursor='hand2'))
        self.chat_text.tag_bind(link_tag, '<Leave>',
                                lambda e: self.chat_text.config(cursor=''))

    # Adiciona uma mensagem à área de chat com formatação e suporte a emojis.
    #
    # O estilo visual é determinado pela preferência 'msg_style' salva no banco:
    # - 'bubble': WhatsApp-style com bolhas coloridas (meu=direita, peer=esquerda)
    # - 'linear': LAN Messenger clássico (nome + hora acima do texto da mensagem)
    #
    # O widget fica em state='disabled' para bloquear edição pelo usuário. É
    # temporariamente habilitado para inserir a mensagem e depois desabilitado novamente.
    def _append_message(self, sender, text, is_mine, timestamp=None,
                        msg_id='', reply_to=''):
        ts = datetime.fromtimestamp(timestamp or time.time()).strftime('%H:%M')
        self.chat_text.configure(state='normal')  # habilita temporariamente para inserção

        # Renderiza quote de reply se houver
        if reply_to:
            orig = self.messenger.db.get_message_by_id(reply_to)
            if orig:
                q_sender = orig.get('from_user', '')
                q_text = orig.get('content', '')[:80]
                if q_sender == self.messenger.user_id:
                    q_name = self.messenger.display_name
                else:
                    q_name = self.peer_name
                self.chat_text.insert('end', f'{q_name}\n', 'quote_name')
                self.chat_text.insert('end', f'{q_text}\n', 'quote')

        style = self.messenger.db.get_setting('msg_style', 'bubble')

        if style == 'bubble':
            # --- Modo bolha (WhatsApp-style) ---
            # Tags diferentes para lado esquerdo (peer) e direito (próprio)
            if is_mine:
                name_tag = 'my_bubble_name'
                time_tag = 'my_bubble_time'
                msg_tag = 'my_bubble'
            else:
                name_tag = 'peer_bubble_name'
                time_tag = 'peer_bubble_time'
                msg_tag = 'peer_bubble'
            self.chat_text.insert('end', f'{sender}', name_tag)
            self.chat_text.insert('end', f'  {ts}\n', time_tag)
            body_start = self.chat_text.index('end-1c')
            self._insert_text_with_emojis(text, msg_tag)
            body_end = self.chat_text.index('end-1c')
            self.chat_text.insert('end', '\n', msg_tag)
        else:
            # --- Modo linear (padrão LAN Messenger) ---
            tag = 'my_name' if is_mine else 'peer_name'
            self.chat_text.insert('end', f'{sender}', tag)
            self.chat_text.insert('end', f'  {ts}\n', 'time')
            body_start = self.chat_text.index('end-1c')
            self._insert_text_with_emojis(text, 'msg')
            body_end = self.chat_text.index('end-1c')
            self.chat_text.insert('end', '\n', 'msg')

        # Tag unica por mensagem: habilita hover copy + modo selecao
        n = len(self._msg_data)
        msg_tag_name = f'msg_{n}'
        self.chat_text.tag_add(msg_tag_name,
                               self.chat_text.index(f'{body_start}'),
                               self.chat_text.index(f'{body_end}'))
        start_mark = f'mstart_{n}'
        end_mark = f'mend_{n}'
        self.chat_text.mark_set(start_mark, body_start)
        self.chat_text.mark_set(end_mark, body_end)
        self.chat_text.mark_gravity(start_mark, 'left')
        self.chat_text.mark_gravity(end_mark, 'right')
        self._msg_ranges_idx.append((start_mark, end_mark))
        self.chat_text.tag_bind(msg_tag_name, '<Enter>',
                                lambda e, idx=n: self._on_msg_hover_enter(idx))
        self.chat_text.tag_bind(msg_tag_name, '<Leave>',
                                lambda e, idx=n: self._on_msg_hover_leave(idx))

        self._msg_ranges.append(text)        # salva texto para funcionalidade copiar
        self._msg_data.append({'msg_id': msg_id, 'sender': sender,
                               'text': text, 'is_mine': is_mine,
                               'timestamp': timestamp or time.time()})
        self.chat_text.insert('end', '\n')   # linha em branco entre mensagens
        self.chat_text.configure(state='disabled')  # bloqueia edição novamente
        self.chat_text.see('end')            # rola para mostrar a última mensagem

    # Copia texto da mensagem clicada.
    def _on_copy_click(self, event):
        try:
            idx = self.chat_text.index(f'@{event.x},{event.y}')
            # Pega a linha atual e copia
            line_start = self.chat_text.index(f'{idx} linestart')
            line_end = self.chat_text.index(f'{idx} lineend')
            text = self.chat_text.get(line_start, line_end).strip()
            if text:
                self.clipboard_clear()
                self.clipboard_append(text)
        except Exception:
            log.exception('Erro ao copiar mensagem')

    # Chamado pelo app quando uma nova mensagem é recebida do contato.
    #
    # Exibe a mensagem no chat, marca como lida no banco e toca o bipe do sistema
    # se a janela não estiver em foco (útil para notificar o usuário em background).
    # Este método é sempre chamado na main thread via app._safe().
    def receive_message(self, content, timestamp=None, reply_to='', msg_id=''):
        self._append_message(self.peer_name, content, False,
                             timestamp=timestamp, msg_id=msg_id,
                             reply_to=reply_to)
        self.messenger.mark_as_read(self.peer_id)
        if self.focus_get() is None:
            self.bell()   # bipe do sistema quando a janela está sem foco

    # Atualiza o label de 'está digitando...' no cabeçalho da janela.
    #
    # Chamado via callbacks de rede quando recebe MT_TYPING do contato.
    # Exibe o nome do peer + ' está digitando...' ou limpa o label.
    def set_typing(self, is_typing):
        self.lbl_typing.config(
            text=f'{self.peer_name} {_t("typing")}' if is_typing else '')

    # Envia a mensagem ao pressionar Enter (sem Shift). Shift+Enter = nova linha.
    def _on_enter(self, event):
        if not (event.state & 0x1):  # 0x1 = bit do Shift — se não pressionado, envia
            self._send_message()
            return 'break'  # consome evento para não inserir nova linha

    # <<Modified>> dispara SEMPRE que o conteudo do tk.Text muda.
    # Isso inclui: teclado, IME, Windows Emoji Picker (Win+.), paste, etc.
    # <KeyRelease> NAO dispara para IME/Emoji Picker, por isso usamos <<Modified>>.
    def _on_modified(self, event):
        # Reseta o flag de modificação (obrigatório para que o evento dispare novamente)
        try:
            self.entry.edit_modified(False)
        except Exception:
            pass
        # Agenda scan com delay para que o widget esteja estável após a modificação
        self.after(30, self._do_emoji_scan)

    # <KeyRelease> usado APENAS para gerenciar o indicador 'digitando...'.
    # Não processa emojis — isso é feito pelo <<Modified>>.
    def _on_key_typing(self, event):
        try:
            # Gerencia indicador 'digitando...' para o contato
            if not self._was_typing:
                self._was_typing = True
                threading.Thread(target=self.messenger.send_typing,
                                 args=(self.peer_id, True),
                                 daemon=True).start()
            if self._typing_timer:
                self.after_cancel(self._typing_timer)
            self._typing_timer = self.after(2000, self._stop_typing)
        except Exception:
            log.exception('Erro em _on_key_typing')

    # Executa o scan de emojis no campo de entrada.
    def _do_emoji_scan(self):
        try:
            _scan_entry_emojis(self.entry, self._entry_emoji_cache,
                               self._entry_img_map, prefix='entry_emoji', size=18)
        except Exception:
            pass

    # Para o indicador de digitação e notifica o contato.
    def _stop_typing(self):
        self._was_typing = False  # redefine flag
        # Notifica o contato que paramos de digitar (em thread separada)
        threading.Thread(target=self.messenger.send_typing,
                         args=(self.peer_id, False),
                         daemon=True).start()

    # Mostra barra de reply acima do campo de entrada (estilo WhatsApp)
    def _show_reply_bar(self, msg_id, sender, text_preview):
        self._reply_to = {'msg_id': msg_id, 'sender': sender,
                          'text': text_preview}
        if self._reply_bar:
            self._reply_bar.destroy()
        outer = tk.Frame(self, bg='#2451a0')
        outer.pack(fill='x', side='bottom', after=self._input_outer, padx=8, pady=(0, 2))
        bar = tk.Frame(outer, bg='#e2e8f0')
        bar.pack(fill='both', expand=True, padx=(3, 0))
        tk.Label(bar, text=sender,
                 font=('Segoe UI', 9, 'bold'), bg='#e2e8f0',
                 fg='#2451a0', anchor='w').pack(fill='x', padx=8, pady=(4, 0))
        preview = text_preview[:80] if text_preview else '[Mensagem]'
        tk.Label(bar, text=preview,
                 font=('Segoe UI', 8), bg='#e2e8f0',
                 fg='#4a5568', anchor='w').pack(fill='x', padx=8, pady=(0, 4))
        btn_x = tk.Button(bar, text='\u2715', font=('Segoe UI', 8, 'bold'),
                           bg='#e2e8f0', fg='#718096', relief='flat', bd=0,
                           cursor='hand2', command=self._cancel_reply)
        btn_x.place(relx=1.0, x=-6, y=4, anchor='ne')
        self._reply_bar = outer

    # Remove barra de reply
    def _cancel_reply(self):
        self._reply_to = None
        if self._reply_bar:
            self._reply_bar.destroy()
            self._reply_bar = None

    # Clique direito no chat: mostra menu contexto (Responder / Copiar / Selecionar)
    def _on_chat_right_click(self, event):
        if self._img_click_handled:
            self._img_click_handled = False
            return
        idx = self.chat_text.index(f'@{event.x},{event.y}')
        self._ctx_click_index = idx
        self._ctx_msg_idx = self._find_msg_idx_at_xy(event.x, event.y)
        msg_idx = self._ctx_msg_idx
        if 0 <= msg_idx < len(self._msg_data) and self._msg_data[msg_idx].get('is_mine'):
            self._chat_ctx.entryconfigure(0, state='disabled')
        else:
            self._chat_ctx.entryconfigure(0, state='normal')
        self._chat_ctx.tk_popup(event.x_root, event.y_root)

    # Encontra indice da mensagem na posicao da linha clicada
    def _find_msg_at_line(self, click_line):
        # Percorre mensagens de tras pra frente procurando a mais proxima
        total_lines = int(self.chat_text.index('end').split('.')[0])
        # Conta linhas por mensagem (estimativa: cada msg ocupa ~3-5 linhas)
        # Abordagem simples: cada _msg_data entry corresponde a blocos sequenciais
        if not self._msg_data:
            return -1
        # Busca reversa: ultima mensagem cujo bloco comeca antes da linha clicada
        return max(0, min(len(self._msg_data) - 1,
                          click_line // 4))  # estimativa conservadora

    # Contexto: Responder mensagem clicada
    def _ctx_reply(self):
        idx = getattr(self, '_ctx_msg_idx', -1)
        if idx < 0 or idx >= len(self._msg_data):
            return
        data = self._msg_data[idx]
        if data.get('msg_id'):
            self._show_reply_bar(data['msg_id'], data['sender'], data['text'])
            self.entry.focus_set()

    # Contexto: Copiar texto da mensagem clicada
    def _ctx_copy(self):
        idx = getattr(self, '_ctx_msg_idx', -1)
        if idx < 0 or idx >= len(self._msg_data):
            return
        text = self._msg_data[idx].get('text', '')
        if text:
            self.clipboard_clear()
            self.clipboard_append(text)

    # Contexto: Entra em modo selecao com a mensagem clicada ja marcada
    def _ctx_select(self):
        idx = getattr(self, '_ctx_msg_idx', -1)
        if idx < 0 or idx >= len(self._msg_data):
            return
        self._enter_selection_mode(idx)

    # ========================================
    # HOVER COPY + SELECTION MODE
    # ========================================

    def _on_msg_hover_enter(self, idx):
        if self._selection_mode:
            return
        self._cancel_hover_hide()
        self._show_hover_copy(idx)

    def _on_msg_hover_leave(self, idx):
        if self._selection_mode:
            return
        self._schedule_hover_hide()

    def _cancel_hover_hide(self):
        if self._hover_hide_after:
            try:
                self.after_cancel(self._hover_hide_after)
            except Exception:
                pass
            self._hover_hide_after = None

    def _schedule_hover_hide(self):
        self._cancel_hover_hide()
        self._hover_hide_after = self.after(180, self._hide_hover_copy)

    def _hide_hover_copy(self):
        try:
            self._hover_copy_btn.place_forget()
        except Exception:
            pass
        self._hover_copy_visible_idx = None

    def _show_hover_copy(self, idx):
        if idx < 0 or idx >= len(self._msg_ranges_idx):
            return
        start_mark, end_mark = self._msg_ranges_idx[idx]
        try:
            bbox = self.chat_text.bbox(start_mark)
            if not bbox:
                return
            x, y, w, h = bbox
            # Posiciona no canto superior direito da linha da mensagem
            chat_w = self.chat_text.winfo_width()
            btn_x = max(4, chat_w - 32)
            btn_y = max(2, y - 2)
            self._hover_copy_btn.place(in_=self.chat_text, x=btn_x, y=btn_y)
            self._hover_copy_visible_idx = idx
        except Exception:
            pass

    def _on_hover_copy_click(self, event):
        idx = self._hover_copy_visible_idx
        if idx is None or idx >= len(self._msg_data):
            return
        text = self._msg_data[idx].get('text', '')
        if not text:
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        # Feedback visual: muda para check por 600ms
        original = self._hover_copy_btn.cget('text')
        self._hover_copy_btn.config(text='\u2714', fg='#2a7f3f')
        self.after(600, lambda: self._hover_copy_btn.config(text=original, fg='#4a5568'))

    # --- Long-press detection ---
    def _on_chat_press(self, event):
        if self._selection_mode:
            # Em modo selecao: clique toggla a mensagem sob o cursor
            idx = self._find_msg_idx_at_xy(event.x, event.y)
            if idx >= 0:
                self._toggle_msg_selection(idx)
            return 'break'
        self._long_press_origin = (event.x, event.y)
        self._long_press_msg_idx = self._find_msg_idx_at_xy(event.x, event.y)
        if self._long_press_after:
            try:
                self.after_cancel(self._long_press_after)
            except Exception:
                pass
        if self._long_press_msg_idx >= 0:
            self._long_press_after = self.after(500, self._long_press_fire)

    def _on_chat_motion(self, event):
        if self._long_press_after and self._long_press_origin:
            ox, oy = self._long_press_origin
            if abs(event.x - ox) > 5 or abs(event.y - oy) > 5:
                try:
                    self.after_cancel(self._long_press_after)
                except Exception:
                    pass
                self._long_press_after = None

    def _on_chat_release(self, event):
        if self._long_press_after:
            try:
                self.after_cancel(self._long_press_after)
            except Exception:
                pass
            self._long_press_after = None

    def _long_press_fire(self):
        self._long_press_after = None
        idx = self._long_press_msg_idx
        if idx is None or idx < 0:
            return
        # Limpa selecao nativa de texto antes de entrar em modo selecao
        try:
            self.chat_text.tag_remove('sel', '1.0', 'end')
        except Exception:
            pass
        self._enter_selection_mode(idx)

    # Encontra o indice da mensagem correspondente a uma coordenada (x,y).
    def _find_msg_idx_at_xy(self, x, y):
        try:
            click_idx = self.chat_text.index(f'@{x},{y}')
        except Exception:
            return -1
        return self._find_msg_idx_at_index(click_idx)

    def _find_msg_idx_at_index(self, click_idx):
        # Procura a ultima mensagem cujo start_mark esta <= click_idx
        best = -1
        for i, (sm, em) in enumerate(self._msg_ranges_idx):
            try:
                s = self.chat_text.index(sm)
                e = self.chat_text.index(em)
            except Exception:
                continue
            if self.chat_text.compare(click_idx, '>=', s) and \
               self.chat_text.compare(click_idx, '<=', e):
                return i
            if self.chat_text.compare(click_idx, '>=', s):
                best = i
        return best

    # --- Selection mode ---
    def _enter_selection_mode(self, initial_idx):
        if self._selection_mode:
            self._toggle_msg_selection(initial_idx)
            return
        self._selection_mode = True
        self._selection_set = set()
        self._hide_hover_copy()
        self._build_selection_bar()
        self._toggle_msg_selection(initial_idx)

    def _build_selection_bar(self):
        if self._selection_bar is not None:
            return
        bar = tk.Frame(self, bg='#0f2a5c', height=34)
        bar.pack(fill='x', side='top', before=self.chat_text.master)
        self._sel_count_lbl = tk.Label(
            bar, text='1 selecionada', font=('Segoe UI', 9, 'bold'),
            bg='#0f2a5c', fg='#ffffff')
        self._sel_count_lbl.pack(side='left', padx=10, pady=6)
        btn_copy = tk.Button(
            bar, text='\U0001f4cb Copiar', font=('Segoe UI', 9),
            bg='#1a3f7a', fg='#ffffff', relief='flat', bd=0,
            cursor='hand2', padx=10, pady=3,
            activebackground='#2451a0', activeforeground='#ffffff',
            command=self._selection_copy)
        btn_copy.pack(side='left', padx=4, pady=4)
        btn_fwd = tk.Button(
            bar, text='\u27a4 Encaminhar', font=('Segoe UI', 9),
            bg='#1a3f7a', fg='#ffffff', relief='flat', bd=0,
            cursor='hand2', padx=10, pady=3,
            activebackground='#2451a0', activeforeground='#ffffff',
            command=self._selection_forward)
        btn_fwd.pack(side='left', padx=4, pady=4)
        btn_cancel = tk.Button(
            bar, text='\u2715 Cancelar', font=('Segoe UI', 9),
            bg='#7a1a1a', fg='#ffffff', relief='flat', bd=0,
            cursor='hand2', padx=10, pady=3,
            activebackground='#a02424', activeforeground='#ffffff',
            command=self._exit_selection_mode)
        btn_cancel.pack(side='right', padx=10, pady=4)
        self._selection_bar = bar

    def _toggle_msg_selection(self, idx):
        if idx < 0 or idx >= len(self._msg_ranges_idx):
            return
        sm, em = self._msg_ranges_idx[idx]
        if idx in self._selection_set:
            self._selection_set.discard(idx)
            self.chat_text.tag_remove('selected_msg',
                                      self.chat_text.index(sm),
                                      self.chat_text.index(em))
        else:
            self._selection_set.add(idx)
            self.chat_text.tag_add('selected_msg',
                                   self.chat_text.index(sm),
                                   self.chat_text.index(em))
        self._update_selection_count()
        if not self._selection_set:
            self._exit_selection_mode()

    def _update_selection_count(self):
        if self._sel_count_lbl:
            n = len(self._selection_set)
            label = f'{n} selecionada' if n == 1 else f'{n} selecionadas'
            self._sel_count_lbl.config(text=label)

    def _exit_selection_mode(self, *args):
        if not self._selection_mode:
            return
        # Remove highlight de todas
        for idx in list(self._selection_set):
            if idx < len(self._msg_ranges_idx):
                sm, em = self._msg_ranges_idx[idx]
                try:
                    self.chat_text.tag_remove('selected_msg',
                                              self.chat_text.index(sm),
                                              self.chat_text.index(em))
                except Exception:
                    pass
        self._selection_set.clear()
        self._selection_mode = False
        if self._selection_bar is not None:
            try:
                self._selection_bar.destroy()
            except Exception:
                pass
            self._selection_bar = None
            self._sel_count_lbl = None

    def _on_escape_selection(self, event):
        if self._selection_mode:
            self._exit_selection_mode()
            return 'break'

    def _collect_selected_messages(self):
        out = []
        for idx in sorted(self._selection_set):
            if idx < len(self._msg_data):
                d = self._msg_data[idx]
                ts = datetime.fromtimestamp(
                    d.get('timestamp') or time.time()).strftime('%H:%M')
                out.append(f"[{ts}] {d.get('sender','')}: {d.get('text','')}")
        return out

    def _selection_copy(self):
        lines = self._collect_selected_messages()
        if not lines:
            return
        text = '\n'.join(lines)
        self.clipboard_clear()
        self.clipboard_append(text)
        self._exit_selection_mode()

    def _selection_forward(self):
        msgs = [self._msg_data[i]['text'] for i in sorted(self._selection_set)
                if i < len(self._msg_data) and self._msg_data[i].get('text')]
        if not msgs:
            return
        self._open_forward_dialog(msgs)
        self._exit_selection_mode()

    def _open_forward_dialog(self, messages):
        dlg = tk.Toplevel(self)
        dlg.title('Encaminhar mensagens')
        dlg.configure(bg='#f5f7fa')
        dlg.geometry('320x420')
        dlg.transient(self)
        dlg.grab_set()
        tk.Label(dlg, text=f'Encaminhar {len(messages)} mensagem(ns) para:',
                 font=('Segoe UI', 10, 'bold'),
                 bg='#f5f7fa', fg='#1a202c').pack(padx=12, pady=(12, 6), anchor='w')
        list_frame = tk.Frame(dlg, bg='#ffffff', bd=1, relief='solid')
        list_frame.pack(fill='both', expand=True, padx=12, pady=4)
        lb = tk.Listbox(list_frame, font=('Segoe UI', 9),
                        bg='#ffffff', fg='#1a202c',
                        selectbackground='#1e66d0',
                        selectforeground='#ffffff',
                        bd=0, relief='flat', activestyle='none')
        lb.pack(fill='both', expand=True)
        targets = []  # list of (kind, id, label)
        # Contatos online
        for uid, info in self.app.peer_info.items():
            if uid == self.messenger.user_id:
                continue
            name = info.get('display_name', uid)
            status = info.get('status', 'offline')
            if status == 'offline':
                continue
            targets.append(('peer', uid, f'\U0001f464 {name}'))
        # Grupos abertos
        for gid, gw in self.app.group_windows.items():
            try:
                name = gw.group_info.get('name', gid)
            except Exception:
                name = gid
            targets.append(('group', gid, f'\U0001f465 {name}'))
        for t in targets:
            lb.insert('end', t[2])
        btn_frame = tk.Frame(dlg, bg='#f5f7fa')
        btn_frame.pack(fill='x', padx=12, pady=10)

        def _send():
            sel = lb.curselection()
            if not sel:
                return
            kind, ident, _ = targets[sel[0]]
            body = '[Encaminhada]\n' + '\n'.join(messages)
            try:
                if kind == 'peer':
                    self.messenger.send_message(ident, body)
                else:
                    self.messenger.send_group_message(ident, body)
            except Exception:
                log.exception('Erro ao encaminhar')
            dlg.destroy()

        tk.Button(btn_frame, text='Enviar', font=('Segoe UI', 9, 'bold'),
                  bg='#1a3f7a', fg='#ffffff', relief='flat', bd=0,
                  cursor='hand2', padx=14, pady=4,
                  activebackground='#2451a0', activeforeground='#ffffff',
                  command=_send).pack(side='right', padx=4)
        tk.Button(btn_frame, text='Cancelar', font=('Segoe UI', 9),
                  bg='#e2e8f0', fg='#4a5568', relief='flat', bd=0,
                  cursor='hand2', padx=14, pady=4,
                  command=dlg.destroy).pack(side='right', padx=4)
        dlg.bind('<Escape>', lambda e: dlg.destroy())

    # Envia o conteúdo do campo de entrada para o contato.
    # Reconstrói emojis das imagens, limpa o campo e dispara envio em thread.
    def _send_message(self):
        content = self._get_entry_content()
        pending_img = self._pending_image
        if not content and not pending_img:
            return
        reply_to_id = self._reply_to['msg_id'] if self._reply_to else ''
        self._cancel_reply()
        self._cancel_image_preview()
        self.entry.delete('1.0', 'end')
        self._entry_img_map.clear()
        if content:
            self._append_message(self.messenger.display_name, content, True,
                                 reply_to=reply_to_id)
            threading.Thread(target=self.messenger.send_message,
                             args=(self.peer_id, content, reply_to_id),
                             daemon=True).start()
        if pending_img:
            self._send_clipboard_image(pending_img)

    # Abre diálogo de seleção de arquivo e inicia transferência p2p para o contato.
    def _send_file(self):
        filepath = filedialog.askopenfilename(parent=self, title='Enviar arquivo')
        if filepath:
            self.app._start_file_send(self.peer_id, filepath)  # inicia transferência

    # Abre janela de histórico completo com as últimas 500 mensagens.
    #
    # Exibe em formato texto puro: [YYYY-MM-DD HH:MM:SS] Nome: mensagem.
    # Somente leitura (state='disabled'). Fecha com Escape.
    def _show_history(self):
        all_history = self.messenger.get_chat_history(self.peer_id, limit=5000)
        t = THEMES.get(self.app._current_theme, THEMES.get('MB Contabilidade', {}))
        header_bg = t.get('chat_header_bg', t.get('bg_header', '#0f2a5c'))
        header_fg = t.get('chat_header_fg', '#ffffff')
        win_bg = t.get('bg_window', '#f5f7fa')

        win = tk.Toplevel(self)
        win.title(f'Histórico - {self.peer_name}')
        _center_window(win, 560, 500)
        win.configure(bg=win_bg)
        win.bind('<Escape>', lambda e: win.destroy())
        _apply_rounded_corners(win)
        ico = _get_icon_path()
        if ico:
            try:
                win.iconbitmap(ico)
            except Exception:
                pass

        # Header
        hdr = tk.Frame(win, bg=header_bg)
        hdr.pack(fill='x')
        tk.Label(hdr, text=f'  \U0001f4dc  Histórico - {self.peer_name}',
                 font=('Segoe UI', 11, 'bold'), bg=header_bg, fg=header_fg,
                 anchor='w').pack(fill='x', padx=8, pady=8)

        # Toolbar: busca + datas
        toolbar = tk.Frame(win, bg=win_bg)
        toolbar.pack(fill='x', padx=8, pady=(8, 4))

        # Busca
        tk.Label(toolbar, text='\U0001f50d', font=('Segoe UI', 10),
                 bg=win_bg).pack(side='left')
        search_var = tk.StringVar()
        search_entry = tk.Entry(toolbar, textvariable=search_var,
                                font=('Segoe UI', 10), width=20)
        search_entry.pack(side='left', padx=(4, 12), fill='x', expand=True)
        search_entry.focus_set()

        # Contagem de resultados
        count_lbl = tk.Label(toolbar, text='', font=('Segoe UI', 9),
                             bg=win_bg, fg='#666666')
        count_lbl.pack(side='right', padx=(8, 0))

        # Datas De/Até
        date_frame = tk.Frame(win, bg=win_bg)
        date_frame.pack(fill='x', padx=8, pady=(0, 4))

        tk.Label(date_frame, text='De:', font=('Segoe UI', 9),
                 bg=win_bg).pack(side='left')
        date_from_var = tk.StringVar()
        date_from = tk.Entry(date_frame, textvariable=date_from_var,
                             font=('Segoe UI', 9), width=12)
        date_from.pack(side='left', padx=(4, 12))
        date_from.insert(0, 'dd/mm/aaaa')
        date_from.config(fg='#999999')

        tk.Label(date_frame, text='Até:', font=('Segoe UI', 9),
                 bg=win_bg).pack(side='left')
        date_to_var = tk.StringVar()
        date_to = tk.Entry(date_frame, textvariable=date_to_var,
                           font=('Segoe UI', 9), width=12)
        date_to.pack(side='left', padx=(4, 0))
        date_to.insert(0, 'dd/mm/aaaa')
        date_to.config(fg='#999999')

        # Placeholder behavior
        def _on_focus_in(entry, var, placeholder):
            if entry.get() == placeholder:
                entry.delete(0, 'end')
                entry.config(fg='#000000')
        def _on_focus_out(entry, var, placeholder):
            if not entry.get().strip():
                entry.insert(0, placeholder)
                entry.config(fg='#999999')

        ph = 'dd/mm/aaaa'
        date_from.bind('<FocusIn>', lambda e: _on_focus_in(date_from, date_from_var, ph))
        date_from.bind('<FocusOut>', lambda e: _on_focus_out(date_from, date_from_var, ph))
        date_to.bind('<FocusIn>', lambda e: _on_focus_in(date_to, date_to_var, ph))
        date_to.bind('<FocusOut>', lambda e: _on_focus_out(date_to, date_to_var, ph))

        # Separador
        tk.Frame(win, bg='#cccccc', height=1).pack(fill='x', padx=8)

        # Area de texto
        txt_frame = tk.Frame(win, bg=win_bg)
        txt_frame.pack(fill='both', expand=True, padx=8, pady=(4, 8))
        txt = tk.Text(txt_frame, font=FONT_SMALL, wrap='word', bg='#ffffff',
                      relief='flat', bd=0, padx=8, pady=4)
        scr = ttk.Scrollbar(txt_frame, command=txt.yview, style='Clean.Vertical.TScrollbar')
        txt.configure(yscrollcommand=scr.set)
        scr.pack(side='right', fill='y')
        txt.pack(fill='both', expand=True)
        txt.tag_configure('highlight', background='#fff176', foreground='#000000')
        txt.tag_configure('ts', foreground='#888888')
        txt.tag_configure('me', foreground='#0d47a1', font=('Segoe UI', 9, 'bold'))
        txt.tag_configure('peer', foreground='#2e7d32', font=('Segoe UI', 9, 'bold'))

        def _parse_date(s):
            s = s.strip()
            if not s or s == ph:
                return None
            try:
                parts = s.split('/')
                if len(parts) == 3:
                    return datetime(int(parts[2]), int(parts[1]), int(parts[0]))
            except (ValueError, IndexError):
                pass
            return None

        def _refresh(*_args):
            query = search_var.get().strip().lower()
            d_from = _parse_date(date_from.get())
            d_to = _parse_date(date_to.get())
            if d_to:
                d_to = d_to.replace(hour=23, minute=59, second=59)

            txt.configure(state='normal')
            txt.delete('1.0', 'end')
            match_count = 0
            total = 0

            for m in all_history:
                ts_dt = datetime.fromtimestamp(m['timestamp'])
                if d_from and ts_dt < d_from:
                    continue
                if d_to and ts_dt > d_to:
                    continue

                ts_str = ts_dt.strftime('%d/%m/%Y %H:%M:%S')
                who = 'Você' if m['is_sent'] else self.peer_name
                content = m['content']

                if query and query not in content.lower() and query not in who.lower():
                    continue

                total += 1
                is_image = m.get('msg_type') == 'image'
                display_content = '[Imagem]' if is_image else content
                line = f'[{ts_str}] {who}: {display_content}\n'
                start_idx = txt.index('end-1c')
                txt.insert('end', f'[{ts_str}] ', 'ts')
                who_tag = 'me' if m['is_sent'] else 'peer'
                txt.insert('end', f'{who}: ', who_tag)
                if is_image:
                    tag_img = f'hist_img_{total}'
                    txt.insert('end', '[Imagem]\n', tag_img)
                    txt.tag_config(tag_img, foreground='#1976d2', underline=True)
                    txt.tag_bind(tag_img, '<Button-1>',
                                 lambda e, p=content: os.startfile(p) if os.path.exists(p) else None)
                    txt.tag_bind(tag_img, '<Enter>',
                                 lambda e: txt.config(cursor='hand2'))
                    txt.tag_bind(tag_img, '<Leave>',
                                 lambda e: txt.config(cursor=''))
                else:
                    txt.insert('end', f'{content}\n')

                # Highlight matches
                if query:
                    line_start = txt.index(f'{start_idx} linestart')
                    line_end = txt.index(f'{start_idx} lineend +1c')
                    full_line = txt.get(line_start, line_end).lower()
                    search_start = 0
                    while True:
                        pos = full_line.find(query, search_start)
                        if pos < 0:
                            break
                        h_start = f'{line_start}+{pos}c'
                        h_end = f'{line_start}+{pos + len(query)}c'
                        txt.tag_add('highlight', h_start, h_end)
                        match_count += 1
                        search_start = pos + 1

            txt.configure(state='disabled')

            if query:
                count_lbl.config(text=f'{match_count} ocorrências em {total} mensagens')
            elif d_from or d_to:
                count_lbl.config(text=f'{total} mensagens')
            else:
                count_lbl.config(text=f'{len(all_history)} mensagens')

        search_var.trace_add('write', _refresh)
        date_from_var.trace_add('write', _refresh)
        date_to_var.trace_add('write', _refresh)
        _refresh()

    # Abre o diálogo de configuração de fonte, capturando quaisquer exceções.
    def _change_font(self):
        try:
            self._change_font_impl()
        except Exception:
            log.exception('Erro ao abrir dialogo de fonte')

    # Implementação do diálogo de fonte.
    #
    # Permite escolher família (Listbox com todas as fontes do sistema),
    # tamanho (radiobuttons) e cor (colorchooser). Preview em tempo real.
    # Aplica ao tag 'msg' do chat e ao campo de entrada desta janela.
    def _change_font_impl(self):
        win = tk.Toplevel(self)
        win.title(_t('font_btn'))
        win.resizable(False, False)
        _center_window(win, 340, 420)
        win.configure(bg=BG_WINDOW)
        win.transient(self)
        try:
            win.grab_set()
        except Exception:
            pass
        win.bind('<Escape>', lambda e: win.destroy())

        cur_family = 'Segoe UI'
        cur_size = 9
        try:
            cur = self.chat_text.cget('font') or FONT_CHAT
            if isinstance(cur, str):
                f = tkfont.Font(font=cur)
                cur_family = f.actual('family')
                cur_size = f.actual('size')
            elif isinstance(cur, (tuple, list)) and len(cur) >= 2:
                cur_family = cur[0]
                cur_size = int(cur[1])
        except Exception:
            log.exception('Erro ao ler fonte atual')

        # Font family list
        tk.Label(win, text='Fonte:', font=FONT, bg=BG_WINDOW).pack(
            anchor='w', padx=8, pady=(8, 2))
        family_var = tk.StringVar(value=cur_family)
        family_frame = tk.Frame(win, bg=BG_WINDOW)
        family_frame.pack(fill='x', padx=8)
        family_list = tk.Listbox(family_frame, font=FONT_SMALL, height=10,
                                 exportselection=False)
        family_scroll = ttk.Scrollbar(family_frame, command=family_list.yview, style='Clean.Vertical.TScrollbar')
        family_list.configure(yscrollcommand=family_scroll.set)
        family_scroll.pack(side='right', fill='y')
        family_list.pack(fill='x', expand=True)

        families = sorted(set(tkfont.families()), key=str.lower)
        for fam in families:
            family_list.insert('end', fam)
        # Select current
        for i, fam in enumerate(families):
            if fam.lower() == cur_family.lower():
                family_list.selection_set(i)
                family_list.see(i)
                break

        # Size
        tk.Label(win, text='Tamanho:', font=FONT, bg=BG_WINDOW).pack(
            anchor='w', padx=8, pady=(6, 2))
        size_var = tk.IntVar(value=cur_size)
        size_frame = tk.Frame(win, bg=BG_WINDOW)
        size_frame.pack(fill='x', padx=8)
        for s in [8, 9, 10, 11, 12, 14, 16, 18, 20]:
            tk.Radiobutton(size_frame, text=str(s), variable=size_var,
                           value=s, font=FONT_SMALL, bg=BG_WINDOW
                           ).pack(side='left', padx=2)

        # Color
        cur_color = self.entry.cget('fg') or FG_BLACK
        color_var = [cur_color]

        color_frame = tk.Frame(win, bg=BG_WINDOW)
        color_frame.pack(fill='x', padx=8, pady=(6, 2))
        tk.Label(color_frame, text='Cor da letra:', font=FONT,
                 bg=BG_WINDOW).pack(side='left')
        color_swatch = tk.Label(color_frame, text='   ', bg=cur_color,
                                relief='sunken', width=4)
        color_swatch.pack(side='left', padx=6)

        def pick_color():
            result = colorchooser.askcolor(color=color_var[0], parent=win,
                                           title='Cor da letra')
            if result[1]:
                color_var[0] = result[1]
                color_swatch.configure(bg=result[1])
                update_preview()

        tk.Button(color_frame, text='Escolher...', font=FONT_SMALL,
                  command=pick_color).pack(side='left', padx=4)

        # Preview
        preview = tk.Label(win, text='AaBbCc 123', relief='sunken',
                           bg='#ffffff', fg=cur_color, height=2)
        preview.pack(fill='x', padx=8, pady=8)

        def update_preview(*_):
            try:
                sel = family_list.curselection()
                fam = families[sel[0]] if sel else cur_family
                sz = size_var.get()
                preview.configure(font=(fam, sz), fg=color_var[0])
            except Exception:
                log.exception('Erro ao atualizar preview de fonte')

        family_list.bind('<<ListboxSelect>>', update_preview)
        size_var.trace_add('write', update_preview)
        update_preview()

        def apply():
            try:
                sel = family_list.curselection()
                fam = families[sel[0]] if sel else cur_family
                sz = size_var.get()
                new_font = (fam, sz)
                fg = color_var[0]
                self.chat_text.tag_configure('msg', font=new_font, foreground=fg)
                self.entry.configure(font=new_font, fg=fg)
            except Exception:
                log.exception('Erro ao aplicar fonte')
            win.destroy()

        btn_frame = tk.Frame(win, bg=BG_WINDOW)
        btn_frame.pack(fill='x', padx=8, pady=(0, 8))
        tk.Button(btn_frame, text='OK', font=FONT, width=8,
                  command=apply).pack(side='right', padx=4)
        tk.Button(btn_frame, text='Cancelar', font=FONT, width=8,
                  command=win.destroy).pack(side='right')

    # Abre o seletor de emojis, com captura de exceções.
    def _show_emoji_picker(self):
        try:
            self._show_emoji_picker_impl()
        except Exception:
            log.exception('Erro ao abrir emoji picker')

    # Cria ícone usando Segoe MDL2 Assets (fonte de ícones nativa do Windows).
    def _create_mdl2_icon(self, char, size=18, color='#718096'):
        try:
            from PIL import ImageDraw, ImageFont
            font_path = 'C:/Windows/Fonts/segmdl2.ttf'
            if not os.path.exists(font_path):
                font_path = 'C:/Windows/Fonts/SegoeIcons.ttf'
            if not os.path.exists(font_path):
                return None
            s = size * 4  # super-sample
            font = ImageFont.truetype(font_path, s - 4)
            img = Image.new('RGBA', (s, s), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            bbox = draw.textbbox((0, 0), char, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            x = (s - tw) // 2 - bbox[0]
            y = (s - th) // 2 - bbox[1]
            r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
            draw.text((x, y), char, font=font, fill=(r, g, b, 255))
            img = img.resize((size, size), Image.LANCZOS)
            return ImageTk.PhotoImage(img)
        except Exception:
            log.exception('Erro ao criar ícone MDL2')
            return None

    # Desenha ícone de clipe/anexo profissional com PIL.
    def _create_clip_icon(self, size, color, bg_color):
        try:
            from PIL import ImageDraw
            s = size * 8  # super-sample para anti-alias
            img = Image.new('RGBA', (s, s), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
            pen = (r, g, b, 255)
            w = s // 12
            cx = s * 0.5
            # Outer loop
            ow = s * 0.22
            ot, ob = s * 0.15, s * 0.85
            draw.arc([cx - ow, ot, cx + ow, ot + ow * 2], 180, 0, fill=pen, width=w)
            draw.line([(cx - ow, ot + ow), (cx - ow, ob - ow)], fill=pen, width=w)
            draw.arc([cx - ow, ob - ow * 2, cx + ow, ob], 0, 180, fill=pen, width=w)
            draw.line([(cx + ow, ob - ow), (cx + ow, s * 0.28 + s * 0.11)], fill=pen, width=w)
            # Inner loop
            iw = s * 0.11
            it, ib = s * 0.28, s * 0.72
            draw.arc([cx - iw, it, cx + iw, it + iw * 2], 180, 0, fill=pen, width=w)
            draw.line([(cx - iw, it + iw), (cx - iw, ib - iw)], fill=pen, width=w)
            draw.arc([cx - iw, ib - iw * 2, cx + iw, ib], 0, 180, fill=pen, width=w)
            draw.line([(cx + iw, ib - iw), (cx + iw, it + iw)], fill=pen, width=w)
            # Rotacionar (inclinado como referência)
            img = img.rotate(35, resample=Image.BICUBIC, expand=True,
                             fillcolor=(0, 0, 0, 0))
            bbox = img.getbbox()
            if bbox:
                img = img.crop(bbox)
            mx = max(img.size)
            out = Image.new('RGBA', (mx, mx), (0, 0, 0, 0))
            out.paste(img, ((mx - img.size[0]) // 2, (mx - img.size[1]) // 2))
            out = out.resize((size, size), Image.LANCZOS)
            return ImageTk.PhotoImage(out)
        except Exception:
            log.exception('Erro ao criar ícone de clipe')
            return None

    # Renderiza um emoji Unicode como PhotoImage colorida via PIL (método de instância).
    #
    # Versão de instância usada por _get_chat_emoji() e _get_entry_emoji() com
    # cache por janela. Usa seguiemj.ttf com embedded_color=True para renderizar
    # os emojis com suas cores reais (tecnologia COLR/CPAL da fonte Segoe UI Emoji).
    def _render_emoji_image(self, emoji_char, size=28, bg_color=None):
        if not HAS_PIL:
            return None
        try:
            from PIL import ImageFont, ImageDraw
            font_path = 'C:/Windows/Fonts/seguiemj.ttf'
            if not os.path.exists(font_path):
                return None
            clean = emoji_char.replace('\ufe0f', '')
            font = ImageFont.truetype(font_path, size)
            tmp = Image.new('RGBA', (size * 3, size * 3), (255, 255, 255, 0))
            d = ImageDraw.Draw(tmp)
            bbox = d.textbbox((0, 0), clean, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            canvas_sz = size + 4
            if bg_color:
                r, g, b = self._hex_to_rgb(bg_color)
                bg = (r, g, b, 255)
            else:
                bg = (255, 255, 255, 0)
            img = Image.new('RGBA', (canvas_sz, canvas_sz), bg)
            draw = ImageDraw.Draw(img)
            x = (canvas_sz - tw) // 2 - bbox[0]
            y = (canvas_sz - th) // 2 - bbox[1]
            draw.text((x, y), clean, font=font, embedded_color=True)
            return ImageTk.PhotoImage(img)
        except Exception:
            log.exception('Erro ao renderizar emoji')
            return None

    @staticmethod
    def _hex_to_rgb(hex_color):
        hex_color = hex_color.lstrip('#')
        return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))

    # Cria o popup do seletor de emojis com grade clicável e campo de busca.
    #
    # Posicionado próximo ao botão de emoji. Cada emoji é exibido como imagem PIL
    # colorida (ou texto Unicode como fallback). Clicar num emoji insere-o no campo
    # de entrada via _entry_insert_emoji(). Fecha ao clicar fora (FocusOut).
    def _show_emoji_picker_impl(self):
        popup = tk.Toplevel(self)
        popup.title('Emoticons')
        popup.resizable(False, False)
        popup.configure(bg='#f0f0f0')
        popup.transient(self)

        x = self.winfo_rootx() + 10
        y = self.winfo_rooty() + 50
        popup.geometry(f'280x230+{x}+{y}')

        # Cache de imagens de emoji para evitar garbage collection
        popup._emoji_images = {}

        # Nomes em português para busca
        _emoji_names = {
            '\U0001f600': 'sorriso feliz', '\U0001f603': 'sorriso olhos abertos',
            '\U0001f604': 'sorriso olhos sorrindo', '\U0001f601': 'sorriso radiante',
            '\U0001f606': 'rindo', '\U0001f605': 'rindo suando',
            '\U0001f602': 'chorando de rir lagrimas', '\U0001f923': 'rolando de rir',
            '\U0001f60a': 'sorrindo corado', '\U0001f607': 'anjo aureola',
            '\U0001f609': 'piscando piscadela', '\U0001f60d': 'olhos de coracao apaixonado',
            '\U0001f929': 'estrelas nos olhos', '\U0001f60e': 'oculos escuros legal cool',
            '\U0001f618': 'mandando beijo beijinho', '\U0001f617': 'beijando',
            '\U0001f61a': 'beijo olhos fechados',
            '\U0001f60b': 'delicioso gostoso lingua', '\U0001f61b': 'lingua pra fora',
            '\U0001f61c': 'lingua piscando', '\U0001f92a': 'maluco doido louco',
            '\U0001f61d': 'nojo lingua olhos fechados',
            '\U0001f911': 'dinheiro cifrao rico', '\U0001f917': 'abraco',
            '\U0001f914': 'pensando pensativo hmm', '\U0001f910': 'boca fechada ziper',
            '\U0001f928': 'sobrancelha levantada desconfiado',
            '\U0001f610': 'neutro sem expressao', '\U0001f611': 'inexpressivo',
            '\U0001f636': 'sem boca', '\U0001f60f': 'sorriso de lado debochado',
            '\U0001f612': 'descontente chateado', '\U0001f644': 'revirando olhos',
            '\U0001f62c': 'cara de grimace', '\U0001f925': 'mentiroso pinoquio',
            '\U0001f60c': 'aliviado', '\U0001f614': 'pensativo triste',
            '\U0001f62a': 'sonolento sono', '\U0001f924': 'babando baba',
            '\U0001f634': 'dormindo zzz', '\U0001f637': 'mascara doente',
            '\U0001f912': 'termometro febre', '\U0001f915': 'machucado bandagem',
            '\U0001f922': 'enjoado nausea', '\U0001f92e': 'vomitando',
            '\U0001f927': 'espirrando espirro gripe', '\U0001f975': 'quente calor',
            '\U0001f976': 'frio congelando gelado', '\U0001f974': 'tonto zonzo',
            '\U0001f620': 'bravo irritado', '\U0001f621': 'raiva furioso vermelho',
            '\U0001f624': 'triunfante bufando', '\U0001f622': 'chorando triste',
            '\U0001f62d': 'chorando muito', '\U0001f616': 'confuso',
            '\U0001f623': 'cansado perseverante', '\U0001f625': 'desapontado aliviado',
            '\U0001f628': 'assustado medo', '\U0001f631': 'gritando horror',
            '\U0001f630': 'ansioso suando', '\U0001f629': 'exausto cansado',
            '\U0001f62b': 'cansado exausto', '\U0001f633': 'corado envergonhado',
            '\U0001f632': 'surpreso espantado', '\U0001f61e': 'desapontado',
            '\U0001f613': 'suando frio', '\U0001f635': 'tonto x olhos',
            '\U0001f608': 'sorriso diabo', '\U0001f47f': 'diabo bravo demonio',
            '\U0001f4a9': 'coco cocô', '\U0001f921': 'palhaco',
            '\U0001f47b': 'fantasma', '\U0001f480': 'caveira cranio',
            # Gestos
            '\U0001f44d': 'positivo joinha legal like', '\U0001f44e': 'negativo ruim dislike',
            '\U0001f44a': 'soco punho', '\u270a': 'punho levantado',
            '\U0001f91b': 'punho esquerdo', '\U0001f91c': 'punho direito',
            '\U0001f44f': 'palmas aplausos parabens', '\U0001f64c': 'maos levantadas celebrar',
            '\U0001f450': 'maos abertas', '\U0001f932': 'palmas para cima',
            '\U0001f91d': 'aperto de mao', '\U0001f64f': 'orar rezar por favor',
            '\U0001f4aa': 'forca musculo braco forte', '\U0001f44b': 'acenando tchau oi',
            '\U0001f91a': 'mao levantada', '\u270b': 'mao aberta pare',
            '\U0001f596': 'vulcano spock', '\U0001f44c': 'ok perfeito',
            '\U0001f91e': 'dedos cruzados sorte', '\U0001f91f': 'te amo amor',
            '\U0001f918': 'rock chifres metal', '\U0001f448': 'apontando esquerda',
            '\U0001f449': 'apontando direita', '\U0001f446': 'apontando cima',
            '\U0001f447': 'apontando baixo', '\U0001f485': 'unha pintando esmalte',
            '\U0001f933': 'selfie', '\u270c\ufe0f': 'paz vitoria',
            '\U0001f590\ufe0f': 'mao dedos abertos', '\u261d\ufe0f': 'indicador cima',
            '\U0001f919': 'me liga telefone hang loose',
            '\U0001f9b5': 'perna', '\U0001f9b6': 'pe',
            # Comida e Bebida
            '\U0001f34e': 'maca vermelha', '\U0001f34f': 'maca verde',
            '\U0001f350': 'pera', '\U0001f34a': 'tangerina laranja',
            '\U0001f34b': 'limao', '\U0001f34c': 'banana',
            '\U0001f349': 'melancia', '\U0001f347': 'uva',
            '\U0001f353': 'morango', '\U0001f348': 'melao',
            '\U0001f352': 'cereja', '\U0001f351': 'pessego',
            '\U0001f95d': 'kiwi', '\U0001f345': 'tomate',
            '\U0001f346': 'berinjela', '\U0001f955': 'cenoura',
            '\U0001f33d': 'milho espiga', '\U0001f336\ufe0f': 'pimenta',
            '\U0001f954': 'batata', '\U0001f360': 'batata doce',
            '\U0001f950': 'croissant', '\U0001f35e': 'pao',
            '\U0001f956': 'baguete pao frances', '\U0001f9c0': 'queijo',
            '\U0001f356': 'carne osso', '\U0001f357': 'coxa frango',
            '\U0001f354': 'hamburguer', '\U0001f35f': 'batata frita',
            '\U0001f355': 'pizza', '\U0001f32d': 'cachorro quente hot dog',
            '\U0001f32e': 'taco', '\U0001f32f': 'burrito',
            '\U0001f373': 'ovo frigideira', '\U0001f958': 'panela',
            '\U0001f372': 'sopa', '\U0001f35c': 'ramen macarrao',
            '\U0001f363': 'sushi', '\U0001f371': 'bento',
            '\U0001f35b': 'curry arroz', '\U0001f35a': 'arroz',
            '\U0001f359': 'onigiri', '\U0001f370': 'bolo fatia',
            '\U0001f382': 'aniversario bolo vela', '\U0001f36e': 'pudim',
            '\U0001f36d': 'pirulito', '\U0001f36c': 'bala doce',
            '\U0001f36b': 'chocolate', '\U0001f369': 'donut rosquinha',
            '\U0001f368': 'sorvete', '\U0001f366': 'sorvete cone casquinha',
            '\U0001f367': 'raspadinha gelo',
            '\u2615': 'cafe xicara cha', '\U0001f375': 'cha verde',
            '\U0001f376': 'sake', '\U0001f37a': 'cerveja chope chopp beer',
            '\U0001f37b': 'brinde cervejas chope chopp', '\U0001f377': 'vinho taca',
            '\U0001f378': 'coquetel martini drink', '\U0001f379': 'drink tropical',
            '\U0001f37e': 'champagne garrafa', '\U0001f944': 'colher',
            '\U0001f95b': 'leite copo',
            # Corações
            '\u2764\ufe0f': 'coracao vermelho amor', '\U0001f9e1': 'coracao laranja',
            '\U0001f49b': 'coracao amarelo', '\U0001f49a': 'coracao verde',
            '\U0001f499': 'coracao azul', '\U0001f49c': 'coracao roxo',
            '\U0001f5a4': 'coracao preto', '\U0001f90e': 'coracao marrom',
            '\U0001f90d': 'coracao branco', '\U0001f494': 'coracao partido',
            '\U0001f495': 'dois coracoes', '\U0001f49e': 'coracoes girando',
            '\U0001f493': 'coracao batendo', '\U0001f497': 'coracao crescendo',
            '\U0001f496': 'coracao brilhando', '\U0001f498': 'coracao flechado cupido',
            '\U0001f48c': 'carta amor', '\U0001f48b': 'beijo marca batom',
            '\U0001f48d': 'anel alianca', '\U0001f48e': 'diamante joia',
            '\U0001f4ab': 'tontura estrela', '\U0001f4a5': 'explosao boom',
            '\U0001f4a2': 'raiva simbolo', '\U0001f4a6': 'gotas suor',
            '\U0001f4a8': 'vento sopro', '\U0001f573\ufe0f': 'buraco',
            '\U0001f4a3': 'bomba', '\U0001f4ac': 'balao fala', '\U0001f4ad': 'balao pensamento',
            '\U0001f5e8\ufe0f': 'balao comentario',
            # Viagem e Objetos
            '\U0001f697': 'carro automovel', '\U0001f695': 'taxi',
            '\U0001f68c': 'onibus', '\U0001f691': 'ambulancia',
            '\U0001f692': 'bombeiro caminhao', '\U0001f693': 'policia viatura',
            '\U0001f3ce\ufe0f': 'carro corrida formula',
            '\u2708\ufe0f': 'aviao', '\U0001f680': 'foguete',
            '\U0001f6f8': 'disco voador ufo', '\U0001f6a2': 'navio',
            '\U0001f3e0': 'casa', '\U0001f3e2': 'escritorio predio',
            '\U0001f3eb': 'escola', '\U0001f3e5': 'hospital',
            '\U0001f3ed': 'fabrica', '\u26ea': 'igreja',
            '\U0001f5fc': 'torre tokyo', '\U0001f4f1': 'celular telefone',
            '\U0001f4bb': 'computador notebook laptop', '\U0001f4f7': 'camera foto',
            '\U0001f4f9': 'camera video filmadora', '\U0001f4fa': 'televisao tv',
            '\U0001f4fb': 'radio', '\u23f0': 'despertador alarme',
            '\u231a': 'relogio', '\U0001f4a1': 'lampada ideia',
            '\U0001f526': 'lanterna', '\U0001f4b0': 'dinheiro saco',
            '\U0001f4b5': 'dinheiro nota dolar', '\U0001f4b3': 'cartao credito',
            '\U0001f4e7': 'email', '\U0001f4e8': 'email recebido',
            '\U0001f4e9': 'email enviado', '\U0001f4ce': 'clipe anexo',
            '\U0001f4c1': 'pasta', '\U0001f4c2': 'pasta aberta',
            '\U0001f4c4': 'documento pagina', '\U0001f4c5': 'calendario',
            '\U0001f4ca': 'grafico barras', '\U0001f4cb': 'prancheta',
            '\U0001f4cc': 'tachinha', '\U0001f4dd': 'memo nota escrita',
            '\u270f\ufe0f': 'lapis', '\U0001f512': 'cadeado fechado',
            '\U0001f513': 'cadeado aberto', '\U0001f527': 'chave inglesa ferramenta',
            '\U0001f528': 'martelo', '\U0001f6e0\ufe0f': 'ferramentas',
            '\u2601': 'nuvem cloud', '\U0001f327': 'nuvem chuva',
            '\U0001f328': 'nuvem neve', '\u26c5': 'sol nuvem parcialmente nublado',
            '\U0001f324': 'sol nuvem pequena', '\U0001f325': 'sol nuvem grande',
            # Símbolos e Esportes
            '\U0001f3c6': 'trofeu copa', '\U0001f3c5': 'medalha esporte',
            '\U0001f947': 'medalha ouro primeiro', '\U0001f948': 'medalha prata segundo',
            '\U0001f949': 'medalha bronze terceiro', '\u26bd': 'futebol bola',
            '\U0001f3c0': 'basquete', '\U0001f3c8': 'futebol americano',
            '\U0001f3be': 'tenis', '\U0001f3d0': 'volei',
            '\U0001f3b1': 'sinuca bilhar', '\U0001f3b3': 'boliche',
            '\U0001f3af': 'alvo dardo', '\U0001f3ae': 'videogame joystick',
            '\U0001f3b2': 'dado', '\U0001f3b0': 'caca niquel slot',
            '\U0001f3b5': 'nota musical', '\U0001f3b6': 'notas musicais musica',
            '\U0001f3a4': 'microfone karaoke', '\U0001f3a7': 'fone ouvido',
            '\U0001f3b8': 'guitarra', '\U0001f3b9': 'teclado piano',
            '\U0001f3ba': 'trompete', '\U0001f3bb': 'violino',
            '\U0001f525': 'fogo chama quente', '\U0001f4af': 'cem pontos perfeito',
            '\U0001f389': 'festa confete', '\U0001f388': 'balao festa',
            '\U0001f381': 'presente', '\U0001f380': 'laco fita',
            '\U0001f3c1': 'bandeira chegada', '\u2705': 'check verde ok',
            '\u274c': 'x vermelho errado nao', '\u26a0\ufe0f': 'aviso alerta',
            '\U0001f6ab': 'proibido', '\u2753': 'interrogacao pergunta',
            '\u2757': 'exclamacao', '\U0001f4ac': 'balao fala conversa',
            '\U0001f4ad': 'balao pensamento', '\U0001f6a9': 'bandeira triangular',
            '\U0001f3f3\ufe0f': 'bandeira branca', '\U0001f3f4': 'bandeira preta',
        }

        categories = {
            # Rostos e Pessoas
            '\U0001f600': [
                '\U0001f600', '\U0001f603', '\U0001f604', '\U0001f601',
                '\U0001f606', '\U0001f605', '\U0001f602', '\U0001f923',
                '\U0001f60a', '\U0001f607', '\U0001f609', '\U0001f60d',
                '\U0001f929', '\U0001f60e', '\U0001f618', '\U0001f617', '\U0001f61a',
                '\U0001f60b', '\U0001f61b', '\U0001f61c', '\U0001f92a',
                '\U0001f61d', '\U0001f911', '\U0001f917', '\U0001f914',
                '\U0001f910', '\U0001f928', '\U0001f610', '\U0001f611',
                '\U0001f636', '\U0001f60f', '\U0001f612', '\U0001f644',
                '\U0001f62c', '\U0001f925', '\U0001f60c', '\U0001f614',
                '\U0001f62a', '\U0001f924', '\U0001f634', '\U0001f637',
                '\U0001f912', '\U0001f915', '\U0001f922', '\U0001f92e',
                '\U0001f927', '\U0001f975', '\U0001f976', '\U0001f974',
                '\U0001f620', '\U0001f621', '\U0001f624', '\U0001f622',
                '\U0001f62d', '\U0001f616', '\U0001f623', '\U0001f625',
                '\U0001f628', '\U0001f631', '\U0001f630', '\U0001f629',
                '\U0001f62b', '\U0001f633', '\U0001f632', '\U0001f61e',
                '\U0001f613', '\U0001f635', '\U0001f608', '\U0001f47f',
                '\U0001f4a9', '\U0001f921', '\U0001f47b', '\U0001f480',
            ],
            # Gestos e Mãos
            '\U0001f44d': [
                '\U0001f44d', '\U0001f44e', '\U0001f44a', '\u270a',
                '\U0001f91b', '\U0001f91c', '\U0001f44f', '\U0001f64c',
                '\U0001f450', '\U0001f932', '\U0001f91d', '\U0001f64f',
                '\U0001f4aa', '\U0001f44b', '\U0001f91a', '\u270b',
                '\U0001f596', '\U0001f44c', '\U0001f91e', '\U0001f91f',
                '\U0001f918', '\U0001f448', '\U0001f449', '\U0001f446',
                '\U0001f447', '\U0001f485', '\U0001f933', '\u270c\ufe0f',
                '\U0001f590\ufe0f', '\u261d\ufe0f', '\U0001f919',
                '\U0001f9b5', '\U0001f9b6',
            ],
            # Comida e Bebida
            '\U0001f354': [
                '\U0001f34e', '\U0001f34f', '\U0001f350', '\U0001f34a',
                '\U0001f34b', '\U0001f34c', '\U0001f349', '\U0001f347',
                '\U0001f353', '\U0001f348', '\U0001f352', '\U0001f351',
                '\U0001f95d', '\U0001f345', '\U0001f346', '\U0001f955',
                '\U0001f33d', '\U0001f336\ufe0f', '\U0001f954', '\U0001f360',
                '\U0001f950', '\U0001f35e', '\U0001f956', '\U0001f9c0',
                '\U0001f356', '\U0001f357', '\U0001f354', '\U0001f35f',
                '\U0001f355', '\U0001f32d', '\U0001f32e', '\U0001f32f',
                '\U0001f373', '\U0001f958', '\U0001f372', '\U0001f35c',
                '\U0001f363', '\U0001f371', '\U0001f35b', '\U0001f35a',
                '\U0001f359', '\U0001f370', '\U0001f382', '\U0001f36e',
                '\U0001f36d', '\U0001f36c', '\U0001f36b', '\U0001f369',
                '\U0001f368', '\U0001f366', '\U0001f367',
                '\u2615', '\U0001f375', '\U0001f376', '\U0001f37a',
                '\U0001f37b', '\U0001f377', '\U0001f378', '\U0001f379',
                '\U0001f37e', '\U0001f944', '\U0001f95b',
            ],
            # Corações e Amor
            '\u2764\ufe0f': [
                '\u2764\ufe0f', '\U0001f9e1', '\U0001f49b', '\U0001f49a',
                '\U0001f499', '\U0001f49c', '\U0001f5a4', '\U0001f90e',
                '\U0001f90d', '\U0001f494', '\U0001f495', '\U0001f49e',
                '\U0001f493', '\U0001f497', '\U0001f496', '\U0001f498',
                '\U0001f48c', '\U0001f48b', '\U0001f48d', '\U0001f48e',
                '\U0001f4ab', '\U0001f4a5', '\U0001f4a2', '\U0001f4a6',
                '\U0001f4a8', '\U0001f573\ufe0f', '\U0001f4a3',
                '\U0001f4ac', '\U0001f4ad', '\U0001f5e8\ufe0f',
            ],
            # Viagem e Objetos
            '\U0001f3e0': [
                '\U0001f697', '\U0001f695', '\U0001f68c', '\U0001f691',
                '\U0001f692', '\U0001f693', '\U0001f3ce\ufe0f',
                '\u2708\ufe0f', '\U0001f680', '\U0001f6f8',
                '\U0001f6a2',
                '\u2601', '\U0001f327', '\U0001f328',
                '\u26c5', '\U0001f324', '\U0001f325',
                '\U0001f3e0', '\U0001f3e2', '\U0001f3eb',
                '\U0001f3e5', '\U0001f3ed', '\u26ea', '\U0001f5fc',
                '\U0001f4f1', '\U0001f4bb', '\U0001f4f7', '\U0001f4f9',
                '\U0001f4fa', '\U0001f4fb', '\u23f0', '\u231a',
                '\U0001f4a1', '\U0001f526', '\U0001f4b0', '\U0001f4b5',
                '\U0001f4b3', '\U0001f4e7', '\U0001f4e8', '\U0001f4e9',
                '\U0001f4ce', '\U0001f4c1', '\U0001f4c2', '\U0001f4c4',
                '\U0001f4c5', '\U0001f4ca', '\U0001f4cb', '\U0001f4cc',
                '\U0001f4dd', '\u270f\ufe0f', '\U0001f512', '\U0001f513',
                '\U0001f527', '\U0001f528', '\U0001f6e0\ufe0f',
            ],
            # Símbolos e Esportes
            '\U0001f3c6': [
                '\U0001f3c6', '\U0001f3c5', '\U0001f947', '\U0001f948',
                '\U0001f949', '\u26bd', '\U0001f3c0', '\U0001f3c8',
                '\U0001f3be', '\U0001f3d0', '\U0001f3b1', '\U0001f3b3',
                '\U0001f3af', '\U0001f3ae', '\U0001f3b2', '\U0001f3b0',
                '\U0001f3b5', '\U0001f3b6', '\U0001f3a4', '\U0001f3a7',
                '\U0001f3b8', '\U0001f3b9', '\U0001f3ba', '\U0001f3bb',
                '\U0001f525', '\U0001f4af', '\U0001f389', '\U0001f388',
                '\U0001f381', '\U0001f380', '\U0001f3c1',
                '\u2705', '\u274c', '\u26a0\ufe0f', '\U0001f6ab',
                '\u2753', '\u2757', '\U0001f4ac', '\U0001f4ad',
                '\U0001f6a9', '\U0001f3f3\ufe0f', '\U0001f3f4',
            ],
        }

        # Barra de busca de emojis
        search_frame = tk.Frame(popup, bg='#ffffff')
        search_frame.pack(fill='x', padx=4, pady=(4, 2))

        search_icon = _create_mdl2_icon_static('\uE721', size=12, color='#a0aec0')
        if search_icon:
            popup._emoji_images['_search'] = search_icon
            tk.Label(search_frame, image=search_icon,
                     bg='#ffffff').pack(side='left', padx=(4, 2))

        emoji_search_var = tk.StringVar()
        emoji_search_entry = tk.Entry(search_frame, textvariable=emoji_search_var,
                                       font=('Segoe UI', 8), bg='#ffffff',
                                       fg='#1a202c', relief='flat', bd=0,
                                       insertbackground='#1a202c')
        emoji_search_entry.pack(side='left', fill='x', expand=True, ipady=2, padx=2)
        emoji_search_entry.insert(0, 'Buscar emoji...')
        emoji_search_entry.config(fg='#a0aec0')

        def _emoji_search_focus_in(e):
            if emoji_search_entry.get() == 'Buscar emoji...':
                emoji_search_entry.delete(0, 'end')
                emoji_search_entry.config(fg='#1a202c')
        def _emoji_search_focus_out(e):
            if not emoji_search_entry.get().strip():
                emoji_search_entry.insert(0, 'Buscar emoji...')
                emoji_search_entry.config(fg='#a0aec0')
        emoji_search_entry.bind('<FocusIn>', _emoji_search_focus_in)
        emoji_search_entry.bind('<FocusOut>', _emoji_search_focus_out)

        tk.Frame(popup, bg='#e2e8f0', height=1).pack(fill='x', padx=6)

        # Category tabs
        tab_frame = tk.Frame(popup, bg='#e8e8e8', bd=0, relief='flat')
        tab_frame.pack(fill='x')

        # Scrollable emoji grid
        grid_frame = tk.Frame(popup, bg='#ffffff')
        grid_frame.pack(fill='both', expand=True)

        canvas = tk.Canvas(grid_frame, bg='#ffffff', highlightthickness=0)
        inner = tk.Frame(canvas, bg='#ffffff')
        canvas.pack(fill='both', expand=True)
        canvas.create_window((0, 0), window=inner, anchor='nw')

        def insert_emoji(emoji):
            self._entry_insert_emoji(emoji)

        cat_keys = list(categories.keys())
        all_emojis = []
        for emlist in categories.values():
            all_emojis.extend(emlist)

        def _emoji_scroll(e):
            canvas.yview_scroll(-1 * (e.delta // 60), 'units')

        def _bind_wheel_recursive(widget):
            widget.bind('<MouseWheel>', _emoji_scroll)
            for child in widget.winfo_children():
                _bind_wheel_recursive(child)

        def _populate_grid(emojis):
            for w in inner.winfo_children():
                w.destroy()
            cols = 8
            for i, em in enumerate(emojis):
                r, c = divmod(i, cols)
                img = self._render_emoji_image(em, 22)
                if img:
                    popup._emoji_images[em] = img
                    btn = tk.Label(inner, image=img,
                                   bg='#ffffff', cursor='hand2',
                                   padx=2, pady=2)
                else:
                    btn = tk.Label(inner, text=em,
                                   font=('Segoe UI Emoji', 16),
                                   bg='#ffffff', cursor='hand2',
                                   padx=2, pady=2)
                btn.grid(row=r, column=c, padx=0, pady=0)
                btn.bind('<Button-1>',
                         lambda e, emoji=em: insert_emoji(emoji))
                btn.bind('<Enter>',
                         lambda e, b=btn: b.configure(bg='#e8f0fe'))
                btn.bind('<Leave>',
                         lambda e, b=btn: b.configure(bg='#ffffff'))
            inner.update_idletasks()
            canvas.configure(scrollregion=canvas.bbox('all'))
            canvas.yview_moveto(0)
            _bind_wheel_recursive(inner)

        def show_category(cat_key):
            _populate_grid(categories[cat_key])
            for b in tab_buttons:
                b.configure(bg='#e8e8e8', relief='flat')
            idx = cat_keys.index(cat_key)
            tab_buttons[idx].configure(bg='#ffffff', relief='sunken')

        def _on_emoji_search(*args):
            query = emoji_search_var.get().strip().lower()
            if query == 'buscar emoji...' or not query:
                show_category(cat_keys[0])
                return
            # Desmarcar tabs
            for b in tab_buttons:
                b.configure(bg='#e8e8e8', relief='flat')
            # Filtrar emojis por nome PT
            results = []
            for em, name in _emoji_names.items():
                if query in name:
                    results.append(em)
            if results:
                _populate_grid(results)
            else:
                _populate_grid([])

        emoji_search_var.trace_add('write', _on_emoji_search)

        tab_buttons = []
        for cat_key in cat_keys:
            tab_img = self._render_emoji_image(cat_key, 20)
            if tab_img:
                popup._emoji_images[f'tab_{cat_key}'] = tab_img
                btn = tk.Label(tab_frame, image=tab_img,
                               bg='#e8e8e8', cursor='hand2',
                               padx=8, pady=3, relief='flat')
            else:
                btn = tk.Label(tab_frame, text=cat_key,
                               font=('Segoe UI Emoji', 12),
                               bg='#e8e8e8', cursor='hand2',
                               padx=8, pady=2, relief='flat')
            btn.pack(side='left', padx=1)
            btn.bind('<Button-1>', lambda e, k=cat_key: show_category(k))
            tab_buttons.append(btn)

        canvas.bind('<MouseWheel>', _emoji_scroll)
        inner.bind('<MouseWheel>', _emoji_scroll)

        show_category(cat_keys[0])
        _bind_wheel_recursive(inner)
        popup.bind('<Escape>', lambda e: popup.destroy())

        # Fechar ao clicar fora do popup
        def _check_focus():
            if not popup.winfo_exists():
                return
            try:
                focused = popup.focus_get()
                if focused is None or not str(focused).startswith(str(popup)):
                    popup.destroy()
            except Exception:
                popup.destroy()
        popup.bind('<FocusOut>', lambda e: popup.after(100, _check_focus))
        popup.focus_set()

    # Mostra preview da imagem colada antes de enviar
    def _show_image_preview(self, img):
        try:
            self._cancel_image_preview()
            self._pending_image = img
            outer = tk.Frame(self, bg='#2451a0')
            outer.pack(fill='x', side='bottom', after=self._input_outer, padx=8, pady=(0, 2))
            bar = tk.Frame(outer, bg='#e2e8f0')
            bar.pack(fill='both', expand=True, padx=(3, 0))
            thumb = img.copy()
            thumb.thumbnail((80, 80), Image.LANCZOS)
            tk_thumb = ImageTk.PhotoImage(thumb)
            self._preview_thumb_ref = tk_thumb
            tk.Label(bar, image=tk_thumb, bg='#e2e8f0').pack(side='left', padx=6, pady=4)
            tk.Label(bar, text='Imagem pronta para enviar\nEnter para enviar',
                     font=('Segoe UI', 8), bg='#e2e8f0', fg='#4a5568',
                     anchor='w', justify='left').pack(side='left', fill='x', expand=True, padx=4)
            tk.Button(bar, text='\u2715', font=('Segoe UI', 8, 'bold'),
                      bg='#e2e8f0', fg='#718096', relief='flat', bd=0,
                      cursor='hand2', command=self._cancel_image_preview).pack(side='right', padx=4)
            self._image_preview_bar = outer
            self.entry.focus_set()
        except Exception:
            log.exception('Erro em _show_image_preview')

    def _cancel_image_preview(self):
        self._pending_image = None
        self._preview_thumb_ref = None
        if self._image_preview_bar:
            self._image_preview_bar.destroy()
            self._image_preview_bar = None

    def _on_paste(self, event):
        if not HAS_PIL:
            return
        try:
            img = _grab_clipboard_image()
            if img is not None:
                self._show_image_preview(img)
                return 'break'
        except Exception:
            log.exception('Erro em _on_paste')

    # Comprime e envia imagem do clipboard para o peer
    def _send_clipboard_image(self, img):
        # Redimensiona se muito grande
        max_dim = 1920
        if img.width > max_dim or img.height > max_dim:
            img.thumbnail((max_dim, max_dim), Image.LANCZOS)
        # Converte RGBA -> RGB (JPEG nao suporta alpha)
        if img.mode == 'RGBA':
            bg = Image.new('RGB', img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[3])
            img = bg
        elif img.mode != 'RGB':
            img = img.convert('RGB')
        # Comprime como JPEG
        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=85)
        image_bytes = buf.getvalue()
        # Limite 2MB
        if len(image_bytes) > 2 * 1024 * 1024:
            buf = io.BytesIO()
            img.save(buf, format='JPEG', quality=60)
            image_bytes = buf.getvalue()

        def _do_send():
            ok, path = self.messenger.send_image(self.peer_id, image_bytes)
            if ok and path:
                self.after(0, lambda: self._append_image(
                    self.messenger.display_name, path, True))
        threading.Thread(target=_do_send, daemon=True).start()

    # Chamado quando uma imagem e recebida do peer
    def receive_image(self, image_path, timestamp=None):
        self._append_image(self.peer_name, image_path, False, timestamp=timestamp)
        self.messenger.mark_as_read(self.peer_id)
        if self.focus_get() is None:
            self.bell()

    # Renderiza imagem no chat (thumbnail clicavel)
    def _append_image(self, sender, image_path, is_mine, timestamp=None):
        ts = datetime.fromtimestamp(timestamp or time.time()).strftime('%H:%M')
        self.chat_text.configure(state='normal')
        style = self.messenger.db.get_setting('msg_style', 'bubble')

        if style == 'bubble':
            if is_mine:
                name_tag, time_tag, msg_tag = 'my_bubble_name', 'my_bubble_time', 'my_bubble'
            else:
                name_tag, time_tag, msg_tag = 'peer_bubble_name', 'peer_bubble_time', 'peer_bubble'
        else:
            name_tag = 'my_name' if is_mine else 'peer_name'
            time_tag = 'time'
            msg_tag = 'msg'

        self.chat_text.insert('end', f'{sender}', name_tag)
        self.chat_text.insert('end', f'  {ts}\n', time_tag)

        # Carrega e redimensiona imagem para thumbnail
        try:
            pil_img = Image.open(image_path)
            max_w = 300
            if pil_img.width > max_w:
                ratio = max_w / pil_img.width
                pil_img = pil_img.resize(
                    (max_w, int(pil_img.height * ratio)), Image.LANCZOS)
            tk_img = ImageTk.PhotoImage(pil_img)
            self._image_cache[image_path] = tk_img  # evita garbage collection
            self.chat_text.image_create('end', image=tk_img, padx=4, pady=2)
            # Aplica tag de alinhamento (justify right para is_mine em bubble mode)
            img_idx = self.chat_text.index('end - 2 chars')
            self.chat_text.tag_add(msg_tag, img_idx, self.chat_text.index('end - 1 chars'))
            # Clique abre imagem no visualizador padrao do sistema
            tag_name = f'img_{id(tk_img)}'
            self.chat_text.tag_add(tag_name,
                                   self.chat_text.index('end - 2 chars'),
                                   self.chat_text.index('end - 1 chars'))
            self.chat_text.tag_config(tag_name, underline=False)
            self.chat_text.tag_bind(tag_name, '<Button-1>',
                                    lambda e, p=image_path: self._on_image_click(p))
            self.chat_text.tag_bind(tag_name, '<Button-3>',
                                    lambda e, p=image_path: self._on_image_right_click(e, p))
            self.chat_text.tag_bind(tag_name, '<Enter>',
                                    lambda e: self.chat_text.config(cursor='hand2'))
            self.chat_text.tag_bind(tag_name, '<Leave>',
                                    lambda e: self.chat_text.config(cursor=''))
        except Exception:
            self.chat_text.insert('end', '[Imagem indisponível]', msg_tag)

        self.chat_text.insert('end', '\n', msg_tag)
        self.chat_text.insert('end', '\n')
        self.chat_text.configure(state='disabled')
        self.chat_text.see('end')

    def _on_image_click(self, image_path):
        self._img_click_handled = True
        self._open_image_file(image_path)

    def _on_image_right_click(self, event, image_path):
        self._img_click_handled = True
        self._show_image_ctx(event, image_path)

    def _open_image_file(self, image_path):
        if not os.path.exists(image_path):
            return
        def _open():
            try:
                os.startfile(image_path)
            except Exception:
                try:
                    import subprocess
                    subprocess.Popen(['explorer', image_path])
                except Exception:
                    log.exception('Erro ao abrir imagem')
        threading.Thread(target=_open, daemon=True).start()

    def _show_image_ctx(self, event, image_path):
        m = tk.Menu(self, tearoff=0, font=('Segoe UI', 9))
        m.add_command(label='Abrir', command=lambda: self._open_image_file(image_path))
        m.add_command(label='Salvar como...', command=lambda: self._save_image_as(image_path))
        m.tk_popup(event.x_root, event.y_root)

    def _save_image_as(self, image_path):
        ext = os.path.splitext(image_path)[1] or '.jpg'
        dest = filedialog.asksaveasfilename(
            parent=self, title='Salvar imagem',
            defaultextension=ext,
            initialfile=os.path.basename(image_path),
            filetypes=[('Imagem JPEG', '*.jpg'), ('Imagem PNG', '*.png'), ('Todos', '*.*')])
        if dest:
            try:
                import shutil
                shutil.copy2(image_path, dest)
            except Exception:
                log.exception('Erro ao salvar imagem')

    def _on_close(self):
        # Cancela timer de typing e notifica que parou de digitar
        if self._typing_timer:
            self.after_cancel(self._typing_timer)
            self._typing_timer = None
        if self._was_typing:
            self._was_typing = False
            threading.Thread(target=self.messenger.send_typing,
                             args=(self.peer_id, False), daemon=True).start()
        if self.peer_id in self.app.chat_windows:
            del self.app.chat_windows[self.peer_id]
        self.destroy()


# =============================================================
#  GROUP CHAT WINDOW
# =============================================================
# Janela de Bate Papo em grupo (multi-participantes) - estilo LAN Messenger.
class GroupChatWindow(tk.Toplevel):

    def __init__(self, app, group_id, group_name, group_type='temp', start_hidden=False):
        super().__init__(app.root)
        if start_hidden:
            self.withdraw()
        self.app = app                  # Referência ao LanMessengerApp (janela principal)
        self.group_id = group_id        # ID único do grupo (UUID)
        self.group_name = group_name    # Nome do grupo exibido no título
        self.group_type = group_type    # 'temp' (temporário) ou 'fixed' (fixo/persistente)
        self._members = {}              # uid -> {display_name, ip, status, note} - membros ativos
        self._panel_visible = True      # Se o painel lateral de participantes está visível
        self._chat_emoji_cache = {}     # Cache de emojis renderizados para a área de chat
        self._entry_emoji_cache = {}    # Cache de emojis renderizados para o campo de entrada
        self._entry_img_map = {}        # Mapeamento img_name -> emoji_char (para converter imagens de volta para texto)
        self._participant_widgets = {}  # uid -> {frame, name_lbl, note_lbl, avatar_lbl} - widgets do painel
        self._participant_avatars = {}  # Cache de imagens de avatar dos participantes

        tipo_label = 'Fixo' if group_type == 'fixed' else 'Temporário'
        self.title(f'{group_name} ({tipo_label})')
        self.minsize(480, 380)
        _center_window(self, 620, 480)
        _apply_rounded_corners(self)
        self.protocol('WM_DELETE_WINDOW', self._on_close)
        self.bind('<Escape>', lambda e: self._on_close())
        try:
            self.app._force_taskbar_entry(self)
        except Exception:
            pass
        self.bind('<Map>', lambda e: self.app._on_group_window_mapped(self))

        ico = _get_icon_path()
        if ico:
            try:
                self.iconbitmap(ico)
            except Exception:
                pass

        t = THEMES.get(app._current_theme if hasattr(app, '_current_theme')
                       else 'MB Contabilidade',
                       THEMES.get('MB Contabilidade', {}))
        self._theme = t
        self._build_ui(t)
        self.bind('<FocusIn>', lambda e: app._stop_flash(self))

    def _build_ui(self, t):
        NAVY = '#0f2a5c'

        # ===== Header =====
        header = tk.Frame(self, bg=NAVY, bd=0)
        header.pack(fill='x')
        header._navy_panel = True
        hinner = tk.Frame(header, bg=NAVY)
        hinner.pack(fill='x', padx=10, pady=7)

        self._lbl_title = tk.Label(hinner, text=self.group_name,
                                   font=('Segoe UI', 11, 'bold'),
                                   bg=NAVY, fg='#ffffff')
        self._lbl_title.pack(side='left')

        self._lbl_count = tk.Label(hinner, text='0 participantes',
                                   font=('Segoe UI', 8),
                                   bg=NAVY, fg='#c8d6e5')
        self._lbl_count.pack(side='left', padx=(8, 0))

        # Botao toggle painel participantes
        self._btn_toggle = tk.Button(hinner, text='\u25b6',
                                     font=('Segoe UI', 9), bg='#1a3f7a',
                                     fg='#ffffff', relief='flat', bd=0,
                                     cursor='hand2', padx=6, pady=1,
                                     command=self._toggle_panel)
        self._btn_toggle.pack(side='right')
        _add_hover(self._btn_toggle, '#1a3f7a', '#2451a0')

        # Botao "Sair do Grupo" (visivel apenas para grupo fixo)
        if self.group_type == 'fixed':
            btn_leave = tk.Button(hinner, text='Sair do Grupo',
                                  font=('Segoe UI', 7),
                                  bg='#1a3f7a', fg='#8aa0cc',
                                  relief='flat', bd=0,
                                  cursor='hand2', padx=6, pady=1,
                                  activebackground='#2451a0',
                                  activeforeground='#ffffff',
                                  command=self._confirm_leave)
            btn_leave.pack(side='right', padx=(0, 6))
            _add_hover(btn_leave, '#1a3f7a', '#2451a0')

        # ===== Barra de ações (bottom - pack antes do input) =====
        win_bg = t.get('bg_window', '#f5f7fa')
        btn_frame = tk.Frame(self, bg=win_bg)
        btn_frame.pack(fill='x', side='bottom', padx=6, pady=(0, 5))

        # Botão Enviar destacado em navy
        send_bg = t.get('btn_send_bg', t.get('btn_bg', '#0f2a5c'))
        send_fg = t.get('btn_send_fg', '#ffffff')
        btn_send = tk.Button(btn_frame, text=f' {_t("send_btn")} ',
                             font=('Segoe UI', 9, 'bold'),
                             bg=send_bg, fg=send_fg,
                             relief='flat', bd=0, cursor='hand2',
                             padx=12, pady=3,
                             activebackground=t.get('btn_active', '#1a3f7a'),
                             activeforeground=send_fg,
                             command=self._send_message)
        btn_send.pack(side='right', pady=2)
        _add_hover(btn_send, '#0f2a5c', '#1a3f7a')

        # Botões flat à esquerda
        flat_fg = '#4a5568'

        # Emoji button
        _emoji_img = _render_color_emoji('\U0001f60a', 18)
        if _emoji_img:
            self._toolbar_emoji_img = _emoji_img
            btn_emoji = tk.Button(btn_frame, image=_emoji_img, relief='flat',
                                  bd=0, cursor='hand2',
                                  bg=win_bg, activebackground='#e2e8f0',
                                  command=self._show_emoji_picker)
        else:
            btn_emoji = tk.Button(btn_frame, text='\U0001f60a',
                                  font=('Segoe UI', 10), relief='flat',
                                  bd=0, cursor='hand2',
                                  bg=win_bg,
                                  command=self._show_emoji_picker)
        btn_emoji.pack(side='left', pady=2, padx=(0, 2))

        # Font button
        btn_font = tk.Button(btn_frame, text='A', font=('Segoe UI', 10, 'bold'),
                             relief='flat', bd=0, cursor='hand2',
                             bg=win_bg, fg=flat_fg,
                             activebackground='#e2e8f0',
                             command=self._change_font)
        btn_font.pack(side='left', pady=2, padx=(0, 2))

        # Attach file button
        _attach_ico = _create_mdl2_icon_static('\uE723', 18, flat_fg)
        if _attach_ico:
            self._toolbar_attach_img = _attach_ico
            btn_attach = tk.Button(btn_frame, image=_attach_ico, relief='flat',
                                   bd=0, cursor='hand2',
                                   bg=win_bg, activebackground='#e2e8f0',
                                   command=self._send_file)
        else:
            btn_attach = tk.Button(btn_frame, text='\U0001f4ce',
                                   font=('Segoe UI', 10), relief='flat',
                                   bd=0, cursor='hand2',
                                   bg=win_bg, activebackground='#e2e8f0',
                                   command=self._send_file)
        btn_attach.pack(side='left', pady=2, padx=(0, 2))

        # Botao Enquete
        btn_poll = tk.Button(btn_frame, text='\U0001f4ca', font=('Segoe UI', 10),
                             relief='flat', bd=0, cursor='hand2',
                             bg=win_bg, fg=flat_fg,
                             activebackground='#e2e8f0',
                             command=self._create_poll_dialog)
        btn_poll.pack(side='left', pady=2, padx=(0, 2))
        _Tooltip(btn_poll, 'Criar Enquete')

        # ===== Input area =====
        self._input_outer = tk.Frame(self, bg=t.get('input_border', '#e2e8f0'))
        self._input_outer.pack(side='bottom', fill='x', padx=6, pady=(2, 2))
        input_outer = self._input_outer

        self.entry = tk.Text(input_outer, font=('Segoe UI', 11),
                             bg=t.get('bg_input', '#f7fafc'),
                             fg=t.get('fg_black', '#1a202c'),
                             relief='flat', bd=0, height=3,
                             wrap='word', padx=8, pady=6,
                             insertbackground=t.get('fg_black', '#1a202c'),
                             undo=True, autoseparators=True, maxundo=-1)
        self.entry.pack(fill='both', expand=True, padx=1, pady=1)
        def _redo(e):
            try: self.entry.edit_redo()
            except tk.TclError: pass
            return 'break'
        self.entry.bind('<Control-y>', _redo)
        self.entry.bind('<Control-Y>', _redo)
        self.entry.bind('<Return>', self._on_enter)
        self.entry.bind('<Shift-Return>', lambda e: None)
        self.entry.bind('<Control-v>', self._on_paste)
        self.entry.bind('<Control-V>', self._on_paste)
        self.entry.bind('<KeyRelease>', self._on_entry_key)
        # <<Modified>> dispara SEMPRE que o conteúdo muda (teclado, IME, Win+., paste)
        self.entry.bind('<<Modified>>', self._on_modified)
        self.entry.focus_set()

        self._image_cache = {}  # path -> PhotoImage para imagens no chat
        self._reply_to = None   # {msg_id, sender, text}
        self._reply_bar = None  # Frame da barra de reply
        self._pending_image = None        # PIL Image aguardando envio (Ctrl+V preview)
        self._image_preview_bar = None    # Frame da barra de preview de imagem
        self._preview_thumb_ref = None    # referencia para evitar GC do thumbnail
        self._msg_data = []     # [{msg_id, sender, text, is_mine}] para reply
        self._img_click_handled = False
        self._mention_popup = None  # Popup de autocomplete @mencao

        # Drag & Drop de arquivos (windnd) — toplevel + entry; chat_text hook apos sua criacao
        if HAS_WINDND:
            try:
                windnd.hook_dropfiles(self, func=self._on_drop_files)
                windnd.hook_dropfiles(self.entry, func=self._on_drop_files)
                _allow_uipi_drop(self)
                _allow_uipi_drop(self.entry)
            except Exception:
                pass

        # ===== Separator =====
        tk.Frame(self, bg='#e2e8f0', height=1).pack(side='bottom', fill='x')

        # ===== Body (chat + panel) com splitter arrastavel =====
        self._paned = tk.PanedWindow(self, orient='horizontal',
                                      sashwidth=6, sashrelief='raised',
                                      bg='#e2e8f0', bd=0)
        self._paned.pack(fill='both', expand=True)

        # Chat area (left)
        chat_frame = tk.Frame(self._paned, bg=t.get('bg_chat', '#f5f7fa'))

        self.chat_text = tk.Text(chat_frame, font=('Segoe UI', 10),
                                  bg=t.get('bg_chat', '#f5f7fa'),
                                  fg=t.get('fg_msg', '#1a202c'),
                                  relief='flat', bd=0,
                                  wrap='word', state='disabled',
                                  padx=10, pady=8,
                                  selectbackground='#1e66d0',
                                  selectforeground='#ffffff',
                                  inactiveselectbackground='#1e66d0')
        sb = tk.Scrollbar(chat_frame, command=self.chat_text.yview, width=6)
        sb.pack(side='right', fill='y')
        self.chat_text.configure(yscrollcommand=sb.set)
        self.chat_text.pack(fill='both', expand=True)

        # Hook DnD tambem no chat_text (agora que ja foi criado)
        if HAS_WINDND:
            try:
                windnd.hook_dropfiles(self.chat_text, func=self._on_drop_files)
                _allow_uipi_drop(self.chat_text)
            except Exception:
                pass

        self.chat_text.tag_configure('my_name',
                                     font=('Segoe UI', 8, 'bold'),
                                     foreground='#2451a0')
        self.chat_text.tag_configure('peer_name',
                                     font=('Segoe UI', 8, 'bold'),
                                     foreground='#cc2222')
        self.chat_text.tag_configure('sys_msg',
                                     font=('Segoe UI', 8, 'italic'),
                                     foreground='#718096',
                                     justify='center')
        self.chat_text.tag_configure('time', font=('Segoe UI', 7),
                                     foreground='#718096')
        self.chat_text.tag_configure('msg', font=('Segoe UI', 10),
                                     foreground=t.get('fg_msg', '#1a202c'))

        # Tags para modo bolha (WhatsApp style) — mesmas do ChatWindow
        msg_my_bg = t.get('msg_my_bg', '#e8f0fe')
        msg_peer_bg = t.get('msg_peer_bg', '#f0f0f0')
        fg_time = '#718096'
        self.chat_text.tag_configure('my_bubble',
                                     background=msg_my_bg,
                                     justify='right', rmargin=8,
                                     lmargin1=80, lmargin2=80,
                                     spacing1=6, spacing3=2)
        self.chat_text.tag_configure('my_bubble_name',
                                     background=msg_my_bg,
                                     foreground='#2451a0',
                                     font=('Segoe UI', 8, 'bold'),
                                     justify='right', rmargin=8,
                                     lmargin1=80, lmargin2=80,
                                     spacing1=6)
        self.chat_text.tag_configure('my_bubble_time',
                                     background=msg_my_bg,
                                     foreground=fg_time,
                                     font=('Segoe UI', 7),
                                     justify='right', rmargin=8,
                                     lmargin1=80, lmargin2=80)
        self.chat_text.tag_configure('peer_bubble',
                                     background=msg_peer_bg,
                                     justify='left', lmargin1=8,
                                     lmargin2=8, rmargin=80,
                                     spacing1=6, spacing3=2)
        self.chat_text.tag_configure('peer_bubble_name',
                                     background=msg_peer_bg,
                                     foreground='#cc2222',
                                     font=('Segoe UI', 8, 'bold'),
                                     justify='left', lmargin1=8,
                                     lmargin2=8, rmargin=80,
                                     spacing1=6)
        self.chat_text.tag_configure('peer_bubble_time',
                                     background=msg_peer_bg,
                                     foreground=fg_time,
                                     font=('Segoe UI', 7),
                                     justify='left', lmargin1=8,
                                     lmargin2=8, rmargin=80)

        # Tags para quote/reply (barra azul simulada via lmargin + background)
        self.chat_text.tag_configure('quote_name',
                                     background='#e2e8f0',
                                     foreground='#2451a0',
                                     font=('Segoe UI', 8, 'bold'),
                                     lmargin1=12, lmargin2=12,
                                     rmargin=40,
                                     spacing1=4, spacing3=0)
        self.chat_text.tag_configure('quote',
                                     background='#e2e8f0',
                                     foreground='#4a5568',
                                     font=('Segoe UI', 8),
                                     lmargin1=12, lmargin2=12,
                                     rmargin=40,
                                     spacing1=0, spacing3=4)

        # Tag para @mencao destacada
        self.chat_text.tag_configure('mention',
                                     foreground='#2451a0',
                                     font=('Segoe UI', 10, 'bold'))

        self.chat_text.tag_configure('selected_msg', background='#fff3b0')
        try:
            self.chat_text.tag_raise('sel')
        except tk.TclError:
            pass

        # Estado de copy-hover + selection mode (mesmo padrao da ChatWindow)
        self._msg_ranges_idx = []
        self._link_counter = 0
        self._selection_mode = False
        self._selection_set = set()
        self._selection_bar = None
        self._sel_count_lbl = None
        self._long_press_after = None
        self._long_press_origin = None
        self._long_press_msg_idx = None

        self._hover_copy_btn = tk.Label(
            self.chat_text, text='\uE8C8', font=('Segoe MDL2 Assets', 9),
            bg='#f0f0f0', fg='#666666', cursor='hand2', bd=0, relief='flat',
            padx=2, pady=0)
        self._hover_copy_btn.bind('<Button-1>', self._on_hover_copy_click)
        self._hover_copy_btn.bind('<Enter>', lambda e: self._cancel_hover_hide())
        self._hover_copy_btn.bind('<Leave>', lambda e: self._schedule_hover_hide())
        self._hover_copy_visible_idx = None
        self._hover_hide_after = None

        self.chat_text.bind('<ButtonPress-1>', self._on_chat_press, add='+')
        self.chat_text.bind('<B1-Motion>', self._on_chat_motion, add='+')
        self.chat_text.bind('<ButtonRelease-1>', self._on_chat_release, add='+')
        self.bind('<Escape>', self._on_escape_selection, add='+')

        # Menu de contexto no chat (Responder / Copiar / Selecionar)
        self._chat_ctx = tk.Menu(self, tearoff=0, font=('Segoe UI', 9))
        self._chat_ctx.add_command(label='Responder', command=self._ctx_reply)
        self._chat_ctx.add_command(label='Copiar', command=self._ctx_copy)
        self._chat_ctx.add_command(label='Selecionar', command=self._ctx_select)
        self.chat_text.bind('<Button-3>', self._on_chat_right_click)
        self._ctx_click_index = None

        # ===== Participants panel (right) =====
        self._panel = tk.Frame(self._paned, bg='#f8fafc', width=250)
        self._panel.pack_propagate(False)

        # Panel header
        ph = tk.Frame(self._panel, bg='#edf2f7')
        ph.pack(fill='x')
        tk.Label(ph, text='Participantes', font=('Segoe UI', 9, 'bold'),
                 bg='#edf2f7', fg='#2d3748').pack(side='left', padx=8, pady=5)

        btn_add = tk.Button(ph, text='+', font=('Segoe UI', 10, 'bold'),
                            bg='#edf2f7', fg='#2451a0', relief='flat',
                            bd=0, cursor='hand2', padx=6,
                            command=self._add_participants_dialog)
        btn_add.pack(side='right', padx=4)
        _add_hover(btn_add, '#edf2f7', '#e2e8f0')

        # Panel scrollable list
        self._panel_canvas = tk.Canvas(self._panel, bg='#f8fafc',
                                        highlightthickness=0)
        self._panel_inner = tk.Frame(self._panel_canvas, bg='#f8fafc')
        self._panel_canvas.pack(fill='both', expand=True)
        self._panel_canvas.create_window((0, 0), window=self._panel_inner,
                                          anchor='nw', tags='inner')
        self._panel_inner.bind('<Configure>',
            lambda e: self._panel_canvas.configure(
                scrollregion=self._panel_canvas.bbox('all')))
        self._panel_canvas.bind('<Configure>',
            lambda e: self._panel_canvas.itemconfig('inner', width=e.width))
        self._panel_canvas.bind('<MouseWheel>',
            lambda e: self._panel_canvas.yview_scroll(-1*(e.delta//120), 'units'))

        # Add panes to PanedWindow
        self._paned.add(chat_frame, minsize=300)
        self._paned.add(self._panel, minsize=150, width=250)

    # ===== Panel toggle =====
    def _toggle_panel(self):
        if self._panel_visible:
            self._paned.forget(self._panel)
            self._btn_toggle.config(text='\u25c0')
            self._panel_visible = False
        else:
            self._paned.add(self._panel, minsize=150, width=250)
            self._btn_toggle.config(text='\u25b6')
            self._panel_visible = True

    # ===== Members =====
    def add_member(self, uid, display_name, info=None):
        self._members[uid] = {
            'display_name': display_name,
            'ip': info.get('ip', '') if info else '',
            'status': info.get('status', 'online') if info else 'online',
            'note': info.get('note', '') if info else '',
        }
        self._lbl_count.config(text=f'{len(self._members)} participante(s)')
        self._add_participant_widget(uid)

    # Remove membro do grupo e do painel de participantes.
    def remove_member(self, uid):
        if uid in self._members:
            del self._members[uid]
        if uid in self._participant_widgets:
            try:
                self._participant_widgets[uid]['frame'].destroy()
            except Exception:
                pass
            del self._participant_widgets[uid]
        self._lbl_count.config(text=f'{len(self._members)} participante(s)')

    # Atualiza info de um membro (nota, status, etc).
    def update_member_info(self, uid, info):
        if uid not in self._members:
            return
        self._members[uid]['display_name'] = info.get('display_name',
            self._members[uid]['display_name'])
        self._members[uid]['status'] = info.get('status', 'online')
        self._members[uid]['note'] = info.get('note', '')
        self._refresh_participant_widget(uid)

    # Cria widget de participante no painel.
    def _add_participant_widget(self, uid):
        member = self._members[uid]
        name = member['display_name']
        note = member.get('note', '')
        status = member.get('status', 'online')

        row = tk.Frame(self._panel_inner, bg='#f8fafc')
        row.pack(fill='x', padx=4, pady=2)

        # Avatar
        avatar = self._create_member_avatar(uid, name, status)
        av_lbl = tk.Label(row, image=avatar, bg='#f8fafc')
        av_lbl.pack(side='left', padx=(4, 6), pady=2)

        # Name + Note
        info_frame = tk.Frame(row, bg='#f8fafc')
        info_frame.pack(side='left', fill='x', expand=True)

        name_lbl = tk.Label(info_frame, text=name, font=('Segoe UI', 8, 'bold'),
                            bg='#f8fafc', fg='#2d3748', anchor='w')
        name_lbl.pack(fill='x')

        note_txt = tk.Text(info_frame, font=('Segoe UI', 7, 'italic'),
                           bg='#f8fafc', fg='#718096', relief='flat', bd=0,
                           height=1, wrap='none', highlightthickness=0,
                           state='disabled', cursor='arrow')
        note_txt.bind("<FocusIn>", lambda e: self.focus_set())
        if note:
            note_txt.config(state='normal')
            note_txt.insert('1.0', note)
            note_txt.config(state='disabled')
            note_txt.pack(fill='x')
            _scan_entry_emojis(note_txt, self._chat_emoji_cache, {}, prefix=f'part_note_{uid}', size=12)

        self._participant_widgets[uid] = {
            'frame': row, 'name_lbl': name_lbl,
            'note_txt': note_txt, 'avatar_lbl': av_lbl
        }

    # Atualiza widget de participante existente.
    def _refresh_participant_widget(self, uid):
        if uid not in self._participant_widgets:
            return
        member = self._members[uid]
        w = self._participant_widgets[uid]
        w['name_lbl'].config(text=member['display_name'])
        note = member.get('note', '')
        w['note_txt'].config(state='normal')
        w['note_txt'].delete('1.0', 'end')
        if note:
            w['note_txt'].insert('1.0', note)
            _scan_entry_emojis(w['note_txt'], self._chat_emoji_cache, {}, prefix=f'part_note_{uid}', size=12)
            w['note_txt'].config(state='disabled')
            w['note_txt'].pack(fill='x')
        else:
            w['note_txt'].config(state='disabled')
            w['note_txt'].pack_forget()
        # Atualizar avatar com status
        avatar = self._create_member_avatar(uid, member['display_name'],
                                             member.get('status', 'online'))
        w['avatar_lbl'].config(image=avatar)

    # Cria avatar 30x30 para painel de participantes.
    def _create_member_avatar(self, uid, name, status='online'):
        size = 30
        dot_size = 8
        dot_colors = {
            'online': '#48bb78', 'away': '#ecc94b',
            'busy': '#f56565', 'offline': '#a0aec0',
        }
        contact = self.app.messenger.db.get_contact(uid)
        idx = contact.get('avatar_index', 0) if contact else 0
        av_color, _ = AVATAR_COLORS[idx % len(AVATAR_COLORS)]

        if HAS_PIL:
            from PIL import ImageDraw, ImageFont
            img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            draw.ellipse([1, 1, size - 2, size - 2], fill=av_color,
                         outline='#0f2a5c', width=1)
            initial = name[0].upper() if name else 'U'
            try:
                font = ImageFont.truetype('segoeui.ttf', 12)
            except Exception:
                font = ImageFont.load_default()
            bbox = draw.textbbox((0, 0), initial, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            draw.text(((size - tw) / 2 - bbox[0],
                       (size - th) / 2 - bbox[1]),
                      initial, fill='white', font=font)
            dot_color = dot_colors.get(status, '#a0aec0')
            dx, dy = size - dot_size - 1, size - dot_size - 1
            draw.ellipse([dx - 1, dy - 1, dx + dot_size + 1, dy + dot_size + 1],
                         fill='white')
            draw.ellipse([dx, dy, dx + dot_size, dy + dot_size],
                         fill=dot_color)
            photo = ImageTk.PhotoImage(img)
        else:
            photo = tk.PhotoImage(width=size, height=size)

        self._participant_avatars[f'{uid}_{status}'] = photo
        return photo

    # ===== Add participants dialog =====
    def _add_participants_dialog(self):
        NAVY = '#0f2a5c'
        win = tk.Toplevel(self)
        win.title('Adicionar Participantes')
        win.transient(self)
        win.grab_set()
        win.configure(bg='#f5f7fa')
        _center_window(win, 300, 380)
        _apply_rounded_corners(win)
        win.resizable(False, False)
        win.bind('<Escape>', lambda e: win.destroy())

        header = tk.Frame(win, bg=NAVY)
        header.pack(fill='x')
        tk.Label(header, text='Adicionar ao Grupo', font=('Segoe UI', 10, 'bold'),
                 bg=NAVY, fg='#ffffff').pack(padx=10, pady=8)

        content = tk.Frame(win, bg='#f5f7fa')
        content.pack(fill='both', expand=True, padx=8, pady=8)

        peer_vars = {}
        # Filtrar peers que ja estao no grupo
        existing_uids = set(self._members.keys())
        for uid, info in self.app.peer_info.items():
            if uid in existing_uids:
                continue
            if info.get('status', 'offline') == 'offline':
                continue
            var = tk.BooleanVar(value=False)
            peer_vars[uid] = var
            row = tk.Frame(content, bg='#ffffff')
            row.pack(fill='x', pady=1)
            cb = tk.Checkbutton(row, text=f"  {info.get('display_name', uid)}",
                                variable=var, font=('Segoe UI', 9),
                                bg='#ffffff', fg='#1a202c',
                                activebackground='#ffffff', anchor='w',
                                selectcolor='#ffffff')
            cb.pack(fill='x', padx=4, pady=2)

        if not peer_vars:
            tk.Label(content, text='Nenhum contato disponivel',
                     font=('Segoe UI', 9, 'italic'),
                     bg='#f5f7fa', fg='#718096').pack(pady=20)

        def add_selected():
            new_ids = [uid for uid, var in peer_vars.items() if var.get()]
            if not new_ids:
                win.destroy()
                return
            group = self.app.messenger._groups.get(self.group_id)
            # Adicionar novos membros
            for uid in new_ids:
                info = self.app.peer_info.get(uid, {})
                name = info.get('display_name', uid)
                self.add_member(uid, name, info)
                self.system_message(f'{name} entrou no grupo.')
                # Atualizar lista no messenger
                if group:
                    group['members'].append({
                        'uid': uid,
                        'display_name': name,
                        'ip': info.get('ip', '')
                    })
                # Notificar membros existentes sobre novo membro
                self.app.messenger.notify_group_join(
                    self.group_id, uid, name)
            # Enviar convite para novos membros com lista completa
            if group:
                for uid in new_ids:
                    info = self.app.peer_info.get(uid, {})
                    ip = info.get('ip', '')
                    if ip:
                        from network import TCPClient, TCP_PORT, MT_GROUP_INV
                        TCPClient.send_message(ip, TCP_PORT, {
                            'type': MT_GROUP_INV,
                            'from_user': self.app.messenger.user_id,
                            'display_name': self.app.messenger.display_name,
                            'group_id': self.group_id,
                            'group_name': self.group_name,
                            'group_type': self.group_type,
                            'members': group['members'],
                        })
            win.destroy()

        btn_frame = tk.Frame(win, bg='#f5f7fa')
        btn_frame.pack(fill='x', padx=8, pady=8)
        btn_add = tk.Button(btn_frame, text='Adicionar',
                            font=('Segoe UI', 9, 'bold'),
                            bg=NAVY, fg='#ffffff', relief='flat',
                            bd=0, padx=14, pady=4, cursor='hand2',
                            command=add_selected)
        btn_add.pack(side='left')
        _add_hover(btn_add, NAVY, '#1a3f7a')
        btn_cancel = tk.Button(btn_frame, text='Cancelar',
                               font=('Segoe UI', 9),
                               bg='#e2e8f0', fg='#4a5568', relief='flat',
                               bd=0, padx=14, pady=4, cursor='hand2',
                               command=win.destroy)
        btn_cancel.pack(side='left', padx=(6, 0))
        _add_hover(btn_cancel, '#e2e8f0', '#cbd5e0')

    # ===== Emoji — renderização e cache de emojis coloridos =====
    # Renderiza um emoji Unicode como imagem colorida (PIL + seguiemj.ttf).
    # Igual à versão module-level _render_color_emoji(), mas como método de instância.
    def _render_emoji_image(self, emoji_char, size=28, bg_color=None):
        if not HAS_PIL:
            return None
        try:
            from PIL import ImageFont, ImageDraw
            font_path = 'C:/Windows/Fonts/seguiemj.ttf'  # Fonte Segoe UI Emoji do Windows
            if not os.path.exists(font_path):
                return None
            clean = emoji_char.replace('\ufe0f', '')
            font = ImageFont.truetype(font_path, size)
            tmp = Image.new('RGBA', (size * 3, size * 3), (255, 255, 255, 0))
            d = ImageDraw.Draw(tmp)
            bbox = d.textbbox((0, 0), clean, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            canvas_sz = size + 4
            if bg_color:
                r, g, b = self._hex_to_rgb(bg_color)
                bg = (r, g, b, 255)
            else:
                bg = (255, 255, 255, 0)
            img = Image.new('RGBA', (canvas_sz, canvas_sz), bg)
            draw = ImageDraw.Draw(img)
            x = (canvas_sz - tw) // 2 - bbox[0]
            y = (canvas_sz - th) // 2 - bbox[1]
            draw.text((x, y), clean, font=font, embedded_color=True)
            return ImageTk.PhotoImage(img)
        except Exception:
            return None

    @staticmethod
    def _hex_to_rgb(hex_color):
        hex_color = hex_color.lstrip('#')
        return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))

    # Retorna emoji renderizado para a área de chat (20px), com cache.
    def _get_chat_emoji(self, emoji_char, bg_color=None):
        cache_key = f'{emoji_char}_{bg_color}' if bg_color else emoji_char
        if cache_key in self._chat_emoji_cache:
            return self._chat_emoji_cache[cache_key]
        img = self._render_emoji_image(emoji_char, size=20, bg_color=bg_color)
        if img:
            self._chat_emoji_cache[cache_key] = img
        return img

    # Retorna emoji renderizado para o campo de entrada (18px), com cache.
    def _get_entry_emoji(self, emoji_char):
        if emoji_char in self._entry_emoji_cache:
            return self._entry_emoji_cache[emoji_char]
        img = self._render_emoji_image(emoji_char, size=18)
        if img:
            self._entry_emoji_cache[emoji_char] = img
        return img

    # Insere um emoji como imagem no campo de entrada.
    # Se PIL não está disponível, insere como texto Unicode puro.
    def _entry_insert_emoji(self, emoji_char, pos='insert'):
        img = self._get_entry_emoji(emoji_char)
        if img:
            # Cria nome único para a imagem e mapeia de volta para o caractere emoji
            img_name = f'gentry_emoji_{len(self._entry_img_map)}'
            self._entry_img_map[img_name] = emoji_char
            self.entry.image_create(pos, image=img, name=img_name, padx=1)
        else:
            self.entry.insert(pos, emoji_char)  # Fallback: texto puro

    # Extrai o conteúdo do campo de entrada, convertendo imagens de volta para texto.
    # Percorre o dump do widget Text e reconstrói a string com emojis Unicode.
    def _get_entry_content(self):
        result = []
        for key, value, index in self.entry.dump('1.0', 'end', image=True, text=True):
            if key == 'text':
                result.append(value)  # Texto normal
            elif key == 'image':
                emoji = self._entry_img_map.get(value, '')  # Converte imagem → emoji char
                result.append(emoji)
        return ''.join(result).strip()

    # Insere texto na área de chat, substituindo emojis Unicode por imagens coloridas.
    # Usa _EMOJI_RE para separar texto e emojis, inserindo cada um com a tag correta.
    def _insert_text_with_emojis(self, text, tag):
        bg = self.chat_text.tag_cget(tag, 'background') or self.chat_text.cget('bg')
        last = 0
        for m in _URL_RE.finditer(text):
            if m.start() > last:
                self._insert_emoji_run(text[last:m.start()], tag, bg)
            self._insert_link(m.group(0), tag)
            last = m.end()
        if last < len(text):
            self._insert_emoji_run(text[last:], tag, bg)

    def _insert_emoji_run(self, text, tag, bg):
        parts = _EMOJI_RE.split(text)
        emojis = _EMOJI_RE.findall(text)
        for i, part in enumerate(parts):
            if part:
                self.chat_text.insert('end', part, tag)
            if i < len(emojis):
                img = self._get_chat_emoji(emojis[i], bg_color=bg)
                if img:
                    mark = self.chat_text.index('end-1c')
                    self.chat_text.image_create('end', image=img, padx=1)
                    self.chat_text.tag_add(tag, mark, 'end-1c')
                else:
                    self.chat_text.insert('end', emojis[i], tag)

    def _insert_link(self, url, base_tag):
        n = getattr(self, '_link_counter', 0) + 1
        self._link_counter = n
        link_tag = f'link_{n}'
        bg = self.chat_text.tag_cget(base_tag, 'background') or self.chat_text.cget('bg')
        self.chat_text.tag_configure(link_tag, foreground='#0066cc',
                                     underline=True, background=bg)
        self.chat_text.insert('end', url, (base_tag, link_tag))
        self.chat_text.tag_bind(link_tag, '<Button-1>',
                                lambda e, u=url: _open_url(u))
        self.chat_text.tag_bind(link_tag, '<Enter>',
                                lambda e: self.chat_text.config(cursor='hand2'))
        self.chat_text.tag_bind(link_tag, '<Leave>',
                                lambda e: self.chat_text.config(cursor=''))

    # Abre emoji picker (reutiliza logica do ChatWindow).
    def _show_emoji_picker(self):
        popup = tk.Toplevel(self)
        popup.title('Emoticons')
        popup.resizable(False, False)
        popup.configure(bg='#f0f0f0')
        popup.transient(self)

        x = self.winfo_rootx() + 10
        y = self.winfo_rooty() + self.winfo_height() - 280
        popup.geometry(f'280x230+{x}+{y}')
        popup._emoji_images = {}

        emojis_list = [
            '\U0001f600', '\U0001f603', '\U0001f604', '\U0001f601',
            '\U0001f606', '\U0001f605', '\U0001f602', '\U0001f923',
            '\U0001f60a', '\U0001f607', '\U0001f609', '\U0001f60d',
            '\U0001f929', '\U0001f60e', '\U0001f618', '\U0001f617',
            '\U0001f61a', '\U0001f60b', '\U0001f61b', '\U0001f61c',
            '\U0001f92a', '\U0001f61d', '\U0001f911', '\U0001f917',
            '\U0001f914', '\U0001f910', '\U0001f928', '\U0001f610',
            '\U0001f611', '\U0001f636', '\U0001f60f', '\U0001f612',
            '\U0001f620', '\U0001f621', '\U0001f622', '\U0001f62d',
            '\U0001f44d', '\U0001f44e', '\U0001f44f', '\U0001f64f',
            '\u2601', '\u26c5', '\U0001f37a', '\U0001f37b',
        ]

        grid_frame = tk.Frame(popup, bg='#ffffff')
        grid_frame.pack(fill='both', expand=True, padx=1, pady=1)

        col, row = 0, 0
        for em in emojis_list:
            img = self._render_emoji_image(em, 22)
            def ins(emoji=em):
                self._entry_insert_emoji(emoji)
                popup.destroy()
            if img:
                popup._emoji_images[em] = img
                b = tk.Button(grid_frame, image=img, relief='flat', bd=0,
                              cursor='hand2', command=ins, bg='#ffffff',
                              activebackground='#f0f5ff', width=30, height=30)
            else:
                b = tk.Button(grid_frame, text=em, font=('Segoe UI', 14),
                              relief='flat', bd=0, cursor='hand2',
                              command=ins, bg='#ffffff',
                              activebackground='#f0f5ff')
            b.grid(row=row, column=col, padx=1, pady=1)
            col += 1
            if col >= 8:
                col = 0
                row += 1

        popup.bind('<Escape>', lambda e: popup.destroy())
        def _check_focus():
            if not popup.winfo_exists():
                return
            try:
                focused = popup.focus_get()
                if focused is None or not str(focused).startswith(str(popup)):
                    popup.destroy()
            except Exception:
                popup.destroy()
        popup.bind('<FocusOut>', lambda e: popup.after(100, _check_focus))
        popup.focus_set()

    # ===== Font =====
    def _change_font(self):
        try:
            self._change_font_impl()
        except Exception:
            log.exception('Erro ao abrir dialogo de fonte no grupo')

    def _change_font_impl(self):
        win = tk.Toplevel(self)
        win.title('Fonte')
        win.resizable(False, False)
        _center_window(win, 280, 200)
        win.configure(bg=BG_WINDOW)
        win.transient(self)
        win.bind('<Escape>', lambda e: win.destroy())
        try:
            win.grab_set()
        except Exception:
            pass

        cur_font = self.chat_text.tag_cget('msg', 'font') or 'Segoe UI 10'
        parts = cur_font.split()
        cur_size = 10
        for p in parts:
            if p.isdigit():
                cur_size = int(p)

        tk.Label(win, text='Tamanho da fonte:', font=FONT,
                 bg=BG_WINDOW).pack(padx=10, pady=(10, 4), anchor='w')

        size_var = tk.IntVar(value=cur_size)
        sizes_frame = tk.Frame(win, bg=BG_WINDOW)
        sizes_frame.pack(padx=10, fill='x')
        for s in [8, 9, 10, 11, 12, 14, 16]:
            rb = tk.Radiobutton(sizes_frame, text=str(s), variable=size_var,
                                value=s, font=FONT, bg=BG_WINDOW)
            rb.pack(side='left', padx=4)

        def apply():
            new_size = size_var.get()
            self.chat_text.tag_configure('msg', font=('Segoe UI', new_size))
            win.destroy()

        tk.Button(win, text='OK', font=FONT, width=8,
                  command=apply).pack(pady=10)

    # ===== File send =====
    def _send_file(self):
        filepath = filedialog.askopenfilename(parent=self, title='Enviar arquivo')
        if not filepath:
            return
        threading.Thread(target=self.app.messenger.send_file_to_group,
                         args=(self.group_id, filepath),
                         daemon=True).start()
        filename = os.path.basename(filepath)
        self.system_message(f'Enviando "{filename}" para o grupo...')

    # ===== Messages — envio e exibição de mensagens no grupo =====
    # Exibe mensagem de sistema no chat (ex: 'X entrou/saiu do grupo').
    def system_message(self, text):
        self.chat_text.configure(state='normal')   # Desbloqueia para inserir
        self.chat_text.insert('end', f'\u2014 {text} \u2014\n\n', 'sys_msg')  # Traços em volta
        self.chat_text.configure(state='disabled')  # Bloqueia edição novamente
        self.chat_text.see('end')  # Rola para a última mensagem

    # Adiciona uma mensagem na area de chat com nome, horario e emojis coloridos.
    # Suporta modo linear (padrao) e modo bolha (WhatsApp style) conforme preferencia.
    def _append_message(self, sender, text, is_mine, timestamp=None,
                        msg_id='', reply_to='', mentions=None):
        ts = datetime.fromtimestamp(timestamp or time.time()).strftime('%H:%M')
        self.chat_text.configure(state='normal')

        # Renderiza quote de reply
        if reply_to:
            orig = self.app.messenger.db.get_message_by_id(reply_to)
            if orig:
                q_name = orig.get('from_user', '')[:20]
                q_text = orig.get('content', '')[:80]
                self.chat_text.insert('end', f'{q_name}\n', 'quote_name')
                self.chat_text.insert('end', f'{q_text}\n', 'quote')

        style = self.app.messenger.db.get_setting('msg_style', 'bubble')

        if style == 'bubble':
            if is_mine:
                name_tag = 'my_bubble_name'
                time_tag = 'my_bubble_time'
                msg_tag = 'my_bubble'
            else:
                name_tag = 'peer_bubble_name'
                time_tag = 'peer_bubble_time'
                msg_tag = 'peer_bubble'
            self.chat_text.insert('end', f'{sender}', name_tag)
            self.chat_text.insert('end', f'  {ts}\n', time_tag)
            body_start = self.chat_text.index('end-1c')
            self._insert_text_with_mentions(text, msg_tag, mentions)
            body_end = self.chat_text.index('end-1c')
            self.chat_text.insert('end', '\n', msg_tag)
        else:
            name_tag = 'my_name' if is_mine else 'peer_name'
            self.chat_text.insert('end', sender, name_tag)
            self.chat_text.insert('end', f'  {ts}\n', 'time')
            body_start = self.chat_text.index('end-1c')
            self._insert_text_with_mentions(text, 'msg', mentions)
            body_end = self.chat_text.index('end-1c')
            self.chat_text.insert('end', '\n')

        n = len(self._msg_data)
        msg_tag_name = f'msg_{n}'
        self.chat_text.tag_add(msg_tag_name,
                               self.chat_text.index(body_start),
                               self.chat_text.index(body_end))
        start_mark = f'gmstart_{n}'
        end_mark = f'gmend_{n}'
        self.chat_text.mark_set(start_mark, body_start)
        self.chat_text.mark_set(end_mark, body_end)
        self.chat_text.mark_gravity(start_mark, 'left')
        self.chat_text.mark_gravity(end_mark, 'right')
        self._msg_ranges_idx.append((start_mark, end_mark))
        self.chat_text.tag_bind(msg_tag_name, '<Enter>',
                                lambda e, idx=n: self._on_msg_hover_enter(idx))
        self.chat_text.tag_bind(msg_tag_name, '<Leave>',
                                lambda e, idx=n: self._on_msg_hover_leave(idx))

        self._msg_data.append({'msg_id': msg_id, 'sender': sender,
                               'text': text, 'is_mine': is_mine,
                               'timestamp': timestamp or time.time()})
        self.chat_text.insert('end', '\n')
        self.chat_text.configure(state='disabled')
        self.chat_text.see('end')

    # Insere texto com @mencoes destacadas
    def _insert_text_with_mentions(self, text, base_tag, mentions=None):
        if not mentions:
            self._insert_text_with_emojis(text, base_tag)
            return
        # Busca @nomes no texto e destaca
        parts = re.split(r'(@\w+)', text)
        member_names = {m.get('display_name', '').lower()
                        for m in self._members.values()}
        for part in parts:
            if part.startswith('@') and part[1:].lower() in member_names:
                self.chat_text.insert('end', part, 'mention')
            else:
                self._insert_text_with_emojis(part, base_tag)

    # Callback chamado ao receber mensagem de outro membro do grupo.
    def receive_message(self, display_name, content, timestamp=None,
                        reply_to='', mentions=None, msg_id=''):
        self._append_message(display_name, content, False, timestamp,
                             msg_id=msg_id, reply_to=reply_to,
                             mentions=mentions)

    # <<Modified>> dispara SEMPRE que o conteúdo do tk.Text muda.
    # Inclui teclado, IME, Windows Emoji Picker (Win+.), paste, etc.
    def _on_modified(self, event):
        try:
            self.entry.edit_modified(False)
        except Exception:
            pass
        self.after(30, self._do_emoji_scan)

    # Executa o scan de emojis no campo de entrada do grupo.
    def _do_emoji_scan(self):
        try:
            _scan_entry_emojis(self.entry, self._entry_emoji_cache,
                               self._entry_img_map, prefix='gentry_emoji', size=18)
        except Exception:
            pass

    # Enter envia mensagem; Shift+Enter insere nova linha.
    def _on_enter(self, event):
        if not (event.state & 1):  # state & 1 = Shift pressionado
            self._send_message()
            return 'break'  # Impede inserção de nova linha

    def _show_reply_bar(self, msg_id, sender, text_preview):
        self._reply_to = {'msg_id': msg_id, 'sender': sender,
                          'text': text_preview}
        if self._reply_bar:
            self._reply_bar.destroy()
        outer = tk.Frame(self, bg='#2451a0')
        outer.pack(fill='x', side='bottom', after=self._input_outer, padx=6, pady=(0, 2))
        bar = tk.Frame(outer, bg='#e2e8f0')
        bar.pack(fill='both', expand=True, padx=(3, 0))
        tk.Label(bar, text=sender,
                 font=('Segoe UI', 9, 'bold'), bg='#e2e8f0',
                 fg='#2451a0', anchor='w').pack(fill='x', padx=8, pady=(4, 0))
        preview = text_preview[:80] if text_preview else '[Mensagem]'
        tk.Label(bar, text=preview,
                 font=('Segoe UI', 8), bg='#e2e8f0',
                 fg='#4a5568', anchor='w').pack(fill='x', padx=8, pady=(0, 4))
        btn_x = tk.Button(bar, text='\u2715', font=('Segoe UI', 8, 'bold'),
                           bg='#e2e8f0', fg='#718096', relief='flat', bd=0,
                           cursor='hand2', command=self._cancel_reply)
        btn_x.place(relx=1.0, x=-6, y=4, anchor='ne')
        self._reply_bar = outer

    def _cancel_reply(self):
        self._reply_to = None
        if self._reply_bar:
            self._reply_bar.destroy()
            self._reply_bar = None

    def _on_chat_right_click(self, event):
        if self._img_click_handled:
            self._img_click_handled = False
            return
        self._ctx_msg_idx = self._find_msg_idx_at_xy(event.x, event.y)
        msg_idx = self._ctx_msg_idx
        if 0 <= msg_idx < len(self._msg_data) and self._msg_data[msg_idx].get('is_mine'):
            self._chat_ctx.entryconfigure(0, state='disabled')
        else:
            self._chat_ctx.entryconfigure(0, state='normal')
        self._chat_ctx.tk_popup(event.x_root, event.y_root)

    def _ctx_reply(self):
        idx = getattr(self, '_ctx_msg_idx', -1)
        if idx < 0 or idx >= len(self._msg_data):
            return
        data = self._msg_data[idx]
        if data.get('msg_id'):
            self._show_reply_bar(data['msg_id'], data['sender'], data['text'])
            self.entry.focus_set()

    def _ctx_copy(self):
        idx = getattr(self, '_ctx_msg_idx', -1)
        if idx < 0 or idx >= len(self._msg_data):
            return
        text = self._msg_data[idx].get('text', '')
        if text:
            self.clipboard_clear()
            self.clipboard_append(text)

    def _ctx_select(self):
        idx = getattr(self, '_ctx_msg_idx', -1)
        if idx < 0 or idx >= len(self._msg_data):
            return
        self._enter_selection_mode(idx)

    # ========================================
    # HOVER COPY + SELECTION MODE (GroupChatWindow)
    # ========================================
    def _on_msg_hover_enter(self, idx):
        if self._selection_mode:
            return
        self._cancel_hover_hide()
        self._show_hover_copy(idx)

    def _on_msg_hover_leave(self, idx):
        if self._selection_mode:
            return
        self._schedule_hover_hide()

    def _cancel_hover_hide(self):
        if self._hover_hide_after:
            try:
                self.after_cancel(self._hover_hide_after)
            except Exception:
                pass
            self._hover_hide_after = None

    def _schedule_hover_hide(self):
        self._cancel_hover_hide()
        self._hover_hide_after = self.after(180, self._hide_hover_copy)

    def _hide_hover_copy(self):
        try:
            self._hover_copy_btn.place_forget()
        except Exception:
            pass
        self._hover_copy_visible_idx = None

    def _show_hover_copy(self, idx):
        if idx < 0 or idx >= len(self._msg_ranges_idx):
            return
        start_mark, end_mark = self._msg_ranges_idx[idx]
        try:
            # Linha do header (sender + horario): 1 linha acima do body_start
            header_idx = self.chat_text.index(f'{start_mark} -1c linestart')
            info = self.chat_text.dlineinfo(header_idx)
            if not info:
                return
            lx, ly, lw, lh, _ = info
            chat_w = self.chat_text.winfo_width()
            btn_x = min(chat_w - 20, lx + lw + 6)
            btn_y = ly + 1
            self._hover_copy_btn.place(in_=self.chat_text, x=btn_x, y=btn_y)
            self._hover_copy_visible_idx = idx
        except Exception:
            pass

    def _on_hover_copy_click(self, event):
        idx = self._hover_copy_visible_idx
        if idx is None or idx >= len(self._msg_data):
            return
        text = self._msg_data[idx].get('text', '')
        if not text:
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        original = self._hover_copy_btn.cget('text')
        self._hover_copy_btn.config(text='\u2714', fg='#2a7f3f')
        self.after(600, lambda: self._hover_copy_btn.config(text=original, fg='#4a5568'))

    def _on_chat_press(self, event):
        if self._selection_mode:
            idx = self._find_msg_idx_at_xy(event.x, event.y)
            if idx >= 0:
                self._toggle_msg_selection(idx)
            return 'break'
        self._long_press_origin = (event.x, event.y)
        self._long_press_msg_idx = self._find_msg_idx_at_xy(event.x, event.y)
        if self._long_press_after:
            try:
                self.after_cancel(self._long_press_after)
            except Exception:
                pass
        if self._long_press_msg_idx >= 0:
            self._long_press_after = self.after(500, self._long_press_fire)

    def _on_chat_motion(self, event):
        if self._long_press_after and self._long_press_origin:
            ox, oy = self._long_press_origin
            if abs(event.x - ox) > 5 or abs(event.y - oy) > 5:
                try:
                    self.after_cancel(self._long_press_after)
                except Exception:
                    pass
                self._long_press_after = None

    def _on_chat_release(self, event):
        if self._long_press_after:
            try:
                self.after_cancel(self._long_press_after)
            except Exception:
                pass
            self._long_press_after = None

    def _long_press_fire(self):
        self._long_press_after = None
        idx = self._long_press_msg_idx
        if idx is None or idx < 0:
            return
        try:
            self.chat_text.tag_remove('sel', '1.0', 'end')
        except Exception:
            pass
        self._enter_selection_mode(idx)

    def _find_msg_idx_at_xy(self, x, y):
        try:
            click_idx = self.chat_text.index(f'@{x},{y}')
        except Exception:
            return -1
        return self._find_msg_idx_at_index(click_idx)

    def _find_msg_idx_at_index(self, click_idx):
        best = -1
        for i, (sm, em) in enumerate(self._msg_ranges_idx):
            try:
                s = self.chat_text.index(sm)
                e = self.chat_text.index(em)
            except Exception:
                continue
            if self.chat_text.compare(click_idx, '>=', s) and \
               self.chat_text.compare(click_idx, '<=', e):
                return i
            if self.chat_text.compare(click_idx, '>=', s):
                best = i
        return best

    def _enter_selection_mode(self, initial_idx):
        if self._selection_mode:
            self._toggle_msg_selection(initial_idx)
            return
        self._selection_mode = True
        self._selection_set = set()
        self._hide_hover_copy()
        self._build_selection_bar()
        self._toggle_msg_selection(initial_idx)

    def _build_selection_bar(self):
        if self._selection_bar is not None:
            return
        bar = tk.Frame(self, bg='#0f2a5c', height=34)
        bar.pack(fill='x', side='top', before=self.chat_text.master)
        self._sel_count_lbl = tk.Label(
            bar, text='1 selecionada', font=('Segoe UI', 9, 'bold'),
            bg='#0f2a5c', fg='#ffffff')
        self._sel_count_lbl.pack(side='left', padx=10, pady=6)
        btn_copy = tk.Button(
            bar, text='\U0001f4cb Copiar', font=('Segoe UI', 9),
            bg='#1a3f7a', fg='#ffffff', relief='flat', bd=0,
            cursor='hand2', padx=10, pady=3,
            activebackground='#2451a0', activeforeground='#ffffff',
            command=self._selection_copy)
        btn_copy.pack(side='left', padx=4, pady=4)
        btn_fwd = tk.Button(
            bar, text='\u27a4 Encaminhar', font=('Segoe UI', 9),
            bg='#1a3f7a', fg='#ffffff', relief='flat', bd=0,
            cursor='hand2', padx=10, pady=3,
            activebackground='#2451a0', activeforeground='#ffffff',
            command=self._selection_forward)
        btn_fwd.pack(side='left', padx=4, pady=4)
        btn_cancel = tk.Button(
            bar, text='\u2715 Cancelar', font=('Segoe UI', 9),
            bg='#7a1a1a', fg='#ffffff', relief='flat', bd=0,
            cursor='hand2', padx=10, pady=3,
            activebackground='#a02424', activeforeground='#ffffff',
            command=self._exit_selection_mode)
        btn_cancel.pack(side='right', padx=10, pady=4)
        self._selection_bar = bar

    def _toggle_msg_selection(self, idx):
        if idx < 0 or idx >= len(self._msg_ranges_idx):
            return
        sm, em = self._msg_ranges_idx[idx]
        if idx in self._selection_set:
            self._selection_set.discard(idx)
            self.chat_text.tag_remove('selected_msg',
                                      self.chat_text.index(sm),
                                      self.chat_text.index(em))
        else:
            self._selection_set.add(idx)
            self.chat_text.tag_add('selected_msg',
                                   self.chat_text.index(sm),
                                   self.chat_text.index(em))
        self._update_selection_count()
        if not self._selection_set:
            self._exit_selection_mode()

    def _update_selection_count(self):
        if self._sel_count_lbl:
            n = len(self._selection_set)
            label = f'{n} selecionada' if n == 1 else f'{n} selecionadas'
            self._sel_count_lbl.config(text=label)

    def _exit_selection_mode(self, *args):
        if not self._selection_mode:
            return
        for idx in list(self._selection_set):
            if idx < len(self._msg_ranges_idx):
                sm, em = self._msg_ranges_idx[idx]
                try:
                    self.chat_text.tag_remove('selected_msg',
                                              self.chat_text.index(sm),
                                              self.chat_text.index(em))
                except Exception:
                    pass
        self._selection_set.clear()
        self._selection_mode = False
        if self._selection_bar is not None:
            try:
                self._selection_bar.destroy()
            except Exception:
                pass
            self._selection_bar = None
            self._sel_count_lbl = None

    def _on_escape_selection(self, event):
        if self._selection_mode:
            self._exit_selection_mode()
            return 'break'

    def _collect_selected_messages(self):
        out = []
        for idx in sorted(self._selection_set):
            if idx < len(self._msg_data):
                d = self._msg_data[idx]
                ts = datetime.fromtimestamp(
                    d.get('timestamp') or time.time()).strftime('%H:%M')
                out.append(f"[{ts}] {d.get('sender','')}: {d.get('text','')}")
        return out

    def _selection_copy(self):
        lines = self._collect_selected_messages()
        if not lines:
            return
        text = '\n'.join(lines)
        self.clipboard_clear()
        self.clipboard_append(text)
        self._exit_selection_mode()

    def _selection_forward(self):
        msgs = [self._msg_data[i]['text'] for i in sorted(self._selection_set)
                if i < len(self._msg_data) and self._msg_data[i].get('text')]
        if not msgs:
            return
        self._open_forward_dialog(msgs)
        self._exit_selection_mode()

    def _open_forward_dialog(self, messages):
        dlg = tk.Toplevel(self)
        dlg.title('Encaminhar mensagens')
        dlg.configure(bg='#f5f7fa')
        dlg.geometry('320x420')
        dlg.transient(self)
        dlg.grab_set()
        tk.Label(dlg, text=f'Encaminhar {len(messages)} mensagem(ns) para:',
                 font=('Segoe UI', 10, 'bold'),
                 bg='#f5f7fa', fg='#1a202c').pack(padx=12, pady=(12, 6), anchor='w')
        list_frame = tk.Frame(dlg, bg='#ffffff', bd=1, relief='solid')
        list_frame.pack(fill='both', expand=True, padx=12, pady=4)
        lb = tk.Listbox(list_frame, font=('Segoe UI', 9),
                        bg='#ffffff', fg='#1a202c',
                        selectbackground='#1e66d0',
                        selectforeground='#ffffff',
                        bd=0, relief='flat', activestyle='none')
        lb.pack(fill='both', expand=True)
        targets = []
        for uid, info in self.app.peer_info.items():
            if uid == self.messenger.user_id:
                continue
            name = info.get('display_name', uid)
            status = info.get('status', 'offline')
            if status == 'offline':
                continue
            targets.append(('peer', uid, f'\U0001f464 {name}'))
        for gid, gw in self.app.group_windows.items():
            if gid == self.group_id:
                continue
            try:
                name = gw.group_info.get('name', gid)
            except Exception:
                name = gid
            targets.append(('group', gid, f'\U0001f465 {name}'))
        for t in targets:
            lb.insert('end', t[2])
        btn_frame = tk.Frame(dlg, bg='#f5f7fa')
        btn_frame.pack(fill='x', padx=12, pady=10)

        def _send():
            sel = lb.curselection()
            if not sel:
                return
            kind, ident, _ = targets[sel[0]]
            body = '[Encaminhada]\n' + '\n'.join(messages)
            try:
                if kind == 'peer':
                    self.messenger.send_message(ident, body)
                else:
                    self.messenger.send_group_message(ident, body)
            except Exception:
                log.exception('Erro ao encaminhar')
            dlg.destroy()

        tk.Button(btn_frame, text='Enviar', font=('Segoe UI', 9, 'bold'),
                  bg='#1a3f7a', fg='#ffffff', relief='flat', bd=0,
                  cursor='hand2', padx=14, pady=4,
                  activebackground='#2451a0', activeforeground='#ffffff',
                  command=_send).pack(side='right', padx=4)
        tk.Button(btn_frame, text='Cancelar', font=('Segoe UI', 9),
                  bg='#e2e8f0', fg='#4a5568', relief='flat', bd=0,
                  cursor='hand2', padx=14, pady=4,
                  command=dlg.destroy).pack(side='right', padx=4)
        dlg.bind('<Escape>', lambda e: dlg.destroy())

    # Callback do windnd: arquivos arrastados para a janela do grupo
    def _on_drop_files(self, files):
        for f in files:
            path = f.decode('utf-8') if isinstance(f, bytes) else str(f)
            if os.path.isfile(path):
                self.app._start_group_file_send(self.group_id, path)
                break

    # Extrai @mencoes do texto para enviar no payload
    def _extract_mentions(self, text):
        mentions = []
        parts = re.findall(r'@(\w+)', text)
        for name in parts:
            for uid, info in self._members.items():
                if info.get('display_name', '').lower() == name.lower():
                    mentions.append(uid)
                    break
        return mentions if mentions else None

    # Detecta @ digitado e mostra popup de autocomplete
    def _on_entry_key(self, event):
        try:
            cursor = self.entry.index('insert')
            line_start = self.entry.index(f'{cursor} linestart')
            text_before = self.entry.get(line_start, cursor)
            # Procura @ seguido de texto parcial
            m = re.search(r'@(\w*)$', text_before)
            if m:
                prefix = m.group(1).lower()
                names = [info.get('display_name', '')
                         for uid, info in self._members.items()
                         if info.get('display_name', '').lower().startswith(prefix)
                         and uid != self.app.messenger.user_id]
                if names:
                    self._show_mention_popup(names, m.start())
                    return
            self._hide_mention_popup()
        except Exception:
            pass

    # Mostra popup de autocomplete de @mencao
    def _show_mention_popup(self, names, at_pos):
        self._hide_mention_popup()
        popup = tk.Toplevel(self)
        popup.wm_overrideredirect(True)
        popup.configure(bg='#e2e8f0')
        # Posiciona acima do campo de entrada
        try:
            x = self.entry.winfo_rootx() + 10
            y = self.entry.winfo_rooty() - min(len(names), 8) * 26 - 4
            if y < 0:
                y = self.entry.winfo_rooty() + self.entry.winfo_height() + 2
        except Exception:
            x, y = 100, 100
        popup.geometry(f'+{x}+{y}')
        for name in names[:8]:
            btn = tk.Button(popup, text=f'  @{name}', font=('Segoe UI', 9),
                            bg='#ffffff', fg='#1a202c', relief='flat',
                            bd=0, anchor='w', padx=8, pady=3, cursor='hand2',
                            activebackground='#e8f0fe',
                            command=lambda n=name: self._insert_mention(n, at_pos))
            btn.pack(fill='x', padx=1, pady=(1, 0))
            _add_hover(btn, '#ffffff', '#e8f0fe')
        self._mention_popup = popup
        popup.bind('<FocusOut>', lambda e: self._hide_mention_popup())

    def _hide_mention_popup(self):
        if self._mention_popup:
            try:
                self._mention_popup.destroy()
            except Exception:
                pass
            self._mention_popup = None

    # Insere @nome no campo de entrada substituindo o @parcial
    def _insert_mention(self, name, at_pos):
        self._hide_mention_popup()
        try:
            cursor = self.entry.index('insert')
            line_start = self.entry.index(f'{cursor} linestart')
            text_before = self.entry.get(line_start, cursor)
            # Remove @parcial e insere @nome completo
            m = re.search(r'@\w*$', text_before)
            if m:
                del_start = f'{line_start}+{m.start()}c'
                self.entry.delete(del_start, cursor)
                self.entry.insert(del_start, f'@{name} ')
        except Exception:
            pass
        self.entry.focus_set()

    # Dialogo para criar enquete no grupo
    def _create_poll_dialog(self):
        dlg = tk.Toplevel(self)
        dlg.title('Criar Enquete')
        dlg.transient(self)
        dlg.grab_set()
        dlg.configure(bg='#ffffff')
        _center_window(dlg, 380, 340)
        _apply_rounded_corners(dlg)
        dlg.bind('<Escape>', lambda e: dlg.destroy())

        tk.Label(dlg, text='Pergunta:', font=('Segoe UI', 10, 'bold'),
                 bg='#ffffff', fg='#1a202c').pack(anchor='w', padx=12, pady=(12, 4))
        q_entry = tk.Entry(dlg, font=('Segoe UI', 10), relief='flat',
                           bg='#f7fafc', highlightthickness=1,
                           highlightbackground='#e2e8f0')
        q_entry.pack(fill='x', padx=12)
        q_entry.focus_set()

        tk.Label(dlg, text='Opcoes (uma por linha):',
                 font=('Segoe UI', 10, 'bold'),
                 bg='#ffffff', fg='#1a202c').pack(anchor='w', padx=12, pady=(12, 4))
        opts_text = tk.Text(dlg, font=('Segoe UI', 10), height=6, relief='flat',
                            bg='#f7fafc', highlightthickness=1,
                            highlightbackground='#e2e8f0', wrap='word')
        opts_text.pack(fill='both', expand=True, padx=12)

        def _create():
            question = q_entry.get().strip()
            options = [l.strip() for l in opts_text.get('1.0', 'end').strip().split('\n')
                       if l.strip()]
            if not question or len(options) < 2:
                messagebox.showwarning('Enquete', 'Insira uma pergunta e pelo menos 2 opcoes.',
                                        parent=dlg)
                return
            dlg.destroy()
            def _do():
                poll_id = self.app.messenger.create_poll(self.group_id, question, options)
                if poll_id:
                    self.after(0, lambda: self._display_poll(
                        question, options, self.app.messenger.display_name, poll_id))
            threading.Thread(target=_do, daemon=True).start()

        btn_frame = tk.Frame(dlg, bg='#ffffff')
        btn_frame.pack(fill='x', padx=12, pady=10)
        tk.Button(btn_frame, text='Criar', font=('Segoe UI', 9, 'bold'),
                  bg='#0f2a5c', fg='#ffffff', relief='flat', bd=0,
                  padx=16, pady=4, cursor='hand2',
                  command=_create).pack(side='right')
        tk.Button(btn_frame, text='Cancelar', font=('Segoe UI', 9),
                  bg='#e2e8f0', fg='#4a5568', relief='flat', bd=0,
                  padx=12, pady=4, cursor='hand2',
                  command=dlg.destroy).pack(side='right', padx=(0, 6))

    # Exibe enquete no chat como card estilo WhatsApp/Google Forms
    def _display_poll(self, question, options, creator, poll_id):
        # Busca votos atuais do banco
        votes = self.app.messenger.db.get_poll_votes(poll_id)
        vote_counts = {}
        my_vote = None
        my_uid = self.app.messenger.user_id
        for v in votes:
            idx = v['option_index']
            vote_counts[idx] = vote_counts.get(idx, 0) + 1
            if v['voter_uid'] == my_uid:
                my_vote = idx
        total_votes = sum(vote_counts.values())

        # Cria o card como widget Frame embutido no chat_text
        self.chat_text.configure(state='normal')
        self.chat_text.insert('end', '\n')

        card = tk.Frame(self.chat_text, bg='#ffffff', relief='solid', bd=1,
                        highlightthickness=1, highlightbackground='#e2e8f0')

        # Header
        hdr = tk.Frame(card, bg='#f0f4ff')
        hdr.pack(fill='x')
        tk.Label(hdr, text=f'\U0001f4ca  Enquete', font=('Segoe UI', 9, 'bold'),
                 bg='#f0f4ff', fg='#3b5998').pack(side='left', padx=10, pady=6)
        tk.Label(hdr, text=f'por {creator}', font=('Segoe UI', 8),
                 bg='#f0f4ff', fg='#718096').pack(side='right', padx=10, pady=6)

        # Pergunta
        tk.Label(card, text=question, font=('Segoe UI', 11, 'bold'),
                 bg='#ffffff', fg='#1a202c', wraplength=350,
                 justify='left', anchor='w').pack(fill='x', padx=12, pady=(10, 6))

        # Opcoes com barras de progresso
        opts_frame = tk.Frame(card, bg='#ffffff')
        opts_frame.pack(fill='x', padx=12, pady=(0, 6))

        # Guarda refs para atualizar votos depois
        if not hasattr(self, '_poll_widgets'):
            self._poll_widgets = {}
        self._poll_widgets[poll_id] = {'opts_frame': opts_frame, 'options': options,
                                        'card': card, 'question': question, 'creator': creator}

        self._render_poll_options(poll_id, opts_frame, options, vote_counts, total_votes, my_vote)

        # Footer com total de votos
        footer = tk.Frame(card, bg='#f8f9fa')
        footer.pack(fill='x')
        lbl_total = tk.Label(footer, text=f'{total_votes} voto{"s" if total_votes != 1 else ""}',
                             font=('Segoe UI', 8), bg='#f8f9fa', fg='#718096')
        lbl_total.pack(side='left', padx=10, pady=4)
        if not hasattr(self, '_poll_total_labels'):
            self._poll_total_labels = {}
        self._poll_total_labels[poll_id] = lbl_total

        self.chat_text.window_create('end', window=card, padx=10, pady=4)
        self.chat_text.insert('end', '\n')
        self.chat_text.configure(state='disabled')
        self.chat_text.see('end')

    def _render_poll_options(self, poll_id, parent, options, vote_counts, total_votes, my_vote):
        for w in parent.winfo_children():
            w.destroy()
        colors = ['#4285f4', '#ea4335', '#fbbc04', '#34a853', '#ff6d01', '#46bdc6',
                  '#7b61ff', '#f538a0']
        for i, opt in enumerate(options):
            count = vote_counts.get(i, 0)
            pct = int((count / total_votes * 100) if total_votes > 0 else 0)
            color = colors[i % len(colors)]
            is_mine = (my_vote == i)

            opt_frame = tk.Frame(parent, bg='#ffffff', cursor='hand2')
            opt_frame.pack(fill='x', pady=2)

            # Barra de progresso com canvas
            bar_h = 32
            bar_canvas = tk.Canvas(opt_frame, height=bar_h, bg='#f0f2f5',
                                   highlightthickness=0, bd=0)
            bar_canvas.pack(fill='x')

            def _draw_bar(canvas=bar_canvas, p=pct, c=color, mine=is_mine,
                          text=opt, cnt=count):
                canvas.update_idletasks()
                w = canvas.winfo_width()
                if w < 10:
                    w = 340
                # Fundo
                canvas.create_rectangle(0, 0, w, bar_h, fill='#f0f2f5', outline='')
                # Barra preenchida
                if p > 0:
                    fill_w = max(int(w * p / 100), 4)
                    canvas.create_rectangle(0, 0, fill_w, bar_h, fill=c,
                                            outline='', stipple='' if mine else 'gray50')
                # Texto da opcao (esquerda)
                prefix = '\u2714 ' if mine else ''
                canvas.create_text(10, bar_h // 2, text=f'{prefix}{text}',
                                   anchor='w', font=('Segoe UI', 9, 'bold' if mine else ''),
                                   fill='#1a202c')
                # Percentual e contagem (direita)
                canvas.create_text(w - 10, bar_h // 2, text=f'{p}% ({cnt})',
                                   anchor='e', font=('Segoe UI', 8, 'bold' if mine else ''),
                                   fill='#4a5568')

            bar_canvas.bind('<Configure>', lambda e, db=_draw_bar: db())
            bar_canvas.after(50, _draw_bar)

            # Click para votar
            def _on_click(e, pi=poll_id, oi=i):
                self._vote_poll(pi, oi)
            bar_canvas.bind('<Button-1>', _on_click)

    # Vota numa opcao da enquete
    def _vote_poll(self, poll_id, option_index):
        def _do():
            self.app.messenger.vote_poll(self.group_id, poll_id, option_index)
            self.after(0, lambda: self._refresh_poll_ui(poll_id))
        threading.Thread(target=_do, daemon=True).start()

    # Atualiza a UI do poll apos voto (proprio ou de outro membro)
    def _refresh_poll_ui(self, poll_id):
        if not hasattr(self, '_poll_widgets') or poll_id not in self._poll_widgets:
            return
        pw = self._poll_widgets[poll_id]
        opts_frame = pw['opts_frame']
        options = pw['options']
        try:
            if not opts_frame.winfo_exists():
                return
        except Exception:
            return

        votes = self.app.messenger.db.get_poll_votes(poll_id)
        vote_counts = {}
        my_vote = None
        my_uid = self.app.messenger.user_id
        for v in votes:
            idx = v['option_index']
            vote_counts[idx] = vote_counts.get(idx, 0) + 1
            if v['voter_uid'] == my_uid:
                my_vote = idx
        total_votes = sum(vote_counts.values())

        self._render_poll_options(poll_id, opts_frame, options, vote_counts, total_votes, my_vote)

        # Atualiza label de total
        if hasattr(self, '_poll_total_labels') and poll_id in self._poll_total_labels:
            try:
                lbl = self._poll_total_labels[poll_id]
                if lbl.winfo_exists():
                    lbl.config(text=f'{total_votes} voto{"s" if total_votes != 1 else ""}')
            except Exception:
                pass

    # Envia mensagem para todos os membros do grupo via mesh (ponto-a-ponto).
    def _send_message(self):
        content = self._get_entry_content()
        pending_img = self._pending_image
        if not content and not pending_img:
            return
        reply_to_id = self._reply_to['msg_id'] if self._reply_to else ''
        mentions = self._extract_mentions(content) if content else []
        self._cancel_reply()
        self._cancel_image_preview()
        self.entry.delete('1.0', 'end')
        self._entry_img_map.clear()
        if content:
            self._append_message(self.app.messenger.display_name, content, True,
                                 reply_to=reply_to_id, mentions=mentions)
            threading.Thread(target=self.app.messenger.send_group_message,
                             args=(self.group_id, content, reply_to_id, mentions),
                             daemon=True).start()
        if pending_img:
            self._send_clipboard_image(pending_img)

    def _show_image_preview(self, img):
        try:
            self._cancel_image_preview()
            self._pending_image = img
            outer = tk.Frame(self, bg='#2451a0')
            outer.pack(fill='x', side='bottom', after=self._input_outer, padx=6, pady=(0, 2))
            bar = tk.Frame(outer, bg='#e2e8f0')
            bar.pack(fill='both', expand=True, padx=(3, 0))
            thumb = img.copy()
            thumb.thumbnail((80, 80), Image.LANCZOS)
            tk_thumb = ImageTk.PhotoImage(thumb)
            self._preview_thumb_ref = tk_thumb
            tk.Label(bar, image=tk_thumb, bg='#e2e8f0').pack(side='left', padx=6, pady=4)
            tk.Label(bar, text='Imagem pronta para enviar\nEnter para enviar',
                     font=('Segoe UI', 8), bg='#e2e8f0', fg='#4a5568',
                     anchor='w', justify='left').pack(side='left', fill='x', expand=True, padx=4)
            tk.Button(bar, text='\u2715', font=('Segoe UI', 8, 'bold'),
                      bg='#e2e8f0', fg='#718096', relief='flat', bd=0,
                      cursor='hand2', command=self._cancel_image_preview).pack(side='right', padx=4)
            self._image_preview_bar = outer
            self.entry.focus_set()
        except Exception:
            log.exception('Erro em _show_image_preview')

    def _cancel_image_preview(self):
        self._pending_image = None
        self._preview_thumb_ref = None
        if self._image_preview_bar:
            self._image_preview_bar.destroy()
            self._image_preview_bar = None

    def _on_paste(self, event):
        if not HAS_PIL:
            return
        try:
            img = _grab_clipboard_image()
            if img is not None:
                self._show_image_preview(img)
                return 'break'
        except Exception:
            log.exception('Erro em _on_paste')

    # Comprime e envia imagem do clipboard para todos os membros do grupo
    def _send_clipboard_image(self, img):
        max_dim = 1920
        if img.width > max_dim or img.height > max_dim:
            img.thumbnail((max_dim, max_dim), Image.LANCZOS)
        if img.mode == 'RGBA':
            bg = Image.new('RGB', img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[3])
            img = bg
        elif img.mode != 'RGB':
            img = img.convert('RGB')
        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=85)
        image_bytes = buf.getvalue()
        if len(image_bytes) > 2 * 1024 * 1024:
            buf = io.BytesIO()
            img.save(buf, format='JPEG', quality=60)
            image_bytes = buf.getvalue()

        def _do_send():
            path = self.app.messenger.send_group_image(self.group_id, image_bytes)
            if path:
                self.after(0, lambda: self._append_image(
                    self.app.messenger.display_name, path, True))
        threading.Thread(target=_do_send, daemon=True).start()

    # Chamado quando imagem e recebida de outro membro do grupo
    def receive_image(self, display_name, image_path, timestamp=None):
        self._append_image(display_name, image_path, False, timestamp=timestamp)

    # Renderiza imagem no chat do grupo (thumbnail clicavel)
    def _append_image(self, sender, image_path, is_mine, timestamp=None):
        ts = datetime.fromtimestamp(timestamp or time.time()).strftime('%H:%M')
        self.chat_text.configure(state='normal')
        style = self.app.messenger.db.get_setting('msg_style', 'bubble')

        if style == 'bubble':
            if is_mine:
                name_tag, time_tag, msg_tag = 'my_bubble_name', 'my_bubble_time', 'my_bubble'
            else:
                name_tag, time_tag, msg_tag = 'peer_bubble_name', 'peer_bubble_time', 'peer_bubble'
        else:
            name_tag = 'my_name' if is_mine else 'peer_name'
            time_tag = 'time'
            msg_tag = 'msg'

        self.chat_text.insert('end', f'{sender}', name_tag)
        self.chat_text.insert('end', f'  {ts}\n', time_tag)

        try:
            pil_img = Image.open(image_path)
            max_w = 300
            if pil_img.width > max_w:
                ratio = max_w / pil_img.width
                pil_img = pil_img.resize(
                    (max_w, int(pil_img.height * ratio)), Image.LANCZOS)
            tk_img = ImageTk.PhotoImage(pil_img)
            self._image_cache[image_path] = tk_img
            self.chat_text.image_create('end', image=tk_img, padx=4, pady=2)
            # Aplica tag de alinhamento (justify right para is_mine em bubble mode)
            img_idx = self.chat_text.index('end - 2 chars')
            self.chat_text.tag_add(msg_tag, img_idx, self.chat_text.index('end - 1 chars'))
            tag_name = f'img_{id(tk_img)}'
            self.chat_text.tag_add(tag_name,
                                   self.chat_text.index('end - 2 chars'),
                                   self.chat_text.index('end - 1 chars'))
            self.chat_text.tag_config(tag_name, underline=False)
            self.chat_text.tag_bind(tag_name, '<Button-1>',
                                    lambda e, p=image_path: self._on_image_click(p))
            self.chat_text.tag_bind(tag_name, '<Button-3>',
                                    lambda e, p=image_path: self._on_image_right_click(e, p))
            self.chat_text.tag_bind(tag_name, '<Enter>',
                                    lambda e: self.chat_text.config(cursor='hand2'))
            self.chat_text.tag_bind(tag_name, '<Leave>',
                                    lambda e: self.chat_text.config(cursor=''))
        except Exception:
            self.chat_text.insert('end', '[Imagem indisponível]', msg_tag)

        self.chat_text.insert('end', '\n', msg_tag)
        self.chat_text.insert('end', '\n')
        self.chat_text.configure(state='disabled')
        self.chat_text.see('end')

    def _on_image_click(self, image_path):
        self._img_click_handled = True
        self._open_image_file(image_path)

    def _on_image_right_click(self, event, image_path):
        self._img_click_handled = True
        self._show_image_ctx(event, image_path)

    def _open_image_file(self, image_path):
        if not os.path.exists(image_path):
            return
        def _open():
            try:
                os.startfile(image_path)
            except Exception:
                try:
                    import subprocess
                    subprocess.Popen(['explorer', image_path])
                except Exception:
                    log.exception('Erro ao abrir imagem')
        threading.Thread(target=_open, daemon=True).start()

    def _show_image_ctx(self, event, image_path):
        m = tk.Menu(self, tearoff=0, font=('Segoe UI', 9))
        m.add_command(label='Abrir', command=lambda: self._open_image_file(image_path))
        m.add_command(label='Salvar como...', command=lambda: self._save_image_as(image_path))
        m.tk_popup(event.x_root, event.y_root)

    def _save_image_as(self, image_path):
        ext = os.path.splitext(image_path)[1] or '.jpg'
        dest = filedialog.asksaveasfilename(
            parent=self, title='Salvar imagem',
            defaultextension=ext,
            initialfile=os.path.basename(image_path),
            filetypes=[('Imagem JPEG', '*.jpg'), ('Imagem PNG', '*.png'), ('Todos', '*.*')])
        if dest:
            try:
                import shutil
                shutil.copy2(image_path, dest)
            except Exception:
                log.exception('Erro ao salvar imagem')

    # Confirmação para sair de grupo fixo.
    def _confirm_leave(self):
        if messagebox.askyesno('Sair do Grupo',
                                'Deseja sair do grupo permanentemente?',
                                parent=self):
            self._leave_group()

    def _on_close(self):
        if self.group_type == 'fixed':
            # Grupo fixo: esconder janela, permanece no grupo
            self.withdraw()
        else:
            # Grupo temporário: perguntar se quer sair
            resp = messagebox.askyesno('Sair do Grupo',
                                       'Deseja sair do grupo?',
                                       parent=self)
            if resp:
                # Sim: sai do grupo (notifica todos)
                self._leave_group()
            else:
                # Não: fecha janela mas permanece no grupo
                self.withdraw()

    # Sai do grupo e destrói a janela.
    # Envia notificações de saída em thread background para não travar a UI.
    def _leave_group(self):
        gid = self.group_id
        app = self.app
        # Remove da UI imediatamente (responsivo)
        if gid in app.group_windows:
            del app.group_windows[gid]
        if gid in app._group_tree_items:
            try:
                app.tree.delete(app._group_tree_items[gid])
            except Exception:
                pass
            del app._group_tree_items[gid]
        self.destroy()
        # Envia notificações TCP + deleta do banco em background
        threading.Thread(target=app.messenger.leave_group,
                         args=(gid,), daemon=True).start()


# =============================================================
#  MAIN WINDOW
# =============================================================
# Janela principal do MB Chat.
#
# Contém o TreeView de contatos, barra de status, nota pessoal,
# menus e gerencia todas as janelas filhas (chat, grupo, preferências).
class LanMessengerApp:
    def __init__(self):
        # Define AppUserModelID antes de criar qualquer janela para que
        # Windows agrupe todas as Toplevels deste processo sob o mesmo
        # botao da taskbar (com thumbnails nativos no hover)
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                'MBContabilidade.MBChat')
        except Exception:
            pass
        self.root = tk.Tk()                  # Janela principal tkinter
        self.root.title(APP_NAME)            # "MB Chat" na barra de título
        self.root.minsize(260, 450)          # Tamanho mínimo
        self.root.geometry('280x520')        # Tamanho inicial
        self.root.configure(bg=BG_WINDOW)
        self.root.update_idletasks()         # Força render para pegar dimensões
        _apply_rounded_corners(self.root)    # Bordas arredondadas no Windows 11+

        # Captura exceções não tratadas do tkinter para o log
        def _tk_exception(exc_type, exc_value, exc_tb):
            log.error('Tkinter exception', exc_info=(exc_type, exc_value, exc_tb))
        self.root.report_callback_exception = _tk_exception

        # Ícone da janela (iconphoto = ícone nítido na taskbar do Windows)
        self._icon_path = _get_icon_path()
        if self._icon_path:
            try:
                self.root.iconbitmap(self._icon_path)  # Ícone .ico padrão
                if HAS_PIL:
                    _ico_img = Image.open(self._icon_path)
                    _ico_img = _ico_img.resize((48, 48), Image.LANCZOS)
                    self._icon_photo = ImageTk.PhotoImage(_ico_img)
                    self.root.iconphoto(True, self._icon_photo)  # Ícone de alta qualidade
            except Exception:
                pass

        # Posiciona no canto direito da tela após a janela estar visível
        self.root.after(10, self._position_right)

        # === Dicionários de rastreamento ===
        self.chat_windows = {}              # peer_id -> ChatWindow (chats individuais abertos)
        self.group_windows = {}             # group_id -> GroupChatWindow (grupos abertos)
        self._pending_group_msgs = {}       # group_id -> [(nome, conteúdo, timestamp)] - msgs de grupo sem janela
        self.peer_items = {}                # peer_id -> item_id do TreeView
        self.peer_info = {}                 # peer_id -> {display_name, ip, status, note, ...}
        self._contact_render_cache = {}     # peer_id -> (cache_key, PIL image) para evitar re-render
        self._dept_nodes = {}               # department_name -> tree item id (nos de departamento)
        self._file_dialogs = {}             # file_id -> FileTransferDialog (diálogos de transferência)
        self._reminders_window = None       # Referência à janela de Lembretes (se aberta)
        self._reminders_list_frame = None   # Frame de lista para auto-refresh pelo timer
        self._transfer_history = []         # Histórico de transferências para a janela de transferências
        self._transfers_window = None       # Referência à janela de Transferências (se aberta)
        self._tray_icon = None              # Ícone do system tray (pystray)
        self._last_notif_peer = None        # Último peer que gerou notificação (para clique no tray)
        self._pending_flash_target = None   # Alvo pendente para abrir ao clicar no app piscando (peer_id, 'group:gid', '__reminders__')

        self._build_ui()
        self.root.protocol('WM_DELETE_WINDOW', self._on_close)
        self.root.bind('<FocusIn>', self._on_main_focus)

        # Init pesado deferido: janela aparece rapido, depois carrega rede/DB/tray
        self.root.after_idle(self._deferred_init)

    # Inicializacao deferida - roda apos a janela aparecer.
    def _deferred_init(self):
        self._init_messenger()

        # Carregar ramal salvo
        try:
            self.ramal_var.set(self.messenger.ramal or '')
        except Exception:
            pass

        # Carregar nota salva do banco
        saved_note = self.messenger.note
        if saved_note:
            self.note_entry.delete('1.0', 'end')
            self.note_entry.insert('1.0', saved_note)
            self.note_entry.config(fg='#ffffff')
            self._last_saved_note = saved_note
            # Renderiza emojis coloridos na nota restaurada
            self.root.after(50, self._do_note_emoji_scan)

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

        # Carrega grupos fixos salvos no DB
        self._load_saved_groups()

        # Inicia tray icon para notificacoes
        if HAS_TRAY and HAS_PIL:
            self.root.after(50, self._start_tray)

        # Registra autostart respeitando escolha do instalador na primeira execucao
        autostart_val = self.messenger.db.get_setting('autostart', None)
        if autostart_val is None:
            # Primeira execucao — detecta se instalador criou atalho na pasta Startup
            startup_lnk = os.path.join(
                os.environ.get('APPDATA', ''),
                'Microsoft', 'Windows', 'Start Menu', 'Programs', 'Startup', 'MB Chat.lnk')
            autostart_val = '1' if os.path.exists(startup_lnk) else '0'
            self.messenger.db.set_setting('autostart', autostart_val)
        if autostart_val == '1':
            _setup_autostart()

        # Mostra barra de "atualizacao concluida" se versao mudou
        self._check_post_update()

        # Verifica atualizacoes em background
        self.root.after(2000, self._check_update_startup)

    # Posiciona a janela no canto direito da tela, centralizada na vertical.
    def _position_right(self):
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
            on_group_invite=self._safe(self._on_group_invite),
            on_group_message=self._safe(self._on_group_message),
            on_group_leave=self._safe(self._on_group_leave),
            on_group_join=self._safe(self._on_group_join),
            on_image=self._safe(self._on_image),
            on_poll=self._safe(self._on_poll),
            on_status=self._safe(self._on_peer_status),
        )
        self.messenger.start()
        # Conecta SoundPlayer ao db e migra settings antigas de alertas
        SoundPlayer.db = self.messenger.db
        self._migrate_alert_settings()
        self.lbl_username.config(text=f' {self.messenger.display_name}')
        self.root.title(APP_NAME)
        self._update_avatar()
        self._start_reminder_timer()

    # Migracao one-shot: valores antigos (sound, notif_windows, flash_taskbar,
    # sound_msg) passam para as novas chaves granulares se estas ainda nao existirem.
    def _migrate_alert_settings(self):
        try:
            db = self.messenger.db
            pairs = [
                ('sound', 'sound_master'),
                ('sound_msg', 'sound_msg_private'),
                ('notif_windows', 'notif_msg_private'),
                ('flash_taskbar', 'flash_taskbar_msg'),
            ]
            for old, new in pairs:
                existing_new = db.get_setting(new, None)
                if existing_new is not None:
                    continue
                old_val = db.get_setting(old, None)
                if old_val is not None:
                    db.set_setting(new, old_val)
        except Exception:
            pass

    def _safe(self, func):
        def wrapper(*args, **kwargs):
            if kwargs:
                self.root.after(0, lambda: func(*args, **kwargs))
            else:
                self.root.after(0, func, *args)
        return wrapper

    # Atualiza textos da UI apos mudanca de idioma.
    def _rebuild_ui_language(self):
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
        m2.add_command(label='Lembretes',
                       command=self._show_reminders)
        m2.add_separator()
        m2.add_command(label=_t('menu_check_update'),
                       command=self._manual_check_update)
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
        note_text = self._note_get_text()
        if not note_text.strip() or \
           note_text in ('Digite uma nota', 'Type a note'):
            self.note_entry.delete('1.0', 'end')
            self.note_entry.insert('1.0', _t('note_placeholder'))

        # Update group label
        self.tree.item(self.group_general, text=_t('group_general'))

        # Update context menu
        self.ctx_menu.entryconfigure(0, label=_t('ctx_send_msg'))
        self.ctx_menu.entryconfigure(1, label=_t('ctx_send_file'))
        self.ctx_menu.entryconfigure(3, label=_t('ctx_info'))

    # Aplica um tema em toda a interface.
    def apply_theme(self, theme_name):
        t = THEMES.get(theme_name, THEMES['MB Contabilidade'])
        self._theme = t
        self._current_theme = theme_name
        self._contact_render_cache.clear()  # cores podem mudar, invalida cache de render

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
                        rowheight=44)
        style.configure('Contacts.Treeview.Heading',
                        background=t['bg_group'],
                        foreground=t.get('fg_group', '#4a5568'))
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
                                    foreground=t.get('fg_group', '#4a5568'),
                                    font=('Segoe UI', 8, 'bold'))
            self.tree.tag_configure('online', foreground=t['fg_black'])
            self.tree.tag_configure('away', foreground=t['fg_orange'])
            self.tree.tag_configure('busy', foreground=t['fg_red'])
            self.tree.tag_configure('offline', foreground=t['fg_gray'])


        # --- User info panel (navy header) ---
        navy = t.get('accent', '#0f2a5c')
        navy_light = t.get('btn_active', '#1a3f7a')
        if hasattr(self, 'lbl_username'):
            self.lbl_username.configure(bg=navy, fg='#ffffff')
            # Re-apply navy to parent frames
            for w in (self.lbl_username.master, self.lbl_username.master.master,
                      self.lbl_username.master.master.master):
                try:
                    w.configure(bg=navy)
                except Exception:
                    pass
        if hasattr(self, 'avatar_canvas'):
            self.avatar_canvas.configure(bg=navy)
        if hasattr(self, 'note_entry'):
            self.note_entry.configure(bg=navy_light, fg='#c8d6e5',
                                      insertbackground='#c8d6e5')
            try:
                self.note_entry.master.configure(bg=navy_light)
                self.note_entry.master.master.configure(bg=navy)
            except Exception:
                pass
        if hasattr(self, 'status_combo'):
            st = ttk.Style()
            st.configure('Status.TCombobox',
                         fieldbackground=navy, background=navy,
                         foreground='#c8d6e5')
            st.map('Status.TCombobox',
                   fieldbackground=[('readonly', navy)],
                   background=[('readonly', navy_light)],
                   foreground=[('readonly', '#c8d6e5')],
                   bordercolor=[('readonly', navy)],
                   lightcolor=[('readonly', navy)],
                   darkcolor=[('readonly', navy)])

        # --- Chat windows abertas ---
        for cw in self.chat_windows.values():
            self._apply_theme_to_chat(cw, t)
        # --- Group windows abertas ---
        for gw in self.group_windows.values():
            self._apply_theme_to_group_chat(gw, t)

    # Aplica cores basicas em frames e labels recursivamente.
    def _apply_theme_recursive(self, widget, t):
        # Skip navy user panel and its children
        if getattr(widget, '_navy_panel', False):
            return
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

    # Aplica tema em uma ChatWindow.
    def _apply_theme_to_chat(self, cw, t):
        try:
            cw.configure(bg=t['bg_window'])
            chat_bg = t.get('bg_chat', t['bg_white'])
            cw.chat_text.configure(bg=chat_bg, fg=t['fg_msg'],
                                   insertbackground=t['fg_black'])
            cw.chat_text.tag_configure('time', foreground=t['fg_time'])
            cw.chat_text.tag_configure('my_name', foreground=t['fg_my_name'])
            cw.chat_text.tag_configure('peer_name',
                                       foreground=t['fg_peer_name'])
            cw.chat_text.tag_configure('msg', foreground=t['fg_msg'])
            # Bubble tags
            msg_my_bg = t.get('msg_my_bg', '#e8f0fe')
            msg_peer_bg = t.get('msg_peer_bg', '#f0f0f0')
            for tag_suffix in ('', '_name', '_time'):
                cw.chat_text.tag_configure(f'my_bubble{tag_suffix}',
                                           background=msg_my_bg)
                cw.chat_text.tag_configure(f'peer_bubble{tag_suffix}',
                                           background=msg_peer_bg)
            if hasattr(cw, '_chat_scrollbar'):
                cw._chat_scrollbar.configure(troughcolor=chat_bg)
            input_bg = t.get('bg_input', t['bg_white'])
            cw.entry.configure(bg=input_bg, fg=t['fg_black'],
                               insertbackground=t['fg_black'])
            # Header navy
            header_bg = t.get('chat_header_bg', t.get('bg_header', '#0f2a5c'))
            header_fg = t.get('chat_header_fg', '#ffffff')
            header_sub = t.get('chat_header_sub', t['fg_gray'])
            cw.lbl_peer.configure(bg=header_bg, fg=header_fg)
            cw.lbl_typing.configure(bg=header_bg, fg=header_sub)
            try: cw.chat_text.tag_raise('sel')
            except tk.TclError: pass
        except Exception:
            log.exception('Erro ao aplicar tema no chat')

    # Aplica tema em uma GroupChatWindow (bolhas + cores)
    def _apply_theme_to_group_chat(self, gw, t):
        try:
            chat_bg = t.get('bg_chat', t['bg_white'])
            gw.chat_text.configure(bg=chat_bg, fg=t['fg_msg'])
            gw.chat_text.tag_configure('time', foreground=t['fg_time'])
            gw.chat_text.tag_configure('my_name', foreground=t['fg_my_name'])
            gw.chat_text.tag_configure('peer_name', foreground=t['fg_peer_name'])
            gw.chat_text.tag_configure('msg', foreground=t['fg_msg'])
            msg_my_bg = t.get('msg_my_bg', '#e8f0fe')
            msg_peer_bg = t.get('msg_peer_bg', '#f0f0f0')
            for tag_suffix in ('', '_name', '_time'):
                gw.chat_text.tag_configure(f'my_bubble{tag_suffix}',
                                           background=msg_my_bg)
                gw.chat_text.tag_configure(f'peer_bubble{tag_suffix}',
                                           background=msg_peer_bg)
            input_bg = t.get('bg_input', t['bg_white'])
            gw.entry.configure(bg=input_bg, fg=t['fg_black'],
                               insertbackground=t['fg_black'])
            try: gw.chat_text.tag_raise('sel')
            except tk.TclError: pass
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
        m2.add_command(label='Lembretes', command=self._show_reminders)
        m2.add_separator()
        m2.add_command(label=_t('menu_check_update'), command=self._manual_check_update)
        menubar.add_cascade(label=_t('menu_tools'), menu=m2)

        m3 = tk.Menu(menubar, tearoff=0, font=FONT)
        m3.add_command(label=f'{_t("menu_about")} {APP_NAME}', command=self._show_about)
        menubar.add_cascade(label=_t('menu_help'), menu=m3)

        self.root.config(menu=menubar)

        # User Info Panel - Navy header (identidade MB)
        NAVY = '#0f2a5c'
        user_frame = tk.Frame(self.root, bg=NAVY, bd=0, relief='flat')
        user_frame._navy_panel = True  # skip in recursive theme
        user_frame.pack(fill='x', padx=0, pady=0)

        user_inner = tk.Frame(user_frame, bg=NAVY)
        user_inner.pack(fill='x', padx=10, pady=(10, 8))

        # Avatar 40x40
        self.avatar_canvas = tk.Canvas(user_inner, width=40, height=40,
                                       bg=NAVY, highlightthickness=0,
                                       cursor='hand2')
        self.avatar_canvas.pack(side='left', padx=(0, 10))
        self.avatar_canvas.bind('<Button-1>',
                                lambda e: self._show_account())
        self._draw_default_avatar(0)

        name_status = tk.Frame(user_inner, bg=NAVY)
        name_status.pack(side='left', fill='x', expand=True)

        self.lbl_username = tk.Label(name_status, text=_t('user_default'),
                                     font=('Segoe UI', 11, 'bold'),
                                     bg=NAVY, fg='#ffffff', anchor='w')
        self.lbl_username.pack(fill='x')

        status_row = tk.Frame(name_status, bg=NAVY)
        status_row.pack(fill='x')

        # Estilizar combobox moderno
        style = ttk.Style()
        style.configure('Status.TCombobox',
                        fieldbackground=NAVY, background=NAVY,
                        foreground='#c8d6e5', selectbackground=NAVY,
                        selectforeground='#ffffff', borderwidth=0,
                        arrowcolor='#c8d6e5')
        style.map('Status.TCombobox',
                  fieldbackground=[('readonly', NAVY)],
                  background=[('readonly', '#1a3f7a')],
                  foreground=[('readonly', '#c8d6e5')],
                  bordercolor=[('readonly', NAVY)],
                  lightcolor=[('readonly', NAVY)],
                  darkcolor=[('readonly', NAVY)],
                  arrowcolor=[('readonly', '#c8d6e5')])

        self.status_var = tk.StringVar(value=_t('status_available'))
        self.status_combo = ttk.Combobox(
            status_row, textvariable=self.status_var,
            values=[_t('status_available'), _t('status_away'),
                    _t('status_busy'), _t('status_offline')],
            state='readonly', font=('Segoe UI', 8), width=12,
            style='Status.TCombobox')
        self.status_combo.pack(side='left')
        self.status_combo.bind('<<ComboboxSelected>>',
                               self._on_status_change)

        # Ramal (4 digitos numericos) — substitui badge de Departamento no TreeView
        tk.Label(status_row, text='Ramal:', font=('Segoe UI', 8),
                 bg=NAVY, fg='#c8d6e5').pack(side='left', padx=(10, 3))
        vcmd = (self.root.register(self._validate_ramal_entry), '%P')
        self.ramal_var = tk.StringVar(value='')
        self.ramal_entry = tk.Entry(status_row, textvariable=self.ramal_var,
                                    font=('Segoe UI', 9), width=6,
                                    bg='#1a3f7a', fg='#ffffff',
                                    insertbackground='#ffffff',
                                    relief='flat', bd=0, justify='center',
                                    validate='key', validatecommand=vcmd)
        self.ramal_entry.pack(side='left', ipady=2)
        self.ramal_entry.bind('<FocusOut>', lambda e: self._save_ramal())
        self.ramal_entry.bind('<Return>', lambda e: (self._save_ramal(), self.root.focus_set()))

        # Botões de ação rápida: Transmitir e Bate Papo
        action_row = tk.Frame(user_frame, bg=NAVY)
        action_row.pack(fill='x', padx=10, pady=(0, 4))

        btn_bcast = tk.Button(action_row, text='\U0001f4e2  Transmitir',
                              font=('Segoe UI', 8, 'bold'), bg='#1a3f7a',
                              fg='#ffffff', relief='flat', bd=0,
                              cursor='hand2', padx=10, pady=3,
                              activebackground='#2451a0',
                              activeforeground='#ffffff',
                              command=self._show_broadcast)
        btn_bcast.pack(side='left', padx=(0, 6))

        btn_grp = tk.Button(action_row, text='\U0001f4ac  Criar Grupo',
                            font=('Segoe UI', 8, 'bold'), bg='#1a3f7a',
                            fg='#ffffff', relief='flat', bd=0,
                            cursor='hand2', padx=10, pady=3,
                            activebackground='#2451a0',
                            activeforeground='#ffffff',
                            command=self._show_group_chat_dialog)
        btn_grp.pack(side='left')

        # Nota do usuário
        note_row = tk.Frame(user_frame, bg=NAVY)
        note_row.pack(fill='x', padx=10, pady=(0, 8))

        note_border = tk.Frame(note_row, bg='#1a3f7a', bd=0)
        note_border.pack(fill='x')

        # Emoji button colorido para a nota — empacotado PRIMEIRO (side='right')
        # para garantir que reserve espaço antes do Text expandir
        self._note_emoji_cache = {}   # cache emoji_char -> PhotoImage
        self._note_img_map = {}       # img_name -> emoji_char
        self._note_emoji_btn_img = _render_color_emoji('\U0001f60a', 16)
        if self._note_emoji_btn_img:
            btn_note_emoji = tk.Button(note_border, image=self._note_emoji_btn_img,
                                       relief='flat', bd=0, cursor='hand2',
                                       bg='#1a3f7a', activebackground='#2451a0',
                                       command=self._show_note_emoji_picker)
        else:
            btn_note_emoji = tk.Button(note_border, text='\U0001f60a', font=('Segoe UI', 10),
                                       relief='flat', bd=0, cursor='hand2',
                                       bg='#1a3f7a', fg='#c8d6e5', activebackground='#2451a0',
                                       command=self._show_note_emoji_picker)
        btn_note_emoji.pack(side='right', padx=2)

        self.note_entry = tk.Text(note_border, font=FONT, bg='#1a3f7a',
                                   fg='#c8d6e5', relief='flat', bd=0,
                                   insertbackground='#c8d6e5',
                                   height=1, width=1, wrap='none', undo=False,
                                   pady=5, padx=4)
        self.note_entry.pack(side='left', fill='x', expand=True)

        self.note_entry.insert('1.0', _t('note_placeholder'))
        self._last_saved_note = ''
        self.note_entry.bind('<FocusIn>', self._note_focus_in)
        self.note_entry.bind('<FocusOut>', self._note_focus_out)
        self.note_entry.bind('<Return>', self._note_save)
        self.note_entry.bind('<<Modified>>', self._on_note_modified)

        # Separador
        tk.Frame(self.root, bg='#e2e8f0', height=1).pack(fill='x')

        # Barra de Busca (borda arredondada via Canvas)
        search_frame = tk.Frame(self.root, bg=BG_WINDOW)
        search_frame.pack(fill='x', padx=8, pady=6)

        # Borda via Frame-in-Frame (portátil em qualquer PC)
        search_border = tk.Frame(search_frame, bg='#d0d5dd', bd=0,
                                  highlightthickness=0)
        search_border.pack(fill='x')

        search_inner = tk.Frame(search_border, bg='#ffffff', bd=0,
                                highlightthickness=0)
        search_inner.pack(fill='x', padx=1, pady=1)

        self._search_icon = _create_mdl2_icon_static('\uE721', size=14, color='#a0aec0')
        if self._search_icon:
            tk.Label(search_inner, image=self._search_icon,
                     bg='#ffffff').pack(side='left', padx=(6, 2))
        else:
            tk.Label(search_inner, text='\u2315', font=('Segoe UI', 9),
                     bg='#ffffff', fg='#a0aec0').pack(side='left', padx=(6, 2))

        self._search_var = tk.StringVar()
        self._search_entry = tk.Entry(search_inner, textvariable=self._search_var,
                                       font=('Segoe UI', 9), bg='#ffffff',
                                       fg='#1a202c', relief='flat', bd=0,
                                       insertbackground='#1a202c')
        self._search_entry.pack(side='left', fill='x', expand=True, ipady=4, padx=2)
        self._search_entry.insert(0, 'Buscar contatos...')
        self._search_entry.config(fg='#a0aec0')
        self._search_entry.bind('<FocusIn>', self._search_focus_in)
        self._search_entry.bind('<FocusOut>', self._search_focus_out)
        self._search_var.trace_add('write', self._filter_contacts)

        # Contact Treeview
        tree_frame = tk.Frame(self.root, bg=BG_WHITE, bd=0,
                              highlightthickness=0)
        tree_frame.pack(fill='both', expand=True, padx=0, pady=0)

        style = ttk.Style()
        style.theme_use('clam')
        _setup_scrollbar_style()
        style.configure('Contacts.Treeview', background='#ffffff',
                         foreground='#1a202c', fieldbackground='#ffffff',
                         font=('Segoe UI', 10), rowheight=44, borderwidth=0,
                         indent=5)
        style.configure('Contacts.Treeview.Heading', background='#e2e2e2',
                         foreground='#4a5568', font=FONT_BOLD)
        style.map('Contacts.Treeview',
                   background=[('selected', '#e8f0fe')],
                   foreground=[('selected', '#1a202c')])
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

        # Imagens de bolinha colorida para indicar status (10x10 pixels)
        self._status_dots = {}
        self._create_status_dots()  # Gera as bolinhas de cor para cada status

        # Cria o nó raiz "Geral" no TreeView — contatos sem departamento caem aqui.
        # Fica logicamente abaixo dos departamentos; novos nos de departamento sao
        # inseridos ANTES de group_general via _get_dept_node.
        self.group_general = self.tree.insert('', 'end', text=_t('group_general'),
                                              open=True, tags=('group',))
        # Cria o nó raiz "Grupos" — grupos de bate papo aparecem aqui (sempre ultimo)
        self.group_groups = self.tree.insert('', 'end', text='Grupos',
                                             open=True, tags=('group',))
        # Offline: contatos offline nao aparecem no TreeView (sao detachados)
        # group_offline mantido como atributo mas sem no visivel
        self.group_offline = None
        # Dicionário que mapeia group_id -> iid do item no TreeView
        self._group_tree_items = {}  # group_id -> tree item id
        # Configura visual do cabeçalho de seção (cinza, bold, menor)
        self.tree.tag_configure('group', background='#e2e2e2',
                                foreground='#4a5568',
                                font=('Segoe UI', 8, 'bold'))
        # Configura visual de item de grupo (cor escura, fonte normal)
        self.tree.tag_configure('group_item', foreground='#1a202c',
                                font=('Segoe UI', 9))
        # Tags de cor para cada status de contato
        self.tree.tag_configure('online', foreground=FG_BLACK)   # online = preto
        self.tree.tag_configure('away', foreground=FG_ORANGE)    # ausente = laranja
        self.tree.tag_configure('busy', foreground=FG_RED)       # ocupado = vermelho
        self.tree.tag_configure('offline', foreground=FG_GRAY)   # offline = cinza
        self.tree.tag_configure('unread', font=FONT_BOLD)        # não lido = negrito

        # Duplo clique abre chat ou grupo
        self.tree.bind('<Double-1>', self._on_tree_dbl)
        # Botão direito abre menu de contexto
        self.tree.bind('<Button-3>', self._on_tree_right)

        # Menu de contexto (clique direito no contato)
        self.ctx_menu = tk.Menu(self.root, tearoff=0, font=FONT)
        self.ctx_menu.add_command(label=_t('ctx_send_msg'),
                                  command=self._ctx_chat)   # Abrir chat
        self.ctx_menu.add_command(label=_t('ctx_send_file'),
                                  command=self._ctx_file)   # Enviar arquivo
        self.ctx_menu.add_separator()
        self.ctx_menu.add_command(label=_t('ctx_info'), command=self._ctx_info)


    # Cria imagens de bolinha colorida (10x10px) para cada status possível.
    #
    # Utiliza equação de círculo (dx²+dy² <= r²) pixel a pixel para
    # desenhar bolinhas suaves sem precisar do PIL.
    # As imagens ficam salvas em self._status_dots[status].
    def _create_status_dots(self):
        # Mapa de status -> cor hexadecimal da bolinha
        dot_colors = {
            'online': '#48bb78',   # verde
            'away': '#ecc94b',     # amarelo
            'busy': '#f56565',     # vermelho
            'offline': '#a0aec0',  # cinza
        }
        size = 10  # tamanho em pixels da bolinha
        for status, color in dot_colors.items():
            img = tk.PhotoImage(width=size, height=size)  # imagem vazia
            cx, cy, r = size // 2, size // 2, size // 2 - 1  # centro e raio
            for y in range(size):
                for x in range(size):
                    dx, dy = x - cx, y - cy  # distância do centro
                    if dx * dx + dy * dy <= r * r:  # está dentro do círculo?
                        img.put(color, (x, y))  # pinta o pixel
            self._status_dots[status] = img  # salva no cache
        # Cache de imagens de avatar por contato (uid_status -> PhotoImage)
        self._contact_avatars = {}
        self._contact_avatar_pil = {}   # uid_status -> PIL Image (para composição)
        self._row_images = {}           # uid -> PhotoImage da linha composta

    # Cria imagem de avatar circular com status dot para o treeview.
    def _create_contact_avatar(self, uid, name, status='online'):
        size = 36
        dot_size = 10
        dot_colors = {
            'online': '#48bb78', 'away': '#ecc94b',
            'busy': '#f56565', 'offline': '#a0aec0',
        }
        contact = self.messenger.db.get_contact(uid)
        idx = contact.get('avatar_index', 0) if contact else 0
        avatar_data_b64 = contact.get('avatar_data', '') if contact else ''
        av_color, _ = AVATAR_COLORS[idx % len(AVATAR_COLORS)]

        if HAS_PIL:
            from PIL import ImageDraw, ImageFont
            has_custom = False

            # Tentar usar foto do peer (avatar_data via rede)
            if avatar_data_b64:
                try:
                    import base64
                    from io import BytesIO
                    raw = base64.b64decode(avatar_data_b64)
                    pil_img = Image.open(BytesIO(raw))
                    img = _make_circular_avatar(pil_img, size)
                    has_custom = True
                except Exception:
                    pass

            if not has_custom:
                # Avatar padrão com antialias 2x (sem borda)
                big = size * 2
                img_big = Image.new('RGBA', (big, big), (0, 0, 0, 0))
                draw_big = ImageDraw.Draw(img_big)
                draw_big.ellipse([0, 0, big - 1, big - 1], fill=av_color)
                initial = name[0].upper() if name else 'U'
                try:
                    font = ImageFont.truetype('segoeui.ttf', 30)
                except Exception:
                    font = ImageFont.load_default()
                bbox = draw_big.textbbox((0, 0), initial, font=font)
                tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
                draw_big.text(((big - tw) / 2 - bbox[0],
                               (big - th) / 2 - bbox[1]),
                              initial, fill='white', font=font)
                img = img_big.resize((size, size), Image.LANCZOS)

            # Status dot (bottom-right) com borda branca
            draw = ImageDraw.Draw(img)
            dot_color = dot_colors.get(status, '#a0aec0')
            dx, dy = size - dot_size - 1, size - dot_size - 1
            draw.ellipse([dx - 1, dy - 1, dx + dot_size + 1, dy + dot_size + 1],
                         fill='white')
            draw.ellipse([dx, dy, dx + dot_size, dy + dot_size],
                         fill=dot_color)
            self._contact_avatar_pil[f'{uid}_{status}'] = img.copy()
            photo = ImageTk.PhotoImage(img)
        else:
            photo = tk.PhotoImage(width=size, height=size)
            cx, cy, r = size // 2, size // 2, size // 2 - 2
            for y in range(size):
                for x in range(size):
                    ddx, ddy = x - cx, y - cy
                    if ddx * ddx + ddy * ddy <= r * r:
                        photo.put(av_color, (x, y))
            dot_color = dot_colors.get(status, '#a0aec0')
            dcx, dcy = size - dot_size // 2 - 2, size - dot_size // 2 - 2
            dr = dot_size // 2
            for y in range(size):
                for x in range(size):
                    ddx, ddy = x - dcx, y - dcy
                    if ddx * ddx + ddy * ddy <= dr * dr:
                        photo.put(dot_color, (x, y))

        self._contact_avatars[f'{uid}_{status}'] = photo
        return photo

    # Renderiza linha composta (avatar + nome + nota com emojis coloridos) para o TreeView.
    # Retorna ImageTk.PhotoImage ou None se PIL indisponível.
    def _render_contact_display(self, uid, name, note, status, bold=False, unread_count=0, dept='', ramal=''):
        if not HAS_PIL:
            return None
        from PIL import ImageDraw, ImageFont
        emoji_size = 20
        try:
            font_name = 'seguisb.ttf' if bold else 'segoeui.ttf'
            name_font = ImageFont.truetype(font_name, 16)
            note_font = ImageFont.truetype('segoeui.ttf', 13)
            dept_font = ImageFont.truetype('segoeui.ttf', 12)
            emoji_font_path = 'C:/Windows/Fonts/seguiemj.ttf'
            has_emoji_font = os.path.exists(emoji_font_path)
            emoji_font = ImageFont.truetype(emoji_font_path, emoji_size) if has_emoji_font else None
        except Exception:
            return None

        status_colors = {
            'online': '#1a202c', 'away': '#cc8800',
            'busy': '#cc0000', 'offline': '#888888'
        }
        name_color = status_colors.get(status, '#1a202c')
        note_color = '#718096'
        dept_color = '#5a7bb5'

        name_text = name
        if unread_count > 0:
            name_text += f' ({unread_count})'

        tmp = Image.new('RGBA', (1, 1))
        d = ImageDraw.Draw(tmp)

        name_bbox = d.textbbox((0, 0), name_text, font=name_font)
        name_w = name_bbox[2] - name_bbox[0]

        # Ramal badge (substituiu badge de Departamento)
        dept_w = 0
        dept_text = ''
        if ramal:
            dept_text = f'[{ramal}]'
            db = d.textbbox((0, 0), dept_text, font=dept_font)
            dept_w = db[2] - db[0] + 6

        # Segmentos da nota (texto e emoji separados)
        note_segments = []
        total_note_w = 0
        emoji_render_size = emoji_size + 4  # tamanho final do emoji na imagem composta (bate com canvas_sz)
        if note:
            sep = '  -  '
            sep_bbox = d.textbbox((0, 0), sep, font=note_font)
            sep_w = sep_bbox[2] - sep_bbox[0]
            note_segments.append(('text', sep, sep_w))
            total_note_w += sep_w

            last_end = 0
            for m in _EMOJI_RE.finditer(note):
                if m.start() > last_end:
                    part = note[last_end:m.start()]
                    bbox = d.textbbox((0, 0), part, font=note_font)
                    w = bbox[2] - bbox[0]
                    note_segments.append(('text', part, w))
                    total_note_w += w
                emoji_char = m.group()
                note_segments.append(('emoji', emoji_char, emoji_render_size))
                total_note_w += emoji_render_size
                last_end = m.end()
            if last_end < len(note):
                part = note[last_end:]
                bbox = d.textbbox((0, 0), part, font=note_font)
                w = bbox[2] - bbox[0]
                note_segments.append(('text', part, w))
                total_note_w += w

        # Monta imagem composta
        av_size = 36
        gap = 10
        total_w = av_size + gap + name_w + dept_w + total_note_w + 10
        height = 46

        img = Image.new('RGBA', (total_w, height), (255, 255, 255, 0))

        # Cola avatar (centralizado verticalmente)
        cache_key = f'{uid}_{status}'
        avatar_pil = self._contact_avatar_pil.get(cache_key)
        if avatar_pil:
            av_y = (height - av_size) // 2
            img.paste(avatar_pil, (0, av_y), avatar_pil)

        draw = ImageDraw.Draw(img)
        text_y = (height - 18) // 2  # centro vertical para texto ~16px

        # Nome
        x = av_size + gap
        draw.text((x, text_y), name_text, fill=name_color, font=name_font)
        x += name_w

        # Departamento
        if dept_text:
            draw.text((x + 4, text_y + 2), dept_text, fill=dept_color, font=dept_font)
            x += dept_w

        # Nota com emojis coloridos
        for seg_type, seg_text, seg_w in note_segments:
            if seg_type == 'emoji' and emoji_font:
                try:
                    clean_seg = seg_text.replace('\ufe0f', '')
                    # Mesmo approach de _render_color_emoji: canvas do tamanho final, sem resize
                    canvas_sz = emoji_render_size
                    em_img = Image.new('RGBA', (canvas_sz, canvas_sz), (255, 255, 255, 0))
                    em_draw = ImageDraw.Draw(em_img)
                    eb = em_draw.textbbox((0, 0), clean_seg, font=emoji_font)
                    ew, eh = eb[2] - eb[0], eb[3] - eb[1]
                    ex = (canvas_sz - ew) // 2 - eb[0]
                    ey_off = (canvas_sz - eh) // 2 - eb[1]
                    em_draw.text((ex, ey_off), clean_seg, font=emoji_font, embedded_color=True)
                    paste_y = (height - canvas_sz) // 2
                    img.paste(em_img, (int(x), paste_y), em_img)
                except Exception:
                    draw.text((x, text_y), seg_text, fill=note_color, font=note_font)
            else:
                draw.text((x, text_y), seg_text, fill=note_color, font=note_font)
            x += seg_w

        photo = ImageTk.PhotoImage(img)
        self._row_images[uid] = photo  # previne garbage collection
        return photo

    # Carrega todos os contatos do banco (inclusive offline) no TreeView ao iniciar.
    #
    # Chamado uma vez na inicializacao para popular a lista lateral com
    # contatos previamente vistos. Online -> secao Geral. Offline -> secao Offline.
    # Tambem inicializa peer_info com dados do banco.
    def _load_saved_contacts(self):
        contacts = self.messenger.db.get_contacts(online_only=False)  # busca todos do banco

        # Deduplica por display_name: mantém apenas o registro mais recente (last_seen)
        seen_names = {}   # display_name -> (uid, last_seen)
        stale_uids = set()
        for c in contacts:
            uid = c['user_id']
            if uid == self.messenger.user_id:
                continue
            name = c.get('display_name', 'Unknown')
            last_seen = c.get('last_seen', 0) or 0
            if name in seen_names:
                prev_uid, prev_ls = seen_names[name]
                if last_seen > prev_ls:
                    stale_uids.add(prev_uid)
                    seen_names[name] = (uid, last_seen)
                else:
                    stale_uids.add(uid)
            else:
                seen_names[name] = (uid, last_seen)
        # Remove registros obsoletos do banco
        for stale_uid in stale_uids:
            self.messenger.db.delete_contact(stale_uid)

        for c in contacts:
            uid = c['user_id']
            if uid == self.messenger.user_id:  # pula o proprio usuario
                continue
            if uid in stale_uids:  # registro obsoleto (duplicata antiga)
                continue
            if uid in self.peer_items:  # ja esta no TreeView (peer ativo)? pula
                continue
            status = c.get('status', 'offline')  # status salvo no banco
            tag = status if status in ('online', 'away', 'busy') else 'offline'
            name = c.get('display_name', 'Unknown')
            note = c.get('note', '')
            dept = c.get('department', '')
            ramal = c.get('ramal', '')
            avatar = self._create_contact_avatar(uid, name, tag)
            row_img = self._render_contact_display(uid, name, note, tag, dept=dept, ramal=ramal)
            # Offline nao aparece no TreeView — salva info mas nao insere
            if tag == 'offline':
                self.peer_info[uid] = {
                    'display_name': name,
                    'ip': c.get('ip_address', ''),
                    'hostname': c.get('hostname', ''),
                    'status': status,
                    'note': note,
                }
                continue
            parent = self.group_general
            if dept:
                parent = self._get_dept_node(dept)
            if row_img:
                iid = self.tree.insert(parent, 'end', text='', tags=(tag,), image=row_img)
            else:
                display = f'  {name}'
                if note:
                    display += f'  -  {note}'
                iid = self.tree.insert(parent, 'end', text=display, tags=(tag,), image=avatar)
            self.peer_items[uid] = iid
            self.peer_info[uid] = {
                'display_name': name,
                'ip': c.get('ip_address', ''),
                'hostname': c.get('hostname', ''),
                'status': status,
                'note': note,
                'department': dept,
                'ramal': ramal,
            }
        self._sort_tree_children(self.group_general)

    # --- Avatar ---
    # Desenha avatar padrao (circulo colorido com letra U) no canvas do header.
    def _draw_default_avatar(self, idx):
        self.avatar_canvas.delete('all')   # limpa canvas antes de redesenhar
        color, _ = AVATAR_COLORS[idx % len(AVATAR_COLORS)]  # cor baseada no indice
        self.avatar_canvas.create_oval(2, 2, 38, 38, fill=color,
                                       outline='', width=0)  # circulo sem borda
        self.avatar_canvas.create_text(20, 20, text='U', fill='white',
                                       font=('Segoe UI', 14, 'bold'))  # letra U centralizada

    # Atualiza o canvas de avatar do header com foto ou circulo colorido do usuario.
    #
    # Tenta carregar foto personalizada do banco (custom_avatar = caminho do arquivo).
    # Se nao houver ou falhar, desenha circulo colorido com a inicial do nome.
    # Suporta PIL (recorte circular antialias) e fallback sem PIL (oval nativa).
    def _update_avatar(self):
        db = self.messenger.db                              # atalho para o banco local
        idx = int(db.get_setting('avatar_index', '0'))    # indice de cor padrao do usuario
        custom = db.get_setting('custom_avatar', '')      # caminho do arquivo de foto (ou vazio)
        self.avatar_canvas.delete('all')

        if custom and os.path.exists(custom):  # arquivo de foto existe no disco?
            try:
                if HAS_PIL:  # PIL disponivel: usa recorte circular antialias
                    img = _make_circular_avatar(custom, 36)   # recorta em circulo 36px
                    self._avatar_img = ImageTk.PhotoImage(img)  # converte para tkinter
                else:  # fallback sem PIL: carrega direto e redimensiona por subsample
                    self._avatar_img = tk.PhotoImage(file=custom)  # carrega imagem
                    w = self._avatar_img.width()   # largura em pixels
                    h = self._avatar_img.height()  # altura em pixels
                    if w > 0 and h > 0:
                        factor = max(w // 28, h // 28, 1)  # fator de reducao para 28px
                        self._avatar_img = self._avatar_img.subsample(factor)  # reduz
                self.avatar_canvas.create_image(20, 20,
                                                image=self._avatar_img)  # exibe no canvas
                return  # foto carregada: nao precisa gerar avatar padrao
            except Exception:
                pass  # foto corrompida ou inacessivel: cai para avatar padrao

        # Sem foto personalizada: gera avatar padrao (circulo colorido, sem borda)
        color, _ = AVATAR_COLORS[idx % len(AVATAR_COLORS)]  # cor conforme indice
        initial = self.messenger.display_name[0].upper() if self.messenger.display_name else 'U'  # inicial
        if HAS_PIL:
            from PIL import ImageDraw, ImageFont
            big = 72
            img_big = Image.new('RGBA', (big, big), (0, 0, 0, 0))
            draw_big = ImageDraw.Draw(img_big)
            draw_big.ellipse([0, 0, big - 1, big - 1], fill=color)
            try:
                font = ImageFont.truetype('segoeui.ttf', 28)
            except Exception:
                font = ImageFont.load_default()
            bbox = draw_big.textbbox((0, 0), initial, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            draw_big.text(((big - tw) / 2 - bbox[0],
                           (big - th) / 2 - bbox[1]),
                          initial, fill='white', font=font)
            img = img_big.resize((36, 36), Image.LANCZOS)
            self._avatar_img = ImageTk.PhotoImage(img)
            self.avatar_canvas.create_image(20, 20,
                                            image=self._avatar_img)
        else:
            self.avatar_canvas.create_oval(2, 2, 38, 38, fill=color,
                                           outline='', width=0)
            self.avatar_canvas.create_text(20, 20, text=initial, fill='white',
                                           font=('Segoe UI', 14, 'bold'))

    # --- Search bar ---
    # Remove o placeholder quando o campo de busca de contatos recebe foco.
    def _search_focus_in(self, e):
        if self._search_entry.get() == 'Buscar contatos...':  # so limpa se for o placeholder
            self._search_entry.delete(0, 'end')               # apaga o texto placeholder
            self._search_entry.config(fg='#1a202c')           # cor de texto normal

    # Reinsere o placeholder quando a busca perde foco e esta vazia.
    def _search_focus_out(self, e):
        if not self._search_entry.get().strip():               # campo vazio?
            self._search_entry.insert(0, 'Buscar contatos...')  # placeholder de volta
            self._search_entry.config(fg='#a0aec0')             # cor cinza do placeholder

    # Filtra contatos visiveis no TreeView conforme texto da barra de busca.
    #
    # Busca vazia ou placeholder: restaura todos os contatos no grupo correto.
    # Texto digitado: oculta (detach) contatos cujo nome nao contem o texto.
    def _filter_contacts(self, *args):
        query = self._search_var.get().strip().lower()  # texto de busca em minusculas
        if query == 'buscar contatos...' or not query:  # busca vazia ou placeholder
            # Restaurar todos os contatos online nos grupos corretos
            for uid, iid in self.peer_items.items():
                tags = self.tree.item(iid, 'tags')
                if 'offline' in tags:
                    continue  # offline permanece escondido
                info = self.peer_info.get(uid, {})
                dept = info.get('department', '')
                parent = self._get_dept_node(dept) if dept else self.group_general
                cur_parent = self.tree.parent(iid)
                if not cur_parent:
                    # Item estava detachado (filtrado), reattach na posicao correta
                    self.tree.reattach(iid, parent, 'end')
                # Se ja esta no parent correto, nao move (evita pipocar)
            return
        for uid, iid in self.peer_items.items():
            tags = self.tree.item(iid, 'tags')
            if 'offline' in tags:
                continue  # offline permanece escondido
            info = self.peer_info.get(uid, {})
            name = info.get('display_name', '').lower()
            note = info.get('note', '').lower()
            if query in name or query in note:
                # Match: garantir que esta visivel sem mover de posicao
                cur_parent = self.tree.parent(iid)
                if not cur_parent:
                    dept = info.get('department', '')
                    parent = self._get_dept_node(dept) if dept else self.group_general
                    self.tree.reattach(iid, parent, 'end')
            else:
                self.tree.detach(iid)

    # --- Note ---
    # Lê o conteúdo do campo de nota reconstruindo emojis das imagens embutidas.
    # Funciona como _get_entry_content() do ChatWindow.
    def _note_get_text(self):
        result = []
        try:
            for key, value, index in self.note_entry.dump('1.0', 'end', image=True, text=True):
                if key == 'text':
                    result.append(value)
                elif key == 'image':
                    emoji = self._note_img_map.get(value, '')
                    result.append(emoji)
        except Exception:
            pass
        return ''.join(result).strip()

    # <<Modified>> handler — varre emojis unicode e substitui por imagens coloridas.
    def _on_note_modified(self, event):
        try:
            self.note_entry.edit_modified(False)
        except Exception:
            pass
        self.note_entry.after(30, self._do_note_emoji_scan)

    # Executa o scan de emojis no campo de nota (reutiliza _scan_entry_emojis).
    def _do_note_emoji_scan(self):
        try:
            _scan_entry_emojis(self.note_entry, self._note_emoji_cache,
                               self._note_img_map, prefix='note_emoji', size=14)
        except Exception:
            pass

    # Insere emoji como imagem colorida no campo de nota.
    def _note_insert_emoji(self, emoji_char, pos='insert'):
        if emoji_char in self._note_emoji_cache:
            img = self._note_emoji_cache[emoji_char]
        else:
            img = _render_color_emoji(emoji_char, 14)
            if img:
                self._note_emoji_cache[emoji_char] = img
        if img:
            img_name = f'note_emoji_{len(self._note_img_map)}'
            self._note_img_map[img_name] = emoji_char
            self.note_entry.image_create(pos, image=img, name=img_name, padx=1)
        else:
            self.note_entry.insert(pos, emoji_char)

    # Remove o placeholder da nota pessoal quando o campo recebe foco.
    def _note_focus_in(self, e):
        text = self._note_get_text()
        if text in ('Digite uma nota', 'Type a note',
                                        _t('note_placeholder')):  # e um placeholder?
            self.note_entry.delete('1.0', 'end')      # limpa o placeholder
            self.note_entry.config(fg='#ffffff')  # cor de texto real (branco)

    # Salva ou limpa nota pessoal quando o campo perde foco.
    #
    # Campo vazio: restaura placeholder e envia nota vazia via rede.
    # Texto mudou: persiste no banco local e propaga via UDP announce.
    def _note_focus_out(self, e):
        text = self._note_get_text()  # texto atual sem espacos nas bordas
        if not text:
            self.note_entry.insert('1.0', _t('note_placeholder'))
            self.note_entry.config(fg='#c8d6e5')
            # Se tinha nota antes, agora limpou
            if self._last_saved_note:
                self._last_saved_note = ''
                self.messenger.change_note('')
        else:  # campo tem conteudo
            # Salva nota se o texto mudou desde o ultimo salvamento
            if text != self._last_saved_note:          # texto mudou?
                self._last_saved_note = text            # atualiza cache local
                self.messenger.change_note(text)        # persiste no banco e propaga via UDP

    # Salva nota pessoal ao pressionar Enter; salva no banco e propaga via UDP.
    #
    # Ignora placeholders. Salva apenas se o texto mudou desde o ultimo save.
    # Remove foco do campo apos salvar.
    def _note_save(self, e=None):
        text = self._note_get_text()  # texto atual sem espacos
        placeholders = ('Digite uma nota', 'Type a note', _t('note_placeholder'))
        note = '' if text in placeholders else text
        if note != self._last_saved_note:
            self._last_saved_note = note
            self.messenger.change_note(note)
        # Tirar foco do entry
        self.root.focus_set()
        return 'break'  # impede nova linha no tk.Text ao pressionar Enter

    # Valida entrada do Entry de Ramal: apenas digitos, max 4.
    def _validate_ramal_entry(self, proposed):
        if proposed == '':
            return True
        return proposed.isdigit() and len(proposed) <= 4

    # Salva ramal no banco + propaga via announce.
    def _save_ramal(self):
        ramal = (self.ramal_var.get() or '').strip()
        # Aceita vazio OU exatamente 4 digitos
        if ramal and (not ramal.isdigit() or len(ramal) != 4):
            return
        if ramal == (self.messenger.ramal or ''):
            return
        self.messenger.change_ramal(ramal)

    def _show_note_emoji_picker(self):
        popup = tk.Toplevel(self.root)
        popup.title('Emoticons')
        popup.resizable(False, False)
        popup.configure(bg='#f0f0f0')
        popup.transient(self.root)

        # Posicionar acima do campo de nota
        x = self.note_entry.winfo_rootx()
        y = self.note_entry.winfo_rooty() - 240
        popup.geometry(f'280x230+{x}+{y}')

        popup._emoji_images = {}

        # Mesmos nomes de busca do chat
        _emoji_names = {
            '\U0001f600': 'sorriso feliz', '\U0001f603': 'sorriso olhos abertos',
            '\U0001f604': 'sorriso olhos sorrindo', '\U0001f601': 'sorriso radiante',
            '\U0001f606': 'rindo', '\U0001f605': 'rindo suando',
            '\U0001f602': 'chorando de rir lagrimas', '\U0001f923': 'rolando de rir',
            '\U0001f60a': 'sorrindo corado', '\U0001f607': 'anjo aureola',
            '\U0001f609': 'piscando piscadela', '\U0001f60d': 'olhos de coracao apaixonado',
            '\U0001f929': 'estrelas nos olhos', '\U0001f60e': 'oculos escuros legal cool',
            '\U0001f618': 'mandando beijo beijinho', '\U0001f617': 'beijando',
            '\U0001f61a': 'beijo olhos fechados',
            '\U0001f60b': 'delicioso gostoso lingua', '\U0001f61b': 'lingua pra fora',
            '\U0001f61c': 'lingua piscando', '\U0001f92a': 'maluco doido louco',
            '\U0001f61d': 'nojo lingua olhos fechados',
            '\U0001f911': 'dinheiro cifrao rico', '\U0001f917': 'abraco',
            '\U0001f914': 'pensando pensativo hmm', '\U0001f910': 'boca fechada ziper',
            '\U0001f928': 'sobrancelha levantada desconfiado',
            '\U0001f610': 'neutro sem expressao', '\U0001f611': 'inexpressivo',
            '\U0001f636': 'sem boca', '\U0001f60f': 'sorriso de lado debochado',
            '\U0001f612': 'descontente chateado', '\U0001f644': 'revirando olhos',
            '\U0001f62c': 'cara de grimace', '\U0001f925': 'mentiroso pinoquio',
            '\U0001f60c': 'aliviado', '\U0001f614': 'pensativo triste',
            '\U0001f62a': 'sonolento sono', '\U0001f924': 'babando baba',
            '\U0001f634': 'dormindo zzz', '\U0001f637': 'mascara doente',
            '\U0001f912': 'termometro febre', '\U0001f915': 'machucado bandagem',
            '\U0001f922': 'enjoado nausea', '\U0001f92e': 'vomitando',
            '\U0001f927': 'espirrando espirro gripe', '\U0001f975': 'quente calor',
            '\U0001f976': 'frio congelando gelado', '\U0001f974': 'tonto zonzo',
            '\U0001f620': 'bravo irritado', '\U0001f621': 'raiva furioso vermelho',
            '\U0001f624': 'triunfante bufando', '\U0001f622': 'chorando triste',
            '\U0001f62d': 'chorando muito', '\U0001f616': 'confuso',
            '\U0001f623': 'cansado perseverante', '\U0001f625': 'desapontado aliviado',
            '\U0001f628': 'assustado medo', '\U0001f631': 'gritando horror',
            '\U0001f630': 'ansioso suando', '\U0001f629': 'exausto cansado',
            '\U0001f62b': 'cansado exausto', '\U0001f633': 'corado envergonhado',
            '\U0001f632': 'surpreso espantado', '\U0001f61e': 'desapontado',
            '\U0001f613': 'suando frio', '\U0001f635': 'tonto x olhos',
            '\U0001f608': 'sorriso diabo', '\U0001f47f': 'diabo bravo demonio',
            '\U0001f4a9': 'coco cocô', '\U0001f921': 'palhaco',
            '\U0001f47b': 'fantasma', '\U0001f480': 'caveira cranio',
            '\U0001f44d': 'positivo joinha legal like', '\U0001f44e': 'negativo ruim dislike',
            '\U0001f44a': 'soco punho', '\u270a': 'punho levantado',
            '\U0001f91b': 'punho esquerdo', '\U0001f91c': 'punho direito',
            '\U0001f44f': 'palmas aplausos parabens', '\U0001f64c': 'maos levantadas celebrar',
            '\U0001f450': 'maos abertas', '\U0001f932': 'palmas para cima',
            '\U0001f91d': 'aperto de mao', '\U0001f64f': 'orar rezar por favor',
            '\U0001f4aa': 'forca musculo braco forte', '\U0001f44b': 'acenando tchau oi',
            '\U0001f91a': 'mao levantada', '\u270b': 'mao aberta pare',
            '\U0001f596': 'vulcano spock', '\U0001f44c': 'ok perfeito',
            '\U0001f91e': 'dedos cruzados sorte', '\U0001f91f': 'te amo amor',
            '\U0001f918': 'rock chifres metal', '\U0001f448': 'apontando esquerda',
            '\U0001f449': 'apontando direita', '\U0001f446': 'apontando cima',
            '\U0001f447': 'apontando baixo', '\U0001f485': 'unha pintando esmalte',
            '\U0001f933': 'selfie', '\u270c\ufe0f': 'paz vitoria',
            '\U0001f590\ufe0f': 'mao dedos abertos', '\u261d\ufe0f': 'indicador cima',
            '\U0001f919': 'me liga telefone hang loose',
            '\U0001f9b5': 'perna', '\U0001f9b6': 'pe',
            '\U0001f34e': 'maca vermelha', '\U0001f34f': 'maca verde',
            '\U0001f350': 'pera', '\U0001f34a': 'tangerina laranja',
            '\U0001f34b': 'limao', '\U0001f34c': 'banana',
            '\U0001f349': 'melancia', '\U0001f347': 'uva',
            '\U0001f353': 'morango', '\U0001f348': 'melao',
            '\U0001f352': 'cereja', '\U0001f351': 'pessego',
            '\U0001f95d': 'kiwi', '\U0001f345': 'tomate',
            '\U0001f346': 'berinjela', '\U0001f955': 'cenoura',
            '\U0001f33d': 'milho espiga', '\U0001f336\ufe0f': 'pimenta',
            '\U0001f954': 'batata', '\U0001f360': 'batata doce',
            '\U0001f950': 'croissant', '\U0001f35e': 'pao',
            '\U0001f956': 'baguete pao frances', '\U0001f9c0': 'queijo',
            '\U0001f356': 'carne osso', '\U0001f357': 'coxa frango',
            '\U0001f354': 'hamburguer', '\U0001f35f': 'batata frita',
            '\U0001f355': 'pizza', '\U0001f32d': 'cachorro quente hot dog',
            '\U0001f32e': 'taco', '\U0001f32f': 'burrito',
            '\U0001f373': 'ovo frigideira', '\U0001f958': 'panela',
            '\U0001f372': 'sopa', '\U0001f35c': 'ramen macarrao',
            '\U0001f363': 'sushi', '\U0001f371': 'bento',
            '\U0001f35b': 'curry arroz', '\U0001f35a': 'arroz',
            '\U0001f359': 'onigiri', '\U0001f370': 'bolo fatia',
            '\U0001f382': 'aniversario bolo vela', '\U0001f36e': 'pudim',
            '\U0001f36d': 'pirulito', '\U0001f36c': 'bala doce',
            '\U0001f36b': 'chocolate', '\U0001f369': 'donut rosquinha',
            '\U0001f368': 'sorvete', '\U0001f366': 'sorvete cone casquinha',
            '\U0001f367': 'raspadinha gelo',
            '\u2615': 'cafe xicara cha', '\U0001f375': 'cha verde',
            '\U0001f376': 'sake', '\U0001f37a': 'cerveja chope chopp beer',
            '\U0001f37b': 'brinde cervejas chope chopp', '\U0001f377': 'vinho taca',
            '\U0001f378': 'coquetel martini drink', '\U0001f379': 'drink tropical',
            '\U0001f37e': 'champagne garrafa', '\U0001f944': 'colher',
            '\U0001f95b': 'leite copo',
            '\u2764\ufe0f': 'coracao vermelho amor', '\U0001f9e1': 'coracao laranja',
            '\U0001f49b': 'coracao amarelo', '\U0001f49a': 'coracao verde',
            '\U0001f499': 'coracao azul', '\U0001f49c': 'coracao roxo',
            '\U0001f5a4': 'coracao preto', '\U0001f90e': 'coracao marrom',
            '\U0001f90d': 'coracao branco', '\U0001f494': 'coracao partido',
            '\U0001f495': 'dois coracoes', '\U0001f49e': 'coracoes girando',
            '\U0001f493': 'coracao batendo', '\U0001f497': 'coracao crescendo',
            '\U0001f496': 'coracao brilhando', '\U0001f498': 'coracao flechado cupido',
            '\U0001f48c': 'carta amor', '\U0001f48b': 'beijo marca batom',
            '\U0001f48d': 'anel alianca', '\U0001f48e': 'diamante joia',
            '\U0001f4ab': 'tontura estrela', '\U0001f4a5': 'explosao boom',
            '\U0001f4a2': 'raiva simbolo', '\U0001f4a6': 'gotas suor',
            '\U0001f4a8': 'vento sopro', '\U0001f573\ufe0f': 'buraco',
            '\U0001f4a3': 'bomba', '\U0001f4ac': 'balao fala', '\U0001f4ad': 'balao pensamento',
            '\U0001f5e8\ufe0f': 'balao comentario',
            '\U0001f697': 'carro automovel', '\U0001f695': 'taxi',
            '\U0001f68c': 'onibus', '\U0001f691': 'ambulancia',
            '\U0001f692': 'bombeiro caminhao', '\U0001f693': 'policia viatura',
            '\U0001f3ce\ufe0f': 'carro corrida formula',
            '\u2708\ufe0f': 'aviao', '\U0001f680': 'foguete',
            '\U0001f6f8': 'disco voador ufo', '\U0001f6a2': 'navio',
            '\U0001f3e0': 'casa', '\U0001f3e2': 'escritorio predio',
            '\U0001f3eb': 'escola', '\U0001f3e5': 'hospital',
            '\U0001f3ed': 'fabrica', '\u26ea': 'igreja',
            '\U0001f5fc': 'torre tokyo', '\U0001f4f1': 'celular telefone',
            '\U0001f4bb': 'computador notebook laptop', '\U0001f4f7': 'camera foto',
            '\U0001f4f9': 'camera video filmadora', '\U0001f4fa': 'televisao tv',
            '\U0001f4fb': 'radio', '\u23f0': 'despertador alarme',
            '\u231a': 'relogio', '\U0001f4a1': 'lampada ideia',
            '\U0001f526': 'lanterna', '\U0001f4b0': 'dinheiro saco',
            '\U0001f4b5': 'dinheiro nota dolar', '\U0001f4b3': 'cartao credito',
            '\U0001f4e7': 'email', '\U0001f4e8': 'email recebido',
            '\U0001f4e9': 'email enviado', '\U0001f4ce': 'clipe anexo',
            '\U0001f4c1': 'pasta', '\U0001f4c2': 'pasta aberta',
            '\U0001f4c4': 'documento pagina', '\U0001f4c5': 'calendario',
            '\U0001f4ca': 'grafico barras', '\U0001f4cb': 'prancheta',
            '\U0001f4cc': 'tachinha', '\U0001f4dd': 'memo nota escrita',
            '\u270f\ufe0f': 'lapis', '\U0001f512': 'cadeado fechado',
            '\U0001f513': 'cadeado aberto', '\U0001f527': 'chave inglesa ferramenta',
            '\U0001f528': 'martelo', '\U0001f6e0\ufe0f': 'ferramentas',
            '\u2601': 'nuvem cloud', '\U0001f327': 'nuvem chuva',
            '\U0001f328': 'nuvem neve', '\u26c5': 'sol nuvem parcialmente nublado',
            '\U0001f324': 'sol nuvem pequena', '\U0001f325': 'sol nuvem grande',
            '\U0001f3c6': 'trofeu copa', '\U0001f3c5': 'medalha esporte',
            '\U0001f947': 'medalha ouro primeiro', '\U0001f948': 'medalha prata segundo',
            '\U0001f949': 'medalha bronze terceiro', '\u26bd': 'futebol bola',
            '\U0001f3c0': 'basquete', '\U0001f3c8': 'futebol americano',
            '\U0001f3be': 'tenis', '\U0001f3d0': 'volei',
            '\U0001f3b1': 'sinuca bilhar', '\U0001f3b3': 'boliche',
            '\U0001f3af': 'alvo dardo', '\U0001f3ae': 'videogame joystick',
            '\U0001f3b2': 'dado', '\U0001f3b0': 'caca niquel slot',
            '\U0001f3b5': 'nota musical', '\U0001f3b6': 'notas musicais musica',
            '\U0001f3a4': 'microfone karaoke', '\U0001f3a7': 'fone ouvido',
            '\U0001f3b8': 'guitarra', '\U0001f3b9': 'teclado piano',
            '\U0001f3ba': 'trompete', '\U0001f3bb': 'violino',
            '\U0001f525': 'fogo chama quente', '\U0001f4af': 'cem pontos perfeito',
            '\U0001f389': 'festa confete', '\U0001f388': 'balao festa',
            '\U0001f381': 'presente', '\U0001f380': 'laco fita',
            '\U0001f3c1': 'bandeira chegada', '\u2705': 'check verde ok',
            '\u274c': 'x vermelho errado nao', '\u26a0\ufe0f': 'aviso alerta',
            '\U0001f6ab': 'proibido', '\u2753': 'interrogacao pergunta',
            '\u2757': 'exclamacao',
            '\U0001f6a9': 'bandeira triangular',
            '\U0001f3f3\ufe0f': 'bandeira branca', '\U0001f3f4': 'bandeira preta',
        }

        # Mesmas categorias do chat
        categories = {
            '\U0001f600': [
                '\U0001f600', '\U0001f603', '\U0001f604', '\U0001f601',
                '\U0001f606', '\U0001f605', '\U0001f602', '\U0001f923',
                '\U0001f60a', '\U0001f607', '\U0001f609', '\U0001f60d',
                '\U0001f929', '\U0001f60e', '\U0001f618', '\U0001f617', '\U0001f61a',
                '\U0001f60b', '\U0001f61b', '\U0001f61c', '\U0001f92a',
                '\U0001f61d', '\U0001f911', '\U0001f917', '\U0001f914',
                '\U0001f910', '\U0001f928', '\U0001f610', '\U0001f611',
                '\U0001f636', '\U0001f60f', '\U0001f612', '\U0001f644',
                '\U0001f62c', '\U0001f925', '\U0001f60c', '\U0001f614',
                '\U0001f62a', '\U0001f924', '\U0001f634', '\U0001f637',
                '\U0001f912', '\U0001f915', '\U0001f922', '\U0001f92e',
                '\U0001f927', '\U0001f975', '\U0001f976', '\U0001f974',
                '\U0001f620', '\U0001f621', '\U0001f624', '\U0001f622',
                '\U0001f62d', '\U0001f616', '\U0001f623', '\U0001f625',
                '\U0001f628', '\U0001f631', '\U0001f630', '\U0001f629',
                '\U0001f62b', '\U0001f633', '\U0001f632', '\U0001f61e',
                '\U0001f613', '\U0001f635', '\U0001f608', '\U0001f47f',
                '\U0001f4a9', '\U0001f921', '\U0001f47b', '\U0001f480',
            ],
            '\U0001f44d': [
                '\U0001f44d', '\U0001f44e', '\U0001f44a', '\u270a',
                '\U0001f91b', '\U0001f91c', '\U0001f44f', '\U0001f64c',
                '\U0001f450', '\U0001f932', '\U0001f91d', '\U0001f64f',
                '\U0001f4aa', '\U0001f44b', '\U0001f91a', '\u270b',
                '\U0001f596', '\U0001f44c', '\U0001f91e', '\U0001f91f',
                '\U0001f918', '\U0001f448', '\U0001f449', '\U0001f446',
                '\U0001f447', '\U0001f485', '\U0001f933', '\u270c\ufe0f',
                '\U0001f590\ufe0f', '\u261d\ufe0f', '\U0001f919',
                '\U0001f9b5', '\U0001f9b6',
            ],
            '\U0001f354': [
                '\U0001f34e', '\U0001f34f', '\U0001f350', '\U0001f34a',
                '\U0001f34b', '\U0001f34c', '\U0001f349', '\U0001f347',
                '\U0001f353', '\U0001f348', '\U0001f352', '\U0001f351',
                '\U0001f95d', '\U0001f345', '\U0001f346', '\U0001f955',
                '\U0001f33d', '\U0001f336\ufe0f', '\U0001f954', '\U0001f360',
                '\U0001f950', '\U0001f35e', '\U0001f956', '\U0001f9c0',
                '\U0001f356', '\U0001f357', '\U0001f354', '\U0001f35f',
                '\U0001f355', '\U0001f32d', '\U0001f32e', '\U0001f32f',
                '\U0001f373', '\U0001f958', '\U0001f372', '\U0001f35c',
                '\U0001f363', '\U0001f371', '\U0001f35b', '\U0001f35a',
                '\U0001f359', '\U0001f370', '\U0001f382', '\U0001f36e',
                '\U0001f36d', '\U0001f36c', '\U0001f36b', '\U0001f369',
                '\U0001f368', '\U0001f366', '\U0001f367',
                '\u2615', '\U0001f375', '\U0001f376', '\U0001f37a',
                '\U0001f37b', '\U0001f377', '\U0001f378', '\U0001f379',
                '\U0001f37e', '\U0001f944', '\U0001f95b',
            ],
            '\u2764\ufe0f': [
                '\u2764\ufe0f', '\U0001f9e1', '\U0001f49b', '\U0001f49a',
                '\U0001f499', '\U0001f49c', '\U0001f5a4', '\U0001f90e',
                '\U0001f90d', '\U0001f494', '\U0001f495', '\U0001f49e',
                '\U0001f493', '\U0001f497', '\U0001f496', '\U0001f498',
                '\U0001f48c', '\U0001f48b', '\U0001f48d', '\U0001f48e',
                '\U0001f4ab', '\U0001f4a5', '\U0001f4a2', '\U0001f4a6',
                '\U0001f4a8', '\U0001f573\ufe0f', '\U0001f4a3',
                '\U0001f4ac', '\U0001f4ad', '\U0001f5e8\ufe0f',
            ],
            '\U0001f3e0': [
                '\U0001f697', '\U0001f695', '\U0001f68c', '\U0001f691',
                '\U0001f692', '\U0001f693', '\U0001f3ce\ufe0f',
                '\u2708\ufe0f', '\U0001f680', '\U0001f6f8',
                '\U0001f6a2',
                '\u2601', '\U0001f327', '\U0001f328',
                '\u26c5', '\U0001f324', '\U0001f325',
                '\U0001f3e0', '\U0001f3e2', '\U0001f3eb',
                '\U0001f3e5', '\U0001f3ed', '\u26ea', '\U0001f5fc',
                '\U0001f4f1', '\U0001f4bb', '\U0001f4f7', '\U0001f4f9',
                '\U0001f4fa', '\U0001f4fb', '\u23f0', '\u231a',
                '\U0001f4a1', '\U0001f526', '\U0001f4b0', '\U0001f4b5',
                '\U0001f4b3', '\U0001f4e7', '\U0001f4e8', '\U0001f4e9',
                '\U0001f4ce', '\U0001f4c1', '\U0001f4c2', '\U0001f4c4',
                '\U0001f4c5', '\U0001f4ca', '\U0001f4cb', '\U0001f4cc',
                '\U0001f4dd', '\u270f\ufe0f', '\U0001f512', '\U0001f513',
                '\U0001f527', '\U0001f528', '\U0001f6e0\ufe0f',
            ],
            '\U0001f3c6': [
                '\U0001f3c6', '\U0001f3c5', '\U0001f947', '\U0001f948',
                '\U0001f949', '\u26bd', '\U0001f3c0', '\U0001f3c8',
                '\U0001f3be', '\U0001f3d0', '\U0001f3b1', '\U0001f3b3',
                '\U0001f3af', '\U0001f3ae', '\U0001f3b2', '\U0001f3b0',
                '\U0001f3b5', '\U0001f3b6', '\U0001f3a4', '\U0001f3a7',
                '\U0001f3b8', '\U0001f3b9', '\U0001f3ba', '\U0001f3bb',
                '\U0001f525', '\U0001f4af', '\U0001f389', '\U0001f388',
                '\U0001f381', '\U0001f380', '\U0001f3c1',
                '\u2705', '\u274c', '\u26a0\ufe0f', '\U0001f6ab',
                '\u2753', '\u2757', '\U0001f4ac', '\U0001f4ad',
                '\U0001f6a9', '\U0001f3f3\ufe0f', '\U0001f3f4',
            ],
        }

        # Barra de busca
        search_frame = tk.Frame(popup, bg='#ffffff')
        search_frame.pack(fill='x', padx=4, pady=(4, 2))

        search_icon = _create_mdl2_icon_static('\uE721', size=12, color='#a0aec0')
        if search_icon:
            popup._emoji_images['_search'] = search_icon
            tk.Label(search_frame, image=search_icon,
                     bg='#ffffff').pack(side='left', padx=(4, 2))

        emoji_search_var = tk.StringVar()
        emoji_search_entry = tk.Entry(search_frame, textvariable=emoji_search_var,
                                       font=('Segoe UI', 8), bg='#ffffff',
                                       fg='#1a202c', relief='flat', bd=0,
                                       insertbackground='#1a202c')
        emoji_search_entry.pack(side='left', fill='x', expand=True, ipady=2, padx=2)
        emoji_search_entry.insert(0, 'Buscar emoji...')
        emoji_search_entry.config(fg='#a0aec0')

        def _emoji_search_focus_in(e):
            if emoji_search_entry.get() == 'Buscar emoji...':
                emoji_search_entry.delete(0, 'end')
                emoji_search_entry.config(fg='#1a202c')
        def _emoji_search_focus_out(e):
            if not emoji_search_entry.get().strip():
                emoji_search_entry.insert(0, 'Buscar emoji...')
                emoji_search_entry.config(fg='#a0aec0')
        emoji_search_entry.bind('<FocusIn>', _emoji_search_focus_in)
        emoji_search_entry.bind('<FocusOut>', _emoji_search_focus_out)

        tk.Frame(popup, bg='#e2e8f0', height=1).pack(fill='x', padx=6)

        # Abas de categorias
        tab_frame = tk.Frame(popup, bg='#e8e8e8', bd=0, relief='flat')
        tab_frame.pack(fill='x')

        # Grid scrollavel
        grid_frame = tk.Frame(popup, bg='#ffffff')
        grid_frame.pack(fill='both', expand=True)

        canvas = tk.Canvas(grid_frame, bg='#ffffff', highlightthickness=0)
        inner = tk.Frame(canvas, bg='#ffffff')
        canvas.pack(fill='both', expand=True)
        canvas.create_window((0, 0), window=inner, anchor='nw')

        def insert_emoji(emoji):
            # Limpa placeholder se necessario
            cur_text = self._note_get_text()
            if cur_text in ('Digite uma nota', 'Type a note', _t('note_placeholder')):
                self.note_entry.delete('1.0', 'end')
                self.note_entry.config(fg='#ffffff')
            self._note_insert_emoji(emoji)
            self.note_entry.focus_set()

        cat_keys = list(categories.keys())

        def _emoji_scroll(e):
            canvas.yview_scroll(-1 * (e.delta // 60), 'units')

        def _bind_wheel_recursive(widget):
            widget.bind('<MouseWheel>', _emoji_scroll)
            for child in widget.winfo_children():
                _bind_wheel_recursive(child)

        def _populate_grid(emojis):
            for w in inner.winfo_children():
                w.destroy()
            cols = 8
            for i, em in enumerate(emojis):
                r, c = divmod(i, cols)
                img = self._note_emoji_cache.get(em)
                if img is None:
                    img = _render_color_emoji(em, 20)
                    if img:
                        self._note_emoji_cache[em] = img
                if img:
                    popup._emoji_images[em] = img
                    btn = tk.Label(inner, image=img,
                                   bg='#ffffff', cursor='hand2',
                                   padx=2, pady=2)
                else:
                    btn = tk.Label(inner, text=em,
                                   font=('Segoe UI Emoji', 16),
                                   bg='#ffffff', cursor='hand2',
                                   padx=2, pady=2)
                btn.grid(row=r, column=c, padx=0, pady=0)
                btn.bind('<Button-1>',
                         lambda e, emoji=em: insert_emoji(emoji))
                btn.bind('<Enter>',
                         lambda e, b=btn: b.configure(bg='#e8f0fe'))
                btn.bind('<Leave>',
                         lambda e, b=btn: b.configure(bg='#ffffff'))
            inner.update_idletasks()
            canvas.configure(scrollregion=canvas.bbox('all'))
            canvas.yview_moveto(0)
            _bind_wheel_recursive(inner)

        def show_category(cat_key):
            _populate_grid(categories[cat_key])
            for b in tab_buttons:
                b.configure(bg='#e8e8e8', relief='flat')
            idx = cat_keys.index(cat_key)
            tab_buttons[idx].configure(bg='#ffffff', relief='sunken')

        def _on_emoji_search(*args):
            query = emoji_search_var.get().strip().lower()
            if query == 'buscar emoji...' or not query:
                show_category(cat_keys[0])
                return
            for b in tab_buttons:
                b.configure(bg='#e8e8e8', relief='flat')
            results = [em for em, name in _emoji_names.items() if query in name]
            _populate_grid(results)

        emoji_search_var.trace_add('write', _on_emoji_search)

        tab_buttons = []
        for cat_key in cat_keys:
            tab_img = _render_color_emoji(cat_key, 20)
            if tab_img:
                popup._emoji_images[f'tab_{cat_key}'] = tab_img
                btn = tk.Label(tab_frame, image=tab_img,
                               bg='#e8e8e8', cursor='hand2',
                               padx=8, pady=3, relief='flat')
            else:
                btn = tk.Label(tab_frame, text=cat_key,
                               font=('Segoe UI Emoji', 12),
                               bg='#e8e8e8', cursor='hand2',
                               padx=8, pady=2, relief='flat')
            btn.pack(side='left', padx=1)
            btn.bind('<Button-1>', lambda e, k=cat_key: show_category(k))
            tab_buttons.append(btn)

        canvas.bind('<MouseWheel>', _emoji_scroll)
        inner.bind('<MouseWheel>', _emoji_scroll)

        show_category(cat_keys[0])
        _bind_wheel_recursive(inner)
        popup.bind('<Escape>', lambda e: popup.destroy())

        def _check_focus():
            if not popup.winfo_exists():
                return
            try:
                focused = popup.focus_get()
                if focused is None or not str(focused).startswith(str(popup)):
                    popup.destroy()
            except Exception:
                popup.destroy()
        popup.bind('<FocusOut>', lambda e: popup.after(100, _check_focus))
        popup.focus_set()
        ep.focus_set()

    # Callback do combobox de status: traduz label para codigo e propaga via UDP.
    #
    # Converte o texto exibido ('Disponivel') para o codigo interno ('online')
    # e chama messenger.change_status() que atualiza o proximo UDP announce.
    def _on_status_change(self, e=None):
        m = {_t('status_available'): 'online',  # 'Disponivel' -> 'online'
             _t('status_away'): 'away',
             _t('status_busy'): 'busy',
             _t('status_offline'): 'invisible'}
        self.messenger.change_status(m.get(self.status_var.get(), 'online'))  # envia via UDP

    # --- Tree ---
    # Retorna uid do contato selecionado no TreeView, ou None se invalido.
    #
    # Retorna None para: sem selecao, headers de secao, grupos, ou contatos
    # offline (a menos que allow_offline=True seja passado explicitamente).
    def _get_selected_peer(self, allow_offline=False):
        sel = self.tree.selection()  # lista de items atualmente selecionados
        if not sel:
            return None
        item = sel[0]
        if item in (self.group_general, self.group_groups):
            return None  # clicou em um header de secao, nao em um contato
        if item in self._dept_nodes.values():
            return None  # clicou em header de departamento
        # Verifica se o item clicado e um grupo (nao um contato)
        if item in self._group_tree_items.values():
            return None  # e um item de grupo, nao um contato
        for uid, iid in self.peer_items.items():  # procura o uid pelo iid do TreeView
            if iid == item:
                if not allow_offline:              # bloquear contatos offline?
                    # Bloqueia interacao com contatos offline por padrao
                    tags = self.tree.item(item, 'tags')
                    if 'offline' in tags:          # contato esta offline?
                        return None               # retorna None para bloquear acao
                return uid  # retorna o uid do contato selecionado
        return None  # item nao encontrado em peer_items

    def _sort_tree_children(self, parent):
        # Obtém a seleção atual para restaurá-la após a movimentação
        current_sel = self.tree.selection()
        
        items = list(self.tree.get_children(parent))
        # Ordena alfabeticamente ignorando maiúsculas/minúsculas
        sorted_items = sorted(items, key=lambda x: self.tree.item(x, 'text').lower())
        
        # Só move se a ordem realmente mudou para evitar flicker visual (piscar)
        needs_reorder = False
        for index, item in enumerate(sorted_items):
            if items[index] != item:
                needs_reorder = True
                break
        
        if needs_reorder:
            for index, item in enumerate(sorted_items):
                self.tree.move(item, parent, index)
            
            # Restaura a seleção se ainda existir (evita que a seleção 'suma' ao mover)
            if current_sel:
                try:
                    self.tree.selection_set(current_sel)
                except Exception:
                    pass

    # Adiciona ou atualiza contato no TreeView e em peer_info.
    #
    # Existente: atualiza texto/tag/avatar e move para grupo correto (Geral/Offline).
    # Novo: insere como item no TreeView no grupo correspondente ao status.
    # Tambem propaga atualizacao de nota para janelas de grupo abertas.
    def _get_dept_node(self, dept_name):
        if dept_name in self._dept_nodes:
            return self._dept_nodes[dept_name]
        # Cria no de departamento ANTES de Geral (que por sua vez fica antes de Grupos)
        node = self.tree.insert('', self.tree.index(self.group_general),
                                text=dept_name, open=True, tags=('group',))
        self._dept_nodes[dept_name] = node
        return node

    # Esconde secao Geral quando nao tem filhos visiveis (todos os peers tem dept).
    # Mostra de volta quando volta a ter conteudo.
    def _update_general_visibility(self):
        try:
            has_children = bool(self.tree.get_children(self.group_general))
            cur_parent = self.tree.parent(self.group_general)
            if has_children and not cur_parent:
                # Reattach na posicao correta: antes de Grupos
                self.tree.reattach(self.group_general, '',
                                   self.tree.index(self.group_groups))
            elif not has_children and cur_parent == '':
                self.tree.detach(self.group_general)
        except tk.TclError:
            pass

    def _add_contact(self, uid, info):
        status = info.get('status', 'online')  # status atual do contato recebido
        tag = status if status in ('online', 'away', 'busy') else 'offline'
        name = info.get('display_name', 'Unknown')
        note = info.get('note', '')
        dept = info.get('department', '')
        ramal = info.get('ramal', '')

        # Determina o grupo pai correto (departamento > Geral; offline = detach)
        if tag == 'offline':
            parent = None  # offline nao aparece no TreeView
        elif dept:
            parent = self._get_dept_node(dept)
        else:
            parent = self.group_general

        # Cache key: pula re-render PIL quando nada mudou desde o ultimo announce
        avatar_data = info.get('avatar_data', '')
        cache_key = (name, note, tag, dept, ramal, hash(avatar_data) if avatar_data else 0)
        cached = self._contact_render_cache.get(uid)

        # Early-exit: uid ja existe, parent nao mudou, cache bateu, nao esta em unread
        if cached is not None and cached[0] == cache_key and uid in self.peer_items:
            iid = self.peer_items[uid]
            cur_parent = self.tree.parent(iid)
            expected_parent = parent if parent is not None else ''
            tags_now = self.tree.item(iid, 'tags')
            if cur_parent == expected_parent and 'unread' not in tags_now:
                return  # nada mudou, skip total

        # Tenta renderizar linha composta com emojis coloridos (PIL)
        avatar = self._create_contact_avatar(uid, name, tag)
        if cached is not None and cached[0] == cache_key:
            row_img = cached[1]
        else:
            row_img = self._render_contact_display(uid, name, note, tag, dept=dept, ramal=ramal)
            self._contact_render_cache[uid] = (cache_key, row_img)

        if row_img:
            display = ''  # texto vazio, tudo na imagem
            image = row_img
        else:
            display = f'  {name}'
            if note:
                display += f'  -  {note}'
            image = avatar

        if uid in self.peer_items:
            iid = self.peer_items[uid]
            old_parent = self.tree.parent(iid)

            # Sempre atualiza (nota/status podem mudar)
            self.tree.item(iid, text=display, tags=(tag,), image=image)

            if parent is None:
                # Offline: esconde do TreeView
                self.tree.detach(iid)
            elif old_parent != parent:
                self.tree.move(iid, parent, 'end')
                self._sort_tree_children(parent)
            else:
                self._sort_tree_children(parent)
        else:
            if parent is None:
                # Offline novo: insere em Geral e detacha (precisa existir para referencia)
                iid = self.tree.insert(self.group_general, 'end',
                                       text=display, tags=(tag,), image=image)
                self.peer_items[uid] = iid
                self.tree.detach(iid)
            else:
                iid = self.tree.insert(parent, 'end',
                                       text=display, tags=(tag,), image=image)
                self.peer_items[uid] = iid
                self._sort_tree_children(parent)

        self.peer_info[uid] = info  # atualiza cache local de informacoes do contato

        # Se ha filtro ativo, esconde o contato se nao bater com a busca
        query = self._search_var.get().strip().lower()
        if query and query != 'buscar contatos...':
            if query not in name.lower() and query not in note.lower():
                self.tree.detach(iid)

        # Atualiza a nota do contato em todas as janelas de grupo que ele participa
        for gw in self.group_windows.values():   # percorre janelas de grupo abertas
            if uid in gw._members:               # este contato esta no grupo?
                gw.update_member_info(uid, info) # atualiza nome/nota no painel

        self._update_general_visibility()

    # Marca peer como offline e esconde do TreeView.
    def _remove_contact(self, uid):
        if uid in self.peer_items:
            iid = self.peer_items[uid]
            self.tree.item(iid, tags=('offline',))
            self.tree.detach(iid)  # esconde do TreeView (offline nao aparece)
        self._contact_render_cache.pop(uid, None)
        self._update_general_visibility()

    # Adiciona grupo à seção Grupos do TreeView.
    def _add_group_to_tree(self, group_id, group_name, group_type='fixed'):
        if group_id in self._group_tree_items:
            return
        suffix = '(Fixo)' if group_type == 'fixed' else '(Temporário)'
        iid = self.tree.insert(self.group_groups, 'end',
                               text=f'  \U0001f4ac {group_name} {suffix}',
                               tags=('group_item',))
        self._group_tree_items[group_id] = iid

    # Remove grupo do TreeView.
    def _remove_group_from_tree(self, group_id):
        if group_id in self._group_tree_items:
            try:
                self.tree.delete(self._group_tree_items[group_id])
            except Exception:
                pass
            del self._group_tree_items[group_id]

    # Carrega grupos fixos do DB e exibe no TreeView.
    def _load_saved_groups(self):
        groups = self.messenger.load_saved_groups()
        for g in groups:
            self._add_group_to_tree(g['group_id'], g['name'], 'fixed')

    # Abre/reexibe janela de grupo ao duplo-clicar no TreeView.
    def _on_tree_dbl_group(self, item):
        for gid, iid in self._group_tree_items.items():
            if iid == item:
                self._open_group(gid)
                return True
        return False

    # Marca contato no TreeView como nao lido: aplica tag bold e exibe contagem.
    #
    # Atualiza o avatar do item para refletir o status atual e adiciona
    # o numero de mensagens nao lidas entre parenteses no nome.
    def _mark_unread(self, uid):
        self._contact_render_cache.pop(uid, None)
        if uid in self.peer_items:
            item = self.peer_items[uid]
            tags = list(self.tree.item(item, 'tags'))
            if 'unread' not in tags:
                tags.append('unread')
                self.tree.item(item, tags=tuple(tags))
            info = self.peer_info.get(uid, {})
            name = info.get('display_name', '')
            note = info.get('note', '')
            unread = self.messenger.get_unread_count(uid)
            status_tag = [t for t in tags if t in ('online','away','busy','offline')]
            status = status_tag[0] if status_tag else 'online'
            avatar = self._create_contact_avatar(uid, name, status)
            dept = info.get('department', '')
            ramal = info.get('ramal', '')
            row_img = self._render_contact_display(uid, name, note, status, bold=True, unread_count=unread, dept=dept, ramal=ramal)
            if row_img:
                self.tree.item(item, text='', image=row_img)
            else:
                self.tree.item(item, text=f'  {name} ({unread})', image=avatar)

    def _clear_unread(self, uid):
        self._contact_render_cache.pop(uid, None)
        if uid in self.peer_items:
            item = self.peer_items[uid]
            tags = [t for t in self.tree.item(item, 'tags') if t != 'unread']
            self.tree.item(item, tags=tuple(tags) if tags else ())
            info = self.peer_info.get(uid, {})
            name = info.get('display_name', '')
            note = info.get('note', '')
            dept = info.get('department', '')
            ramal = info.get('ramal', '')
            status = tags[0] if tags and tags[0] != 'group' else 'online'
            avatar = self._create_contact_avatar(uid, name, status)
            row_img = self._render_contact_display(uid, name, note, status, dept=dept, ramal=ramal)
            if row_img:
                self.tree.item(item, text='', image=row_img)
            else:
                self.tree.item(item, text=f'  {name}', image=avatar)

    # Marca grupo no TreeView como unread (bold).
    def _mark_group_unread(self, group_id):
        if group_id in self._group_tree_items:
            item = self._group_tree_items[group_id]
            tags = list(self.tree.item(item, 'tags'))  # tags atuais
            if 'unread' not in tags:         # ainda nao esta marcado?
                tags.append('unread')        # adiciona tag para negrito
                self.tree.item(item, tags=tuple(tags))
            # Atualiza o texto com contagem de mensagens pendentes
            pending = len(self._pending_group_msgs.get(group_id, []))  # qtd de msgs pendentes
            group_data = self.messenger._groups.get(group_id)          # dados do grupo
            g_name = group_data.get('name', 'Grupo') if group_data else 'Grupo'  # nome
            g_type = group_data.get('group_type', 'temp') if group_data else 'temp'  # tipo
            suffix = '(Fixo)' if g_type == 'fixed' else '(Temporário)'  # sufixo do tipo
            if pending > 0:  # tem mensagens pendentes?
                self.tree.item(item,
                    text=f'  \U0001f4ac {g_name} {suffix} ({pending})')  # mostra contagem
            # Garante que a secao Grupos esteja expandida para o usuario ver
            try:
                self.tree.item(self.group_groups, open=True)  # expande secao Grupos
            except Exception:
                pass

    # Limpa unread do grupo no TreeView.
    def _clear_group_unread(self, group_id):
        if group_id in self._group_tree_items:
            item = self._group_tree_items[group_id]
            tags = [t for t in self.tree.item(item, 'tags') if t != 'unread']
            self.tree.item(item, tags=tuple(tags) if tags else ('group_item',))
            group_data = self.messenger._groups.get(group_id)
            g_name = group_data.get('name', 'Grupo') if group_data else 'Grupo'
            g_type = group_data.get('group_type', 'temp') if group_data else 'temp'
            suffix = '(Fixo)' if g_type == 'fixed' else '(Temporário)'
            self.tree.item(item,
                text=f'  \U0001f4ac {g_name} {suffix}')

    # Mostra notificacao toast Windows para mensagem de grupo.
    #
    # Titulo: 'Nome do Grupo - Remetente'. Preview truncado em 120 chars.
    # Usa winotify (toast clicavel) se disponivel, senao balloon tip do tray.
    def _show_group_toast(self, group_id, display_name, content):
        if self.messenger.db.get_setting('notif_msg_group', '1') != '1':
            return
        group_data = self.messenger._groups.get(group_id)             # dados do grupo
        g_name = group_data.get('name', 'Grupo') if group_data else 'Grupo'  # nome do grupo
        title = f'{g_name} - {display_name}'                          # titulo: Grupo - Remetente
        preview = content[:120] + '...' if len(content) > 120 else content  # preview curto

        if HAS_WINOTIFY:  # winotify disponivel? (toast clicavel do Windows 10/11)
            try:
                notif = WinNotification(
                    app_id='MB Chat',
                    title=title,    # titulo = Grupo - Remetente
                    msg=preview,    # corpo = preview da mensagem
                    icon=self._icon_path or '',
                )
                notif.launch = f'mbchat://group/{group_id}'  # URL ao clicar no toast
                notif.set_audio(wn_audio.Default, loop=False)  # som padrao sem loop
                notif.show()   # exibe o toast
                return         # sucesso: nao usa fallback
            except Exception:
                pass  # winotify falhou: tenta fallback

        if self._balloon_notify(preview, title):
            return

    # Abre/reexibe janela de grupo com foco no input.
    def _open_group(self, group_id, surface_only=False):
        if group_id in self.group_windows:  # janela do grupo ja existe?
            gw = self.group_windows[group_id]
            if not surface_only:
                gw.deiconify()   # exibe se estava oculta (hidden)
                gw.lift()        # traz para frente de outras janelas
                gw.focus_force() # forca o foco do sistema operacional
        else:  # janela nao existe: precisa criar
            group_data = self.messenger._groups.get(group_id)  # dados do grupo no messenger
            if not group_data:  # grupo nao existe mais?
                return None
            g_type = group_data.get('group_type', 'temp')  # tipo: 'temp' ou 'fixed'
            gw = GroupChatWindow(self, group_id, group_data['name'],
                                 group_type=g_type,
                                 start_hidden=surface_only)
            self.group_windows[group_id] = gw  # registra no dicionario
            for m in group_data.get('members', []):  # adiciona cada membro ao painel
                m_info = self.peer_info.get(m['uid'],
                            {'ip': m.get('ip', ''),
                             'status': 'online', 'note': ''})  # info do peer ou padrao
                gw.add_member(m['uid'], m['display_name'], m_info)  # adiciona ao painel
            if hasattr(self, '_theme'):  # tema esta configurado?
                self._apply_theme_to_group(gw, self._theme)  # aplica tema atual
        # Exibe mensagens pendentes acumuladas enquanto a janela estava fechada
        pending = self._pending_group_msgs.pop(group_id, [])  # remove do buffer pendente
        for item in pending:       # entrega cada mensagem acumulada
            dname, content, ts = item[0], item[1], item[2]
            rto = item[3] if len(item) > 3 else ''
            ment = item[4] if len(item) > 4 else None
            mid = item[5] if len(item) > 5 else ''
            if isinstance(content, str) and content.startswith('[img]'):
                gw.receive_image(dname, content[5:], ts)
            elif isinstance(content, str) and content.startswith('[poll]'):
                pid = content[6:]
                poll = self.messenger.db.get_poll(pid)
                if poll:
                    import json
                    opts = poll['options'] if isinstance(poll['options'], list) else json.loads(poll['options'])
                    gw._display_poll(poll['question'], opts, dname, pid)
            else:
                gw.receive_message(dname, content, ts,
                                   reply_to=rto, mentions=ment,
                                   msg_id=mid)
        if not surface_only:
            self._clear_group_unread(group_id)   # limpa indicador bold/contagem
            try:
                gw.entry.focus_set()  # foca o campo de texto
            except Exception:
                pass
        return gw

    # Trata duplo clique no TreeView: abre chat (contato) ou janela de grupo.
    def _on_tree_dbl(self, e):
        sel = self.tree.selection()  # item selecionado no TreeView
        if sel and sel[0] in self._group_tree_items.values():
            self._on_tree_dbl_group(sel[0])
            return
        uid = self._get_selected_peer()
        if uid:
            self._open_chat(uid)

    # Trata clique direito no TreeView: exibe menu de contexto para contatos online.
    def _on_tree_right(self, e):
        item = self.tree.identify_row(e.y)  # identifica o item na posicao Y do mouse
        # Ignora nos de secao (Geral, Offline, Grupos, departamentos)
        section_nodes = {self.group_general, self.group_groups}
        section_nodes.update(self._dept_nodes.values())
        if item and item not in section_nodes:
            # Block right-click on offline contacts
            tags = self.tree.item(item, 'tags')
            if 'offline' in tags:
                return
            self.tree.selection_set(item)
            self.ctx_menu.tk_popup(e.x_root, e.y_root)

    # Abre chat com o contato selecionado via menu de contexto.
    def _ctx_chat(self):
        uid = self._get_selected_peer()  # pega uid do contato selecionado no TreeView
        if uid:
            self._open_chat(uid)

    # Abre dialogo de arquivo e envia para o contato selecionado via menu de contexto.
    def _ctx_file(self):
        uid = self._get_selected_peer()  # pega uid do contato selecionado
        if uid:
            fp = filedialog.askopenfilename(title='Enviar arquivo')
            if fp:
                self.messenger.send_file(uid, fp)

    # Exibe dialogo com informacoes detalhadas do contato selecionado.
    def _ctx_info(self):
        uid = self._get_selected_peer()  # pega uid do contato selecionado
        if uid and uid in self.peer_info:
            i = self.peer_info[uid]
            dept = i.get('department', '')
            contact = self.messenger.db.get_contact(uid)
            pnote = contact.get('private_note', '') if contact else ''
            info_text = (
                f"Nome: {i.get('display_name','?')}\n"
                f"IP: {i.get('ip','?')}\n"
                f"Host: {i.get('hostname','?')}\n"
                f"OS: {i.get('os','?')}\n"
                f"Status: {i.get('status','?')}")
            if dept:
                info_text += f"\nDepartamento: {dept}"
            if pnote:
                info_text += f"\nNota privada: {pnote}"
            messagebox.showinfo('Info do Usuário', info_text)

    # Dialogo para editar nota privada do contato selecionado (so visivel localmente)
    def _ctx_private_note(self):
        uid = self._get_selected_peer()
        if not uid:
            return
        name = self.peer_info.get(uid, {}).get('display_name', uid)
        contact = self.messenger.db.get_contact(uid)
        current_note = contact.get('private_note', '') if contact else ''

        dlg = tk.Toplevel(self.root)
        dlg.title(f'Nota Privada - {name}')
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.configure(bg='#ffffff')
        _center_window(dlg, 360, 200)
        _apply_rounded_corners(dlg)
        dlg.bind('<Escape>', lambda e: dlg.destroy())

        tk.Label(dlg, text=f'Nota sobre {name}:',
                 font=('Segoe UI', 10, 'bold'),
                 bg='#ffffff', fg='#1a202c').pack(anchor='w', padx=12, pady=(12, 4))
        tk.Label(dlg, text='So voce pode ver esta nota.',
                 font=('Segoe UI', 8), bg='#ffffff',
                 fg='#718096').pack(anchor='w', padx=12)

        note_text = tk.Text(dlg, font=('Segoe UI', 10), height=4,
                             relief='flat', bg='#f7fafc',
                             highlightthickness=1, highlightbackground='#e2e8f0',
                             wrap='word')
        note_text.pack(fill='both', expand=True, padx=12, pady=(6, 0))
        note_text.insert('1.0', current_note)
        note_text.focus_set()

        def _save_note():
            new_note = note_text.get('1.0', 'end').strip()
            self.messenger.db.set_contact_private_note(uid, new_note)
            dlg.destroy()

        btn_frame = tk.Frame(dlg, bg='#ffffff')
        btn_frame.pack(fill='x', padx=12, pady=10)
        tk.Button(btn_frame, text='Salvar', font=('Segoe UI', 9, 'bold'),
                  bg='#0f2a5c', fg='#ffffff', relief='flat', bd=0,
                  padx=16, pady=4, cursor='hand2',
                  command=_save_note).pack(side='right')
        tk.Button(btn_frame, text='Cancelar', font=('Segoe UI', 9),
                  bg='#e2e8f0', fg='#4a5568', relief='flat', bd=0,
                  padx=12, pady=4, cursor='hand2',
                  command=dlg.destroy).pack(side='right', padx=(0, 6))

    # Abre ou traz ao foco a janela de chat individual com peer_id.
    #
    # Se a janela ja existe, apenas levanta e da foco no campo de texto.
    # Se nao existe, cria uma nova ChatWindow e aplica o tema atual.
    # Limpa o marcador de nao lido do contato ao abrir.
    def _open_chat(self, peer_id, surface_only=False):
        if peer_id in self.chat_windows:  # janela de chat ja esta aberta?
            cw = self.chat_windows[peer_id]
            if not surface_only:
                cw.lift()        # traz para frente
                cw.focus_force() # forca o foco
                try:
                    cw.entry.focus_set()  # foca no campo de texto
                except Exception:
                    pass
            return cw
        name = self.peer_info.get(peer_id, {}).get('display_name', 'Unknown')  # nome do peer
        cw = ChatWindow(self, peer_id, name, start_hidden=surface_only)
        self.chat_windows[peer_id] = cw       # registra no dicionario
        if hasattr(self, '_theme'):            # tema configurado?
            self._apply_theme_to_chat(cw, self._theme)  # aplica tema atual
        # Carrega mensagens nao lidas do banco e exibe na janela recem-aberta
        try:
            unread = self.messenger.db.get_unread_messages(
                self.messenger.user_id, peer_id)
            for msg in unread:
                if msg.get('msg_type') == 'image':
                    cw.receive_image(msg['content'], msg['timestamp'])
                else:
                    cw.receive_message(msg['content'], msg['timestamp'],
                                       reply_to=msg.get('reply_to_id', ''),
                                       msg_id=msg.get('msg_id', ''))
        except Exception:
            pass
        if not surface_only:
            self._clear_unread(peer_id)           # remove marcacao de nao lido
        return cw

    # --- Menu commands ---
    # Abre dialog para o usuario alterar seu proprio nome de exibicao.
    def _change_name(self):
        win = tk.Toplevel(self.root)  # cria janela modal
        win.title('Alterar Nome')
        win.resizable(False, False)
        _center_window(win, 300, 120)
        win.transient(self.root)
        win.grab_set()
        win.bind('<Escape>', lambda e: win.destroy())

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

    # Abre a janela de Preferencias (tema, autostart, avatar, etc).
    def _show_preferences(self):
        PreferencesWindow(self)  # instancia e exibe a janela de preferencias

    # Abre a janela de Conta (nome, avatar personalizado).
    def _show_account(self):
        AccountWindow(self)  # instancia e exibe a janela de conta

    # Abre janela de Historico de Mensagens com busca global em todos os chats.
    # Digita e busca em tempo real em TODAS as conversas, mostrando contato + data + conteúdo.
    def _show_all_history(self):
        t = THEMES.get(self._current_theme, THEMES.get('MB Contabilidade', {}))
        header_bg = t.get('chat_header_bg', t.get('bg_header', '#0f2a5c'))
        header_fg = t.get('chat_header_fg', '#ffffff')
        win_bg = t.get('bg_window', '#f5f7fa')

        win = tk.Toplevel(self.root)
        win.title('Histórico de Mensagens')
        win.configure(bg=win_bg)
        _center_window(win, 700, 520)
        win.bind('<Escape>', lambda e: win.destroy())
        _apply_rounded_corners(win)
        ico = _get_icon_path()
        if ico:
            try:
                win.iconbitmap(ico)
            except Exception:
                pass

        db = self.messenger.db
        user_id = self.messenger.user_id

        # Header
        hdr = tk.Frame(win, bg=header_bg)
        hdr.pack(fill='x')
        tk.Label(hdr, text='  \U0001f4dc  Histórico de Mensagens',
                 font=('Segoe UI', 11, 'bold'), bg=header_bg, fg=header_fg,
                 anchor='w').pack(fill='x', padx=8, pady=8)

        # Toolbar: busca
        toolbar = tk.Frame(win, bg=win_bg)
        toolbar.pack(fill='x', padx=8, pady=(8, 4))

        tk.Label(toolbar, text='\U0001f50d', font=('Segoe UI', 10),
                 bg=win_bg).pack(side='left')
        search_var = tk.StringVar()
        search_entry = tk.Entry(toolbar, textvariable=search_var,
                                font=('Segoe UI', 10), width=30)
        search_entry.pack(side='left', padx=(4, 12), fill='x', expand=True)
        search_entry.focus_set()

        count_lbl = tk.Label(toolbar, text='', font=('Segoe UI', 9),
                             bg=win_bg, fg='#666666')
        count_lbl.pack(side='right', padx=(8, 0))

        # Filtros: contato + datas
        filter_frame = tk.Frame(win, bg=win_bg)
        filter_frame.pack(fill='x', padx=8, pady=(0, 4))

        tk.Label(filter_frame, text='Contato:', font=('Segoe UI', 9),
                 bg=win_bg).pack(side='left')
        contact_var = tk.StringVar(value='Todos')
        contact_combo = ttk.Combobox(filter_frame, textvariable=contact_var,
                                      font=('Segoe UI', 9), width=18,
                                      state='readonly')
        contact_combo.pack(side='left', padx=(4, 12))

        ph = 'dd/mm/aaaa'
        tk.Label(filter_frame, text='De:', font=('Segoe UI', 9),
                 bg=win_bg).pack(side='left')
        date_from_entry = tk.Entry(filter_frame, font=('Segoe UI', 9), width=12)
        date_from_entry.pack(side='left', padx=(4, 12))
        date_from_entry.insert(0, ph)
        date_from_entry.config(fg='#999999')

        tk.Label(filter_frame, text='Até:', font=('Segoe UI', 9),
                 bg=win_bg).pack(side='left')
        date_to_entry = tk.Entry(filter_frame, font=('Segoe UI', 9), width=12)
        date_to_entry.pack(side='left', padx=(4, 0))
        date_to_entry.insert(0, ph)
        date_to_entry.config(fg='#999999')

        def _on_focus_in(entry):
            if entry.get() == ph:
                entry.delete(0, 'end')
                entry.config(fg='#000000')
        def _on_focus_out(entry):
            if not entry.get().strip():
                entry.insert(0, ph)
                entry.config(fg='#999999')

        date_from_entry.bind('<FocusIn>', lambda e: _on_focus_in(date_from_entry))
        date_from_entry.bind('<FocusOut>', lambda e: _on_focus_out(date_from_entry))
        date_to_entry.bind('<FocusIn>', lambda e: _on_focus_in(date_to_entry))
        date_to_entry.bind('<FocusOut>', lambda e: _on_focus_out(date_to_entry))

        # Separador
        tk.Frame(win, bg='#cccccc', height=1).pack(fill='x', padx=8)

        # Area de resultados
        txt_frame = tk.Frame(win, bg=win_bg)
        txt_frame.pack(fill='both', expand=True, padx=8, pady=(4, 8))

        msg_text = tk.Text(txt_frame, font=FONT_SMALL, wrap='word', bg='#ffffff',
                           fg=FG_BLACK, state='disabled', relief='flat',
                           bd=0, padx=8, pady=4)
        msg_scroll = ttk.Scrollbar(txt_frame, command=msg_text.yview,
                                    style='Clean.Vertical.TScrollbar')
        msg_text.configure(yscrollcommand=msg_scroll.set)
        msg_scroll.pack(side='right', fill='y')
        msg_text.pack(fill='both', expand=True)

        msg_text.tag_configure('ts', foreground='#888888')
        msg_text.tag_configure('me', foreground='#0d47a1', font=('Segoe UI', 9, 'bold'))
        msg_text.tag_configure('peer_tag', foreground='#2e7d32', font=('Segoe UI', 9, 'bold'))
        msg_text.tag_configure('contact_header', foreground='#0f2a5c',
                               font=('Segoe UI', 10, 'bold'))
        msg_text.tag_configure('separator', foreground='#cccccc')
        msg_text.tag_configure('highlight', background='#fff176', foreground='#000000')

        # Cache de nomes: resolve peer_id -> display_name
        _name_cache = {}
        _name_to_peer = {}
        def _resolve_name(peer_id):
            if peer_id in _name_cache:
                return _name_cache[peer_id]
            info = self.peer_info.get(peer_id, {})
            name = info.get('display_name', '')
            if not name:
                row = db.get_contact(peer_id)
                name = row['display_name'] if row else peer_id[:20]
            _name_cache[peer_id] = name
            _name_to_peer[name] = peer_id
            return name

        # Popula combobox de contatos
        contacts_data = db.get_history_contacts()
        _contact_names_list = ['Todos']
        for c in contacts_data:
            name = _resolve_name(c['peer'])
            _contact_names_list.append(name)
        contact_combo['values'] = _contact_names_list

        def _parse_date(s):
            s = s.strip()
            if not s or s == ph:
                return None
            try:
                parts = s.split('/')
                if len(parts) == 3:
                    return datetime(int(parts[2]), int(parts[1]), int(parts[0]))
            except (ValueError, IndexError):
                pass
            return None

        _refresh_timer = [None]

        def _schedule_refresh(*_args):
            if _refresh_timer[0]:
                try:
                    win.after_cancel(_refresh_timer[0])
                except Exception:
                    pass
            _refresh_timer[0] = win.after(200, _refresh)

        def _refresh(*_args):
            query = search_var.get().strip()
            d_from = _parse_date(date_from_entry.get())
            d_to = _parse_date(date_to_entry.get())
            selected_contact = contact_var.get()
            selected_peer = _name_to_peer.get(selected_contact) if selected_contact != 'Todos' else None

            d_from_ts = d_from.timestamp() if d_from else None
            d_to_ts = d_to.replace(hour=23, minute=59, second=59).timestamp() if d_to else None

            if not query and not d_from and not d_to and not selected_peer:
                # Sem filtro: mostra resumo de contatos com historico
                msg_text.configure(state='normal')
                msg_text.delete('1.0', 'end')
                msg_text.insert('end', 'Digite para buscar em todas as conversas\n\n', 'ts')
                for c in contacts_data:
                    peer = c['peer']
                    name = _resolve_name(peer)
                    ts = datetime.fromtimestamp(c['last_ts']).strftime('%d/%m/%Y %H:%M')
                    msg_text.insert('end', f'  {name}', 'contact_header')
                    msg_text.insert('end', f'  — última msg: {ts}\n', 'ts')
                count_lbl.config(text=f'{len(contacts_data)} conversas')
                msg_text.configure(state='disabled')
                return

            # Busca: por contato específico ou global
            if selected_peer:
                msgs = db.get_messages_with_peer(user_id, selected_peer,
                                                  date_from=d_from_ts,
                                                  date_to=d_to_ts,
                                                  search_text=query if query else None)
            else:
                msgs = db.search_all_messages(
                    search_text=query if query else None,
                    date_from=d_from_ts, date_to=d_to_ts, limit=500)

            my_name = self.messenger.display_name

            # Agrupa por peer
            grouped = {}
            for m in msgs:
                peer = m['to_user'] if m['is_sent'] else m['from_user']
                if peer not in grouped:
                    grouped[peer] = []
                grouped[peer].append(m)

            msg_text.configure(state='normal')
            msg_text.delete('1.0', 'end')
            match_count = 0
            query_lower = query.lower() if query else ''

            for peer, peer_msgs in grouped.items():
                peer_name = _resolve_name(peer)
                # Header do contato
                msg_text.insert('end', f'\n  {peer_name}', 'contact_header')
                msg_text.insert('end', f'  ({len(peer_msgs)} resultados)\n', 'ts')
                msg_text.insert('end', '  ' + '─' * 60 + '\n', 'separator')

                for m in peer_msgs:
                    who = my_name if m['is_sent'] else peer_name
                    ts = datetime.fromtimestamp(m['timestamp']).strftime('%d/%m/%Y %H:%M')
                    content = m['content']

                    start_idx = msg_text.index('end-1c')
                    msg_text.insert('end', f'  [{ts}] ', 'ts')
                    who_tag = 'me' if m['is_sent'] else 'peer_tag'
                    msg_text.insert('end', f'{who}: ', who_tag)
                    if m.get('msg_type') == 'image':
                        gtag = f'gimg_{match_count}'
                        msg_text.insert('end', '[Imagem]\n', gtag)
                        msg_text.tag_config(gtag, foreground='#1976d2', underline=True)
                        msg_text.tag_bind(gtag, '<Button-1>',
                                          lambda e, p=content: os.startfile(p) if os.path.exists(p) else None)
                        msg_text.tag_bind(gtag, '<Enter>',
                                          lambda e: msg_text.config(cursor='hand2'))
                        msg_text.tag_bind(gtag, '<Leave>',
                                          lambda e: msg_text.config(cursor=''))
                    else:
                        msg_text.insert('end', f'{content}\n')

                    if query_lower:
                        line_start = start_idx
                        line_end = msg_text.index(f'{start_idx} lineend +1c')
                        full_line = msg_text.get(line_start, line_end).lower()
                        s = 0
                        while True:
                            pos = full_line.find(query_lower, s)
                            if pos < 0:
                                break
                            h_start = f'{line_start}+{pos}c'
                            h_end = f'{line_start}+{pos + len(query_lower)}c'
                            msg_text.tag_add('highlight', h_start, h_end)
                            match_count += 1
                            s = pos + 1

            msg_text.configure(state='disabled')

            total = len(msgs)
            if query:
                count_lbl.config(
                    text=f'{match_count} ocorrências em {total} msgs de {len(grouped)} conversas')
            else:
                count_lbl.config(text=f'{total} mensagens de {len(grouped)} conversas')

        search_var.trace_add('write', _schedule_refresh)
        date_from_entry.bind('<KeyRelease>', _schedule_refresh)
        date_to_entry.bind('<KeyRelease>', _schedule_refresh)
        contact_combo.bind('<<ComboboxSelected>>', _schedule_refresh)
        win.bind('<Control-f>', lambda e: search_entry.focus_set())
        _refresh()

    # Delega para _show_transfers_window() que abre/mostra a janela de transferencias.
    def _show_transfers(self):
        self._show_transfers_window()  # abre ou traz ao foco a janela de transferencias

    # Delega para _show_broadcast() que abre o dialog de Transmitir Mensagem.
    def _send_broadcast(self):
        self._show_broadcast()  # abre o dialog de transmissao de mensagem em massa

    # Janela Transmitir Mensagem — envia para contatos selecionados.
    def _show_broadcast(self):
        NAVY = '#0f2a5c'
        win = tk.Toplevel(self.root)
        win.title('Transmitir Mensagem')
        win.transient(self.root)
        win.grab_set()
        win.configure(bg='#f5f7fa')
        _center_window(win, 660, 480)
        win.minsize(560, 420)
        win.bind('<Escape>', lambda e: win.destroy())

        ico = _get_icon_path()
        if ico:
            try:
                win.iconbitmap(ico)
            except Exception:
                pass

        # Cache de emojis coloridos para este dialog
        _bcast_emoji_cache = {}
        _bcast_img_map = {}  # img_name -> emoji_char (para reconstruir texto)

        def _get_bcast_emoji(emoji_char, size=18):
            key = (emoji_char, size)
            if key in _bcast_emoji_cache:
                return _bcast_emoji_cache[key]
            img = _render_color_emoji(emoji_char, size)
            if img:
                _bcast_emoji_cache[key] = img
            return img

        def _bcast_insert_emoji(emoji_char, pos='insert'):
            img = _get_bcast_emoji(emoji_char, size=18)
            if img:
                img_name = f'bcast_emoji_{len(_bcast_img_map)}'
                _bcast_img_map[img_name] = emoji_char
                txt.image_create(pos, image=img, name=img_name, padx=1)
            else:
                txt.insert(pos, emoji_char)

        def _get_bcast_content():
            result = []
            for key, value, index in txt.dump('1.0', 'end',
                                               image=True, text=True):
                if key == 'text':
                    result.append(value)
                elif key == 'image':
                    emoji = _bcast_img_map.get(value, '')
                    result.append(emoji)
            return ''.join(result).strip()

        # Header navy
        header = tk.Frame(win, bg=NAVY, bd=0)
        header.pack(fill='x')
        header_inner = tk.Frame(header, bg=NAVY)
        header_inner.pack(fill='x', padx=14, pady=10)

        # Icone colorido no header
        _hdr_icon = _render_color_emoji('\U0001f4e2', 22)
        hdr_lbl = tk.Frame(header_inner, bg=NAVY)
        hdr_lbl.pack(anchor='w')
        if _hdr_icon:
            il = tk.Label(hdr_lbl, image=_hdr_icon, bg=NAVY)
            il.image = _hdr_icon
            il.pack(side='left', padx=(0, 6))
        tk.Label(hdr_lbl, text='Transmitir Mensagem',
                 font=('Segoe UI', 12, 'bold'),
                 bg=NAVY, fg='#ffffff').pack(side='left')
        tk.Label(header_inner, text='Envie uma mensagem para múltiplos contatos',
                 font=('Segoe UI', 8), bg=NAVY,
                 fg='#8aa0cc').pack(anchor='w')

        font_var = tk.StringVar(value='Médio')

        # Botões principais (pack ANTES do main para ficar embaixo)
        bottom = tk.Frame(win, bg='#f5f7fa')
        bottom.pack(fill='x', side='bottom', padx=12, pady=(0, 12))

        # Layout principal: esquerda (mensagem) | direita (lista)
        main = tk.Frame(win, bg='#f5f7fa')
        main.pack(fill='both', expand=True, padx=12, pady=10)

        # --- Painel direito (pack ANTES do left para reservar espaço) ---
        right = tk.Frame(main, width=230, bg='#f5f7fa')
        right.pack(side='right', fill='y', padx=(10, 0))
        right.pack_propagate(False)

        tk.Label(right, text='Enviar para:', font=('Segoe UI', 9, 'bold'),
                 bg='#f5f7fa', fg='#334155').pack(anchor='w', pady=(0, 4))

        list_border = tk.Frame(right, bg='#e2e8f0', bd=0)
        list_border.pack(fill='both', expand=True)
        list_inner = tk.Frame(list_border, bg='#ffffff', bd=0)
        list_inner.pack(fill='both', expand=True, padx=1, pady=1)

        canvas_r = tk.Canvas(list_inner, bg='#ffffff', highlightthickness=0)
        canvas_r.pack(fill='both', expand=True)

        inner_r = tk.Frame(canvas_r, bg='#ffffff')
        win_id_r = canvas_r.create_window((0, 0), window=inner_r, anchor='nw')

        # Fix: inner_r preenche largura total e scrollregion correto
        def _on_canvas_r_cfg(e):
            canvas_r.itemconfig(win_id_r, width=e.width)
        canvas_r.bind('<Configure>', _on_canvas_r_cfg)
        inner_r.bind('<Configure>',
                     lambda e: canvas_r.configure(
                         scrollregion=(0, 0, e.width, e.height)))

        peer_vars = {}

        # Linha "Todos" (seleciona todos)
        all_var = tk.BooleanVar(value=True)

        def toggle_all():
            v = all_var.get()
            for pv in peer_vars.values():
                pv.set(v)

        gen_row = tk.Frame(inner_r, bg='#e8f0fe', bd=0)
        gen_row.pack(fill='x')
        gen_inner = tk.Frame(gen_row, bg='#e8f0fe')
        gen_inner.pack(fill='x', padx=6, pady=5)
        tk.Checkbutton(gen_inner,
                       text='  Todos os contatos',
                       variable=all_var,
                       font=('Segoe UI', 9, 'bold'), bg='#e8f0fe',
                       fg='#1a202c', activebackground='#e8f0fe',
                       selectcolor='#e8f0fe', anchor='w',
                       command=toggle_all).pack(fill='x')

        # Cada contato
        for uid, info in self.peer_info.items():
            var = tk.BooleanVar(value=True)
            peer_vars[uid] = var
            name = info.get('display_name', uid)
            status = info.get('status', 'offline')

            p_row = tk.Frame(inner_r, bg='#ffffff')
            p_row.pack(fill='x')

            # Separador sutil
            tk.Frame(p_row, bg='#f0f2f5', height=1).pack(fill='x')

            p_content = tk.Frame(p_row, bg='#ffffff')
            p_content.pack(fill='x', padx=6, pady=4)

            cb = tk.Checkbutton(p_content, text=f'  {name}', variable=var,
                                font=('Segoe UI', 9), anchor='w',
                                bg='#ffffff', fg='#1a202c',
                                activebackground='#ffffff',
                                selectcolor='#ffffff')
            cb.pack(side='left', fill='x', expand=True)

            try:
                av = self._create_contact_avatar(uid, name, status)
                lbl_av = tk.Label(p_content, image=av, bg='#ffffff')
                lbl_av.image = av
                lbl_av.pack(side='right', padx=2)
            except Exception:
                pass

        def _scroll_r(e):
            canvas_r.yview_scroll(-1 * (e.delta // 120), 'units')
        win.bind('<MouseWheel>', _scroll_r)

        # Botões seleção
        sel_frame = tk.Frame(right, bg='#f5f7fa')
        sel_frame.pack(fill='x', pady=(4, 0))

        def select_all():
            all_var.set(True)
            for v in peer_vars.values():
                v.set(True)

        def cancel_sel():
            all_var.set(False)
            for v in peer_vars.values():
                v.set(False)

        btn_sel = tk.Button(sel_frame, text='Todos',
                            font=('Segoe UI', 7, 'bold'),
                            bg='#e2e8f0', fg='#4a5568', relief='flat', bd=0,
                            padx=8, pady=2, cursor='hand2',
                            command=select_all)
        btn_sel.pack(side='left')
        _add_hover(btn_sel, '#e2e8f0', '#cbd5e0')

        btn_none = tk.Button(sel_frame, text='Nenhum',
                             font=('Segoe UI', 7, 'bold'),
                             bg='#e2e8f0', fg='#4a5568', relief='flat', bd=0,
                             padx=8, pady=2, cursor='hand2',
                             command=cancel_sel)
        btn_none.pack(side='left', padx=(4, 0))
        _add_hover(btn_none, '#e2e8f0', '#cbd5e0')

        # --- Painel esquerdo ---
        left = tk.Frame(main, bg='#f5f7fa')
        left.pack(side='left', fill='both', expand=True)

        toolbar = tk.Frame(left, bg='#f5f7fa')
        toolbar.pack(fill='x', pady=(0, 6))

        # Font size pill buttons
        tk.Label(toolbar, text='Tamanho da Fonte:', font=('Segoe UI', 8),
                 bg='#f5f7fa', fg='#64748b').pack(side='left', padx=(0, 4))
        pill_frame = tk.Frame(toolbar, bg='#e2e8f0')
        pill_frame.pack(side='left')
        font_pills = {}
        for fname in ('Pequeno', 'Médio', 'Grande'):
            is_sel = fname == 'Médio'
            pb = tk.Button(pill_frame, text=fname, font=('Segoe UI', 7),
                           bg=NAVY if is_sel else '#e2e8f0',
                           fg='#ffffff' if is_sel else '#4a5568',
                           relief='flat', bd=0, padx=8, pady=2,
                           cursor='hand2')
            pb.pack(side='left', padx=0)
            font_pills[fname] = pb

        txt_border = tk.Frame(left, bg='#d0d5dd')
        txt_border.pack(fill='both', expand=True)
        txt_inner = tk.Frame(txt_border, bg='#ffffff')
        txt_inner.pack(fill='both', expand=True, padx=1, pady=1)
        txt = tk.Text(txt_inner, font=('Segoe UI', 10), relief='flat',
                      bd=0, padx=8, pady=6, wrap='word')
        txt.pack(fill='both', expand=True)

        # Detectar emojis: <<Modified>> dispara para QUALQUER alteração de conteúdo
        # (teclado, IME, Windows Emoji Picker, paste). É o único evento confiável.
        def _do_bcast_scan():
            try:
                _scan_entry_emojis(txt, _bcast_emoji_cache, _bcast_img_map,
                                   prefix='bcast_emoji', size=18)
            except Exception:
                pass

        def _on_bcast_modified(event):
            try:
                txt.edit_modified(False)  # Reset obrigatório para re-disparar
            except Exception:
                pass
            txt.after(30, _do_bcast_scan)
        txt.bind('<<Modified>>', _on_bcast_modified)

        def on_pill_click(sel_name):
            sizes = {'Pequeno': 9, 'Médio': 10, 'Grande': 13}
            txt.configure(font=('Segoe UI', sizes.get(sel_name, 10)))
            font_var.set(sel_name)
            for n, b in font_pills.items():
                if n == sel_name:
                    b.config(bg=NAVY, fg='#ffffff')
                else:
                    b.config(bg='#e2e8f0', fg='#4a5568')

        for fname, pbtn in font_pills.items():
            pbtn.config(command=lambda n=fname: on_pill_click(n))

        # Emoji button colorido
        _emoji_btn_img = _render_color_emoji('\U0001f60a', 20)

        def open_bcast_emoji():
            ep = tk.Toplevel(win)
            ep.title('')
            ep.overrideredirect(True)
            ep.configure(bg='#e2e8f0')
            _center_window(ep, 310, 230)
            emojis = ['\U0001f600', '\U0001f601', '\U0001f602', '\U0001f603',
                      '\U0001f604', '\U0001f605', '\U0001f606', '\U0001f607',
                      '\U0001f608', '\U0001f609', '\U0001f60a', '\U0001f60b',
                      '\U0001f60d', '\U0001f60e', '\U0001f60f', '\U0001f610',
                      '\U0001f611', '\U0001f612', '\U0001f613', '\U0001f614',
                      '\U0001f615', '\U0001f616', '\U0001f617', '\U0001f618',
                      '\U0001f619', '\U0001f61a', '\U0001f61b', '\U0001f61c',
                      '\U0001f61d', '\U0001f61e', '\U0001f61f', '\U0001f620',
                      '\U0001f621', '\U0001f622', '\U0001f923', '\U0001f924',
                      '\U0001f44d', '\U0001f44e', '\U0001f44f', '\U0001f64f',
                      '\u2601', '\u26c5', '\U0001f37a', '\U0001f37b']
            fr = tk.Frame(ep, bg='#ffffff')
            fr.pack(fill='both', expand=True, padx=1, pady=1)
            ep._emoji_imgs = {}  # manter referencia para GC
            col, row = 0, 0
            for em in emojis:
                img = _get_bcast_emoji(em, size=24)
                def ins(e=em):
                    _bcast_insert_emoji(e)
                    ep.destroy()
                if img:
                    ep._emoji_imgs[em] = img
                    b = tk.Button(fr, image=img, relief='flat', bd=0,
                                  cursor='hand2', command=ins,
                                  bg='#ffffff', activebackground='#f0f5ff',
                                  width=30, height=30)
                else:
                    b = tk.Button(fr, text=em, font=('Segoe UI', 14),
                                  relief='flat', bd=0, cursor='hand2',
                                  command=ins, bg='#ffffff',
                                  activebackground='#f0f5ff')
                b.grid(row=row, column=col, padx=1, pady=1)
                col += 1
                if col >= 8:
                    col = 0
                    row += 1
            ep.bind('<Escape>', lambda e: ep.destroy())
            # Fechar ao clicar fora
            def _check_ep_focus():
                if not ep.winfo_exists():
                    return
                try:
                    focused = ep.focus_get()
                    if focused is None or not str(focused).startswith(str(ep)):
                        ep.destroy()
                except Exception:
                    ep.destroy()
            ep.bind('<FocusOut>', lambda e: ep.after(100, _check_ep_focus))
            ep.focus_set()

        if _emoji_btn_img:
            btn_emoji = tk.Button(toolbar, image=_emoji_btn_img,
                                  relief='flat', bd=0, cursor='hand2',
                                  bg='#f5f7fa', activebackground='#e2e8f0',
                                  command=open_bcast_emoji)
            btn_emoji.image = _emoji_btn_img
        else:
            btn_emoji = tk.Button(toolbar, text='\U0001f60a',
                                  font=('Segoe UI', 12),
                                  relief='flat', bd=0, cursor='hand2',
                                  bg='#f5f7fa', activebackground='#e2e8f0',
                                  command=open_bcast_emoji)
        btn_emoji.pack(side='left', padx=(8, 0))

        def do_send():
            content = _get_bcast_content()
            if not content:
                messagebox.showwarning('Transmitir', 'Digite uma mensagem.',
                                       parent=win)
                return
            sent = 0
            for uid, var in peer_vars.items():
                if var.get():
                    threading.Thread(target=self.messenger.send_message,
                                     args=(uid, content, '', True),
                                     daemon=True).start()
                    sent += 1
            win.destroy()
            if sent:
                messagebox.showinfo('Transmitir',
                                    f'Mensagem enviada para {sent} contato(s).')

        btn_send = tk.Button(bottom, text='  Enviar  ',
                             font=('Segoe UI', 9, 'bold'),
                             bg=NAVY, fg='#ffffff', relief='flat', bd=0,
                             padx=16, pady=5, cursor='hand2',
                             activebackground='#1a3f7a',
                             activeforeground='#ffffff',
                             command=do_send)
        btn_send.pack(side='left')
        _add_hover(btn_send, NAVY, '#1a3f7a')

        btn_cancel = tk.Button(bottom, text='  Cancelar  ',
                               font=('Segoe UI', 9),
                               bg='#e2e8f0', fg='#4a5568', relief='flat',
                               bd=0, padx=16, pady=5, cursor='hand2',
                               activebackground='#cbd5e0',
                               command=win.destroy)
        btn_cancel.pack(side='left', padx=(8, 0))
        _add_hover(btn_cancel, '#e2e8f0', '#cbd5e0')

        txt.focus_set()

    # Dialog moderno para criar grupo.
    def _show_group_chat_dialog(self):
        NAVY = '#0f2a5c'
        win = tk.Toplevel(self.root)
        win.title('Criar Grupo - Selecionar Contatos')
        win.transient(self.root)
        win.grab_set()
        win.configure(bg='#f5f7fa')
        _center_window(win, 340, 580)
        _apply_rounded_corners(win)
        win.resizable(False, False)
        win.bind('<Escape>', lambda e: win.destroy())

        ico = _get_icon_path()
        if ico:
            try:
                win.iconbitmap(ico)
            except Exception:
                pass

        # Header navy
        header = tk.Frame(win, bg=NAVY, bd=0)
        header.pack(fill='x', side='top')
        header_inner = tk.Frame(header, bg=NAVY)
        header_inner.pack(fill='x', padx=14, pady=10)
        tk.Label(header_inner, text='Criar Grupo',
                 font=('Segoe UI', 12, 'bold'),
                 bg=NAVY, fg='#ffffff').pack(anchor='w')
        tk.Label(header_inner, text='Escolha o tipo e os participantes',
                 font=('Segoe UI', 8), bg=NAVY,
                 fg='#8aa0cc').pack(anchor='w')

        # Bottom: nome + botões (pack ANTES do content para ficar fixo embaixo)
        bottom = tk.Frame(win, bg='#f5f7fa')
        bottom.pack(fill='x', side='bottom', padx=12, pady=(0, 10))

        # Nome do grupo
        name_frame = tk.Frame(bottom, bg='#f5f7fa')
        name_frame.pack(fill='x', pady=(6, 6))
        tk.Label(name_frame, text='Nome do grupo:', font=('Segoe UI', 9),
                 bg='#f5f7fa', fg='#4a5568').pack(side='left')

        name_border = tk.Frame(name_frame, bg='#d0d5dd', bd=0)
        name_border.pack(side='left', fill='x', expand=True, padx=(8, 0))
        name_inner_nm = tk.Frame(name_border, bg='#ffffff', bd=0)
        name_inner_nm.pack(fill='x', padx=1, pady=1)

        name_var = tk.StringVar(value='Grupo')
        name_entry = tk.Entry(name_inner_nm, textvariable=name_var,
                              font=('Segoe UI', 9), bg='#ffffff',
                              fg='#1a202c', relief='flat', bd=0,
                              insertbackground='#1a202c')
        name_entry.pack(fill='x', ipady=3, padx=4)

        # Botões
        btn_frame = tk.Frame(bottom, bg='#f5f7fa')
        btn_frame.pack(fill='x', pady=(2, 0))

        peer_vars = {}

        def criar_grupo():
            selected = [uid for uid, v in peer_vars.items() if v.get()]
            if not selected:
                messagebox.showwarning('Criar Grupo',
                                       'Selecione pelo menos um contato.',
                                       parent=win)
                return
            group_id = str(uuid.uuid4()).replace('-', '')[:12]
            group_name = name_var.get().strip() or 'Grupo'
            group_type = type_var.get()
            win.destroy()
            self._create_group_window(group_id, group_name, selected,
                                      group_type)

        btn_criar = tk.Button(btn_frame, text='  Criar  ',
                              font=('Segoe UI', 9, 'bold'),
                              bg=NAVY, fg='#ffffff', relief='flat', bd=0,
                              padx=16, pady=5, cursor='hand2',
                              activebackground='#1a3f7a',
                              activeforeground='#ffffff',
                              command=criar_grupo)
        btn_criar.pack(side='left')
        _add_hover(btn_criar, NAVY, '#1a3f7a')

        btn_cancel = tk.Button(btn_frame, text='  Cancelar  ',
                               font=('Segoe UI', 9),
                               bg='#e2e8f0', fg='#4a5568', relief='flat',
                               bd=0, padx=16, pady=5, cursor='hand2',
                               activebackground='#cbd5e0',
                               command=win.destroy)
        btn_cancel.pack(side='left', padx=(8, 0))
        _add_hover(btn_cancel, '#e2e8f0', '#cbd5e0')

        # Separador acima do bottom
        tk.Frame(win, bg='#e2e8f0', height=1).pack(fill='x', side='bottom')

        # Content area (entre header e bottom)
        content = tk.Frame(win, bg='#f5f7fa')
        content.pack(fill='both', expand=True, padx=12, pady=(10, 0))

        # Tipo de grupo
        type_frame = tk.Frame(content, bg='#e8f0fe', bd=0)
        type_frame.pack(fill='x', pady=(0, 6))
        type_inner = tk.Frame(type_frame, bg='#e8f0fe')
        type_inner.pack(fill='x', padx=8, pady=6)
        tk.Label(type_inner, text='Tipo:', font=('Segoe UI', 9, 'bold'),
                 bg='#e8f0fe', fg='#1a202c').pack(anchor='w')

        type_var = tk.StringVar(value='temp')
        tk.Radiobutton(type_inner, text='Grupo Temporário',
                        variable=type_var, value='temp',
                        font=('Segoe UI', 9), bg='#e8f0fe',
                        fg='#1a202c', activebackground='#e8f0fe',
                        selectcolor='#e8f0fe').pack(anchor='w')
        tk.Radiobutton(type_inner, text='Grupo Fixo',
                        variable=type_var, value='fixed',
                        font=('Segoe UI', 9), bg='#e8f0fe',
                        fg='#1a202c', activebackground='#e8f0fe',
                        selectcolor='#e8f0fe').pack(anchor='w')

        # "Selecionar todos" option
        pub_var = tk.BooleanVar(value=False)

        pub_row = tk.Frame(content, bg='#f0f5ff', bd=0)
        pub_row.pack(fill='x', pady=(0, 6))
        pub_inner = tk.Frame(pub_row, bg='#f0f5ff')
        pub_inner.pack(fill='x', padx=8, pady=4)

        def toggle_pub():
            for v in peer_vars.values():
                v.set(pub_var.get())

        cb_pub = tk.Checkbutton(pub_inner,
                                text='\U0001f310  Selecionar todos',
                                variable=pub_var, font=('Segoe UI', 9, 'bold'),
                                bg='#f0f5ff', fg='#1a202c',
                                activebackground='#f0f5ff', anchor='w',
                                selectcolor='#f0f5ff', command=toggle_pub)
        cb_pub.pack(fill='x')

        # Lista de contatos ONLINE com scroll
        list_border = tk.Frame(content, bg='#e2e8f0', bd=0)
        list_border.pack(fill='both', expand=True, pady=(0, 4))
        list_inner = tk.Frame(list_border, bg='#ffffff', bd=0)
        list_inner.pack(fill='both', expand=True, padx=1, pady=1)

        canvas_g = tk.Canvas(list_inner, bg='#ffffff', highlightthickness=0)
        scrollbar_g = ttk.Scrollbar(list_inner, orient='vertical',
                                     command=canvas_g.yview)
        canvas_g.configure(yscrollcommand=scrollbar_g.set)
        canvas_g.pack(side='left', fill='both', expand=True)

        inner_g = tk.Frame(canvas_g, bg='#ffffff')
        win_id = canvas_g.create_window((0, 0), window=inner_g, anchor='nw')

        def _on_canvas_cfg(e):
            canvas_g.itemconfig(win_id, width=e.width)
        canvas_g.bind('<Configure>', _on_canvas_cfg)

        def _on_inner_cfg(e):
            canvas_g.configure(scrollregion=(0, 0, e.width, e.height))
            # Mostrar scrollbar só se conteúdo excede canvas
            if e.height > canvas_g.winfo_height():
                scrollbar_g.pack(side='right', fill='y')
            else:
                scrollbar_g.pack_forget()
        inner_g.bind('<Configure>', _on_inner_cfg)

        def _scroll_g(e):
            canvas_g.yview_scroll(-1 * (e.delta // 120), 'units')
        
        win.bind('<MouseWheel>', _scroll_g)

        for uid, info in self.peer_info.items():
            status = info.get('status', 'offline')
            if status == 'offline':
                continue  # Não mostrar offline
            var = tk.BooleanVar(value=False)
            peer_vars[uid] = var
            name = info.get('display_name', uid)

            p_row = tk.Frame(inner_g, bg='#ffffff', cursor='hand2')
            p_row.pack(fill='x')

            tk.Frame(p_row, bg='#f0f2f5', height=1).pack(fill='x')

            p_content = tk.Frame(p_row, bg='#ffffff')
            p_content.pack(fill='x', padx=6, pady=5)

            cb = tk.Checkbutton(p_content, text=f'  {name}', variable=var,
                                font=('Segoe UI', 9), anchor='w',
                                bg='#ffffff', fg='#1a202c',
                                activebackground='#f0f5ff',
                                selectcolor='#ffffff')
            cb.pack(side='left', fill='x', expand=True)

            try:
                av = self._create_contact_avatar(uid, name, status)
                lbl_av = tk.Label(p_content, image=av, bg='#ffffff')
                lbl_av.image = av
                lbl_av.pack(side='right', padx=2)
            except Exception:
                pass

    def _create_group_window(self, group_id, group_name, member_ids,
                              group_type='temp'):
        # Cria uma nova GroupChatWindow e envia convites MT_GROUP_INV para todos os membros.
        #
        # Se a janela ja existir, apenas a exibe. Adiciona o proprio usuario e todos
        # os membros selecionados ao painel da janela. Registra o grupo no TreeView.
        # O envio de convites ocorre em thread separada para nao bloquear a UI.
        if group_id in self.group_windows:  # janela ja existe? apenas exibe
            gw = self.group_windows[group_id]
            gw.deiconify()  # exibe se oculta
            gw.lift()       # traz para frente
            return
        gw = GroupChatWindow(self, group_id, group_name, group_type=group_type)  # cria janela
        self.group_windows[group_id] = gw  # registra no dicionario
        # Envia convites MT_GROUP_INV para todos os membros em thread separada
        threading.Thread(target=self.messenger.send_group_invite,
                         args=(group_id, group_name, member_ids, group_type),
                         daemon=True).start()  # nao bloqueia a UI
        # Adiciona o proprio usuario ao painel lateral da janela de grupo
        my_info = {'ip': '', 'status': 'online', 'note': self.messenger.note}  # propria info
        gw.add_member(self.messenger.user_id, self.messenger.display_name, my_info)
        for uid in member_ids:  # adiciona cada membro convidado ao painel
            info = self.peer_info.get(uid, {})  # info do peer (pode estar vazio)
            gw.add_member(uid, info.get('display_name', uid), info)
        # Registra no TreeView (aparece em Grupos tanto temp quanto fixo)
        self._add_group_to_tree(group_id, group_name, group_type)

    def _on_group_invite(self, group_id, group_name, from_uid, members,
                          group_type='temp'):
        # Recebe convite para entrar em grupo e abre a GroupChatWindow correspondente.
        #
        # Chamado pelo messenger quando chega MT_GROUP_INV pela rede.
        # Se a janela do grupo ja existir, apenas exibe/levanta ela.
        # Adiciona todos os membros recebidos no convite ao painel lateral.
        # Exibe mensagem de sistema informando quem criou o grupo.
        # Pisca a janela para alertar o usuario sobre o novo grupo.
        if group_id in self.group_windows:
            gw = self.group_windows[group_id]
            gw.deiconify()
            gw.lift()
            return
        gw = GroupChatWindow(self, group_id, group_name, group_type=group_type)
        self.group_windows[group_id] = gw
        for m in members:
            m_info = self.peer_info.get(m['uid'], {'ip': m.get('ip', ''),
                        'status': 'online', 'note': ''})
            gw.add_member(m['uid'], m['display_name'], m_info)
        from_name = self.peer_info.get(from_uid, {}).get('display_name',
                                                          from_uid)
        gw.system_message(f'{from_name} criou este grupo.')
        self._pending_flash_target = f'group:{group_id}'
        self._flash_window(gw)
        self._flash_window()
        self._add_group_to_tree(group_id, group_name, group_type)

    def _on_group_message(self, group_id, from_uid, display_name,
                           content, timestamp, reply_to='', mentions=None,
                           msg_id='', **kw):
        # Roteia mensagem de grupo recebida para a janela correta ou acumula pendente.
        #
        # Chamado pelo messenger quando chega MT_GROUP_MSG pela rede.
        # Se a janela do grupo esta aberta: entrega a mensagem diretamente.
        # - Se nao esta em foco: mostra toast + pisca janela e taskbar.
        # Se a janela NAO esta aberta: salva em _pending_group_msgs, marca unread
        # no TreeView, mostra toast e pisca a taskbar principal.
        # Em ambos os casos toca o som de notificacao.
        SoundPlayer.play_msg_group()
        if group_id in self.group_windows:  # janela do grupo esta aberta?
            gw = self.group_windows[group_id]
            gw.receive_message(display_name, content, timestamp,
                               reply_to=reply_to, mentions=mentions,
                               msg_id=msg_id)
            try:
                if not gw.focus_displayof():
                    self._show_group_toast(group_id, display_name, content)
                    self._pending_flash_target = f'group:{group_id}'
                    self._flash_window(gw)
            except Exception:
                pass
        else:
            # Janela nao esta aberta: cria minimizada na taskbar com mensagem dentro
            self._mark_group_unread(group_id)
            self._show_group_toast(group_id, display_name, content)
            self._pending_flash_target = f'group:{group_id}'
            def _create():
                gw = self._open_group(group_id, surface_only=True)
                if gw:
                    gw.receive_message(display_name, content, timestamp,
                                       reply_to=reply_to, mentions=mentions,
                                       msg_id=msg_id)
                return gw
            self._surface_chat_from_tray(_create)

    # Processa notificacao de saida de membro do grupo (MT_GROUP_LEAVE).
    #
    # Se a janela do grupo estiver aberta, exibe mensagem de sistema
    # ('X saiu do grupo.') e remove o membro do painel de participantes.
    def _on_group_leave(self, group_id, uid, display_name):
        if group_id in self.group_windows:
            gw = self.group_windows[group_id]
            gw.system_message(f'{display_name} saiu do grupo.')
            gw.remove_member(uid)

    # Processa notificacao de entrada de novo membro no grupo (MT_GROUP_JOIN).
    #
    # Se a janela do grupo estiver aberta, adiciona o membro ao painel
    # de participantes e exibe mensagem de sistema ('X entrou no grupo.').
    def _on_group_join(self, group_id, uid, display_name):
        if group_id in self.group_windows:
            gw = self.group_windows[group_id]
            m_info = self.peer_info.get(uid, {'ip': '', 'status': 'online',
                                               'note': ''})
            gw.add_member(uid, display_name, m_info)
            gw.system_message(f'{display_name} entrou no grupo.')

    # Abre dialogo de selecao de arquivo e envia ao contato selecionado na toolbar.
    #
    # Se nenhum contato estiver selecionado, exibe aviso ao usuario.
    def _send_file_toolbar(self):
        uid = self._get_selected_peer()  # uid do contato selecionado no TreeView
        if not uid:                        # nenhum contato selecionado?
            messagebox.showinfo(_t('send_file_btn'), _t('file_select_contact'))  # avisa
            return
        fp = filedialog.askopenfilename(title='Enviar arquivo')
        if fp:
            self._start_file_send(uid, fp)

    # Inicia envio de arquivo com dialogo de progresso.
    def _start_file_send(self, peer_id, filepath):
        fid = self.messenger.send_file(peer_id, filepath)
        if fid:
            name = self.peer_info.get(peer_id, {}).get('display_name', 'Unknown')
            fname = os.path.basename(filepath)
            fsize = os.path.getsize(filepath)
            # Garante que a janela de chat esteja aberta para que o usuario
            # veja a mensagem do arquivo enviado (como se tivesse digitado).
            if peer_id not in self.chat_windows:
                try:
                    self._open_chat(peer_id)
                except Exception:
                    pass
            dlg = FileTransferDialog(
                self.root, fid, fname, name,
                direction='send', filesize=fsize,
                on_cancel=self.messenger.cancel_file
            )
            self._file_dialogs[fid] = dlg
            self._add_transfer_entry(fid, fname, name, 'send', fsize,
                                      'pending', peer_id=peer_id)

    # Envia arquivo para todos os membros de um grupo (chamado pelo DnD)
    def _start_group_file_send(self, group_id, filepath):
        threading.Thread(target=self.messenger.send_file_to_group,
                         args=(group_id, filepath),
                         daemon=True).start()
        if group_id in self.group_windows:
            fname = os.path.basename(filepath)
            self.group_windows[group_id].system_message(
                f'Enviando "{fname}" para o grupo...')

    # Dispara um announce UDP imediato para redescobrir peers na rede.
    def _refresh_peers(self):
        self.messenger.discovery._send_announce()  # envia pacote UDP de presenca agora

    # --- Auto-update ---

    # Detecta se o app acabou de ser atualizado comparando versao salva no banco.
    def _check_post_update(self):
        last = self.messenger.db.get_setting('last_version', None)
        self.messenger.db.set_setting('last_version', APP_VERSION)
        if last and last != APP_VERSION:
            self.root.after(500, lambda: self._show_post_update_bar(last))

    # Barra verde "Atualizacao concluida" que some apos 12 segundos ou clicando X.
    def _show_post_update_bar(self, old_ver):
        bar = tk.Frame(self.root, bg='#d4edda', bd=0)
        children = self.root.winfo_children()
        # Posiciona apos o header (user_frame) mas antes do conteudo
        try:
            if len(children) > 1:
                bar.pack(fill='x', before=children[1])
            else:
                bar.pack(fill='x')
        except Exception:
            bar.pack(fill='x')
        tk.Label(bar, text=f'\u2714  Atualização concluída!  {old_ver} \u2192 v{APP_VERSION}',
                 font=('Segoe UI', 9, 'bold'), bg='#d4edda', fg='#155724'
                 ).pack(side='left', padx=(10, 5), pady=6)
        tk.Button(bar, text='\u2715', font=('Segoe UI', 9), bg='#d4edda',
                  fg='#155724', bd=0, cursor='hand2',
                  command=bar.destroy).pack(side='right', padx=(0, 10), pady=6)
        self.root.after(12000, lambda: bar.destroy() if bar.winfo_exists() else None)

    # Verifica update no startup (chamado no _deferred_init em background).
    def _check_update_startup(self):
        def _on_result(has_update, ver):
            if has_update:
                self.root.after(0, lambda: self._show_update_bar(ver))
        updater.check_update_async(_on_result)

    # ========================================
    # LEMBRETES
    # ========================================

    # Inicia timer que checa lembretes pendentes a cada 30s
    def _start_reminder_timer(self):
        self._check_reminders()
        self.root.after(10000, self._start_reminder_timer)

    # Checa lembretes pendentes e dispara notificacao
    def _check_reminders(self):
        try:
            db = self.messenger.db
            pending = db.get_pending_reminders()
            want_notif = db.get_setting('notif_reminder', '1') == '1'
            for rem in pending:
                if rem.get('is_recurring') and rem.get('is_active'):
                    db.reschedule_recurring_reminder(rem['id'])
                else:
                    db.mark_reminder_notified(rem['id'])
                text = rem.get('text', 'Lembrete')
                remind_at = datetime.fromtimestamp(rem['remind_at'])
                time_str = remind_at.strftime('%H:%M')
                title = f'\u23f0 Lembrete ({time_str})'
                notified = False
                # Notificacao Windows via winotify
                if want_notif and HAS_WINOTIFY:
                    try:
                        n = WinNotification(
                            app_id='MB Chat',
                            title=title,
                            msg=text,
                            icon=self._icon_path or '')
                        n.launch = 'mbchat://open/__reminders__'
                        n.add_actions(label='Ver Lembretes', launch='mbchat://open/__reminders__')
                        n.set_audio(wn_audio.Default, loop=False)
                        n.show()
                        notified = True
                    except Exception:
                        log.exception('Erro winotify lembrete')
                # Fallback: balloon tip via pystray
                if want_notif and not notified:
                    if self._balloon_notify(text, title):
                        notified = True
                # Fallback final: messagebox (sempre, se nenhuma notif funcionou)
                if not notified:
                    self.root.after(0, lambda t=text, ti=title: messagebox.showinfo(ti, t))
                SoundPlayer.play_reminder()
                # Abre a janela de Lembretes surfaceando do tray (igual a chat)
                # e pisca-a na taskbar (gate proprio de lembrete)
                try:
                    self._pending_flash_target = '__reminders__'
                    def _create_reminders():
                        existing = getattr(self, '_reminders_window', None)
                        if existing is not None:
                            try:
                                if existing.winfo_exists():
                                    return existing
                            except Exception:
                                pass
                        self._show_reminders()
                        return getattr(self, '_reminders_window', None)
                    self._surface_chat_from_tray(_create_reminders)
                    win = getattr(self, '_reminders_window', None)
                    if win is not None:
                        self._flash_window(win, gate_key='flash_reminder')
                except Exception:
                    log.exception('Erro ao surfacear janela de lembretes')
            # Atualiza janela de lembretes se estiver aberta
            if pending and hasattr(self, '_reminders_list_frame'):
                try:
                    lf = self._reminders_list_frame
                    if lf and lf.winfo_exists():
                        self._refresh_reminders_list(lf)
                except Exception:
                    pass
        except Exception:
            log.exception('Erro ao checar lembretes')

    # Abre janela de gerenciamento de lembretes
    def _show_reminders(self):
        win = tk.Toplevel(self.root)
        win.title('Lembretes')
        win.transient(self.root)
        win.configure(bg='#ffffff')
        _center_window(win, 440, 450)
        _apply_rounded_corners(win)
        win.bind('<Escape>', lambda e: win.destroy())

        # Header
        hdr = tk.Frame(win, bg='#0f2a5c')
        hdr.pack(fill='x')
        tk.Label(hdr, text='\u23f0 Lembretes', font=('Segoe UI', 12, 'bold'),
                 bg='#0f2a5c', fg='#ffffff').pack(padx=12, pady=10, side='left')
        def _show_new_menu():
            menu = tk.Menu(win, tearoff=0, font=('Segoe UI', 10))
            menu.add_command(label='\U0001f4cc  Simples', command=lambda: self._new_simple_reminder_dialog(win, list_frame))
            menu.add_command(label='\u23f0  Programado', command=lambda: self._new_reminder_dialog(win, list_frame))
            menu.add_command(label='\U0001f504  Recorrente', command=lambda: self._new_recurring_reminder_dialog(win, list_frame))
            menu.tk_popup(btn_novo.winfo_rootx(), btn_novo.winfo_rooty() + btn_novo.winfo_height())
        btn_novo = tk.Button(hdr, text='+ Novo', font=('Segoe UI', 9, 'bold'),
                  bg='#2563eb', fg='#ffffff', relief='flat', bd=0,
                  padx=14, pady=4, cursor='hand2',
                  command=_show_new_menu)
        btn_novo.pack(side='right', padx=10, pady=8)
        _add_hover(btn_novo, '#2563eb', '#1d4ed8')

        # Scrollable list
        canvas = tk.Canvas(win, bg='#ffffff', highlightthickness=0)
        scrollbar = ttk.Scrollbar(win, orient='vertical', command=canvas.yview)
        list_frame = tk.Frame(canvas, bg='#ffffff')
        self._reminders_list_frame = list_frame  # ref para auto-refresh pelo timer
        self._reminders_window = win  # ref para surfacing no disparo
        list_frame.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.create_window((0, 0), window=list_frame, anchor='nw', tags='frame')
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side='left', fill='both', expand=True, padx=8, pady=8)
        scrollbar.pack(side='right', fill='y', pady=8)
        canvas.bind('<Configure>', lambda e: canvas.itemconfig('frame', width=e.width))
        # Scroll com roda do mouse
        def _on_mousewheel(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), 'units')
        canvas.bind_all('<MouseWheel>', _on_mousewheel)
        def _on_win_destroy(e):
            if e.widget == win:
                canvas.unbind_all('<MouseWheel>')
                self._reminders_list_frame = None
                self._reminders_window = None
        win.bind('<Destroy>', _on_win_destroy)
        self._refresh_reminders_list(list_frame)

    def _refresh_reminders_list(self, parent):
        for w in parent.winfo_children():
            w.destroy()
        # Mostra pendentes + concluidos recentes (ultimas 24h)
        pending = self.messenger.db.get_all_reminders()
        completed = self.messenger.db.get_completed_reminders()
        if not pending and not completed:
            tk.Label(parent, text='Nenhum lembrete.\nClique em "+ Novo" para criar.',
                     font=('Segoe UI', 10), bg='#ffffff', fg='#a0aec0',
                     justify='center').pack(pady=40)
            return
        # Pendentes
        for rem in pending:
            self._render_reminder_row(parent, rem, completed=False)
        # Separador se tem ambos
        if pending and completed:
            sep = tk.Frame(parent, bg='#e2e8f0', height=1)
            sep.pack(fill='x', pady=8)
            tk.Label(parent, text='Concluidos', font=('Segoe UI', 8),
                     bg='#ffffff', fg='#a0aec0').pack(anchor='w', padx=8)
        for rem in completed:
            self._render_reminder_row(parent, rem, completed=True)

    def _format_interval(self, seconds):
        h = int(seconds) // 3600
        m = (int(seconds) % 3600) // 60
        s = int(seconds) % 60
        parts = []
        if h > 0:
            parts.append(f'{h}h')
        if m > 0:
            parts.append(f'{m}min')
        if s > 0:
            parts.append(f'{s}s')
        return ' '.join(parts) if parts else '0s'

    def _render_reminder_row(self, parent, rem, completed=False):
        is_normal = rem.get('remind_at', 0) == 0  # lembrete normal (sem data)
        is_recurring = rem.get('is_recurring', 0) == 1
        is_active = rem.get('is_active', 1) == 1
        is_overdue = not completed and not is_normal and not is_recurring and datetime.fromtimestamp(rem['remind_at']) < datetime.now()
        is_notified = rem.get('notified', 0) == 1
        if completed:
            bg = '#f0fdf4'
        elif is_recurring:
            bg = '#f0e6ff' if is_active else '#f3f4f6'
        elif is_overdue:
            bg = '#fef2f2'
        elif is_normal:
            bg = '#eff6ff'
        else:
            bg = '#f7fafc'
        fg_text = '#6b7280' if completed or (is_recurring and not is_active) else '#1a202c'
        if is_recurring:
            border_color = '#d8b4fe' if is_active else '#d1d5db'
        elif completed:
            border_color = '#bbf7d0'
        elif is_overdue:
            border_color = '#fecaca'
        elif is_normal:
            border_color = '#bfdbfe'
        else:
            border_color = '#e2e8f0'
        row = tk.Frame(parent, bg=bg, highlightthickness=1,
                       highlightbackground=border_color)
        row.pack(fill='x', pady=3, padx=2)
        # Botao check/toggle
        if is_recurring and not completed:
            # Toggle ativar/desativar para recorrentes
            toggle_txt = '\u25c9' if is_active else '\u25cb'
            toggle_fg = '#7c3aed' if is_active else '#9ca3af'
            toggle_btn = tk.Button(row, text=toggle_txt, font=('Segoe UI', 12),
                                   bg=bg, fg=toggle_fg, relief='flat', bd=0,
                                   cursor='hand2', width=2,
                                   command=lambda rid=rem['id'], p=parent: (
                                       self.messenger.db.toggle_reminder_active(rid),
                                       self._refresh_reminders_list(p)))
            toggle_btn.pack(side='left', padx=(4, 0))
            _add_hover(toggle_btn, bg, '#ede9fe')
        elif not completed:
            check_btn = tk.Button(row, text='\u25cb', font=('Segoe UI', 12),
                                  bg=bg, fg='#22c55e', relief='flat', bd=0,
                                  cursor='hand2', width=2,
                                  command=lambda rid=rem['id'], p=parent: (
                                      self.messenger.db.mark_reminder_completed(rid),
                                      self._refresh_reminders_list(p)))
            check_btn.pack(side='left', padx=(4, 0))
            _add_hover(check_btn, bg, '#dcfce7')
        else:
            tk.Label(row, text='\u2714', font=('Segoe UI', 11),
                     bg=bg, fg='#22c55e', width=2).pack(side='left', padx=(4, 0))
        # Texto e data
        info = tk.Frame(row, bg=bg)
        info.pack(side='left', fill='x', expand=True, padx=4, pady=6)
        text = rem.get('text', '')
        lbl_text = tk.Label(info, text=text, font=('Segoe UI', 10),
                            bg=bg, fg=fg_text, anchor='w', wraplength=250)
        if completed:
            lbl_text.configure(font=('Segoe UI', 10, 'overstrike'))
        lbl_text.pack(anchor='w')
        if is_recurring:
            status_str = 'Ativo' if is_active else 'Pausado'
            rule_json = rem.get('recurrence_rule', '') or ''
            if rule_json:
                import json as _json
                try:
                    _rule = _json.loads(rule_json)
                except Exception:
                    _rule = {}
                _pat_label = {'daily': 'dia(s)', 'weekly': 'semana(s)',
                              'monthly': 'mês(es)', 'yearly': 'ano(s)'}.get(
                    _rule.get('type', 'daily'), 'dia(s)')
                _n = int(_rule.get('interval', 1))
                _next = datetime.fromtimestamp(rem['remind_at']).strftime('%d/%m %H:%M')
                time_str = f'\U0001f504 A cada {_n} {_pat_label} — proximo {_next} — {status_str}'
            else:
                interval = rem.get('recurrence_interval_seconds', 0)
                interval_str = self._format_interval(interval)
                time_str = f'\U0001f504 A cada {interval_str} — {status_str}'
            fg_time = '#7c3aed' if is_active else '#9ca3af'
        elif is_normal:
            # Lembrete normal: mostra data de criacao
            created = datetime.fromtimestamp(rem.get('created_at', 0))
            time_str = '\U0001f4cc Criado em ' + created.strftime('%d/%m %H:%M')
            fg_time = '#718096'
        else:
            remind_at = datetime.fromtimestamp(rem['remind_at'])
            now = datetime.now()
            # Formato relativo amigavel
            if remind_at.date() == now.date():
                time_str = 'Hoje ' + remind_at.strftime('%H:%M')
            elif remind_at.date() == (now + timedelta(days=1)).date():
                time_str = 'Amanha ' + remind_at.strftime('%H:%M')
            else:
                time_str = remind_at.strftime('%d/%m/%Y %H:%M')
            # Se ja passou e nao concluido, destacar em vermelho
            fg_time = '#718096'
            if not completed and is_overdue:
                fg_time = '#ef4444'
                if is_notified:
                    time_str = '\U0001f514 ' + time_str + ' (notificado)'
                else:
                    time_str = '\u26a0 ' + time_str + ' (atrasado)'
        tk.Label(info, text=time_str, font=('Segoe UI', 8),
                 bg=bg, fg=fg_time, anchor='w').pack(anchor='w')
        # Botao X (deletar)
        del_btn = tk.Button(row, text='\u2715', font=('Segoe UI', 9),
                            bg=bg, fg='#ef4444', relief='flat', bd=0,
                            cursor='hand2', width=2,
                            command=lambda rid=rem['id'], p=parent: (
                                self.messenger.db.delete_reminder(rid),
                                self._refresh_reminders_list(p)))
        del_btn.pack(side='right', padx=(0, 4))
        _add_hover(del_btn, bg, '#fef2f2')

    # Dialogo simples para lembrete normal (sem data, so texto)
    def _new_simple_reminder_dialog(self, parent_win, list_frame):
        dlg = tk.Toplevel(parent_win)
        dlg.title('Lembrete Simples')
        dlg.transient(parent_win)
        dlg.grab_set()
        dlg.configure(bg='#ffffff')
        _center_window(dlg, 340, 180)
        _apply_rounded_corners(dlg)
        dlg.bind('<Escape>', lambda e: dlg.destroy())

        hdr = tk.Frame(dlg, bg='#0f2a5c')
        hdr.pack(fill='x')
        tk.Label(hdr, text='\U0001f4cc Lembrete Simples', font=('Segoe UI', 11, 'bold'),
                 bg='#0f2a5c', fg='#ffffff').pack(padx=12, pady=8, side='left')

        body = tk.Frame(dlg, bg='#ffffff')
        body.pack(fill='both', expand=True, padx=14, pady=10)

        tk.Label(body, text='Título:', font=('Segoe UI', 10, 'bold'),
                 bg='#ffffff', fg='#1a202c').pack(anchor='w')
        txt_entry = tk.Entry(body, font=('Segoe UI', 11), relief='flat',
                             bg='#f7fafc', highlightthickness=1,
                             highlightbackground='#cbd5e1')
        txt_entry.pack(fill='x', pady=(4, 12), ipady=4)
        txt_entry.focus_set()

        def _create():
            text = txt_entry.get().strip()
            if not text:
                return
            self.messenger.db.add_reminder(text, remind_at=0)
            self._refresh_reminders_list(list_frame)
            dlg.destroy()

        txt_entry.bind('<Return>', lambda e: _create())
        btn = tk.Button(body, text='Criar', font=('Segoe UI', 10, 'bold'),
                        bg='#2563eb', fg='#ffffff', relief='flat', bd=0,
                        padx=20, pady=6, cursor='hand2', command=_create)
        btn.pack()
        _add_hover(btn, '#2563eb', '#1d4ed8')

    # Helper reusavel: cria um campo de data com popup de calendario.
    # Retorna um dict com 'frame', 'get_date', 'set_date'.
    def _create_date_picker(self, parent, initial_date=None):
        import calendar as cal_mod
        if initial_date is None:
            initial_date = datetime.now()
        state = {'date': initial_date}
        frame = tk.Frame(parent, bg='#ffffff')
        entry_var = tk.StringVar(value=initial_date.strftime('%d/%m/%Y'))
        entry = tk.Entry(frame, textvariable=entry_var, width=12,
                          font=('Segoe UI', 10), relief='flat', bg='#f7fafc',
                          justify='center', state='readonly', readonlybackground='#f7fafc',
                          highlightthickness=1, highlightbackground='#cbd5e1')
        entry.pack(side='left', ipady=3)

        popup_ref = {'win': None}

        def _open_popup():
            if popup_ref['win'] is not None:
                try:
                    popup_ref['win'].destroy()
                except Exception:
                    pass
                popup_ref['win'] = None
                return
            top = tk.Toplevel(parent)
            popup_ref['win'] = top
            top.overrideredirect(True)
            top.configure(bg='#ffffff', highlightthickness=1,
                          highlightbackground='#cbd5e1')

            cur = state['date']
            cal_state = [cur.year, cur.month]
            sel = [cur.year, cur.month, cur.day]

            MONTH_NAMES = ['', 'Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio',
                           'Junho', 'Julho', 'Agosto', 'Setembro', 'Outubro',
                           'Novembro', 'Dezembro']

            nav = tk.Frame(top, bg='#ffffff')
            nav.pack(fill='x', padx=6, pady=(6, 2))
            month_label = tk.Label(nav, font=('Segoe UI', 10, 'bold'),
                                    bg='#ffffff', fg='#1a202c')
            tk.Button(nav, text='\u25c0', font=('Segoe UI', 9), bg='#ffffff',
                      fg='#64748b', relief='flat', bd=0, cursor='hand2',
                      command=lambda: _nav(-1)).pack(side='left')
            month_label.pack(side='left', expand=True)
            tk.Button(nav, text='\u25b6', font=('Segoe UI', 9), bg='#ffffff',
                      fg='#64748b', relief='flat', bd=0, cursor='hand2',
                      command=lambda: _nav(1)).pack(side='right')

            grid = tk.Frame(top, bg='#ffffff')
            grid.pack(padx=6, pady=(0, 4))
            for i, d in enumerate(['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom']):
                fg = '#ef4444' if i >= 5 else '#64748b'
                tk.Label(grid, text=d, font=('Segoe UI', 8), width=4,
                          bg='#ffffff', fg=fg).grid(row=0, column=i)
            day_btns = []
            for r in range(6):
                row = []
                for c in range(7):
                    b = tk.Button(grid, text='', font=('Segoe UI', 9),
                                   width=3, relief='flat', bd=0, bg='#ffffff',
                                   fg='#1a202c', cursor='hand2',
                                   command=lambda rr=r, cc=c: _pick(rr, cc))
                    b.grid(row=r + 1, column=c, pady=1)
                    row.append(b)
                day_btns.append(row)

            def _nav(delta):
                cal_state[1] += delta
                if cal_state[1] > 12:
                    cal_state[1] = 1
                    cal_state[0] += 1
                elif cal_state[1] < 1:
                    cal_state[1] = 12
                    cal_state[0] -= 1
                _refresh()

            def _pick(r, c):
                txt = day_btns[r][c].cget('text')
                if not txt:
                    return
                sel[0] = cal_state[0]
                sel[1] = cal_state[1]
                sel[2] = int(txt)
                new_date = datetime(sel[0], sel[1], sel[2])
                state['date'] = new_date
                entry_var.set(new_date.strftime('%d/%m/%Y'))
                try:
                    top.destroy()
                except Exception:
                    pass
                popup_ref['win'] = None

            def _refresh():
                month_label.config(text=f'{MONTH_NAMES[cal_state[1]]} {cal_state[0]}')
                first_weekday, days_in = cal_mod.monthrange(cal_state[0], cal_state[1])
                today = datetime.now()
                for r in range(6):
                    for c in range(7):
                        day_num = r * 7 + c - first_weekday + 1
                        b = day_btns[r][c]
                        if 1 <= day_num <= days_in:
                            b.config(text=str(day_num), state='normal')
                            is_sel = (day_num == sel[2] and cal_state[1] == sel[1]
                                       and cal_state[0] == sel[0])
                            is_today = (day_num == today.day
                                         and cal_state[1] == today.month
                                         and cal_state[0] == today.year)
                            if is_sel:
                                b.config(bg='#7c3aed', fg='#ffffff')
                            elif is_today:
                                b.config(bg='#e0e7ff', fg='#1e40af')
                            else:
                                fg = '#ef4444' if c >= 5 else '#1a202c'
                                b.config(bg='#ffffff', fg=fg)
                        else:
                            b.config(text='', state='disabled', bg='#ffffff',
                                      disabledforeground='#ffffff')

            def _today():
                t = datetime.now()
                sel[0], sel[1], sel[2] = t.year, t.month, t.day
                cal_state[0], cal_state[1] = t.year, t.month
                state['date'] = t
                entry_var.set(t.strftime('%d/%m/%Y'))
                _refresh()

            btn_today = tk.Button(top, text='Hoje', font=('Segoe UI', 9),
                                   bg='#f1f5f9', fg='#374151', relief='flat',
                                   bd=0, padx=10, pady=3, cursor='hand2',
                                   command=_today)
            btn_today.pack(pady=(0, 6))
            _refresh()

            # Posicionamento com flip-up se nao couber embaixo
            top.update_idletasks()
            pw = top.winfo_reqwidth()
            ph = top.winfo_reqheight()
            sh = top.winfo_screenheight()
            sw = top.winfo_screenwidth()
            ex = entry.winfo_rootx()
            ey = entry.winfo_rooty()
            eh = entry.winfo_height()
            y_down = ey + eh + 2
            if y_down + ph > sh - 10:
                y = ey - ph - 2
                if y < 10:
                    y = max(10, sh - ph - 10)
            else:
                y = y_down
            x = ex
            if x + pw > sw - 10:
                x = max(10, sw - pw - 10)
            top.geometry(f'+{x}+{y}')

            def _close_on_focus(e):
                try:
                    if top.focus_get() is None or str(top.focus_get()).startswith(str(top)) is False:
                        top.destroy()
                        popup_ref['win'] = None
                except Exception:
                    pass
            top.bind('<FocusOut>', _close_on_focus)
            top.focus_set()

        drop_btn = tk.Button(frame, text='\u25bc', font=('Segoe UI', 9),
                              bg='#f7fafc', fg='#374151', relief='flat', bd=0,
                              padx=6, cursor='hand2', command=_open_popup,
                              highlightthickness=1, highlightbackground='#cbd5e1')
        drop_btn.pack(side='left', padx=(2, 0), ipady=2)

        return {
            'frame': frame,
            'get_date': lambda: state['date'],
            'set_date': lambda d: (state.__setitem__('date', d),
                                     entry_var.set(d.strftime('%d/%m/%Y'))),
        }

    # Dialogo para criar lembrete recorrente (padrao diario/semanal/mensal/anual)
    def _new_recurring_reminder_dialog(self, parent_win, list_frame):
        import json as _json
        dlg = tk.Toplevel(parent_win)
        dlg.title('Lembrete Recorrente')
        dlg.transient(parent_win)
        dlg.grab_set()
        dlg.configure(bg='#ffffff')
        _center_window(dlg, 560, 500)
        _apply_rounded_corners(dlg)
        dlg.bind('<Escape>', lambda e: dlg.destroy())

        hdr = tk.Frame(dlg, bg='#7c3aed')
        hdr.pack(fill='x')
        tk.Label(hdr, text='\U0001f504 Lembrete Recorrente',
                 font=('Segoe UI', 12, 'bold'),
                 bg='#7c3aed', fg='#ffffff').pack(padx=14, pady=10, side='left')

        # Botoes fixos no rodape (packed primeiro com side='bottom' para ficarem sempre visiveis)
        btn_row = tk.Frame(dlg, bg='#ffffff')
        btn_row.pack(side='bottom', fill='x', padx=16, pady=(0, 14))

        body = tk.Frame(dlg, bg='#ffffff')
        body.pack(fill='both', expand=True, padx=16, pady=(12, 6))

        now = datetime.now()

        # Linha 1: Titulo + Horario (lado a lado, Horario proximo)
        row1 = tk.Frame(body, bg='#ffffff')
        row1.pack(fill='x', pady=(0, 10))

        col_title = tk.Frame(row1, bg='#ffffff')
        col_title.pack(side='left', fill='x', expand=True)
        tk.Label(col_title, text='Título', font=('Segoe UI', 9, 'bold'),
                 bg='#ffffff', fg='#374151').pack(anchor='w')
        txt_entry = tk.Entry(col_title, font=('Segoe UI', 11), relief='flat',
                             bg='#f7fafc', highlightthickness=1,
                             highlightbackground='#cbd5e1',
                             highlightcolor='#7c3aed', width=28)
        txt_entry.pack(anchor='w', pady=(3, 0), ipady=5, fill='x', expand=False)
        txt_entry.focus_set()

        col_time = tk.Frame(row1, bg='#ffffff')
        col_time.pack(side='left', padx=(16, 0), anchor='n')
        tk.Label(col_time, text='Horário', font=('Segoe UI', 9, 'bold'),
                 bg='#ffffff', fg='#374151').pack(anchor='center')
        time_row = tk.Frame(col_time, bg='#ffffff')
        time_row.pack(anchor='center', pady=(3, 0))
        h_var = tk.StringVar(value=f'{now.hour:02d}')
        m_var = tk.StringVar(value=f'{now.minute:02d}')
        hs = tk.Spinbox(time_row, from_=0, to=23, textvariable=h_var,
                        width=3, font=('Segoe UI', 13, 'bold'), format='%02.0f',
                        relief='flat', bg='#f7fafc', justify='center',
                        highlightthickness=1, highlightbackground='#cbd5e1')
        hs.pack(side='left', ipady=2)
        tk.Label(time_row, text=':', font=('Segoe UI', 14, 'bold'),
                 bg='#ffffff', fg='#374151').pack(side='left', padx=5)
        ms = tk.Spinbox(time_row, from_=0, to=59, textvariable=m_var,
                        width=3, font=('Segoe UI', 13, 'bold'), format='%02.0f',
                        relief='flat', bg='#f7fafc', justify='center',
                        highlightthickness=1, highlightbackground='#cbd5e1',
                        increment=1)
        ms.pack(side='left', ipady=2)

        # Linha 2: Padrao + A cada N (lado a lado)
        tk.Label(body, text='Padrão', font=('Segoe UI', 9, 'bold'),
                 bg='#ffffff', fg='#374151').pack(anchor='w')
        row2 = tk.Frame(body, bg='#ffffff')
        row2.pack(fill='x', pady=(3, 8))

        pat_var = tk.StringVar(value='daily')
        pat_col = tk.Frame(row2, bg='#ffffff')
        pat_col.pack(side='left')
        for label, val in [('Diário', 'daily'), ('Semanal', 'weekly'),
                            ('Mensal', 'monthly'), ('Anual', 'yearly')]:
            tk.Radiobutton(pat_col, text=label, variable=pat_var, value=val,
                           font=('Segoe UI', 10), bg='#ffffff',
                           activebackground='#ffffff',
                           command=lambda: _refresh_pattern()).pack(side='left', padx=(0, 8))

        int_row = tk.Frame(row2, bg='#ffffff')
        int_row.pack(side='left', padx=(14, 0))
        tk.Label(int_row, text='A cada', font=('Segoe UI', 10),
                 bg='#ffffff', fg='#374151').pack(side='left')
        interval_var = tk.StringVar(value='1')
        int_spin = tk.Spinbox(int_row, from_=1, to=99, textvariable=interval_var,
                              width=3, font=('Segoe UI', 10), justify='center',
                              relief='flat', bg='#f7fafc',
                              highlightthickness=1, highlightbackground='#cbd5e1')
        int_spin.pack(side='left', padx=6)
        unit_lbl = tk.Label(int_row, text='dia(s)', font=('Segoe UI', 10),
                            bg='#ffffff', fg='#374151')
        unit_lbl.pack(side='left')

        # Dias da semana (so aparece em "weekly")
        wd_label = tk.Label(body, text='Dias da semana', font=('Segoe UI', 9, 'bold'),
                            bg='#ffffff', fg='#374151')
        wd_frame = tk.Frame(body, bg='#ffffff')
        WEEK_LABELS = [('Seg', 0), ('Ter', 1), ('Qua', 2), ('Qui', 3),
                        ('Sex', 4), ('Sáb', 5), ('Dom', 6)]
        wd_vars = {}
        for label, idx in WEEK_LABELS:
            v = tk.BooleanVar(value=(idx == now.weekday()))
            wd_vars[idx] = v
            tk.Checkbutton(wd_frame, text=label, variable=v,
                           font=('Segoe UI', 9), bg='#ffffff',
                           activebackground='#ffffff').pack(side='left', padx=(0, 2))

        # Separador
        sep = tk.Frame(body, bg='#e2e8f0', height=1)
        sep.pack(fill='x', pady=6)

        # Linha 3: Comeca em + Termino (lado a lado, mesma linha)
        row3 = tk.Frame(body, bg='#ffffff')
        row3.pack(fill='x', pady=(0, 4))

        col_start = tk.Frame(row3, bg='#ffffff')
        col_start.pack(side='left', anchor='n')
        tk.Label(col_start, text='Começa em', font=('Segoe UI', 9, 'bold'),
                 bg='#ffffff', fg='#374151').pack(anchor='w')
        start_picker = self._create_date_picker(col_start, now)
        start_picker['frame'].pack(anchor='w', pady=(3, 0))

        col_end = tk.Frame(row3, bg='#ffffff')
        col_end.pack(side='left', anchor='n', padx=(20, 0), fill='x', expand=True)
        tk.Label(col_end, text='Término', font=('Segoe UI', 9, 'bold'),
                 bg='#ffffff', fg='#374151').pack(anchor='w')
        end_var = tk.StringVar(value='never')
        end_frame = tk.Frame(col_end, bg='#ffffff')
        end_frame.pack(anchor='w', pady=(3, 0), fill='x')

        def _refresh_pattern():
            p = pat_var.get()
            unit_lbl.config(text={'daily': 'dia(s)', 'weekly': 'semana(s)',
                                   'monthly': 'mês(es)', 'yearly': 'ano(s)'}[p])
            if p == 'weekly':
                wd_label.pack(anchor='w', pady=(2, 2), before=sep)
                wd_frame.pack(anchor='w', pady=(0, 6), before=sep)
            else:
                wd_label.pack_forget()
                wd_frame.pack_forget()

        _refresh_pattern()

        tk.Radiobutton(end_frame, text='Sem data de término',
                       variable=end_var, value='never',
                       font=('Segoe UI', 9), bg='#ffffff',
                       activebackground='#ffffff').grid(row=0, column=0, sticky='w', columnspan=2, pady=0)

        tk.Radiobutton(end_frame, text='Após',
                       variable=end_var, value='count',
                       font=('Segoe UI', 9), bg='#ffffff',
                       activebackground='#ffffff').grid(row=1, column=0, sticky='w', pady=0)
        count_row = tk.Frame(end_frame, bg='#ffffff')
        count_row.grid(row=1, column=1, sticky='w', padx=(4, 0))
        count_var = tk.StringVar(value='10')
        tk.Spinbox(count_row, from_=1, to=999, textvariable=count_var,
                   width=4, font=('Segoe UI', 9), justify='center',
                   relief='flat', bg='#f7fafc',
                   highlightthickness=1, highlightbackground='#cbd5e1').pack(side='left')
        tk.Label(count_row, text='ocorrências', font=('Segoe UI', 9),
                 bg='#ffffff', fg='#374151').pack(side='left', padx=(4, 0))

        tk.Radiobutton(end_frame, text='Em',
                       variable=end_var, value='date',
                       font=('Segoe UI', 9), bg='#ffffff',
                       activebackground='#ffffff').grid(row=2, column=0, sticky='w', pady=0)
        end_picker = self._create_date_picker(end_frame, now + timedelta(days=60))
        end_picker['frame'].grid(row=2, column=1, padx=(4, 0), sticky='w')

        lbl_err = tk.Label(body, text='', font=('Segoe UI', 8),
                           bg='#ffffff', fg='#ef4444')
        lbl_err.pack(anchor='w', pady=(6, 0))

        def _create():
            text = txt_entry.get().strip()
            if not text:
                lbl_err.config(text='Digite um título')
                return
            try:
                h = int(h_var.get())
                m = int(m_var.get())
                interval = int(interval_var.get())
            except ValueError:
                lbl_err.config(text='Valores inválidos')
                return
            if not (0 <= h <= 23 and 0 <= m <= 59) or interval < 1:
                lbl_err.config(text='Valores inválidos')
                return
            pat = pat_var.get()
            rule = {'type': pat, 'interval': interval, 'occurrences_done': 0}
            if pat == 'weekly':
                selected = [i for i, v in wd_vars.items() if v.get()]
                if not selected:
                    lbl_err.config(text='Escolha pelo menos um dia da semana')
                    return
                rule['weekdays'] = selected
            end_kind = end_var.get()
            if end_kind == 'never':
                rule['end'] = {'kind': 'never'}
            elif end_kind == 'count':
                try:
                    n = int(count_var.get())
                    if n < 1:
                        raise ValueError
                except ValueError:
                    lbl_err.config(text='Número de ocorrências inválido')
                    return
                rule['end'] = {'kind': 'count', 'count': n}
            else:
                ed = end_picker['get_date']()
                rule['end'] = {'kind': 'date',
                                'date': ed.replace(hour=23, minute=59).timestamp()}

            # Primeira ocorrencia: a partir da data escolhida em "Começa em"
            start_base = start_picker['get_date']()
            start = start_base.replace(hour=h, minute=m, second=0, microsecond=0)
            now_local = datetime.now()
            # Grace period de 60s: se o usuario clicou Criar poucos segundos
            # apos a hora marcada, ainda dispara hoje; so empurra pra amanha
            # se ja passou mais de 1 minuto
            if start <= now_local - timedelta(seconds=60):
                start += timedelta(days=1)
            if pat == 'weekly':
                weekdays = rule['weekdays']
                for _ in range(8):
                    if start.weekday() in weekdays:
                        break
                    start += timedelta(days=1)
            self.messenger.db.add_pattern_reminder(text, start.timestamp(),
                                                    _json.dumps(rule))
            self._refresh_reminders_list(list_frame)
            dlg.destroy()

        btn_cancel = tk.Button(btn_row, text='Cancelar', font=('Segoe UI', 10),
                               bg='#e5e7eb', fg='#374151', relief='flat', bd=0,
                               padx=16, pady=6, cursor='hand2',
                               command=dlg.destroy)
        btn_cancel.pack(side='right', padx=(6, 0))
        _add_hover(btn_cancel, '#e5e7eb', '#d1d5db')
        btn_ok = tk.Button(btn_row, text='Criar lembrete',
                           font=('Segoe UI', 10, 'bold'),
                           bg='#7c3aed', fg='#ffffff', relief='flat', bd=0,
                           padx=18, pady=6, cursor='hand2', command=_create)
        btn_ok.pack(side='right')
        _add_hover(btn_ok, '#7c3aed', '#6d28d9')

    # Dialogo para criar novo lembrete com calendario e campos de tempo
    def _new_reminder_dialog(self, parent_win, list_frame):
        dlg = tk.Toplevel(parent_win)
        dlg.title('Novo Lembrete')
        dlg.transient(parent_win)
        dlg.grab_set()
        dlg.configure(bg='#ffffff')
        _center_window(dlg, 360, 480)
        _apply_rounded_corners(dlg)
        dlg.bind('<Escape>', lambda e: dlg.destroy())

        # Header
        hdr = tk.Frame(dlg, bg='#0f2a5c')
        hdr.pack(fill='x')
        tk.Label(hdr, text='\u23f0 Novo Lembrete', font=('Segoe UI', 11, 'bold'),
                 bg='#0f2a5c', fg='#ffffff').pack(padx=12, pady=8, side='left')

        body = tk.Frame(dlg, bg='#ffffff')
        body.pack(fill='both', expand=True, padx=14, pady=10)

        tk.Label(body, text='Título:', font=('Segoe UI', 10, 'bold'),
                 bg='#ffffff', fg='#1a202c').pack(anchor='w', pady=(0, 4))
        txt_entry = tk.Entry(body, font=('Segoe UI', 10), relief='flat',
                              bg='#f7fafc', highlightthickness=1,
                              highlightbackground='#cbd5e1')
        txt_entry.pack(fill='x')
        txt_entry.focus_set()

        # Atalhos rapidos
        tk.Label(body, text='Atalhos:', font=('Segoe UI', 10, 'bold'),
                 bg='#ffffff', fg='#1a202c').pack(anchor='w', pady=(10, 4))
        quick_frame = tk.Frame(body, bg='#ffffff')
        quick_frame.pack(fill='x', pady=(0, 6))
        now = datetime.now()  # hora atual ao abrir o dialogo
        # Estado do calendario e hora selecionada
        sel_date = [now.year, now.month, now.day]
        sel_hour = [now.hour]
        sel_min = [now.minute]

        def _set_quick(minutes=0, days=0, hour=9, minute=0):
            fresh_now = datetime.now()  # hora fresca ao clicar
            if minutes:
                target = fresh_now + timedelta(minutes=minutes)
            elif days:
                target = fresh_now.replace(hour=hour, minute=minute, second=0) + timedelta(days=days)
            else:
                return
            sel_date[0], sel_date[1], sel_date[2] = target.year, target.month, target.day
            sel_hour[0] = target.hour
            sel_min[0] = target.minute
            _refresh_cal()
            hour_spin.delete(0, 'end')
            hour_spin.insert(0, f'{target.hour:02d}')
            min_spin.delete(0, 'end')
            min_spin.insert(0, f'{target.minute:02d}')

        for label, kw in [('15 min', dict(minutes=15)), ('30 min', dict(minutes=30)),
                           ('1h', dict(minutes=60)), ('2h', dict(minutes=120)),
                           ('Amanhã', dict(days=1)), ('3 dias', dict(days=3))]:
            qb = tk.Button(quick_frame, text=label, font=('Segoe UI', 8),
                           relief='flat', bd=0, bg='#eef2ff', fg='#3730a3',
                           padx=8, pady=2, cursor='hand2',
                           command=lambda k=kw: _set_quick(**k))
            qb.pack(side='left', padx=(0, 4))
            _add_hover(qb, '#eef2ff', '#c7d2fe')

        # Separador
        tk.Frame(body, bg='#e2e8f0', height=1).pack(fill='x', pady=8)

        # Calendario
        tk.Label(body, text='Data e Hora:', font=('Segoe UI', 10, 'bold'),
                 bg='#ffffff', fg='#1a202c').pack(anchor='w', pady=(0, 4))

        cal_state = [now.year, now.month]  # ano, mes exibido no calendario

        cal_frame = tk.Frame(body, bg='#ffffff')
        cal_frame.pack(fill='x')

        # Nav do calendario: < Mes Ano >
        nav = tk.Frame(cal_frame, bg='#ffffff')
        nav.pack(fill='x')
        month_label = tk.Label(nav, font=('Segoe UI', 10, 'bold'),
                               bg='#ffffff', fg='#1a202c')
        MONTH_NAMES = ['', 'Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho',
                       'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro']
        btn_prev = tk.Button(nav, text='\u25c0', font=('Segoe UI', 9),
                             bg='#ffffff', fg='#64748b', relief='flat', bd=0,
                             cursor='hand2', command=lambda: _nav_month(-1))
        btn_prev.pack(side='left')
        month_label.pack(side='left', expand=True)
        btn_next = tk.Button(nav, text='\u25b6', font=('Segoe UI', 9),
                             bg='#ffffff', fg='#64748b', relief='flat', bd=0,
                             cursor='hand2', command=lambda: _nav_month(1))
        btn_next.pack(side='right')

        # Grid de dias
        grid_frame = tk.Frame(cal_frame, bg='#ffffff')
        grid_frame.pack(fill='x', pady=(2, 0))
        # Cabecalho dias da semana
        for i, d in enumerate(['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom']):
            fg = '#ef4444' if i >= 5 else '#64748b'
            tk.Label(grid_frame, text=d, font=('Segoe UI', 8), width=4,
                     bg='#ffffff', fg=fg).grid(row=0, column=i)
        day_buttons = []
        for r in range(6):
            row_btns = []
            for c in range(7):
                b = tk.Button(grid_frame, text='', font=('Segoe UI', 9),
                              width=3, relief='flat', bd=0, bg='#ffffff',
                              fg='#1a202c', cursor='hand2',
                              command=lambda rr=r, cc=c: _select_day(rr, cc))
                b.grid(row=r + 1, column=c, pady=1)
                row_btns.append(b)
            day_buttons.append(row_btns)

        def _nav_month(delta):
            cal_state[1] += delta
            if cal_state[1] > 12:
                cal_state[1] = 1
                cal_state[0] += 1
            elif cal_state[1] < 1:
                cal_state[1] = 12
                cal_state[0] -= 1
            _refresh_cal()

        def _select_day(r, c):
            txt = day_buttons[r][c].cget('text')
            if not txt:
                return
            sel_date[2] = int(txt)
            sel_date[0] = cal_state[0]
            sel_date[1] = cal_state[1]
            _refresh_cal()

        def _refresh_cal():
            month_label.config(text=f'{MONTH_NAMES[cal_state[1]]} {cal_state[0]}')
            first_weekday, days_in = cal_mod.monthrange(cal_state[0], cal_state[1])
            today = datetime.now()
            for r in range(6):
                for c in range(7):
                    day_num = r * 7 + c - first_weekday + 1
                    b = day_buttons[r][c]
                    if 1 <= day_num <= days_in:
                        b.config(text=str(day_num), state='normal')
                        is_selected = (day_num == sel_date[2] and
                                       cal_state[1] == sel_date[1] and
                                       cal_state[0] == sel_date[0])
                        is_today = (day_num == today.day and
                                    cal_state[1] == today.month and
                                    cal_state[0] == today.year)
                        if is_selected:
                            b.config(bg='#0f2a5c', fg='#ffffff')
                        elif is_today:
                            b.config(bg='#e0e7ff', fg='#1e40af')
                        else:
                            fg = '#ef4444' if c >= 5 else '#1a202c'
                            b.config(bg='#ffffff', fg=fg)
                    else:
                        b.config(text='', state='disabled', bg='#ffffff',
                                 disabledforeground='#ffffff')

        _refresh_cal()

        # Hora: HH : MM spinboxes
        time_frame = tk.Frame(body, bg='#ffffff')
        time_frame.pack(fill='x', pady=(8, 0))
        tk.Label(time_frame, text='Hora:', font=('Segoe UI', 10),
                 bg='#ffffff', fg='#1a202c').pack(side='left')
        hour_spin = tk.Spinbox(time_frame, from_=0, to=23, width=3, wrap=True,
                                font=('Segoe UI', 11), format='%02.0f',
                                relief='flat', bg='#f7fafc',
                                highlightthickness=1, highlightbackground='#cbd5e1',
                                justify='center')
        hour_spin.pack(side='left', padx=(8, 0))
        default_time = now + timedelta(minutes=5)
        hour_spin.delete(0, 'end')
        hour_spin.insert(0, f'{default_time.hour:02d}')
        tk.Label(time_frame, text=':', font=('Segoe UI', 11, 'bold'),
                 bg='#ffffff', fg='#1a202c').pack(side='left', padx=2)
        min_spin = tk.Spinbox(time_frame, from_=0, to=59, width=3, wrap=True,
                               font=('Segoe UI', 11), format='%02.0f',
                               relief='flat', bg='#f7fafc',
                               highlightthickness=1, highlightbackground='#cbd5e1',
                               justify='center', increment=1)
        min_spin.pack(side='left')
        min_spin.delete(0, 'end')
        min_spin.insert(0, f'{default_time.minute:02d}')

        def _create():
            text = txt_entry.get().strip()
            if not text:
                messagebox.showwarning('Lembrete', 'Insira o texto do lembrete.',
                                        parent=dlg)
                return
            try:
                h = int(hour_spin.get())
                m = int(min_spin.get())
                dt = datetime(sel_date[0], sel_date[1], sel_date[2], h, m)
                remind_at = dt.timestamp()
            except (ValueError, OverflowError):
                messagebox.showwarning('Lembrete', 'Data/hora invalida.',
                                        parent=dlg)
                return
            self.messenger.db.add_reminder(text, remind_at)
            dlg.destroy()
            self._refresh_reminders_list(list_frame)

        btn_frame = tk.Frame(dlg, bg='#ffffff')
        btn_frame.pack(fill='x', padx=14, pady=(0, 12))
        btn_criar = tk.Button(btn_frame, text='Criar', font=('Segoe UI', 10, 'bold'),
                  bg='#0f2a5c', fg='#ffffff', relief='flat', bd=0,
                  padx=20, pady=5, cursor='hand2',
                  command=_create)
        btn_criar.pack(side='right')
        _add_hover(btn_criar, '#0f2a5c', '#1a3f7a')
        btn_cancel = tk.Button(btn_frame, text='Cancelar', font=('Segoe UI', 9),
                  bg='#e2e8f0', fg='#4a5568', relief='flat', bd=0,
                  padx=14, pady=5, cursor='hand2',
                  command=dlg.destroy)
        btn_cancel.pack(side='right', padx=(0, 6))
        _add_hover(btn_cancel, '#e2e8f0', '#cbd5e1')

    # Verificacao manual via menu Ferramentas.
    def _manual_check_update(self):
        def _on_result(has_update, ver):
            if has_update:
                self.root.after(0, lambda: self._show_update_bar(ver))
            else:
                self.root.after(0, lambda: messagebox.showinfo(
                    APP_NAME, _t('update_none')))
        updater.check_update_async(_on_result)

    # Mostra barra amarela no topo da lista de contatos com botao Atualizar.
    def _show_update_bar(self, version):
        if hasattr(self, '_update_bar') and self._update_bar.winfo_exists():
            return  # ja esta visivel
        bar = tk.Frame(self.root, bg='#fff3cd', bd=0)
        bar.pack(fill='x', before=self.root.winfo_children()[1] if len(self.root.winfo_children()) > 1 else None)
        self._update_bar = bar
        tk.Label(bar, text=_t('update_available').format(ver=version),
                 font=('Segoe UI', 9), bg='#fff3cd', fg='#856404'
                 ).pack(side='left', padx=(10, 5), pady=4)
        btn = tk.Button(bar, text=_t('update_btn'), font=('Segoe UI', 9, 'bold'),
                        bg='#28a745', fg='white', bd=0, padx=10, cursor='hand2',
                        command=lambda: self._do_update(version))
        btn.pack(side='right', padx=(0, 10), pady=4)
        tk.Button(bar, text='\u2715', font=('Segoe UI', 9), bg='#fff3cd',
                  fg='#856404', bd=0, cursor='hand2',
                  command=bar.destroy).pack(side='right', padx=(0, 4), pady=4)

    # Executa o download e apply do update.
    def _do_update(self, version):
        if hasattr(self, '_update_bar') and self._update_bar.winfo_exists():
            for w in self._update_bar.winfo_children():
                w.destroy()
            tk.Label(self._update_bar, text=_t('update_downloading'),
                     font=('Segoe UI', 9), bg='#fff3cd', fg='#856404'
                     ).pack(side='left', padx=10, pady=4)
        def _download():
            path = updater.download_update()
            if path:
                self.root.after(0, lambda: self._apply_and_restart(path))
            else:
                self.root.after(0, lambda: messagebox.showerror(
                    APP_NAME, _t('update_failed')))
                if hasattr(self, '_update_bar') and self._update_bar.winfo_exists():
                    self.root.after(0, self._update_bar.destroy)
        threading.Thread(target=_download, daemon=True).start()

    # Aplica o update e encerra o app. Batch reabre via explorer.exe.
    def _apply_and_restart(self, new_exe_path):
        updater.apply_update(new_exe_path)
        os._exit(0)

    # Exibe dialog 'Sobre o MB Chat' com informacoes do aplicativo.
    def _show_about(self):
        messagebox.showinfo(f'Sobre o {APP_NAME}',  # titulo da caixa de dialogo
            f'{APP_NAME} v{APP_VERSION}\n\n'
            'Mensageiro de rede local\n\n'
            'Funcionalidades:\n'
            '- Descoberta automática de rede\n'
            '- Mensagens instantâneas\n'
            '- Transferência de arquivos\n'
            '- Histórico (SQLite)\n'
            '- Auto-start com o sistema\n\n'
            'Python + tkinter')

    # --- Network callbacks ---
    # Callback: novo peer descoberto ou peer existente atualizou presenca via UDP.
    #
    # Se for um peer realmente novo (nao estava na lista), toca som de conexao.
    # Adiciona ou atualiza o contato no TreeView via _add_contact().
    def _on_user_found(self, uid, info):
        is_new = uid not in self.peer_items  # e um contato novo (nao estava na lista)?
        self._add_contact(uid, info)          # adiciona/atualiza no TreeView e peer_info
        if is_new:
            SoundPlayer.play_connect()

    # Callback: peer saiu da rede (timeout no UDP discovery).
    #
    # Move o contato para a secao Offline no TreeView via _remove_contact().
    def _on_user_lost(self, uid, info):
        self._remove_contact(uid)  # move para secao Offline no TreeView

    def _on_peer_status(self, uid, new_status):
        if uid in self.peer_info:
            self.peer_info[uid]['status'] = new_status
            self._add_contact(uid, self.peer_info[uid])

    # Callback: mensagem individual recebida via TCP.
    #
    # Se a janela de chat esta aberta: entrega a mensagem diretamente.
    # - Se nao esta em foco: mostra toast + pisca as janelas.
    # Se a janela NAO esta aberta: marca contato como nao lido (bold + contagem),
    # mostra toast de notificacao, pisca taskbar e toca o bell do sistema.
    def _on_message(self, from_user, content, msg_id, timestamp,
                    reply_to='', is_broadcast=False, **kw):
        if is_broadcast:
            SoundPlayer.play_msg_broadcast()
        else:
            SoundPlayer.play_msg_private()
        if from_user in self.chat_windows:
            cw = self.chat_windows[from_user]
            cw.receive_message(content, timestamp, reply_to=reply_to,
                               msg_id=msg_id)
            try:
                if not cw.focus_displayof():
                    self._show_toast(from_user, content, is_broadcast=is_broadcast)
                    self._pending_flash_target = from_user
                    self._flash_window(cw)
            except Exception:
                pass
        else:
            self._mark_unread(from_user)
            self._show_toast(from_user, content, is_broadcast=is_broadcast)
            self._pending_flash_target = from_user
            # _open_chat carrega mensagens nao lidas do DB (inclui esta recem-salva
            # por messenger._on_tcp_message). NAO chamar receive_message aqui — dup.
            def _create():
                return self._open_chat(from_user, surface_only=True)
            self._surface_chat_from_tray(_create)

    # Callback: imagem recebida via TCP (MT_IMAGE).
    def _on_image(self, from_user, image_path, msg_id, timestamp,
                  group_id=None, display_name=None):
        if group_id:
            SoundPlayer.play_msg_group()
            # Imagem de grupo
            if group_id in self.group_windows:
                gw = self.group_windows[group_id]
                gw.receive_image(display_name or from_user, image_path, timestamp)
                try:
                    if not gw.focus_displayof():
                        self._show_group_toast(group_id, display_name or from_user, '[Imagem]')
                        self._pending_flash_target = f'group:{group_id}'
                        self._flash_window(gw)
                except Exception:
                    pass
            else:
                self._mark_group_unread(group_id)
                self._show_group_toast(group_id, display_name or from_user, '[Imagem]')
                self._pending_flash_target = f'group:{group_id}'
                def _create():
                    gw = self._open_group(group_id, surface_only=True)
                    if gw:
                        gw.receive_image(display_name or from_user, image_path, timestamp)
                    return gw
                self._surface_chat_from_tray(_create)
        else:
            SoundPlayer.play_msg_private()
            # Imagem individual
            if from_user in self.chat_windows:
                cw = self.chat_windows[from_user]
                cw.receive_image(image_path, timestamp)
                try:
                    if not cw.focus_displayof():
                        self._show_toast(from_user, '[Imagem]')
                        self._pending_flash_target = from_user
                        self._flash_window(cw)
                except Exception:
                    pass
            else:
                self._mark_unread(from_user)
                self._show_toast(from_user, '[Imagem]')
                self._pending_flash_target = from_user
                # _open_chat ja carrega imagens nao lidas do DB — ver _on_message.
                def _create():
                    return self._open_chat(from_user, surface_only=True)
                self._surface_chat_from_tray(_create)

    # Callback: enquete recebida ou voto atualizado (MT_POLL_CREATE / MT_POLL_VOTE)
    def _on_poll(self, group_id, poll_data):
        action = poll_data.get('action')
        if group_id in self.group_windows:
            gw = self.group_windows[group_id]
            if action == 'create':
                gw._display_poll(poll_data['question'], poll_data['options'],
                                 poll_data.get('creator', ''), poll_data['poll_id'])
            elif action == 'vote':
                # Atualiza a UI do poll em tempo real (barras de progresso)
                gw._refresh_poll_ui(poll_data['poll_id'])
        else:
            # Janela nao aberta: acumula como mensagem pendente
            if action == 'create':
                if group_id not in self._pending_group_msgs:
                    self._pending_group_msgs[group_id] = []
                self._pending_group_msgs[group_id].append(
                    (poll_data.get('creator', ''),
                     f'[poll]{poll_data["poll_id"]}',
                     time.time()))
                self._mark_group_unread(group_id)
                self._show_group_toast(group_id, poll_data.get('creator', ''), '\U0001f4ca Enquete')
                self._pending_flash_target = f'group:{group_id}'
                self._flash_window()

    # Callback: indicador de digitacao recebido via TCP (MT_TYPING).
    #
    # Repassa para a ChatWindow do remetente que exibe/oculta 'digitando...'.
    def _on_typing(self, from_user, is_typing):
        if from_user in self.chat_windows:                    # janela do remetente aberta?
            self.chat_windows[from_user].set_typing(is_typing)  # atualiza indicador

    def _on_file_incoming(self, file_id, from_user, display_name,
                          filename, filesize):
        # Callback: solicitacao de transferencia de arquivo recebida (MT_FILE_REQ).
        #
        # Abre o dialogo de transferencia + surfacea a janela de chat do peer
        # do tray com flash (mesmo padrao de mensagem chegando).
        dlg = FileTransferDialog(
            self.root, file_id, filename, display_name,
            direction='receive', filesize=filesize,
            on_cancel=lambda fid: self.messenger.cancel_file(fid)
        )
        self._file_dialogs[file_id] = dlg
        self._add_transfer_entry(file_id, filename, display_name,
                                  'receive', filesize, 'pending', peer_id=from_user)
        SoundPlayer.play_file_start()
        try:
            if self.messenger.db.get_setting('notif_file', '1') == '1':
                self._show_toast_generic(display_name or 'Arquivo',
                                         f'\U0001f4c4 {filename}')
        except Exception:
            pass
        # Surfacea a janela de chat do peer do tray e pisca (igual mensagem)
        self._pending_flash_target = from_user
        if from_user in self.chat_windows:
            cw = self.chat_windows[from_user]
            try:
                self._flash_window(cw, gate_key='flash_taskbar_file')
            except Exception:
                pass
        else:
            def _create():
                return self._open_chat(from_user, surface_only=True)
            try:
                self._surface_chat_from_tray(_create)
                cw = self.chat_windows.get(from_user)
                if cw:
                    self._flash_window(cw, gate_key='flash_taskbar_file')
            except Exception:
                pass

    # Callback: progresso de transferencia atualizado.
    #
    # Atualiza a barra de progresso do dialogo ativo e o status na lista
    # de historico de transferencias para 'transferindo'.
    def _on_file_progress(self, file_id, transferred, total):
        if file_id in self._file_dialogs:                                        # dialogo aberto?
            self._file_dialogs[file_id].update_progress(transferred, total)  # atualiza progresso
        self._update_transfer_entry(file_id, 'transferring')                  # atualiza historico

    # Callback: transferencia de arquivo concluida com sucesso.
    #
    # Notifica o dialogo ativo (exibe botao Abrir Pasta para receptor)
    # e marca o status como 'concluido' no historico.
    def _on_file_complete(self, file_id, filepath):
        if file_id in self._file_dialogs:
            self._file_dialogs[file_id].finish(success=True, filepath=filepath)
        self._update_transfer_entry(file_id, 'completed', filepath=filepath)
        self._save_file_chat_message(file_id, 'completed')
        SoundPlayer.play_file_done()

    # Callback: transferencia de arquivo falhou ou foi cancelada.
    def _on_file_error(self, file_id, error):
        if file_id in self._file_dialogs:
            self._file_dialogs[file_id].finish(success=False)
            del self._file_dialogs[file_id]
        self._update_transfer_entry(file_id, 'error')
        status = 'declined' if 'recus' in str(error).lower() else 'cancelled'
        self._save_file_chat_message(file_id, status)

    def _save_file_chat_message(self, file_id, status):
        entry = None
        for e in self._transfer_history:
            if e['file_id'] == file_id:
                entry = e
                break
        if not entry or not entry.get('peer_id'):
            return
        fname = entry['filename']
        fsize = self._format_filesize(entry.get('filesize', 0))
        if status == 'completed':
            if entry['direction'] == 'send':
                text = f'\U0001f4c4 {fname} \u2705 ({fsize}) \u2014 Enviado'
            else:
                text = f'\U0001f4c4 {fname} \u2705 ({fsize}) \u2014 Recebido'
        elif status == 'declined':
            text = f'\U0001f4c4 {fname} \u2014 Recusado'
        else:
            text = f'\U0001f4c4 {fname} \u2014 Cancelado'
        is_sent = entry['direction'] == 'send'
        peer_id = entry['peer_id']
        import uuid as _uuid
        msg_id = str(_uuid.uuid4())
        self.messenger.db.save_message(
            msg_id, self.messenger.user_id if is_sent else peer_id,
            peer_id if is_sent else self.messenger.user_id,
            text, msg_type='file', is_sent=is_sent)
        # Garante que a janela de chat esteja aberta (pode ter sido fechada durante o envio)
        # e surfacea do tray + pisca como acontece com mensagens normais
        if status == 'completed' and peer_id not in self.chat_windows:
            try:
                def _create():
                    return self._open_chat(peer_id, surface_only=True)
                self._surface_chat_from_tray(_create)
            except Exception:
                pass
        if peer_id in self.chat_windows:
            name = 'Você' if is_sent else entry.get('peer_name', '')
            cw = self.chat_windows[peer_id]
            cw._append_message(name, text, is_sent, msg_id=msg_id)
            # Para o sender tambem: pisca a janela de chat na taskbar (igual a mensagem recebida)
            if status == 'completed':
                try:
                    self._flash_window(cw, gate_key='flash_taskbar_file')
                except Exception:
                    pass

    @staticmethod
    def _format_filesize(size):
        if size < 1024:
            return f'{size} B'
        elif size < 1024 * 1024:
            return f'{size / 1024:.1f} KB'
        else:
            return f'{size / (1024 * 1024):.1f} MB'

    def _add_transfer_entry(self, file_id, filename, peer_name,
                             direction, filesize, status, peer_id=''):
        # Adiciona nova entrada no historico de transferencias e atualiza a janela de transfers.
        #
        # Cria um dicionario com todos os dados da transferencia e o append em
        # self._transfer_history. Se a janela de transfers estiver aberta, atualiza ela.
        entry = {'file_id': file_id, 'filename': filename,  # dicionario com dados da transferencia
                 'peer_name': peer_name, 'direction': direction,
                 'filesize': filesize, 'status': status, 'filepath': '',
                 'peer_id': peer_id}
        self._transfer_history.append(entry)
        if self._transfers_window:
            try:
                self._transfers_window.add_or_update(entry)
            except tk.TclError:
                self._transfers_window = None

    # Atualiza status (e filepath opcional) de uma transferencia no historico.
    #
    # Procura a entrada pelo file_id e atualiza o status e caminho do arquivo.
    # Se a janela de transfers estiver aberta, atualiza o item exibido.
    def _update_transfer_entry(self, file_id, status, filepath=''):
        for e in self._transfer_history:  # procura a entrada pelo file_id
            if e['file_id'] == file_id:
                e['status'] = status
                if filepath:
                    e['filepath'] = filepath
                break
        if self._transfers_window:
            try:
                for e in self._transfer_history:
                    if e['file_id'] == file_id:
                        self._transfers_window.add_or_update(e)
                        break
            except tk.TclError:
                self._transfers_window = None

    # Abre/mostra janela de Transferencias de Arquivos.
    def _show_transfers_window(self):
        if self._transfers_window:
            try:
                self._transfers_window.deiconify()
                self._transfers_window.lift()
                return
            except tk.TclError:
                self._transfers_window = None
        self._transfers_window = FileTransfersWindow(self)

    # Chamado quando uma ChatWindow e restaurada (clique na thumbnail da taskbar).
    # Para o flash da janela e limpa a marcacao de nao lido.
    def _on_chat_window_mapped(self, cw):
        try:
            # Ignora o primeiro Map (criacao). Flag _mapped_once evita falso positivo.
            if not getattr(cw, '_mapped_once', False):
                cw._mapped_once = True
                return
            self._stop_flash(cw)
            peer_id = getattr(cw, 'peer_id', None)
            if peer_id and peer_id in self.peer_items:
                self._clear_unread(peer_id)
        except Exception:
            pass

    # Chamado quando uma GroupChatWindow e restaurada.
    def _on_group_window_mapped(self, gw):
        try:
            if not getattr(gw, '_mapped_once', False):
                gw._mapped_once = True
                return
            self._stop_flash(gw)
            gid = getattr(gw, 'group_id', None)
            if gid:
                self._clear_group_unread(gid)
        except Exception:
            pass

    # Forca a Toplevel a ter entrada propria na taskbar (Win32 WS_EX_APPWINDOW).
    # Sem isso, filhas do root aparecem agrupadas mas nao ganham thumbnail propria.
    def _force_taskbar_entry(self, win):
        try:
            import ctypes
            GWL_EXSTYLE = -20
            WS_EX_APPWINDOW = 0x00040000
            WS_EX_TOOLWINDOW = 0x00000080
            SW_HIDE, SW_SHOWNA = 0, 8
            hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
            if not hwnd:
                return
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            new_style = (style | WS_EX_APPWINDOW) & ~WS_EX_TOOLWINDOW
            if new_style != style:
                ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, new_style)
                # Se a janela ja esta mapeada, precisa do ciclo HIDE+SHOW pra
                # Windows reprocessar a taskbar. Se foi criada withdrawn, o
                # proximo ShowWindow (SW_SHOWMINNOACTIVE) ja pega o estilo novo
                # sem flash visivel.
                try:
                    if win.winfo_ismapped():
                        ctypes.windll.user32.ShowWindow(hwnd, SW_HIDE)
                        ctypes.windll.user32.ShowWindow(hwnd, SW_SHOWNA)
                except Exception:
                    pass
        except Exception:
            pass

    # Mostra a janela na taskbar em estado minimizado, sem roubar foco.
    # Usado quando mensagem chega com app no tray: janela surge minimizada.
    def _show_in_taskbar_minimized(self, win):
        try:
            import ctypes
            SW_SHOWMINNOACTIVE = 7
            hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
            if not hwnd:
                return
            ctypes.windll.user32.ShowWindow(hwnd, SW_SHOWMINNOACTIVE)
        except Exception:
            pass

    # Orquestra surface de uma janela de chat quando mensagem chega com app no tray.
    # 1) Garante que a root apareca minimizada na taskbar (se estava withdrawn)
    # 2) Cria a janela via create_fn (que deve usar surface_only=True)
    # 3) Minimiza a janela recem criada na taskbar
    # 4) Pisca ela para chamar atencao do usuario
    def _surface_chat_from_tray(self, create_fn):
        try:
            if self.root.state() == 'withdrawn':
                self._show_in_taskbar_minimized(self.root)
        except Exception:
            pass
        try:
            win = create_fn()
        except Exception:
            win = None
        if win is None:
            return
        try:
            win.update_idletasks()
            self._show_in_taskbar_minimized(win)
            self._flash_window(win)
        except Exception:
            pass

    # Pisca o ícone na barra de tarefas (Windows FlashWindowEx).
    def _flash_window(self, widget=None, gate_key='flash_taskbar_msg'):
        try:
            if self.messenger.db.get_setting(gate_key, '1') != '1':
                return
        except Exception:
            pass
        try:
            import ctypes
            from ctypes import wintypes

            class FLASHWINFO(ctypes.Structure):
                _fields_ = [
                    ('cbSize', wintypes.UINT),
                    ('hwnd', wintypes.HWND),
                    ('dwFlags', wintypes.DWORD),
                    ('uCount', wintypes.UINT),
                    ('dwTimeout', wintypes.DWORD),
                ]

            FLASHW_ALL = 3         # pisca janela + botao da taskbar
            FLASHW_TIMERNOFG = 12  # continua piscando ate a janela receber foco

            target = widget or self.root  # janela alvo (chat, grupo ou principal)
            hwnd = ctypes.windll.user32.GetParent(target.winfo_id())  # handle Win32
            finfo = FLASHWINFO(
                cbSize=ctypes.sizeof(FLASHWINFO),
                hwnd=hwnd,
                dwFlags=FLASHW_ALL | FLASHW_TIMERNOFG,  # pisca ate receber foco
                uCount=0,      # 0 = pisca indefinidamente ate receber foco
                dwTimeout=0,   # 0 = usa intervalo padrao do cursor piscante
            )
            ctypes.windll.user32.FlashWindowEx(ctypes.byref(finfo))  # chama API Win32
        except Exception:
            pass

    # Para de piscar a barra de tarefas.
    def _stop_flash(self, widget=None):
        try:
            import ctypes
            from ctypes import wintypes

            class FLASHWINFO(ctypes.Structure):
                _fields_ = [
                    ('cbSize', wintypes.UINT),
                    ('hwnd', wintypes.HWND),
                    ('dwFlags', wintypes.DWORD),
                    ('uCount', wintypes.UINT),
                    ('dwTimeout', wintypes.DWORD),
                ]

            FLASHW_STOP = 0  # flag para parar o piscamento
            target = widget or self.root  # janela alvo
            hwnd = ctypes.windll.user32.GetParent(target.winfo_id())  # handle Win32
            finfo = FLASHWINFO(
                cbSize=ctypes.sizeof(FLASHWINFO),
                hwnd=hwnd,
                dwFlags=FLASHW_STOP,  # para o flash imediatamente
                uCount=0,
                dwTimeout=0,
            )
            ctypes.windll.user32.FlashWindowEx(ctypes.byref(finfo))  # para o piscamento
        except Exception:
            pass

    # Callback do FocusIn da janela principal: para o flash na root.
    # Nao abre chat/grupo automaticamente — cada conversa ja tem sua propria
    # janela na taskbar (surface pattern), usuario escolhe qual restaurar via
    # thumbnail. Apenas lembretes abrem aqui, pois nao tem janela dedicada.
    def _on_main_focus(self, event=None):
        self._stop_flash()
        target = self._pending_flash_target
        self._pending_flash_target = None
        if target == '__reminders__':
            self.root.after(100, self._show_reminders)

    # Mostra notificacao toast nativa do Windows (clicavel via winotify).
    def _show_toast(self, from_user, content, is_broadcast=False):
        key = 'notif_msg_broadcast' if is_broadcast else 'notif_msg_private'
        if self.messenger.db.get_setting(key, '1') != '1':
            return
        self._last_notif_peer = from_user  # guarda quem enviou (para abrir ao clicar)
        name = self.peer_info.get(from_user, {}).get('display_name', 'Mensagem')  # nome do remetente
        preview = content[:120] + '...' if len(content) > 120 else content  # trunca em 120 chars

        # Tenta winotify primeiro: toast nativo do Windows 10/11 (clicavel, com icone)
        if HAS_WINOTIFY:
            try:
                notif = WinNotification(
                    app_id='MB Chat',   # identificador do app no Action Center
                    title=name,         # titulo = nome do remetente
                    msg=preview,        # corpo = preview da mensagem
                    icon=self._icon_path or '',  # icone do app
                )
                notif.launch = f'mbchat://open/{from_user}'  # URL ativada ao clicar
                notif.set_audio(wn_audio.Default, loop=False)  # som padrao, sem loop
                notif.show()  # exibe o toast
                return  # sucesso: nao precisa usar fallback
            except Exception:
                pass  # winotify falhou: tenta fallback abaixo

        # Fallback: balloon tip via pystray (mais simples, nao clicavel)
        if self._balloon_notify(preview, name):
            return
        if HAS_TRAY and HAS_PIL and self._tray_icon is None:
            try:
                self._start_tray()
                self._balloon_notify(preview, name)
            except Exception:
                pass

    def _balloon_notify(self, text, title):
        try:
            if self.messenger.db.get_setting('balloon_notify', '1') != '1':
                return False
        except Exception:
            pass
        if self._tray_icon is None:
            return False
        try:
            self._tray_icon.notify(text, title=title)
            return True
        except Exception:
            return False

    def _show_toast_generic(self, title, body):
        preview = body[:120] + '...' if len(body) > 120 else body
        if HAS_WINOTIFY:
            try:
                notif = WinNotification(
                    app_id='MB Chat', title=title, msg=preview,
                    icon=self._icon_path or '')
                notif.set_audio(wn_audio.Default, loop=False)
                notif.show()
                return
            except Exception:
                pass
        self._balloon_notify(preview, title)

    # Minimiza para o system tray ao fechar a janela (se pystray+PIL disponivel).
    #
    # Comportamento:
    # - Com tray disponivel: oculta janela (withdraw) e ativa icone na bandeja.
    # - Sem tray: encerra o aplicativo completamente via _quit().
    def _on_close(self):
        # Destroi qualquer FileTransferDialog ainda vivo — evita que dialogs
        # transient (filhos do root) reapareçam quando o root for restaurado
        # do tray. Usuario interpreta o dialog sumindo com o root como "fechei".
        try:
            for dlg in list(self._file_dialogs.values()):
                try:
                    dlg.destroy()
                except Exception:
                    pass
            self._file_dialogs.clear()
        except Exception:
            pass
        try:
            minimize = self.messenger.db.get_setting('minimize_on_close', '0') == '1'
        except Exception:
            minimize = False
        if minimize:
            try:
                self._show_in_taskbar_minimized(self.root)
            except Exception:
                self.root.iconify()
            return
        if HAS_TRAY and HAS_PIL:   # bibliotecas de tray disponiveis?
            self.root.withdraw()   # esconde a janela (nao destroi)
            self._start_tray()     # inicia o icone na bandeja do sistema
        else:
            self._quit()           # sem tray: encerra o processo

    # Encerra o aplicativo completamente: para tray, destroi janelas, para rede.
    #
    # Sequencia segura de shutdown:
    # 1. Remove icone do tray
    # 2. Destroi janelas de chat abertas
    # 3. Para o messenger (fecha sockets, threads de rede)
    # 4. Destroi a janela principal (encerra o mainloop)
    def _quit(self):
        self._stop_tray()                          # remove icone da bandeja do sistema
        for w in list(self.chat_windows.values()):  # percorre copia da lista (evita mutar durante iteracao)
            try:
                w.destroy()  # destroi janela de chat individual
            except Exception:
                pass          # ignora erros se ja foi destruida
        self.messenger.stop()  # para threads de rede e fecha sockets UDP/TCP
        self.root.destroy()    # destroi janela principal e encerra mainloop
        os._exit(0)  # forca o SO a remover o processo garantindo que nao haja zumbis

    # --- System Tray ---
    # Inicia o icone do MB Chat na bandeja do sistema (system tray).
    #
    # Requer pystray e PIL. Cria icone com menu de duplo-clique (Abrir) e Sair.
    # O icone roda em thread daemon separada para nao bloquear o mainloop.
    def _start_tray(self):
        if self._tray_icon is not None:   # ja existe um icone no tray?
            return                         # nao cria outro
        if not HAS_TRAY or not HAS_PIL:   # bibliotecas disponiveis?
            log.warning(f'Tray icon nao iniciado: pystray={HAS_TRAY}, PIL={HAS_PIL}')
            return
        try:
            if self.messenger.db.get_setting('tray_icon', '1') != '1':
                return  # usuario desativou icone no tray
        except Exception:
            pass

        if self._icon_path:  # tem arquivo de icone?
            icon_image = Image.open(self._icon_path)             # carrega icone do arquivo
        else:
            icon_image = Image.new('RGBA', (64, 64), '#1a3a7a')  # icone fallback azul

        # Cria menu de contexto do tray com duas opcoes
        menu = pystray.Menu(
            pystray.MenuItem('Abrir MB Chat', self._tray_show,
                             default=True),  # default = acao do duplo-clique
            pystray.MenuItem('Sair', self._tray_quit),  # encerra o aplicativo
        )
        self._tray_icon = pystray.Icon('mbchat', icon_image,
                                        APP_NAME, menu)  # cria o icone do tray
        threading.Thread(target=self._tray_icon.run, daemon=True).start()  # roda em thread daemon

    # Remove o icone do system tray.
    def _stop_tray(self):
        if self._tray_icon is not None:
            try:
                self._tray_icon.stop()
            except Exception:
                pass
            self._tray_icon = None

    # Callback do icone do tray (duplo-clique): restaura janela e abre chat pendente.
    #
    # Captura o ultimo peer que enviou notificacao e o passa para _restore_and_open.
    # Usa root.after(0) para executar na thread principal do tkinter (thread-safe).
    def _tray_show(self, icon=None, item=None):
        peer = self._pending_flash_target
        self._pending_flash_target = None
        self.root.after(0, lambda: self._restore_and_open(peer))  # agenda na main thread

    # Restaura a janela principal do tray e abre chat/grupo se peer for fornecido.
    #
    # Usada pelo system tray (click) e pelo listener de instancia unica (OPEN:peer_id).
    # Usa topmost temporario (200ms) para garantir que a janela venha a frente.
    # peer pode ser: uid do contato, 'group:gid' para abrir grupo, ou None.
    def _restore_and_open(self, peer=None):
        self.root.deiconify()                             # mostra a janela que estava oculta
        self.root.state('normal')                         # restaura tamanho normal (nao minimizado)
        self.root.lift()                                  # traz para frente
        self.root.focus_force()                           # forca o foco do sistema
        try:
            self.tree.selection_remove(*self.tree.selection())
        except Exception:
            pass
        self.root.attributes('-topmost', True)            # temporariamente na frente de tudo
        self.root.after(200, lambda: self.root.attributes('-topmost', False))  # remove apos 200ms
        if peer and hasattr(self, 'messenger'):  # tem peer para abrir e messenger inicializado?
            if peer == '__reminders__':             # comando especial para abrir lembretes
                self.root.after(100, self._show_reminders)
            elif peer.startswith('group:'):          # e um grupo? (prefixo group:)
                gid = peer[6:]                     # extrai o group_id sem o prefixo
                if gid in self.messenger._groups:  # grupo existe?
                    self._open_group(gid)          # abre/exibe a janela de grupo
            elif peer in self.peer_info:           # e um contato conhecido?
                self._open_chat(peer)              # abre/exibe a janela de chat

    # Encerra via menu do tray.
    def _tray_quit(self, icon=None, item=None):
        self.root.after(0, self._quit)

    # Inicia o loop principal do tkinter — bloqueia ate o app fechar.
    def run(self):
        self.root.mainloop()  # loop de eventos tkinter (bloqueia aqui ate destroy)


# =============================================================
# Formata um tamanho em bytes para string legivel (B, KB, MB, GB).
#
# Exemplos: 512 -> '512 B', 1536 -> '1.5 KB', 2097152 -> '2.0 MB'.
# Usado na janela de transferencia de arquivos e no historico.
def _format_size(size):
    if size < 1024:              # menos de 1 KB
        return f'{size} B'
    elif size < 1024**2:         # menos de 1 MB
        return f'{size/1024:.1f} KB'
    elif size < 1024**3:         # menos de 1 GB
        return f'{size/1024**2:.1f} MB'
    return f'{size/1024**3:.1f} GB'  # gigabytes


# Registra o MB Chat para iniciar automaticamente com o sistema operacional.
#
# Windows: adiciona entrada no Registro em HKCU\\...\\Run com flag --silent.
# Linux: cria arquivo .desktop em ~/.config/autostart/.
# macOS: cria arquivo .plist em ~/Library/LaunchAgents/.
def _setup_autostart():
    script = os.path.abspath(sys.argv[0])  # caminho absoluto do script/exe atual
    python = sys.executable                # caminho do interpretador Python
    if platform.system() == 'Windows':     # plataforma Windows?
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


# Remove o registro de inicializacao automatica do MB Chat.
#
# Windows: remove entrada do Registro em HKCU\\...\\Run.
# Linux: remove o arquivo .desktop de autostart.
# macOS: remove o arquivo .plist do LaunchAgents.
def _remove_autostart():
    if platform.system() == 'Windows':  # remove chave do Registro do Windows
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


# Registra o protocolo mbchat:// no Windows para notificacoes clicaveis.
def _register_url_protocol():
    if platform.system() != 'Windows':
        return
    try:
        import winreg
        # Funciona tanto em desenvolvimento (python gui.py) quanto como exe (PyInstaller)
        if getattr(sys, 'frozen', False):  # rodando como executavel frozen?
            exe_path = sys.executable      # caminho do .exe
        else:
            exe_path = sys.executable      # caminho do python.exe (desenvolvimento)
        # Cria a chave raiz do protocolo: HKCU\Software\Classes\mbchat
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                               r'Software\Classes\mbchat')
        winreg.SetValueEx(key, '', 0, winreg.REG_SZ, 'URL:MB Chat Protocol')  # descricao
        winreg.SetValueEx(key, 'URL Protocol', 0, winreg.REG_SZ, '')          # marca como protocolo URL
        # Registra o icone do protocolo
        icon_key = winreg.CreateKey(key, r'DefaultIcon')
        winreg.SetValueEx(icon_key, '', 0, winreg.REG_SZ, f'{exe_path},0')  # icone do exe
        winreg.CloseKey(icon_key)
        # Registra o comando que sera executado ao ativar o protocolo
        cmd_key = winreg.CreateKey(key, r'shell\open\command')
        winreg.SetValueEx(cmd_key, '', 0, winreg.REG_SZ,
                          f'"{exe_path}" "%1"')  # %1 = a URL mbchat:// completa
        winreg.CloseKey(cmd_key)
        winreg.CloseKey(key)
    except Exception:
        pass  # falha silenciosa: nao e critico para o funcionamento do app


# Verifica se ja existe uma instancia do MB Chat rodando.
#
# Tenta conectar na porta loopback 50199. Se conseguir, envia 'SHOW' para
# restaurar a instancia existente e retorna False (ja existe outra instancia).
# Se a conexao for recusada (porta livre), somos a primeira instancia: retorna True.
def _check_single_instance():
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.3)   # loopback e rapido, 300ms e suficiente
        sock.connect(('127.0.0.1', SINGLE_INSTANCE_PORT))  # tenta conectar na porta de lock
        sock.sendall(b'SHOW')  # sinaliza para a instancia existente se mostrar
        sock.close()
        return False  # ja existe outra instancia rodando
    except (ConnectionRefusedError, OSError, socket.timeout):
        return True  # porta livre = somos a primeira instancia


# Inicia listener TCP loopback para receber comandos de novas tentativas de abertura.
#
# Escuta na porta 50199 (loopback). Quando outra instancia ou uma notificacao
# clicavel (protocolo mbchat://) envia um comando:
# - 'SHOW': restaura a janela principal
# - 'OPEN:peer_id': restaura e abre chat com o peer (ou grupo)
# Roda em thread daemon para nao bloquear o loop principal.
def _start_instance_listener(app):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)  # socket TCP
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # reutiliza porta imediatamente
    try:
        srv.bind(('127.0.0.1', SINGLE_INSTANCE_PORT))  # bind na porta de lock loopback
    except OSError:
        return  # nao conseguiu bind: outra instancia ja esta escutando
    srv.listen(5)              # aceita ate 5 conexoes na fila
    srv.settimeout(0.2)        # timeout curto para responder notificacoes rapidamente

    # Loop de escuta que processa comandos de outras instancias ou do protocolo URL.
    def listen():
        while True:
            try:
                client, _ = srv.accept()  # aguarda conexao de outro processo
                data = client.recv(256).decode('utf-8', errors='ignore')  # le o comando
                client.close()  # fecha a conexao imediatamente
                if data.startswith('OPEN:'):  # comando para abrir chat/grupo especifico
                    peer_id = data[5:].strip()  # extrai uid ou group:gid
                    app.root.after(0, lambda p=peer_id: app._restore_and_open(p))  # main thread
                elif data == 'SHOW':  # comando para apenas mostrar a janela
                    app.root.after(0, app._restore_and_open)  # restaura na main thread
            except socket.timeout:
                continue  # timeout normal: nenhuma conexao no periodo, continua
            except OSError:
                break  # socket fechado (app encerrando): sai do loop

    t = threading.Thread(target=listen, daemon=True)
    t.start()


def _cleanup_zombie_processes():
    if platform.system() == 'Windows':
        import subprocess
        pid = os.getpid()
        ppid = os.getppid()
        try:
            # Mata qlqr outro MBChat.exe que não seja este processo nem seu processo pai (bootloader do PyInstaller)
            cmd = f'taskkill /F /IM MBChat.exe /FI "PID ne {pid}" /FI "PID ne {ppid}"'
            subprocess.run(cmd, shell=True, creationflags=0x08000000, 
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

# Ponto de entrada principal do MB Chat.
#
# Fluxo de inicializacao:
# 1. Verifica se foi ativado por protocolo mbchat:// (notificacao clicavel).
# Se sim, envia o comando para a instancia existente e sai.
# 2. Verifica instancia unica via porta loopback 50199.
# Se ja existe outra instancia, sai silenciosamente.
# 3. Registra o protocolo mbchat:// no Registro do Windows.
# 4. Cria a LanMessengerApp, inicia o listener de instancia e executa o mainloop.
# 5. O app inicia minimizado na bandeja (root.withdraw).
def main():
    # Verifica se foi ativado por protocolo mbchat:// (ex: clique em notificacao)
    for arg in sys.argv[1:]:  # percorre todos os argumentos da linha de comando
        if arg.startswith('mbchat://'):  # foi ativado pelo protocolo mbchat://?
            peer_id = ''                 # uid do peer ou group:gid a abrir
            if '/group/' in arg:         # e uma URL de grupo (mbchat://group/GID)?
                gid = arg.split('/group/')[-1].strip('/')  # extrai o group_id
                peer_id = f'group:{gid}'                   # formato: group:GID
            elif '/open/' in arg:        # e uma URL de chat (mbchat://open/UID)?
                peer_id = arg.split('/open/')[-1].strip('/')  # extrai o uid
            try:
                # Envia comando para a instancia ja em execucao via loopback
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(0.5)  # loopback e rapido, 500ms basta
                sock.connect(('127.0.0.1', SINGLE_INSTANCE_PORT))  # conecta na instancia
                cmd = f'OPEN:{peer_id}' if peer_id else 'SHOW'
                sock.sendall(cmd.encode())  # envia o comando
                sock.close()
            except Exception:
                pass  # instancia nao respondeu: ignora e sai
            os._exit(0)  # usa os._exit para encerramento imediato e limpo

    if not _check_single_instance():  # ja existe outra instancia rodando?
        os._exit(0)  # usa os._exit para garantir que nao deixa processos pendentes

    # Passamos da verificacao de instancia unica: somos a UNICA instancia legitima.
    # Vamos limpar processos MBChat.exe zumbis que possam ter ficado travados antes.
    _cleanup_zombie_processes()

    _register_url_protocol()  # registra mbchat:// no Registro do Windows

    app = LanMessengerApp()             # cria a aplicacao principal
    _start_instance_listener(app)       # inicia o listener de instancia unica

    # Setting show_main_on_start: True = mostra janela, False = inicia no tray
    try:
        show_main = app.messenger.db.get_setting('show_main_on_start', '1') == '1'
    except Exception:
        show_main = False
    if not show_main:
        app.root.withdraw()
        
    app.run()            # inicia o mainloop do tkinter


if __name__ == '__main__':
    # Ponto de entrada quando o arquivo e executado diretamente (python gui.py)
    # ou como executavel PyInstaller (MBChat.exe)
    try:
        main()  # inicia o aplicativo
    except Exception:
        log.exception('Erro fatal no MB Chat')  # registra a excecao no log antes de propagar
        raise  # propaga para o sistema (mostra traceback em desenvolvimento)
