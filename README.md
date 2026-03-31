# MB Chat

Mensageiro de rede local (LAN) para comunicacao instantanea entre computadores na mesma rede.
Desenvolvido por **Pedro Paiva** para **MB Contabilidade**. Reescrito em Python com interface tkinter.

## Funcionalidades

### Mensagens
- Descoberta automatica de computadores na rede (UDP multicast + broadcast)
- Mensagens instantaneas com indicador de digitacao
- Emojis coloridos renderizados via PIL (seguiemj.ttf)
- **Nota pessoal** visivel para todos em tempo real (persistida no banco local, sincronizada via UDP)
- Historico ilimitado de mensagens (SQLite local) com pesquisa e filtro por data

### Transmitir Mensagem (Broadcast)
- Envio de mensagem para multiplos contatos selecionados
- Suporte a emojis coloridos no input e no picker
- Seletor de fonte e tamanho

### Bate Papo em Grupo
- Chat em grupo estilo LAN Messenger (topologia mesh TCP, sem servidor central)
- Painel lateral de participantes com avatar, nome e nota pessoal (colapsavel)
- Splitter arrastavel entre chat e painel de participantes
- Emoji colorido, alteracao de fonte e envio de arquivo para o grupo
- Adicionar participantes a grupos existentes

### Transferencia de Arquivos
- Envio ponto-a-ponto com dialogo de progresso estilo LAN Messenger
- Envio de arquivo para grupo (envia individualmente para cada membro)
- Aceitar/recusar transferencias recebidas

### Interface
- 3 temas visuais: Classico, Night Mode, MB Contabilidade
- UI moderna com design flat, hover effects e bordas suaves
- Sistema de avatares (12 presets + foto personalizada)
- Bolinhas de status: verde (online), amarela (away), vermelha (busy), cinza (offline)
- Contatos offline persistidos (mostra PCs ja vistos como "offline")
- Popups fecham com Escape, emoji pickers fecham ao clicar fora
- Icones MDL2 (Segoe MDL2 Assets) para toolbar profissional

### Sistema
- Notificacoes Windows 10/11 clicaveis (winotify) - abre direto no chat
- Notificacoes sonoras
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

- **Descoberta**: JSON via UDP multicast/broadcast a cada 5s. Campos: app_id, user_id, display_name, ip, status, note, hostname, os.
- **Mensagens TCP**: Frame = [4 bytes big-endian length][JSON payload UTF-8].
- **Tipos de mensagem**: message, typing, status, ack, file_request, file_accept, file_decline, file_cancel, group_invite, group_message.
- **Nota pessoal**: Campo `note` no pacote UDP announce. Atualiza em tempo real para todos os peers.
- **Grupo**: Topologia mesh - cada membro envia diretamente para todos os outros. Convite inclui lista completa de membros. Suporta adicionar participantes a grupos existentes.
- **Transferencia de arquivo**: Header JSON com file_id/filename/filesize, seguido de OKAY/DENY handshake, seguido de dados em chunks de 64KB. Suporta envio para grupo (envia individualmente para cada membro).

## Firewall

O app tenta adicionar regras automaticamente no Windows Firewall na primeira execucao.
Se falhar, adicione manualmente:

```
netsh advfirewall firewall add rule name=MBChat dir=in action=allow protocol=UDP localport=50100,50101,50102 profile=any
netsh advfirewall firewall add rule name=MBChat dir=in action=allow protocol=TCP localport=50100,50101,50102 profile=any
```

## Autor

Desenvolvido por **Pedro Paiva** para MB Contabilidade.
