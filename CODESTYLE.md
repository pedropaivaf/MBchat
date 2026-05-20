# MB Chat - Padrao de Codigo

## REGRA CRÍTICA: ESTABILIDADE E NÃO-REGRESSÃO

> [!IMPORTANT]
> **GARANTIA DE NÃO-QUEBRA**: Ao implementar qualquer nova funcionalidade, correção de bug ou refatoração, a prioridade máxima é **garantir que nada que já funcione seja quebrado**. 
> Cada alteração deve ser cirúrgica, localizada e de baixo impacto para evitar o efeito cascata de introduzir novos problemas (regressões).
> 
> **Diretrizes**:
> 1. **Análise de Impacto**: Antes de modificar qualquer linha, entenda como ela afeta o ciclo de vida das janelas, manipulação do banco de dados e fluxos de rede.
> 2. **Preservar Histórico**: Nunca desative ou modifique comportamentos consolidados a menos que expressamente solicitado.
> 3. **Testes de Regressão**: Valide se os fluxos anteriores continuam funcionando idênticos após a modificação (ex: comportamento de som, piscamento, minimização e histórico).

## Linguagem e Versao

- Python 3.10+
- Encoding: UTF-8
- Line endings: LF

## Nomenclatura

| Elemento          | Convencao              | Exemplo                          |
|-------------------|------------------------|----------------------------------|
| Modulos           | snake_case             | network.py, database.py         |
| Classes           | PascalCase             | ChatWindow, UDPDiscovery, GroupChatWindow |
| Metodos publicos  | snake_case             | send_message(), get_chat_history |
| Metodos privados  | _snake_case (prefixo _)| _on_user_found(), _build_ui()   |
| Constantes        | UPPER_SNAKE_CASE       | UDP_PORT, BG_WINDOW, FONT_BOLD  |
| Variaveis tkinter | var_ prefixo           | var_display_name, var_font_size |
| Widgets tkinter   | lbl_, btn_, txt_       | lbl_username, self.chat_text    |
| Feature flags     | HAS_ prefixo           | HAS_PIL, HAS_TRAY, HAS_WINOTIFY|
| Msg types         | MT_ prefixo            | MT_MESSAGE, MT_GROUP_INV        |

## Organizacao dos Arquivos

Ordem dentro de cada .py:
1. Docstring do modulo
2. Imports stdlib
3. Imports terceiros (com try/except para opcionais)
4. Imports locais do projeto
5. Constantes
6. Funcoes utilitarias (module-level)
7. Classes (uma principal por arquivo)
8. Entrypoint (if __name__ == '__main__')

## Arquitetura de 4 Camadas

```
gui.py -> messenger.py -> network.py
                       -> database.py
```

Regras:
- gui.py nunca importa network.py diretamente
- network.py nunca importa database.py
- messenger.py e o unico que conhece ambos
- Comunicacao bottom-up via callbacks (nao imports circulares)

## Classes GUI (gui.py)

Padrao interno de cada classe de janela:

```python
class SomeWindow(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.root)
        # 1. Referencias
        self.app = app
        self.messenger = app.messenger
        # 2. Config janela
        self.title('Titulo')
        self.transient(app.root)
        _center_window(self, 400, 300)
        # 3. Variaveis de estado
        self._init_vars()
        # 4. Construcao da UI
        self._build_ui()
        # 5. Protocol de fechamento
        self.protocol('WM_DELETE_WINDOW', self._on_close)
```

### Dialogo de Transferencia (FileTransferDialog)

Padrao para dialogos de progresso:
- Sempre recebe file_id para tracking
- on_cancel callback para cleanup
- update_progress() thread-safe via root.after()
- finish() para auto-destruir

### Funcoes Utilitarias Module-Level

```python
# Emoji colorido (PIL + seguiemj.ttf)
_render_color_emoji(emoji_char, size=28)  # retorna PhotoImage ou None

# Hover effect para qualquer widget
_add_hover(widget, normal_bg, hover_bg, normal_fg=None, hover_fg=None)

# Centralizar janela
_center_window(win, w, h)

# Localizar icone
_get_icon_path()  # retorna path ou None
```

### UI Moderna

Padroes visuais:
- **Navy header**: Frame bg='#0f2a5c' com titulo em branco e subtitulo em '#8aa0cc'
- **Frame-in-Frame border**: outer Frame bg='#e2e8f0', inner Frame padx=1 pady=1
- **Pill buttons**: tk.Button flat com bg toggle entre navy (ativo) e '#e2e8f0' (inativo)
- **Hover effects**: _add_hover() para botoes e rows de lista
- **Botao primario**: bg=NAVY, fg='#ffffff', hover='#1a3f7a'
- **Botao secundario**: bg='#e2e8f0', fg='#4a5568', hover='#cbd5e0'
- **Canvas scrollavel**: create_window + Configure bind para largura total e scrollregion

