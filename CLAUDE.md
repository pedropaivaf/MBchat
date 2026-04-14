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
python build.py --version 1.4.11 --deploy "\\192.168.0.9\Works2026\Publico\mbchat-update"

# Build + instalador + GitHub Release (pipeline completo)
python build.py --version 1.4.11 --release

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
- **updater.py** - Auto-update via GitHub Releases. Baixa zip, extrai, aplica via PowerShell

## Portas de rede

- UDP 50100: Discovery (multicast 239.255.100.200 + broadcast + subnet broadcast)
- TCP 50101: Mensagens (inclui group_invite e group_message)
- TCP 50102: File transfer
- TCP 50199: Single-instance lock (loopback)

**IMPORTANTE**: Portas escolhidas para NAO conflitar com LAN Messenger (50000-50002).

## Descoberta de peers (por que MBChat e mais confiavel que LAN Messenger)

LAN Messenger tem bug conhecido onde peers somem da lista em redes com VPN, Hyper-V, switches gerenciados ou filtros de multicast. MBChat resolveu com 5 decisoes que trabalham juntas — **NAO afrouxar** nenhuma delas sem entender o impacto:

1. **Tri-broadcast** em `_send_announce()` (network.py:348): cada announce sai por 3 caminhos — multicast `239.255.100.200`, broadcast global `255.255.255.255` e subnet-directed broadcast (`_get_subnet_broadcast()`). Se multicast for filtrado, os broadcasts garantem entrega. Para sumir, as 3 rotas teriam que falhar.
2. **Anuncio imediato em eventos** (network.py:295-316): `update_status`/`update_name`/`update_note`/`update_avatar` chamam `_send_announce()` na hora, sem esperar o ciclo.
3. **Anuncio no startup** (network.py:283): primeiro announce sai antes do loop periodico, peer recem-aberto aparece instantaneamente.
4. **Deteccao correta de NIC** em `get_local_ip()`: rota real pro 8.8.8.8 + enumeracao + filtro de interfaces virtuais. Evita bug classico de sair pela NIC da VPN.
5. **Ciclo curto** (`DISCOVERY_INTERVAL = 15`, `PING_TIMEOUT = 45`): refresh a cada 15s, timeout 3x maior que o intervalo. **NAO aumentar para 60s estilo LAN Messenger** — o usuario reclama e quer manter presenca responsiva. Para reduzir carga, usar cache no receptor (ex: `_contact_render_cache` em gui.py:_add_contact), nao aumentar intervalo.

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

- **Colar imagem do clipboard (Ctrl+V)** — captura via PIL ImageGrab + fallback ctypes CF_DIBV5/CF_DIB (Win10 compat), comprime JPEG quality=85, mostra preview bar acima do input antes de enviar. Envia base64 via MT_IMAGE (TCP), receptor salva em %APPDATA%/.mbchat/images/, exibe thumbnail 300px clicavel no chat (abre no visualizador do Windows via thread background). Funciona em chat individual e grupo. Historico mostra [Imagem] clicavel. Clique na imagem no chat NAO dispara menu "Responder/Copiar" (flag `_img_click_handled`).
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
  - "Mostrar Pasta" usa `explorer /select, filepath` via subprocess.Popen (nao os.startfile)
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
  - **v1.4.54**: para o clique no corpo do toast dispatchar o `launch`, Windows exige que o `app_id` do winotify seja um AUMID registrado via atalho Start Menu. Constante `APP_AUMID = 'MBContabilidade.MBChat'` (mesma do `SetCurrentProcessExplicitAppUserModelID`) usada em todas as chamadas `WinNotification`. `_ensure_start_menu_shortcut()` cria `%APPDATA%\Microsoft\Windows\Start Menu\Programs\MB Chat.lnk` apontando pro exe atual e injeta `System.AppUserModel.ID = APP_AUMID` via `IPropertyStore` (pywin32 `propsys` + `pscon.PKEY_AppUserModel_ID`). Roda so em frozen (`sys.frozen`), chamado em `main()` apos `_register_url_protocol()`. Idempotente — sobrescreve a cada startup. Toasts tambem recebem `notif.add_actions(label='Abrir', launch=...)` como fallback redundante (botao de acao e mais confiavel que clique no corpo). Hidden imports `win32com.client`, `win32com.propsys`, `win32com.shell`, `pythoncom` adicionados em `build.py`.
