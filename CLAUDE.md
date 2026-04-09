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

# Build interativo (menu com opcoes)
python build.py

# Build direto via CLI + deploy para share
python build.py --version 1.3.1 --deploy "\\192.168.0.9\Works2026\Publico\mbchat-update"

# Build + instalador + GitHub Release (pipeline completo)
python build.py --version 1.3.1 --release

# Regenerar icone
python create_icon.py
```

### Workflow de build (menu interativo)

Ao rodar `python build.py` sem argumentos, aparece menu:
1. **Build normal** - builda sem mudar versao, sem deploy
2. **Build + versao + deploy** - pede nova versao, builda e copia para o share
3. **Somente deploy** - envia build existente para o share (sem rebuildar)
4. **Build + versao + GitHub release** - build completo + publica no GitHub
5. **Sair**

### O que o build gera
- `dist/MBChat/` — pasta com `MBChat.exe` + `_internal/` (PyInstaller `--onedir`)
- `dist/MBChat_update.zip` — zip para auto-update (gerado automaticamente)
- `dist/MBChat_Setup.exe` — instalador Inno Setup (compilado automaticamente)

### Versionamento automatico
`_set_version(version)` atualiza 3 arquivos de uma vez:
- `version.py` — APP_VERSION
- `installer.iss` — AppVersion e AppVerName
- `docs/index.html` — versao no hero badge da landing page

**IMPORTANTE**: Build usa `--onedir` (NAO `--onefile`). O `--onefile` causa "Failed to load Python DLL" no Windows 10 porque o loader de DLLs do Win10 nao resolve dependencias dentro da pasta temporaria `_MEI*`. Com `--onedir`, DLLs ficam permanentemente em `_internal/`.

## Arquitetura (4 camadas)

- **gui.py** - Apresentacao tkinter (janelas, temas, treeview, system tray, notificacoes, emojis coloridos)
- **messenger.py** - Controller (orquestra rede + banco + GUI via callbacks, grupos)
- **network.py** - Rede (UDP discovery multicast/broadcast + TCP messaging + file transfer + group msgs)
- **database.py** - SQLite local (mensagens, contatos, configuracoes, WAL mode)

gui.py -> messenger.py -> network.py / database.py (nunca pular camadas)
- **version.py** - Constante APP_VERSION (fonte unica de verdade para versao)
- **updater.py** - Auto-update via GitHub Releases (primario) + pasta compartilhada (fallback). Baixa zip, extrai, aplica via PowerShell

## Portas de rede

- UDP 50100: Discovery (multicast 239.255.100.200 + broadcast + subnet broadcast)
- TCP 50101: Mensagens (inclui group_invite e group_message)
- TCP 50102: File transfer
- TCP 50199: Single-instance lock (loopback)

**IMPORTANTE**: Portas escolhidas para NAO conflitar com LAN Messenger (50000-50002).

## Troubleshooting de rede

Se um PC nao descobre peers:
1. **Firewall**: verificar se MBChat tem regra de entrada (UDP+TCP 50100-50102). Rodar como admin uma vez ou adicionar manualmente via `netsh advfirewall firewall add rule name=MBChat dir=in action=allow protocol=UDP localport=50100,50101,50102 profile=any`
2. **Antivirus**: Kaspersky, Norton, etc. podem bloquear o executavel. Adicionar excecao.
3. **Multiplas NICs**: VPN, Hyper-V, Docker criam interfaces virtuais. get_local_ip() tenta detectar a correta (rota LAN -> 8.8.8.8 -> enumeracao), mas pode pegar a errada. Desativar NICs virtuais resolve.
4. **Subnet diferente**: PC deve estar na mesma subnet /24 dos demais (ex: 192.168.0.x). VLANs separadas nao se comunicam.
5. **Porta ocupada**: Se 50100 esta ocupada, o app tenta +10, +20, depois aleatoria. Porta aleatoria nao recebe broadcasts. Verificar com `netstat -an | findstr 50100`.

## Assets

Todos os recursos visuais ficam em `assets/`:
- `mbchat_icon.png` - Logo principal 1024x1024 (fonte para gerar .ico)
- `mbchat.ico` - Icone multi-resolucao (16,24,32,48,64,128,256px)
- `icon_*.png` - Icones de toolbar (Attach, Emoji, Send, History, etc.)

O `build.py` inclui `assets/mbchat.ico` no bundle via `--add-data`.
O `create_icon.py` gera o .ico a partir do PNG em `assets/`.

## Funcionalidades principais

- **Colar imagem do clipboard (Ctrl+V)** — captura via PIL ImageGrab, comprime JPEG quality=85, envia base64 via MT_IMAGE (TCP), receptor salva em %APPDATA%/.mbchat/images/, exibe thumbnail 300px clicavel no chat. Funciona em chat individual e grupo. Historico mostra [Imagem] clicavel.
- Mensagens individuais com emojis coloridos (PIL + seguiemj.ttf)
- Nota pessoal visivel para todos em tempo real (emojis coloridos via tk.Text, persistida no banco local, sincronizada via UDP)
  - Emoji picker completo com 6 categorias, busca por nome em PT e scroll (mesmo do chat)
- Transmitir Mensagem (broadcast para contatos selecionados) com emojis coloridos
- Criar Grupo com 2 tipos: Temporario e Fixo, ambos aparecem na secao Grupos do TreeView
  - Temporario: fechar janela pergunta se quer sair; "Nao" esconde janela mas permanece no grupo
  - Fixo: fechar janela apenas esconde (permanece no grupo); sair via botao "Sair do Grupo"
  - Notificacoes de entrada/saida: "X entrou no grupo" e "X saiu do grupo" para todos os membros
  - Ao sair: remove participante do painel de todos, remove grupo do TreeView de quem saiu
  - Mensagem de grupo NAO abre janela automaticamente: pisca taskbar + notificacao Windows
  - Clicar na notificacao ou duplo-clique no TreeView abre grupo com foco no input
- Avatares com foto personalizada sincronizada via rede (thumbnail JPEG 48x48 no UDP announce)
  - Recorte circular com antialias 2x (PIL mask), sem borda
  - Fotos quadradas recortadas automaticamente para circulo
- Contatos online em "Geral", offline em secao "Offline" recolhida (sem interacao)
  - Deduplicacao automatica: se mesmo display_name existe com UUIDs diferentes (reinstalacao), mantém apenas o mais recente
- Transferencia de arquivos ponto-a-ponto e para grupos (ate 100MB, chunks 256KB, temp file)
  - Dialogo de transferencia com progresso em MB, velocidade, estado visual
  - Quem envia ve "Envio concluido"; quem recebe ve "Abrir Pasta" + "Fechar"
- Historico com busca em tempo real (tipo Ctrl+F, highlight amarelo) e filtro por data De/Até (dd/mm/aaaa)
  - Chat individual: busca dentro da conversa com o contato
  - Global (menu Ferramentas): busca em TODOS os chats de uma vez, resultados agrupados por contato
- Dois estilos de mensagem (Preferencias): linear (padrao LAN Messenger) e bolhas (estilo WhatsApp)
  - Funciona tanto em chat individual quanto em grupo
  - Bolhas proprias alinhadas a direita (azul claro), peer a esquerda (cinza)
- 3 temas visuais + UI modernizada (flat design, hover effects)
- Bordas arredondadas DWM em todas as janelas (Windows 11+)
- Notificacoes Windows clicaveis (winotify) para chats individuais e grupos
  - Chat individual: `mbchat://open/{peer_id}` — abre chat com mensagens nao lidas do banco
  - Grupo: `mbchat://group/{group_id}` — abre grupo com msgs pendentes
