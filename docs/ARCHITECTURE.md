# MB Chat - Arquitetura

## Visao Geral

Arquitetura em 4 camadas com separacao clara de responsabilidades:

```
+---------------------------------------------+
|                  gui.py                      |
|         Apresentacao (View)                  |
|   tkinter: janelas, menus, widgets,          |
|   treeview de contatos, chat windows,        |
|   file transfer dialogs, system tray         |
+----------------------+-----------------------+
                       | callbacks (_safe wrapper)
+----------------------v-----------------------+
|              messenger.py                    |
|         Controller / Orquestrador            |
|   Liga rede <-> banco <-> GUI               |
|   Gerencia estado do usuario local           |
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

### gui.py (~2500 linhas) - Apresentacao

Classes principais:
- **LanMessengerApp**: Janela principal (menu, contatos treeview, toolbar, status bar, temas)
- **ChatWindow**: Conversa individual com peer (envio de msg/arquivo, historico)
- **FileTransferDialog**: Dialogo de progresso de transferencia (estilo LAN Messenger)
- **PreferencesWindow**: 9 abas de configuracao
- **AccountWindow**: Janela de perfil (nome + avatar)
- **SoundPlayer**: Sons de notificacao cross-platform

Mecanismos importantes:
- **Temas**: 3 temas (Classico, Night Mode, MB Contabilidade) com apply_theme() recursivo
- **Status dots**: PhotoImage pixel-a-pixel para bolinhas de status coloridas
- **Custom scrollbar**: Canvas-based com hover/drag e auto-hide
- **Instancia unica**: TCP socket lock na porta 50199 (loopback)
- **Notificacoes**: winotify com protocolo mbchat:// para click-to-open
- **System tray**: pystray com minimize-on-close
- **Thread safety**: _safe() wrapper com root.after(0, callback)

### messenger.py (~290 linhas) - Controller

Classe **Messenger** - orquestra a comunicacao entre camadas:
- Inicializa Database, UDPDiscovery, TCPServer, FileReceiver
- Gera user_id unico via MAC+hostname (generate_user_id())
- Metodos de acao: send_message(), send_file(), change_status(), change_name()
- Recebe eventos da rede e repassa para GUI via callbacks
- Gerencia transferencias de arquivo (FileSender pool, FileReceiver)

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
- Tipos UDP: announce, depart, ping, pong
- Tipos TCP: message, typing, status, file_request, file_accept, file_decline, file_cancel, ack
- File transfer: header JSON -> OKAY/DENY -> raw data chunks

Seguranca de rede:
- Auto-configuracao de firewall Windows via netsh
- Filtragem por app_id ('mbchat') nos pacotes UDP
- Portas diferentes do LAN Messenger para coexistencia

### database.py (~290 linhas) - Persistencia

Classe **Database** - wrapper SQLite thread-safe:

Tabelas:
- **local_user**: id(=1), user_id, display_name, status, avatar_index, note
- **contacts**: user_id(PK), display_name, ip_address, hostname, os_info, status, last_seen, first_seen
- **messages**: id(auto), msg_id, from_user, to_user, content, msg_type, timestamp, is_sent, is_read, is_delivered
- **file_transfers**: file_id(unique), from_user, to_user, filename, filepath, filesize, status, progress
- **settings**: key(PK), value

Thread-safety: threading.local() para conexao por thread, PRAGMA journal_mode=WAL.

### create_icon.py (~120 linhas) - Gerador de Icone

Reproduz o logo corporativo MB Contabilidade:
- Fundo azul escuro (#0c1a3d) com cantos arredondados
- "MB" branco em fonte bold (Arial Bold / Impact)
- Faixa vermelha diagonal (marca corporativa)
- Faixa azul diagonal paralela (acento)
- Supersampling ate 20x para tamanhos pequenos (16px, 24px)
- Gera ICO com 7 resolucoes: 16, 24, 32, 48, 64, 128, 256

### build.py (~50 linhas) - Build Script

PyInstaller --onefile --windowed com:
- Icone embedado (--icon + --add-data)
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
