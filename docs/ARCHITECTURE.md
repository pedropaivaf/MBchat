# MB Chat - Arquitetura

## Visao Geral

Arquitetura em 4 camadas com separacao clara de responsabilidades:

```
+---------------------------------------------+
|                  gui.py                      |
|         Apresentacao (View)                  |
|   tkinter: janelas, menus, widgets,          |
|   treeview de contatos, chat windows,        |
|   group chat, broadcast, file transfer,      |
|   emoji colorido, system tray                |
+----------------------+-----------------------+
                       | callbacks (_safe wrapper)
+----------------------v-----------------------+
|              messenger.py                    |
|         Controller / Orquestrador            |
|   Liga rede <-> banco <-> GUI               |
|   Gerencia estado do usuario local           |
|   Gerencia grupos (mesh topology)            |
+--------+------------------------+------------+
         |                        |
+--------v--------+   +-----------v-----------+
|  network.py     |   |  database.py          |
|  Rede (I/O)     |   |  Dados (SQL)          |
|  UDP + TCP      |   |  SQLite local         |
+-----------------+   +-----------------------+
```

Principio: cada camada so conhece a imediatamente abaixo. GUI nao importa network diretamente.

## Modulos

### gui.py (~5200 linhas) - Apresentacao

Classes principais:
- **LanMessengerApp**: Janela principal (menu, contatos treeview, toolbar, status bar, temas)
- **ChatWindow**: Conversa individual com peer (envio de msg/arquivo, historico, emojis coloridos)
- **GroupChatWindow**: Chat em grupo estilo LAN Messenger (PanedWindow com splitter arrastavel, painel lateral de participantes com avatar/nome/nota colapsavel, emoji colorido, fonte, envio de arquivo para grupo, adicionar participantes, layout bottom-first para input)
- **FileTransferDialog**: Dialogo de progresso de transferencia (estilo LAN Messenger)
- **PreferencesWindow**: 9 abas de configuracao (sidebar moderna com hover)
- **AccountWindow**: Janela de perfil (nome + avatar)
- **SoundPlayer**: Sons de notificacao cross-platform

Funcoes utilitarias module-level:
- **_render_color_emoji(char, size)**: Renderiza emoji colorido via PIL + seguiemj.ttf
- **_create_mdl2_icon_static(char, size, color)**: Renderiza icone Segoe MDL2 Assets via PIL
- **_add_hover(widget, normal_bg, hover_bg)**: Adiciona efeito hover a qualquer widget
- **_center_window(win, w, h)**: Centraliza janela na tela
- **_get_icon_path()**: Localiza mbchat.ico em assets/ (dev ou frozen)

Mecanismos importantes:
- **Temas**: 3 temas (Classico, Night Mode, MB Contabilidade) com apply_theme() recursivo
- **Status dots**: PhotoImage pixel-a-pixel para bolinhas de status coloridas
- **Custom scrollbar**: Canvas-based com hover/drag e auto-hide
- **Instancia unica**: TCP socket lock na porta 50199 (loopback)
- **Notificacoes**: winotify com protocolo mbchat:// para click-to-open
- **System tray**: pystray com minimize-on-close
- **Thread safety**: _safe() wrapper com root.after(0, callback)
- **Emojis coloridos**: PIL renderiza com embedded_color=True (seguiemj.ttf). Detecção em tempo real via evento <<Modified>> para capturar inserções de teclado, clipboard e Windows Emoji Picker (Win+.).
- **Canvas scrollavel**: Pattern com create_window + Configure bind para largura total
- **Frame-in-Frame borders**: Outer frame com bg=border_color, inner com padx/pady=1
- **Transmitir Mensagem**: Broadcast com emoji colorido no picker, input e header
- **Bate Papo**: Dialog de selecao de contatos + GroupChatWindow com PanedWindow
- **Icones MDL2**: _create_mdl2_icon_static() para icones profissionais (Segoe MDL2 Assets)
- **Nota pessoal**: Entry no header navy, salva no DB local, sincroniza via UDP announce em tempo real
- **Popups dismissaveis**: Todas as janelas popup fecham com Escape e emoji pickers fecham ao clicar fora