- System tray, instancia unica, auto-start
- Popups e todas as janelas de Chat/Grupos fecham com a tecla Escape chamando logicamente _on_close() para limpeza de estado
- Emoji pickers fecham ao clicar fora
- Scroll dinamico global no listbox ignorando interceptacao de widgets
- Chat individual abre limpo (sem mensagens), mas carrega mensagens nao lidas do banco ao abrir via notificacao. Historico acessivel via botao History. Mensagens novas aparecem em tempo real via receive_message()
- Filtro de contatos respeita UDP announce: _add_contact() verifica busca ativa e re-detacha contatos que nao batem
- **Responder mensagem (Reply/Quote)** — clique direito na mensagem > "Responder", mostra barra de preview acima do input com a mensagem referenciada. Quote aparece no chat com fundo destacado. Funciona em chat individual e grupo. Campo `reply_to_id` no banco, `reply_to` no payload de rede.
- **Mencoes em grupo (@fulano)** — digitar @ no input de grupo abre popup com lista de membros. Selecionar insere @Nome. Mencoes destacadas em azul negrito no chat. Lista de `mentions` (UIDs) no payload MT_GROUP_MSG.
- **Enquete em grupo** — botao na toolbar do grupo abre dialogo para criar enquete (pergunta + opcoes). Exibe no chat com botoes clicaveis para votar. Contagem atualiza em tempo real via MT_POLL_VOTE. Tabelas `polls` e `poll_votes` no banco.
- **Lembretes** — menu Ferramentas > Lembretes. Criar lembrete com texto e data/hora. Timer de 30s verifica pendentes e dispara notificacao Windows (winotify). Tabela `reminders` no banco.
- **Drag & Drop de arquivos** — arrastar arquivo para janela de chat ou grupo inicia transferencia automaticamente. Usa biblioteca `windnd` para detectar drop no Windows.
- **Departamentos/Equipes** — Preferencias > Conta permite selecionar departamento (Fiscal, Contabil, RH, etc). Contatos agrupados por departamento no TreeView (nodes dinamicos). Campo `department` no UDP announce e na tabela `contacts`.
- **Notas privadas nos contatos** — clique direito no contato > "Nota Privada..." abre dialogo para adicionar nota visivel apenas localmente. Coluna `private_note` na tabela `contacts`. Nota aparece no dialogo de informacoes do contato.
- Auto-update via GitHub Releases (primario) + pasta compartilhada (fallback)
  - App consulta GitHub Releases API no startup (2s delay), compara tag_name com APP_VERSION
  - Se versao nova: barra amarela no topo "Atualizacao vX.Y.Z disponivel [Atualizar] [X]"
  - Clique baixa `MBChat_update.zip` do GitHub, extrai para staging dir, script PowerShell substitui pasta inteira e reabre
  - IMPORTANTE: script PowerShell usa `[Diagnostics.Process]::Start` com `UseShellExecute=$false` (CreateProcess) para reabrir — processo filho HERDA env vars do pai (TEMP longo). NUNCA usar `Start-Process`, `start ""` ou `explorer.exe` — usam ShellExecute que ignora env do pai e causa "Failed to load Python DLL" em maquinas com caminho 8.3 no %TEMP% (ex: PEDRO~1.PAI)
  - IMPORTANTE: `_apply_and_restart()` NAO pode ter messagebox antes de `os._exit()` — bloqueia o script e o move falha porque o exe fica travado
  - Menu Ferramentas > "Verificar atualizacoes" para check manual
  - Configuravel em Preferencias > Rede > "Pasta de atualizacao (UNC)"
  - Default: `\\192.168.0.9\Works2026\Publico\mbchat-update` (definido em updater.DEFAULT_SHARE_PATH)
  - Build usa `--noupx` para evitar compressao que corrompe DLLs do VC runtime

