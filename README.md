# MB Chat

**Mensageiro de rede local (LAN) para comunicacao instantanea entre computadores.**
Desenvolvido por **Pedro Paiva** para **MB Contabilidade**.

Substituto moderno do LAN Messenger (C++), reescrito em Python. Executavel standalone que roda em 30+ maquinas Windows simultaneamente, sem servidor central.

---

## Destaques

- **Zero configuracao** - Descoberta automatica de PCs via UDP multicast + broadcast + subnet broadcast
- **Emojis coloridos em todo lugar** - Renderizados via PIL no chat, notas pessoais e lista de contatos
- **Grupos mesh** - Chat em grupo sem servidor central (cada membro envia direto para os demais)
- **Transferencia de arquivos** - Ponto-a-ponto e para grupos, com dialogo de progresso
- **Executavel unico** - `MBChat.exe` funciona sem Python instalado

---

## Funcionalidades

### Mensagens
- Mensagens instantaneas com indicador de digitacao
- Emojis coloridos renderizados via PIL (seguiemj.ttf) em todos os campos
- **Nota pessoal** visivel para todos em tempo real com emojis coloridos
- Historico ilimitado (SQLite local) com pesquisa e filtro por data
- Chat abre limpo; historico completo acessivel via botao History

### Transmitir Mensagem (Broadcast)
- Envio para multiplos contatos selecionados
- Emojis coloridos no input e no picker
- Seletor de fonte e tamanho

### Bate Papo em Grupo
- Dois tipos: **Temporario** e **Fixo**
- Painel lateral de participantes com avatar, nome e nota (com emojis coloridos)
- Splitter arrastavel, envio de arquivo para grupo
- Notificacoes de entrada/saida de membros

### Transferencia de Arquivos
- Ponto-a-ponto com dialogo de progresso (ate 100MB, chunks 256KB)
- Envio para grupo (envia individualmente para cada membro)
- Aceitar/recusar transferencias recebidas

### Interface
- 3 temas visuais: Classico, Night Mode, MB Contabilidade
- Design flat moderno com hover effects e bordas arredondadas (Windows 11+)
- Avatares com 12 presets + foto personalizada sincronizada via rede
- Bolinhas de status: verde (online), amarela (away), vermelha (busy), cinza (offline)
- Lista de contatos com imagem composta PIL (avatar + nome + nota com emojis coloridos)
- Icones MDL2 (Segoe MDL2 Assets) para toolbar profissional
- Todas as janelas fecham com Escape

### Sistema
- Notificacoes Windows 10/11 clicaveis (winotify) - abre direto no chat
- Instancia unica - clicar no exe restaura a janela existente
- System tray com minimizar ao fechar
- Preferencias completas com 9 categorias
- Suporte a 30+ usuarios simultaneos
- Auto-start com o sistema

---

## Instalacao

### Executavel (recomendado)
Basta copiar `dist/MBChat.exe` para a maquina. Nao precisa de Python.

### Desenvolvimento
```bash
cd MBchat
pip install -r requirements.txt
python gui.py
```

### Build
```bash
python build.py
# Saida: dist/MBChat.exe
```

---

## Estrutura do Projeto

```
MBchat/
  gui.py            # Interface (tkinter) - ~5400 linhas
  messenger.py      # Controller - conecta rede, banco e GUI
  network.py        # Rede - UDP discovery, TCP messaging, file transfer
  database.py       # Persistencia - SQLite local (WAL mode)
  build.py          # Build PyInstaller (--onefile --windowed)
  create_icon.py    # Gera .ico multi-resolucao a partir do PNG
  assets/
    mbchat_icon.png  # Logo 1024x1024
    mbchat.ico       # Icone multi-resolucao
    icon_*.png       # Icones de toolbar
  docs/
    ARCHITECTURE.md  # Arquitetura detalhada (4 camadas)
    CODESTYLE.md     # Padroes de codigo e convencoes
```

### Arquitetura (4 camadas)

```
gui.py  ->  messenger.py  ->  network.py
                           ->  database.py
```

Cada camada so conhece a imediatamente abaixo. GUI nunca importa network diretamente.

---

## Portas de Rede

| Porta | Protocolo | Uso |
|-------|-----------|-----|
| 50100 | UDP       | Descoberta (multicast 239.255.100.200 + broadcast + subnet) |
| 50101 | TCP       | Mensagens, typing, status, ACK, file requests, grupos |
| 50102 | TCP       | Transferencia de dados de arquivos |
| 50199 | TCP       | Instancia unica (loopback only) |

> Portas diferentes do LAN Messenger original (50000-50002) para evitar conflito.

---

## Dados Locais

```
Windows: %APPDATA%/.mbchat/
Linux:   ~/.mbchat/

  mbchat.db   - banco SQLite (mensagens, contatos, configuracoes)
  avatars/    - fotos de perfil
```

---

## Troubleshooting

### PC nao descobre outros na rede

1. **Firewall Windows** - Verificar se MBChat tem regra de entrada. Rodar como admin uma vez ou adicionar manualmente:
   ```
   netsh advfirewall firewall add rule name=MBChat dir=in action=allow protocol=UDP localport=50100,50101,50102 profile=any
   netsh advfirewall firewall add rule name=MBChat dir=in action=allow protocol=TCP localport=50100,50101,50102 profile=any
   ```

2. **Antivirus** - Kaspersky, Norton, Avast, etc. podem bloquear o executavel. Adicionar MBChat.exe como excecao.

3. **Multiplas interfaces de rede** - VPN, Hyper-V, Docker criam NICs virtuais que podem confundir a deteccao de IP. Desativar NICs virtuais desnecessarias resolve.

4. **Subnet diferente** - O PC deve estar na mesma subnet dos demais (ex: todos em 192.168.0.x). VLANs separadas nao se comunicam por broadcast.

5. **Porta ocupada** - Verificar com `netstat -an | findstr 50100`. Se outra aplicacao usa a porta, o app faz fallback para porta aleatoria e perde a capacidade de receber broadcasts.

---

## Autor

Desenvolvido por **Pedro Paiva** para MB Contabilidade.
