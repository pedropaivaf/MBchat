# MB Chat - Padrao de Codigo

## Linguagem e Versao

- Python 3.10+
- Encoding: UTF-8
- Line endings: LF

## Nomenclatura

| Elemento          | Convencao              | Exemplo                          |
|-------------------|------------------------|----------------------------------|
| Modulos           | snake_case             | network.py, database.py         |
| Classes           | PascalCase             | ChatWindow, UDPDiscovery        |
| Metodos publicos  | snake_case             | send_message(), get_chat_history |
| Metodos privados  | _snake_case (prefixo _)| _on_user_found(), _build_ui()   |
| Constantes        | UPPER_SNAKE_CASE       | UDP_PORT, BG_WINDOW, FONT_BOLD  |
| Variaveis tkinter | var_ prefixo           | var_display_name, var_font_size |
| Widgets tkinter   | lbl_, btn_, txt_       | lbl_username, self.chat_text    |
| Feature flags     | HAS_ prefixo           | HAS_PIL, HAS_TRAY, HAS_WINOTIFY|

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
from network import TCP_PORT, UDP_PORT, MT_MESSAGE, ...
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

## Instancia Unica

Mecanismo via TCP socket em 127.0.0.1:50199:
- _check_single_instance() tenta conectar; se consegue, ja existe outra
- _start_instance_listener() aceita SHOW e OPEN:{peer_id}
- Protocolo URL mbchat:// registrado em HKCU\Software\Classes\mbchat

## Commits

- Mensagens em portugues ou ingles (consistente por PR)
- Formato: tipo: descricao curta
- Tipos: feat, fix, refactor, docs, style, build
- Exemplos:
  - feat: adiciona dialogo de transferencia de arquivo
  - fix: corrige timeout de envio de arquivo
  - docs: atualiza arquitetura e padroes de codigo