## Convencoes importantes

- Threading: NUNCA modificar widgets tkinter fora da main thread. Usar _safe() wrapper.
- Dependencias opcionais: sempre try/except com HAS_* flag (PIL, pystray, winotify, windnd).
- Banco: threading.local() para conexao por thread, parametros ? em SQL.
- Temas: dicts em THEMES com chaves padronizadas de cor.
- Chat abre limpo (sem historico), mas _open_chat() carrega mensagens nao lidas do banco (get_unread_messages) para exibir ao abrir via notificacao. Historico completo acessivel via botao History.
- Contatos offline vao para secao "Offline" do TreeView (group_offline). Bloqueia chat/menu. Deduplicados por display_name no startup (delete_contact remove UIDs obsoletos).
- Grupos: tabelas `groups` e `group_members` no DB, carregados no startup. Todos (temp e fixo) no TreeView com sufixo "(Temporário)" ou "(Fixo)". Sair do grupo roda leave_group() em thread background para nao travar a UI.
- Avatares: `_make_circular_avatar()` (module-level) recorta foto para circulo com antialias 2x. `_create_contact_avatar()` usa avatar_data do peer via rede.
- Emojis coloridos: usar `_render_color_emoji()` (module-level) ou `_render_emoji_image()` (ChatWindow/GroupChatWindow). Sempre strip `\ufe0f` (variation selector) antes de medir bbox — PIL dobra a largura com ele.
  - Tamanhos: lista de contatos 20px, nota pessoal 14px (limite do tk.Text height=1), chat 20px, input 18px.