### messenger.py (~360 linhas) - Controller

Classe **Messenger** - orquestra a comunicacao entre camadas:
- Inicializa Database, UDPDiscovery, TCPServer, FileReceiver
- Gera user_id unico via MAC+hostname (generate_user_id())
- Metodos de acao: send_message(), send_file(), change_status(), change_name(), change_note()
- Metodos de grupo: send_group_invite(), send_group_message(), send_file_to_group()
- Recebe eventos da rede e repassa para GUI via callbacks
- Gerencia transferencias de arquivo (FileSender pool, FileReceiver)
- Gerencia estado dos grupos (_groups dict com membros)

### network.py (~680 linhas) - Camada de Rede

Classes de I/O independentes da GUI:
- **UDPDiscovery**: multicast 239.255.100.200:50100 + broadcast fallback
  - Announce loop (5s), cleanup loop (timeout 30s), anti-storm protection
  - Bind com fallback de porta (+10, +20) para PermissionError
  - Buffer UDP 262KB para suportar 30+ peers
- **TCPServer**: aceita conexoes na porta 50101, le frames JSON, backlog 100
- **TCPClient**: metodos estaticos para enviar mensagens JSON
- **FileSender**: envia arquivo em chunks 64KB com progresso (porta 50102)
  - Timeout 120s para aguardar aceite do destinatario
- **FileReceiver**: recebe arquivo com accept/decline handshake

Protocolo:
- Frame TCP: [4 bytes big-endian length][JSON payload UTF-8]
- Tipos UDP: announce (inclui campo note), depart, ping, pong
- Tipos TCP: message, typing, status, file_request, file_accept, file_decline, file_cancel, ack, group_invite, group_message
- File transfer: header JSON -> OKAY/DENY -> raw data chunks
- Group invite: inclui group_id, group_name, lista de membros (uid, display_name, ip)
- Group message: inclui group_id, from_user, display_name, content, timestamp

Seguranca de rede:
- Auto-configuracao de firewall Windows via netsh
- Filtragem por app_id ('mbchat') nos pacotes UDP
- Portas diferentes do LAN Messenger para coexistencia

### database.py (~290 linhas) - Persistencia

Classe **Database** - wrapper SQLite thread-safe:

Tabelas:
- **local_user**: id(=1), user_id, display_name, status, avatar_index, note
- **contacts**: user_id(PK), display_name, ip_address, hostname, os_info, status, note, avatar_index, last_seen, first_seen
- **messages**: id(auto), msg_id, from_user, to_user, content, msg_type, timestamp, is_sent, is_read, is_delivered
- **file_transfers**: file_id(unique), from_user, to_user, filename, filepath, filesize, status, progress
- **settings**: key(PK), value

Thread-safety: threading.local() para conexao por thread, PRAGMA journal_mode=WAL.

### create_icon.py (~35 linhas) - Gerador de Icone

Gera mbchat.ico a partir de mbchat_icon.png (1024x1024 em assets/):
- Carrega PNG, converte para RGBA
- Redimensiona com LANCZOS para 7 resolucoes: 16, 24, 32, 48, 64, 128, 256
- Salva como ICO multi-resolucao em assets/mbchat.ico

### build.py (~50 linhas) - Build Script

PyInstaller --onefile --windowed com:
- Icone embedado de assets/ (--icon + --add-data)
- Hidden imports: messenger, network, database, winotify
- Saida: dist/MBChat.exe

## Fluxos Principais

### Descoberta de Peers
```
1. UDPDiscovery._announce_loop() -> multicast/broadcast JSON
2. Peer recebe -> _handle_packet() -> envia announce de volta
3. Messenger._on_peer_found() -> Database.upsert_contact()
4. GUI._on_user_found() -> adiciona no treeview com status dot
```

