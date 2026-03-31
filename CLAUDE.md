# CLAUDE.md - Contexto do Projeto MB Chat

## O que e este projeto

MB Chat e um mensageiro de rede local (LAN) para MB Contabilidade. Funciona como o LAN Messenger
(C++) mas reescrito em Python. O executavel standalone (MBChat.exe) roda em 30+ maquinas Windows
simultaneamente sem servidor central.

## Como buildar e rodar

```bash
# Desenvolvimento
pip install -r requirements.txt
python gui.py

# Build do executavel
python build.py
# Saida: dist/MBChat.exe

# Regenerar icone
python create_icon.py
```

## Arquitetura (4 camadas)

- **gui.py** - Apresentacao tkinter (janelas, temas, treeview, system tray, notificacoes, emojis coloridos)
- **messenger.py** - Controller (orquestra rede + banco + GUI via callbacks, grupos)
- **network.py** - Rede (UDP discovery multicast/broadcast + TCP messaging + file transfer + group msgs)
- **database.py** - SQLite local (mensagens, contatos, configuracoes, WAL mode)

gui.py -> messenger.py -> network.py / database.py (nunca pular camadas)

## Portas de rede

- UDP 50100: Discovery (multicast 239.255.100.200)
- TCP 50101: Mensagens (inclui group_invite e group_message)
- TCP 50102: File transfer
- TCP 50199: Single-instance lock (loopback)

**IMPORTANTE**: Portas escolhidas para NAO conflitar com LAN Messenger (50000-50002).

## Assets

Todos os recursos visuais ficam em `assets/`:
- `mbchat_icon.png` - Logo principal 1024x1024 (fonte para gerar .ico)
- `mbchat.ico` - Icone multi-resolucao (16,24,32,48,64,128,256px)
- `icon_*.png` - Icones de toolbar (Attach, Emoji, Send, History, etc.)

O `build.py` inclui `assets/mbchat.ico` no bundle via `--add-data`.
O `create_icon.py` gera o .ico a partir do PNG em `assets/`.

## Funcionalidades principais

- Mensagens individuais com emojis coloridos (PIL + seguiemj.ttf)
- Transmitir Mensagem (broadcast para contatos selecionados) com emojis coloridos
- Bate Papo em grupo (mesh TCP, sem servidor) com GroupChatWindow
- Transferencia de arquivos ponto-a-ponto
- Historico com busca e filtro por data
- 3 temas visuais + UI modernizada (flat design, hover effects)
- Notificacoes Windows clicaveis (winotify)
- System tray, instancia unica, auto-start

## Convencoes importantes

- Threading: NUNCA modificar widgets tkinter fora da main thread. Usar _safe() wrapper.
- Dependencias opcionais: sempre try/except com HAS_* flag (PIL, pystray, winotify).
- Banco: threading.local() para conexao por thread, parametros ? em SQL.
- Temas: dicts em THEMES com chaves padronizadas de cor.
- Chat abre limpo (sem historico). Historico acessivel via botao History.
- Contatos offline persistem no DB e aparecem com bolinha cinza.
- Emojis coloridos: usar `_render_color_emoji()` (module-level) ou `_render_emoji_image()` (ChatWindow).
- Hover effects: usar `_add_hover(widget, normal_bg, hover_bg)` helper.
- Bordas modernas: Frame-in-Frame pattern (outer bg=border_color, inner padx/pady=1).

## Tipos de mensagem de rede

Constantes em network.py:
- `MT_MESSAGE`, `MT_TYPING`, `MT_STATUS`, `MT_ACK` - mensagens individuais
- `MT_FILE_REQ`, `MT_FILE_ACC`, `MT_FILE_DEC`, `MT_FILE_CANCEL` - transferencia de arquivos
- `MT_GROUP_INV` - convite para grupo (inclui lista de membros)
- `MT_GROUP_MSG` - mensagem de grupo (mesh: cada membro envia para todos)

## Testes

Sem suite de testes automatizados. Testar manualmente:
1. Abrir em 2+ maquinas na mesma rede
2. Verificar descoberta automatica de peers
3. Enviar/receber mensagens
4. Enviar/receber arquivos (verificar dialogo de progresso)
5. Verificar notificacao clicavel (deve abrir o chat)
6. Fechar e reabrir (deve restaurar, nao criar novo processo)
7. Transmitir Mensagem: emojis coloridos, layout responsivo
8. Bate Papo: criar grupo, enviar/receber mensagens de grupo
9. Preferencias: sidebar moderna, botoes com hover

## Workflow obrigatorio para TODA alteracao

SEMPRE que eu pedir qualquer mudanca, seguir estes passos automaticamente:

### 1. PLANEJAR (antes de tocar codigo)
- Listar quais arquivos serao editados e o que muda em cada um
- Mostrar em 3-5 linhas o plano resumido
- Se a mudanca for ambigua, perguntar ANTES de codar

### 2. EXECUTAR (editar tudo de uma vez)
- Seguir ordem: database.py -> network.py -> messenger.py -> gui.py
- Manter consistencia de nomes entre camadas (mesmo callback, mesma assinatura)
- Editar TODOS os arquivos necessarios em sequencia, sem parar no meio

### 3. VERIFICAR (depois de editar)
- Rodar `python -c "import gui; import messenger; import network; import database"` para checar imports
- Se der erro, corrigir imediatamente sem perguntar
- Mostrar resumo do que foi feito (quais arquivos, quantas linhas)

### 4. BUILD (se a mudanca afetar funcionalidade)
- Rodar `python build.py` para gerar MBChat.exe
- Se der erro de build, corrigir e rodar de novo

### Regras gerais
- NUNCA perguntar "quer que eu faca X?" — ja faz
- NUNCA explicar o que VAI fazer em 10 paragrafos — faz e mostra o resumo depois
- Respostas curtas e diretas, sem enrolacao
- Se eu mandar screenshot de erro, corrigir direto sem pedir mais contexto
- Commits so quando eu pedir explicitamente