- Lista de contatos: `_render_contact_display()` gera imagem PIL composta (avatar + nome + nota com emojis coloridos) para cada item do TreeView. Fallback para texto plano se PIL indisponivel.
- Icones MDL2: usar `_create_mdl2_icon_static()` (module-level) para icones Segoe MDL2 Assets.
- Nota pessoal: salva no DB local (update_local_note), sincroniza via campo `note` no UDP announce. Usa tk.Text(height=1) para permitir suporte a imagens de emojis coloridos inline. Emoji picker completo com categorias/busca/scroll (mesmo do ChatWindow).
- Hover effects: usar `_add_hover(widget, normal_bg, hover_bg)` helper.
- Bordas modernas: Frame-in-Frame pattern (outer bg=border_color, inner padx/pady=1).
- Bordas arredondadas: usar `_apply_rounded_corners(win)` apos `_center_window()` em toda Toplevel.
- Layout GroupChatWindow: btn_frame (toolbar+enviar) e input_outer (texto) packam com side='bottom' ANTES do PanedWindow, mesmo padrao do ChatWindow.
- Comentarios no codigo: usar apenas `#` (inline comments), NUNCA `"""docstrings"""`. Docstrings poluem o sistema (help(), __doc__, error traces).
- Auto-update: `updater.py` usa only stdlib (shutil, subprocess, os, zipfile, json, urllib). GitHub Releases como fonte primaria, share como fallback. GUI checa no startup via `check_update_async()` em thread, resultado marshaled via `root.after(0, cb)`. Script PowerShell com retry loop remove `_internal/`, copia novos arquivos e reabre via `[Diagnostics.Process]::Start` com `UseShellExecute=$false` (CreateProcess herda env do pai). NUNCA usar `Start-Process`, `start ""` ou `explorer.exe` — usam ShellExecute que ignora env e causa "Failed to load Python DLL" em maquinas com caminho 8.3. NUNCA colocar messagebox entre `apply_update()` e `os._exit()` — o script roda em paralelo e falha se o exe estiver travado.
- Versionamento: `version.py` contem `APP_VERSION = "X.Y.Z"`. `build.py` atualiza via `--version` flag ou menu interativo. `_set_version()` sincroniza version.py + installer.iss + docs/index.html. Versao exibida no titulo da janela e no "Sobre".

## Tipos de mensagem de rede

Constantes em network.py:
- `MT_MESSAGE`, `MT_TYPING`, `MT_STATUS`, `MT_ACK` - mensagens individuais
- `MT_FILE_REQ`, `MT_FILE_ACC`, `MT_FILE_DEC`, `MT_FILE_CANCEL` - transferencia de arquivos
- `MT_GROUP_INV` - convite para grupo (inclui lista de membros)
- `MT_GROUP_MSG` - mensagem de grupo (mesh: cada membro envia para todos). Campos opcionais: `reply_to`, `mentions`, `msg_id`
- `MT_GROUP_LEAVE` - notificacao de saida do grupo (remove membro do painel de todos)
- `MT_GROUP_JOIN` - notificacao de entrada no grupo (adiciona membro ao painel de todos)
- `MT_IMAGE` - imagem inline (clipboard base64, chat individual e grupo)
- `MT_POLL_CREATE` - cria enquete em grupo (question, options)
- `MT_POLL_VOTE` - voto em enquete (poll_id, option_index)