### Envio de Mensagem
```
1. Usuario digita + Enter
2. ChatWindow._send_message() -> thread -> Messenger.send_message()
3. TCPClient.send_message() -> TCP:50101 -> peer TCPServer
4. Database.save_message() (ambos os lados)
5. Peer: Messenger._on_tcp_message() -> GUI._on_message()
6. GUI -> ChatWindow.receive_message() + toast notification
```

### Transmitir Mensagem (Broadcast)
```
1. Usuario abre dialog Transmitir Mensagem
2. Seleciona contatos, digita mensagem (com emojis coloridos)
3. _get_bcast_content() reconstroi texto de imagens+texto via dump()
4. Para cada contato selecionado: thread -> Messenger.send_message()
```

### Bate Papo em Grupo
```
1. Usuario abre dialog Bate Papo, seleciona contatos, nomeia grupo
2. _create_group_window() -> abre GroupChatWindow
3. Messenger.send_group_invite() -> envia MT_GROUP_INV para cada membro
4. Cada membro recebe invite -> abre GroupChatWindow
5. Mensagens: Messenger.send_group_message() -> MT_GROUP_MSG para todos
6. Topologia mesh: cada membro envia diretamente para os demais
```

### Transferencia de Arquivo
```
1. Usuario seleciona arquivo -> Messenger.send_file()
2. TCPClient envia FILE_REQUEST via TCP:50101
3. FileSender conecta em TCP:50102 e envia header, aguarda aceite
4. Peer recebe request -> GUI mostra dialogo aceitar/recusar
5. Aceite -> FileReceiver envia OKAY -> FileSender envia dados
6. Progresso atualiza FileTransferDialog em ambos os lados
7. Completo -> dialogo fecha, receptor ve caminho do arquivo salvo
```

### Notificacao Clicavel
```
1. Mensagem chega -> _show_toast(from_user, content)
2. winotify cria toast Windows com launch='mbchat://open/{peer_id}'
3. Usuario clica -> Windows ativa protocolo mbchat://
4. Novo processo: main() detecta arg mbchat://, extrai peer_id
5. Envia 'OPEN:{peer_id}' ao socket 50199 da instancia ativa
6. Instancia ativa: _restore_and_open(peer_id) -> abre chat
```

### Instancia Unica
```
1. main() tenta conectar em 127.0.0.1:50199
2. Se conecta -> outra instancia existe -> envia SHOW -> exit
3. Se falha -> somos a unica instancia -> bind 50199 -> inicia app
4. Listener aceita SHOW/OPEN:{peer_id} -> restaura janela
```

## Decisoes de Design

1. **1 usuario por maquina**: user_id = MAC + hostname, sem login/senha
2. **Portas independentes do LAN Messenger**: 50100-50102 (LAN Messenger usa 50000-50002)
3. **SQLite local, sem servidor central**: cada maquina e independente
4. **tkinter nativo**: zero dependencias de GUI externas
5. **Dependencias opcionais com graceful degradation**: PIL, pystray, winotify
6. **Thread-safe by design**: root.after(), conexao SQL por thread, I/O em threads daemon
7. **Chat limpo ao abrir**: historico acessivel via botao History, chat inicia vazio
8. **Contatos offline persistidos**: PCs ja vistos aparecem como offline no treeview
9. **Firewall auto-config**: netsh na importacao de network.py
10. **Protocolo URL customizado**: mbchat:// registrado em HKCU para notificacoes clicaveis
11. **Grupo mesh**: sem servidor de grupo, cada membro envia para todos os demais via TCP
12. **Emojis coloridos via PIL**: seguiemj.ttf com embedded_color=True para renderizar como imagem. Detecção automática via scans no evento <<Modified>> dos campos de texto.
13. **UI moderna flat**: _add_hover(), Frame-in-Frame borders, navy header, pill buttons
14. **Assets centralizados**: todos os recursos visuais em assets/ (icone, toolbar icons)