- **Preferencias** — Aba Alertas tem 3 secoes em grid 2 colunas: **Notificacoes** (notif_msg_private, notif_msg_group, notif_msg_broadcast, notif_file, notif_reminder), **Sons** (sound_master mestre + sound_msg_private, sound_msg_group, sound_msg_broadcast, sound_file_start, sound_file_done, sound_reminder), **Piscar na barra de tarefas** (flash_taskbar_msg, flash_taskbar_file, flash_reminder). Aba Transferencia de arq. tem apenas "Salvar arquivos em" — recebimento e automatico por padrao. Migracao automatica das chaves antigas (`sound`→`sound_master`, `sound_msg`→`sound_msg_private`, `notif_windows`→`notif_msg_private`, `flash_taskbar`→`flash_taskbar_msg`). Gates reais: `SoundPlayer._gate()` consulta `sound_master` + chave especifica; `_show_toast` gateia `notif_msg_private`/`notif_msg_broadcast` (via flag `is_broadcast` no payload); `_show_group_toast` gateia `notif_msg_group`; `_on_file_incoming` gateia `notif_file` + `sound_file_start`; `_on_file_complete` gateia `sound_file_done`; `_flash_window(gate_key=...)` aceita a chave como parametro — `_on_message`/`_on_image`/`_on_group_message` usam `flash_taskbar_msg`, `_on_file_incoming` usa `flash_taskbar_file`, `_check_reminders` usa `flash_reminder`. Arquivo recebido e lembrete disparado piscam taskbar igual mensagens. Aba **Geral** tem toggles reais: `show_main_on_start` (main() faz `withdraw()` se off), `tray_icon` (`_start_tray` nao cria icone se off), `minimize_on_close` (quando on, X minimiza via `_show_in_taskbar_minimized` em vez de ir pro tray), `balloon_notify` (helper `_balloon_notify` gateia as 5 chamadas `_tray_icon.notify(...)` em `_show_toast`/`_show_toast_generic`/`_show_group_toast`/`_check_reminders`).
- **Taskbar LAN Messenger-style** — AppUserModelID (`MBContabilidade.MBChat`) agrupa todas as janelas (root + ChatWindow + GroupChatWindow) sob o mesmo icone na taskbar, hover mostra thumbnails nativos (DWM live preview). Cada Toplevel recebe `WS_EX_APPWINDOW` via `_force_taskbar_entry()` para ter entrada propria na taskbar mesmo com root withdrawn. **IMPORTANTE**: `_force_taskbar_entry` so faz o ciclo `SW_HIDE`+`SW_SHOWNA` se `winfo_ismapped()` — em janela withdrawn (start_hidden=True) pula o SW_SHOWNA, senao causa flash visivel de 1 frame no centro da tela. Quando mensagem chega com app no tray, `_surface_chat_from_tray()` cria a janela oculta (`start_hidden=True` → `withdraw()` no __init__), aplica estilo sem SW_SHOWNA, minimiza via `SW_SHOWMINNOACTIVE` (Win32 direto, NAO tkinter deiconify) e pisca SOMENTE a propria janela com `FlashWindowEx(hwnd_da_janela)`. **Root NAO pisca** — `_on_message`/`_on_image`/`_on_group_message` so chamam `self._flash_window(cw|gw)` com a janela especifica; nunca `self._flash_window()` sem argumento (que piscaria root). Cada janela pisca individualmente ate o usuario clicar; bind `<Map>` em ChatWindow/GroupChatWindow dispara `_on_chat_window_mapped`/`_on_group_window_mapped` que para o flash daquela janela e limpa unread quando restaurada via thumbnail. Ao fechar uma janela de chat (X), a conversa da sessao zera — mensagens ficam apenas no historico. **FileTransferDialog e transient(root)**: quando root vai pro tray (withdraw), tkinter esconde os transient children junto — se dialog nao foi destruido explicitamente, reaparece quando root e restaurado. `_on_close` destroi todos `self._file_dialogs` ativos antes de withdraw/iconify/quit para evitar que dialogs "fantasma" voltem ao abrir o app. Compativel Win10 (1809+) e Win11 — todas as APIs Win32 (SetCurrentProcessExplicitAppUserModelID, SetWindowLongW, ShowWindow, FlashWindowEx) existem desde Win2000/Win7.
- System tray, instancia unica, auto-start
- Popups e todas as janelas de Chat/Grupos fecham com a tecla Escape chamando logicamente _on_close() para limpeza de estado
- Emoji pickers fecham ao clicar fora
- Scroll dinamico global no listbox ignorando interceptacao de widgets
- Chat individual abre limpo (sem mensagens), mas carrega mensagens nao lidas do banco ao abrir via notificacao. Historico acessivel via botao History. Mensagens novas aparecem em tempo real via receive_message()
- Filtro de contatos respeita UDP announce: _add_contact() verifica busca ativa e re-detacha contatos que nao batem
- **Responder mensagem (Reply/Quote)** — clique direito na mensagem > "Responder", mostra barra de preview acima do input com nome do remetente (azul negrito) + texto da mensagem (estilo WhatsApp). Quote aparece no chat com fundo destacado. Funciona em chat individual e grupo. Campo `reply_to_id` no banco, `reply_to` no payload de rede.
- **Mencoes em grupo (@fulano)** — digitar @ no input de grupo abre popup com lista de membros. Selecionar insere @Nome. Mencoes destacadas em azul negrito no chat. Lista de `mentions` (UIDs) no payload MT_GROUP_MSG.
- **Enquete em grupo** — botao na toolbar do grupo abre dialogo para criar enquete (pergunta + opcoes). Exibe no chat com botoes clicaveis para votar. Contagem atualiza em tempo real via MT_POLL_VOTE. Tabelas `polls` e `poll_votes` no banco.
- **Lembretes** — menu Ferramentas > Lembretes. Tres tipos: **Simples** (sem data, lista amarela ate concluir/excluir, `add_reminder(text, 0)`), **Programado** (calendario + HH:MM, single-shot, `add_reminder(text, remind_at)`), **Recorrente pattern-based** (diario/semanal/mensal/anual com intervalo N + fim never/count/date, `add_pattern_reminder(text, start_ts, rule_json)`). `recurrence_rule` TEXT na tabela `reminders` guarda JSON `{type, interval, weekdays, end, occurrences_done}`. `_compute_next_occurrence` (database.py:24) calcula proxima ocorrencia para cada tipo — weekly escaneia dia a dia respeitando interval de semanas; monthly faz clamp via `calendar.monthrange` (dia 31 + 3 meses -> 30/abr); yearly trata 29/fev com fallback `ValueError` -> dia 28. `reschedule_recurring_reminder` incrementa `occurrences_done`, salva proximo `remind_at`, desativa (`is_active=0`) ao atingir fim. `toggle_reminder_active` pausa/retoma e re-agenda ao reativar. Timer de 10s `_check_reminders` busca `get_pending_reminders()`, dispara notif winotify + sound + flash taskbar (gates `notif_reminder`, `sound_reminder`, `flash_reminder` em Preferencias > Alertas). Dialog recorrente em `_new_recurring_reminder_dialog` (gui.py:9564) usa layout 2 colunas (Titulo + Horario lado a lado, Padrao radios + A cada N, Comeca em + Termino), botoes **Criar/Cancelar fixos no rodape** via `pack(side='bottom')` direto no dlg (nao no body), checkboxes de dias da semana packed com `before=sep` so aparecem em weekly. Spinbox de minutos usa `increment=1`. A partir de v1.4.54 o clique na notificacao abre a tela de lembretes corretamente (corrigido via AUMID + atalho Start Menu + action button, igual mensagens individuais).
- **Date picker reusavel** — `_create_date_picker(parent, initial_date)` (gui.py:9385) retorna dict `{'frame', 'get_date', 'set_date'}` com Entry readonly + botao dropdown que abre Toplevel `overrideredirect(True)` com calendario 7x6, nav de mes, destaque de hoje/selecionado, botao "Hoje". **Flip-up automatico**: mede `winfo_reqheight()` apos `update_idletasks()` e posiciona o popup ACIMA do entry se nao couber pra baixo. Usado em "Começa em" e "Em (termino)" do dialog recorrente.
- **Drag & Drop de arquivos** — arrastar arquivo para janela de chat ou grupo inicia transferencia automaticamente. Usa biblioteca `windnd` para detectar drop no Windows.
- **Departamentos/Equipes** — Preferencias > Conta permite selecionar departamento. Opcoes (ordem alfabetica, com "(Nenhum)" como sentinela): (Nenhum), Administrativo, CS, Comercial, Contabil, Fiscal, Marketing, Pessoal, Processos, Recepcao, TI. Departamento ainda existe e agrupa contatos em secoes do TreeView, mas o badge visual `[Setor]` foi substituido pelo `[Ramal]` a partir de v1.4.53. Campo `department` no UDP announce (enviado E recebido) e na tabela `contacts`. Mudanca no combo aplica na hora via `_on_dept_changed` -> `discovery.update_department()` -> announce imediato.
- **Ramal (v1.4.53)** — Campo de 4 digitos numericos no header da tela principal (ao lado de status) salvo em `local_user.ramal` no DB e propagado via `ramal` no UDP announce. Exibido como badge `[1234]` em azul ao lado do nome no TreeView (substitui o badge de Departamento). Validacao `isdigit() and len==4` em `messenger.change_ramal()`. Vazio = badge some. `self.ramal_var` inicializado vazio em `_build_ui` e populado em `_deferred_init` (messenger so existe apos `after_idle`). Agrupamento por departamento continua intocado.
- **Links clicaveis (v1.4.53)** — `_URL_RE` regex detecta `https?://...` e `www....` no corpo das mensagens. `_insert_text_with_emojis` refatorado para dividir texto em segments URL/nao-URL antes de renderizar emojis; URLs recebem tag `link_N` com `foreground='#0066cc'`, `underline=True`, cursor `hand2` e `tag_bind('<Button-1>', _open_url)`. `_open_url` (module helper) faz strip de `.,);]!?` trailing, prepende `http://` em `www.` e chama `webbrowser.open`. Aplicado em ChatWindow e GroupChatWindow.
- **Copiar rapido no hover (v1.4.53, area ampliada em v1.4.54)** — Cada mensagem em `_append_message` ganha tag `msg_N`. A partir de v1.4.54 a tag cobre `header_start -> body_end` (nome + horario + corpo inteiro do balao), de forma que o hover dispara em qualquer ponto visual da mensagem; antes cobria so o corpo. Marks `mstart_N`/`mend_N` (ChatWindow) / `gmstart_N`/`gmend_N` (GroupChat) continuam apontando para `body_start`/`body_end` para preservar o modo selecao (long-press so sobre o corpo). `_msg_ranges_idx` guarda tuplas `(start_mark, end_mark)` e `_msg_data` guarda `{msg_id, sender, text, is_mine, timestamp}`. Um unico `_hover_copy_btn` (`tk.Label` com icone MDL2 `\uE8C8` cinza minimalista) e reusado por janela, placed via `place(in_=chat_text)`. `tag_bind('<Enter>')` mostra; `<Leave>` agenda `_schedule_hover_hide(180ms)` que e cancelado pelo `<Enter>` no botao. Clique copia `_msg_data[idx]['text']` e da feedback visual `\u2714` por 600ms.
- **Input adaptativo (v1.4.54)** — Campo `self.entry` em ChatWindow e GroupChatWindow inicia com `height=1` e cresce conforme o usuario digita. `_on_modified` chama `_adjust_input_height()` que usa `self.entry.count('1.0','end-1c','displaylines')` (respeita wrap de palavra) para contar linhas visuais, clampa em `[1, 8]` e atualiza `self.entry.configure(height=n)` se mudou. Fallback: conta `\n` em `get` se o `count()` falhar. Ao enviar, `delete('1.0','end')` dispara `<<Modified>>` → altura volta a 1. Acima de 8 linhas, a caixa para de crescer e volta a rolar internamente para nao empurrar o chat. Reply bar e image preview bars continuam packadas com `side='bottom', after=self._input_outer` — o resize da entry propaga pro `_input_outer` e empurra o chat_text pra cima automaticamente.
- **Modo selecao multi-mensagem (v1.4.53)** — Long-press 500ms sobre msg entra em modo selecao. `<ButtonPress-1>` agenda `after(500, _long_press_fire)`; `<B1-Motion>` com threshold 5px cancela (preserva drag-to-select nativo); `<ButtonRelease-1>` cancela. `_long_press_fire` limpa tag `sel` e chama `_enter_selection_mode(idx)`. Barra top-docked azul `_build_selection_bar` com contagem + botoes Copiar/Encaminhar/Cancelar (pack `before=chat_text.master`). Mensagens selecionadas recebem tag `selected_msg` com background `#fff3b0`. Em modo selecao, `<ButtonPress-1>` toggla via `_find_msg_idx_at_xy`+`_toggle_msg_selection` e retorna `'break'`. Escape sai do modo. **Copiar**: junta `[HH:MM] Nome: texto` em clipboard. **Encaminhar**: `_open_forward_dialog` com Listbox de peers online + grupos abertos; envia com prefixo `[Encaminhada]` via `messenger.send_message`/`send_group_message`. Context menu de right-click tem entry "Selecionar" que entra em modo selecao com a msg clicada ja marcada. Implementado tanto em ChatWindow quanto GroupChatWindow (metodos duplicados intencionalmente, mesma logica).
- Auto-update via GitHub Releases (fonte unica — fallback por pasta UNC compartilhada foi removido em v1.4.46)
  - App consulta GitHub Releases API no startup (2s delay), compara tag_name com APP_VERSION
  - Se versao nova: barra amarela no topo "Atualizacao vX.Y.Z disponivel [Atualizar] [X]"
  - Clique baixa `MBChat_update.zip` do GitHub, extrai para staging dir, script PowerShell substitui pasta inteira e reabre
  - IMPORTANTE: script PowerShell usa `[Diagnostics.Process]::Start` com `UseShellExecute=$false` (CreateProcess) para reabrir — processo filho HERDA env vars do pai (TEMP longo). NUNCA usar `Start-Process`, `start ""` ou `explorer.exe` — usam ShellExecute que ignora env do pai e causa "Failed to load Python DLL" em maquinas com caminho 8.3 no %TEMP% (ex: PEDRO~1.PAI)
  - IMPORTANTE: `_apply_and_restart()` NAO pode ter messagebox antes de `os._exit()` — bloqueia o script e o move falha porque o exe fica travado
  - Menu Ferramentas > "Verificar atualizacoes" para check manual
  - Build usa `--noupx` para evitar compressao que corrompe DLLs do VC runtime