## Testes

Sem suite de testes automatizados. Testar manualmente:
1. Abrir em 2+ maquinas na mesma rede
2. Verificar descoberta automatica de peers
3. Enviar/receber mensagens
4. Enviar/receber arquivos (verificar dialogo de progresso)
5. Verificar notificacao clicavel (deve abrir o chat)
6. Fechar e reabrir (deve restaurar, nao criar novo processo)
7. Transmitir Mensagem: emojis coloridos, layout responsivo
8. Bate Papo: criar grupo, splitter arrastavel, enviar/receber mensagens de grupo
9. Preferencias: sidebar moderna, botoes com hover
10. Avatares: foto personalizada visivel em todas as maquinas, recorte circular
11. Grupos: temp fecha/permanece, fixo esconde, notificacoes entrada/saida
12. Transferencia: dialogo diferente para quem envia vs quem recebe
13. Auto-update: build com versao nova, verificar barra amarela, clicar Atualizar, confirmar restart
14. Build interativo: `python build.py` → testar opcoes 1, 2 e 3
15. Reply/Quote: clique direito > Responder em chat e grupo, barra de preview, quote no chat
16. Mencoes: digitar @ em grupo, popup de membros, selecionar, highlight no chat
17. Enquete: criar enquete em grupo, votar, contagem atualiza
18. Lembretes: criar, notificacao Windows dispara no horario
19. Drag & Drop: arrastar arquivo para chat e grupo, transferencia inicia
20. Departamentos: configurar em Preferencias, contatos agrupados no TreeView
21. Nota Privada: clique direito no contato, adicionar/editar nota, visivel no Info

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

### 4. BUILD + RELEASE (OBRIGATORIO quando subir versao)

**PIPELINE COMPLETO — executar TODOS os passos em sequencia, sem parar no meio:**

1. `python build.py --version X.Y.Z --release`
   - Atualiza version.py + installer.iss + docs/index.html
   - Gera MBChat.exe via PyInstaller --onedir
   - Gera MBChat_update.zip (usado pelo auto-update)
   - Compila MBChat_Setup.exe via Inno Setup
   - Cria/atualiza GitHub Release vX.Y.Z com zip + instalador como assets
2. `git add` dos arquivos modificados
3. `git commit` com mensagem descritiva (SEM Co-Authored-By, SEM mencao a AI)
4. `git push origin main`

**IMPORTANTE**: Sem o GitHub Release com assets, o auto-update dos 30+ PCs NAO funciona. NUNCA fazer apenas commit+push sem o release. O comando `python build.py --version X.Y.Z --release` faz tudo automaticamente.

**Gatilhos**: Executar este pipeline sempre que o usuario pedir qualquer variacao de: "subir versao", "enviar ao github", "sobe pro github", "push", "bump de versao", "atualiza", "manda pro github", "release", "publica". Na duvida, executar o pipeline completo.

Se der erro de build, corrigir e rodar de novo.

### Regras gerais
- Ser o MAIS AUTONOMO possivel. Fazer tudo sem perguntar, sem esperar confirmacao
- NUNCA perguntar "quer que eu faca X?" — ja faz
- NUNCA explicar o que VAI fazer em 10 paragrafos — faz e mostra o resumo depois
- Respostas curtas e diretas, sem enrolacao
- Se eu mandar screenshot de erro, corrigir direto sem pedir mais contexto
- NUNCA adicionar "Co-Authored-By" ou qualquer referencia a Claude/AI nos commits, PRs, releases ou qualquer parte do projeto. Autoria e exclusivamente de Pedro Paiva (pedropaivaf). Nenhuma menção a assistente de IA em nenhum lugar.
