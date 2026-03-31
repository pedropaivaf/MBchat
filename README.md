# MB Chat

Mensageiro de rede local (LAN) para comunicacao instantanea entre computadores na mesma rede.
Desenvolvido para **MB Contabilidade**. Reescrito em Python com interface tkinter.

## Funcionalidades

- Descoberta automatica de computadores na rede (UDP multicast + broadcast)
- Mensagens instantaneas com indicador de digitacao e emojis coloridos
- **Transmitir Mensagem** (broadcast) para multiplos contatos selecionados
- **Bate Papo em grupo** (mesh TCP, sem servidor central)
- Transferencia de arquivos ponto-a-ponto com dialogo de progresso
- Historico ilimitado de mensagens (SQLite local) com pesquisa e filtro por data
- 3 temas visuais: Classico, Night Mode, MB Contabilidade
- UI moderna com design flat, hover effects e bordas suaves
- Sistema de avatares (12 presets + foto personalizada)
- Notificacoes Windows 10/11 clicaveis (winotify) - abre direto no chat
- Notificacoes sonoras
- Contatos offline persistidos (mostra PCs ja vistos como "offline" com bolinha cinza)
- Bolinhas de status: verde (online), amarela (away), vermelha (busy), cinza (offline)
- Instancia unica - clicar no exe restaura a janela existente
- System tray com minimizar ao fechar
- Preferencias completas com 9 categorias
- Suporte a 30+ usuarios simultaneos
- Auto-start com o sistema (Windows, Linux, macOS)

## Requisitos

- Python 3.10+
- Dependencias: ver `requirements.txt`

## Instalacao

```bash
cd MBchat
pip install -r requirements.txt
```

## Execucao

```
Windows:   run.bat
Linux:     ./run.sh
Direto:    python gui.py
Silencioso: python gui.py --silent
```

## Build (executavel standalone)

```bash
python build.py
```

Gera `dist/MBChat.exe` (PyInstaller --onefile --windowed). O .exe funciona sem Python instalado.

## Estrutura do Projeto

```
MBchat/
  gui.py            # Interface grafica (tkinter) - janelas, temas, treeview, emojis
  messenger.py      # Controller - conecta rede, banco e GUI (inclui grupos)
  network.py        # Camada de rede - UDP discovery, TCP messaging, file transfer
  database.py       # Persistencia - SQLite local com WAL mode
  create_icon.py    # Gerador do icone a partir do PNG (multi-resolucao)
  build.py          # Script de build PyInstaller
  requirements.txt  # Dependencias Python
  run.bat / run.sh  # Launchers
  assets/
    mbchat_icon.png  # Logo principal 1024x1024
    mbchat.ico       # Icone multi-resolucao (gerado por create_icon.py)
    icon_*.png       # Icones de toolbar
  docs/
    ARCHITECTURE.md  # Arquitetura detalhada do sistema
    CODESTYLE.md     # Padroes de codigo e convencoes
```

## Dados Locais

```
Windows: %APPDATA%/.mbchat/
Linux:   ~/.mbchat/

  mbchat.db   - banco SQLite (mensagens, contatos, configuracoes)
  avatars/    - fotos de perfil
```

## Portas de Rede

| Porta | Protocolo | Uso |
|-------|-----------|-----|
| 50100 | UDP       | Descoberta (multicast 239.255.100.200 + broadcast) |
| 50101 | TCP       | Mensagens, typing, status, ACK, file requests, grupos |
| 50102 | TCP       | Transferencia de dados de arquivos |
| 50199 | TCP       | Instancia unica (loopback only) |

> Portas diferentes do LAN Messenger original (50000-50002) para evitar conflito quando ambos rodam simultaneamente.

## Protocolo de Rede

- **Descoberta**: JSON via UDP multicast/broadcast a cada 5s. Campos: app_id, user_id, display_name, ip, status, hostname, os.
- **Mensagens TCP**: Frame = [4 bytes big-endian length][JSON payload UTF-8].
- **Tipos de mensagem**: message, typing, status, ack, file_request, file_accept, file_decline, file_cancel, group_invite, group_message.
- **Grupo**: Topologia mesh - cada membro envia diretamente para todos os outros. Convite inclui lista completa de membros.
- **Transferencia de arquivo**: Header JSON com file_id/filename/filesize, seguido de OKAY/DENY handshake, seguido de dados em chunks de 64KB.

## Firewall

O app tenta adicionar regras automaticamente no Windows Firewall na primeira execucao.
Se falhar, adicione manualmente:

```
netsh advfirewall firewall add rule name=MBChat dir=in action=allow protocol=UDP localport=50100,50101,50102 profile=any
netsh advfirewall firewall add rule name=MBChat dir=in action=allow protocol=TCP localport=50100,50101,50102 profile=any
```