## Convencoes importantes

- Threading: NUNCA modificar widgets tkinter fora da main thread. Usar _safe() wrapper.
- Dependencias opcionais: sempre try/except com HAS_* flag (PIL, pystray, winotify, windnd).
- Banco: threading.local() para conexao por thread, parametros ? em SQL.
- Temas: dicts em THEMES com chaves padronizadas de cor.
- Chat abre limpo (sem historico), mas _open_chat() carrega mensagens nao lidas do banco (get_unread_messages) para exibir ao abrir via notificacao. Historico completo acessivel via botao History.
- **Ponto unico de entrega de mensagens individuais recebidas**: `messenger._on_tcp_message` chama `db.save_message()` ANTES de disparar o callback `on_message`. Consequencia: quando `_open_chat(surface_only=True)` cria a janela, ele ja carrega a mensagem recem-chegada via `get_unread_messages`. Portanto, o callback `gui._on_message`/`_on_image` NAO deve chamar `cw.receive_message()`/`cw.receive_image()` depois de `_open_chat(surface_only=True)` — isso duplica a msg (bug corrigido em v1.4.51). Regra: no branch de criacao de janela por surface, apenas `_open_chat` — ele cuida do display. No branch "janela ja existe" (peer em `self.chat_windows`), chamar `receive_message`/`receive_image` e correto, pois a janela nao e recriada e `get_unread_messages` nao e lido. **Grupos seguem contrato diferente**: usam buffer `_pending_group_msgs` em memoria (nao DB). `_open_group` pop'a esse buffer ao criar a janela; `_on_group_message` NAO deve empurrar para o buffer antes do surface e DEVE chamar `gw.receive_message` na lambda `_create` apos o surface (caso contrario a msg e perdida). Nao misturar os dois padroes.
- Contatos offline vao para secao "Offline" do TreeView (group_offline). Bloqueia chat/menu. Deduplicados por display_name no startup (delete_contact remove UIDs obsoletos).
- Grupos: tabelas `groups` e `group_members` no DB, carregados no startup. Todos (temp e fixo) no TreeView com sufixo "(Temporário)" ou "(Fixo)". Sair do grupo roda leave_group() em thread background para nao travar a UI.
- Avatares: `_make_circular_avatar()` (module-level) recorta foto para circulo com antialias 2x. `_create_contact_avatar()` usa avatar_data do peer via rede.
- Emojis coloridos: usar `_render_color_emoji()` (module-level) ou `_render_emoji_image()` (ChatWindow/GroupChatWindow). Sempre strip `\ufe0f` (variation selector) antes de medir bbox — PIL dobra a largura com ele.
  - Tamanhos: lista de contatos 20px, nota pessoal 14px (limite do tk.Text height=1), chat 20px, input 18px.