## Threading

**REGRA DE OURO**: Nunca modificar widgets tkinter fora da main thread.

Callbacks de rede usam wrapper `_safe`:
```python
def _safe(self, func):
    def wrapper(*args, **kwargs):
        self.root.after(0, func, *args, **kwargs)
    return wrapper
```

Operacoes de I/O sempre em threads daemon separadas:
```python
threading.Thread(target=self.messenger.send_message,
                 args=(peer_id, content), daemon=True).start()
```

Tracking de dialogos por file_id:
```python
self._file_dialogs = {}  # file_id -> FileTransferDialog
```

## Emojis Coloridos

Renderizacao via PIL com fonte Segoe UI Emoji. Para janelas de entrada, utiliza-se o evento `<<Modified>>` do `tk.Text` para detecção em tempo real, pois eventos de teclado padrão não capturam inserções via IME/Windows Emoji Picker.

```python
# Obrigatorio em ChatWindow, GroupChatWindow, Broadcast:
txt.bind('<<Modified>>', self._on_modified)

def _on_modified(self, event):
    self.entry.edit_modified(False) # Reset necessario
    self.after(30, self._do_emoji_scan)
```

Insercao em tk.Text com tracking para reconstruir texto:
```python
# Inserir como imagem
txt.image_create(pos, image=img, name=img_name, padx=1)
img_map[img_name] = emoji_char  # para reconstruir

# Reconstruir texto + emojis
for key, value, index in txt.dump('1.0', 'end', image=True, text=True):
    if key == 'text': result.append(value)
    elif key == 'image': result.append(img_map.get(value, ''))
```

## Temas

3 dicionarios em THEMES com as mesmas chaves de cor. Para adicionar um novo tema:

1. Copie um tema existente em THEMES
2. Altere os valores de cor
3. O nome da chave do dict e o nome no dropdown

Chaves obrigatorias: bg_window, bg_white, bg_header, bg_group, bg_select, bg_input,
bg_chat, fg_black, fg_gray, fg_white, fg_blue, fg_green, fg_red, fg_orange, fg_msg,
fg_time, fg_my_name, fg_peer_name, btn_bg, btn_fg, btn_active, border,
statusbar_bg, statusbar_fg.

## Banco de Dados

- threading.local() para conexoes por thread
- PRAGMA journal_mode=WAL para concorrencia
- Parametros ? em queries (nunca f-strings em SQL)
- commit() apos cada escrita
- Retornar dict(row) para desacoplar do sqlite3.Row

## Protocolo de Rede

Frames TCP com prefixo de comprimento:
```python
# Enviar
data = json.dumps(payload).encode('utf-8')
sock.sendall(struct.pack('!I', len(data)) + data)

# Receber
raw_len = sock.recv(4)
length = struct.unpack('!I', raw_len)[0]
data = sock.recv(length)
```

Constantes de rede (portas, enderecos) definidas APENAS em network.py.
Outros modulos importam de la:
```python
from network import TCP_PORT, UDP_PORT, MT_MESSAGE, MT_GROUP_INV, ...
```

## Dependencias Opcionais

Sempre com try/except e feature flag:
```python
try:
    from winotify import Notification as WinNotification, audio as wn_audio
    HAS_WINOTIFY = True
except ImportError:
    HAS_WINOTIFY = False
```

Uso condicional:
```python
if HAS_WINOTIFY:
    # usa winotify
else:
    # fallback para pystray.notify() ou nada
```

## Instancia Unica (porta por usuario)

Mecanismo via TCP socket loopback com porta deterministica **por login Windows**:

```python
# SINGLE_INSTANCE_PORT em [50200, 51200)
user = getpass.getuser().lower()
h = int(hashlib.md5(user.encode()).hexdigest()[:8], 16)
SINGLE_INSTANCE_PORT = 50200 + (h % 1000)
```

- Cada login Windows obtem porta distinta → dois usuarios da mesma maquina
  podem ter MBChat aberto simultaneamente sem travar um ao outro
- _check_single_instance() tenta conectar na porta da sessao atual;
  se consegue, ja existe outra instancia DESSA sessao
- _start_instance_listener() aceita SHOW e OPEN:{peer_id}
- Protocolo URL mbchat:// registrado em HKCU\Software\Classes\mbchat
- **Nao usar porta fixa** (<=v1.4.63 usava 50199 e isso travava multi-user)

## Commits

- Mensagens em portugues ou ingles (consistente por PR)
- Formato: tipo: descricao curta
- Tipos: feat, fix, refactor, docs, style, build
- Exemplos:
  - feat: adiciona bate papo em grupo e transmitir mensagem
  - fix: corrige canvas scrollavel em dialogo de grupo
  - docs: atualiza arquitetura e padroes de codigo