- Lista de contatos: `_render_contact_display()` gera imagem PIL composta (avatar + nome + badge departamento + nota com emojis coloridos) para cada item do TreeView. Param `dept` para badge `[Setor]` em azul. Fallback para texto plano se PIL indisponivel.
- Icones MDL2: usar `_create_mdl2_icon_static()` (module-level) para icones Segoe MDL2 Assets.
- Nota pessoal: salva no DB local (update_local_note), sincroniza via campo `note` no UDP announce. Usa tk.Text(height=1) para permitir suporte a imagens de emojis coloridos inline. Emoji picker completo com categorias/busca/scroll (mesmo do ChatWindow).
- Hover effects: usar `_add_hover(widget, normal_bg, hover_bg)` helper.
- Bordas modernas: Frame-in-Frame pattern (outer bg=border_color, inner padx/pady=1).
- Bordas arredondadas: usar `_apply_rounded_corners(win)` apos `_center_window()` em toda Toplevel.
- Layout GroupChatWindow: btn_frame (toolbar+enviar) e input_outer (texto) packam com side='bottom' ANTES do PanedWindow, mesmo padrao do ChatWindow. `self._input_outer` salvo como atributo de instancia para referencia no pack de barras dinamicas (reply bar, image preview).
- Barras dinamicas (reply, image preview): usar `pack(fill='x', side='bottom', after=self._input_outer)` para posicionar acima do input. Com `side='bottom'`, `after=widget` coloca visualmente ACIMA.
- Imagens no chat: `os.startfile()` DEVE rodar em `threading.Thread(daemon=True)` — pode travar/crashar tkinter na main thread. Clique em imagem usa flag `_img_click_handled` para impedir menu "Responder/Copiar" (tkinter tag_bind NAO propaga `return 'break'` de lambdas).
- Clipboard paste (Ctrl+V): bindar AMBOS `<Control-v>` e `<Control-V>` (CapsLock). `_grab_clipboard_image()` tenta PIL ImageGrab, depois CF_DIBV5 (format 17), depois CF_DIB (format 8) com header BMP de 14 bytes prepended.
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
20. Departamentos: configurar em Preferencias, badge [Setor] visivel no TreeView de todos os peers

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
