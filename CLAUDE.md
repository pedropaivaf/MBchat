# CLAUDE.md - Contexto do Projeto MB Chat

## O que e este projeto

MB Chat e um mensageiro de rede local (LAN) para MB Contabilidade. Executavel standalone (MBChat.exe) roda em 30+ maquinas Windows simultaneamente sem servidor central. Python + tkinter. Versao atual: 1.8.11.

## Arquitetura (4 camadas)

```
gui.py -> messenger.py -> network.py / database.py
```

- **gui.py** (~5400 linhas) - Apresentacao tkinter (janelas, temas, treeview, tray, emojis coloridos)
- **tools/theme_builder.py** (~680 linhas) - Janela Toplevel para criar/editar temas customizados, persistencia em `%APPDATA%\.mbchat\user_themes.json`
- **messenger.py** (~360 linhas) - Controller (orquestra rede + banco + GUI via callbacks, grupos)
- **network.py** (~730 linhas) - Rede (UDP discovery multicast/broadcast + TCP messaging + file transfer)
- **database.py** (~290 linhas) - SQLite local (WAL mode, threading.local)
- **version.py** - APP_VERSION (fonte unica de verdade)
- **updater.py** - Auto-update via GitHub Releases
- **build.py** - Build interativo (PyInstaller --onedir + Inno Setup + GitHub Release)

Regra: gui.py -> messenger.py -> network.py / database.py (nunca pular camadas)

## Portas de rede

- UDP 50100: Discovery (multicast 239.255.100.200 + broadcast + subnet broadcast)
- TCP 50101: Mensagens (inclui group_invite e group_message)
- TCP 50102: File transfer
- TCP [50200-51199]: Single-instance lock **por usuario Windows** (loopback). Porta = 50200 + MD5(getpass.getuser().lower()) mod 1000. v1.4.64+ - evita colisao entre logins diferentes na mesma maquina.

## Como buildar e rodar

```bash
# Dev
pip install -r requirements.txt
python gui.py

# Build interativo (menu com opcoes)
python build.py

# Build + deploy para share
python build.py --version X.Y.Z --deploy "\\192.168.0.9\Works2026\Publico\mbchat-update"

# Build + instalador + GitHub Release (pipeline completo)
python build.py --version X.Y.Z --release
```

**IMPORTANTE**: Build usa `--onedir` (NAO `--onefile`). O `--onefile` causa "Failed to load Python DLL" no Win10.

## Workflow obrigatorio para TODA alteracao

### 1. PLANEJAR
- Listar quais arquivos serao editados e o que muda em cada um
- Mostrar plano resumido em 3-5 linhas
- Se ambiguo, perguntar ANTES

### 2. EXECUTAR
- Ordem: database.py -> network.py -> messenger.py -> gui.py
- Manter consistencia de nomes entre camadas
- Editar TODOS os arquivos necessarios em sequencia

### 3. VERIFICAR
- Rodar `python -c "import gui; import messenger; import network; import database"`
- Se erro, corrigir imediatamente

### 4. BUILD + RELEASE (quando subir versao)
1. `python build.py --version X.Y.Z --release` (faz tudo: version, build, installer, GitHub Release)
2. `git add` dos arquivos modificados
3. `git commit` com mensagem descritiva
4. `git push origin main`

**Gatilhos**: "subir versao", "push", "bump", "release", "publica", "manda pro github"

## Convencoes criticas

- **Threading**: NUNCA modificar widgets tkinter fora da main thread. Usar _safe() wrapper
- **Dependencias opcionais**: sempre try/except com HAS_* flag (PIL, pystray, winotify, windnd)
- **Banco**: threading.local() para conexao por thread, parametros ? em SQL
- **Comentarios**: usar apenas `#`, NUNCA `"""docstrings"""`
- **Commits**: NUNCA "Co-Authored-By" ou referencia a Claude/AI. Autoria exclusiva de Pedro Paiva
- **Auto-update**: PowerShell usa `[Diagnostics.Process]::Start` com `UseShellExecute=$false`. NUNCA `Start-Process` ou `explorer.exe`
- **Versionamento**: `_set_version()` atualiza version.py + installer.iss + docs/index.html de uma vez
- **VPN (v1.4.63+)**: tabela `manual_peers` + setting `vpn_enabled` (default OFF). Lista vazia + OFF = zero overhead no caminho LAN. `_manual_announce_loop` + `MT_PEER_LIST` peer exchange propagam a LAN a partir de 1 IP ancora. NAO alterar defaults. Toggle via **Ferramentas > Conectar fora da LAN (VPN)**.

## Regras gerais

- Ser AUTONOMO. Fazer tudo sem perguntar, sem esperar confirmacao
- NUNCA perguntar "quer que eu faca X?" â€” ja faz
- Respostas curtas e diretas
- Se screenshot de erro, corrigir direto

## Workflow de changelog (ao lancar nova versao)

Apos o build+release, atualizar o changelog no cofre Obsidian:
1. Abrir ~/obsidian-cofre/Projetos/MB-Contabilidade/MB Chat - Changelog.md
2. Adicionar entrada no topo (abaixo do separador ---) no formato:
   ## vX.Y.Z ï¿½ DD/MMM/AAAA ï¿½ EMOJI Tipo
   Descricao curta da mudanca
3. Atualizar campo versao-atual no frontmatter
4. Atualizar estatisticas (total de versoes, por tipo)
5. O plugin Obsidian Git faz commit+push automatico a cada 5 min

Tipos: Major Feature, Feature, Bugfix, Refactor, Build, Docs, UI, Performance, QA, Hotfix, UX
Emojis: ver legenda no proprio changelog

## Blindagem de rede e auto-fix de firewall (v1.4.59)

Tres camadas foram adicionadas para tornar falhas de discovery visiveis e auto-recuperaveis:

1. **Log rotativo de rede** em `%APPDATA%\.mbchat\network.log` â€” RotatingFileHandler 1MB x 3 backups.
   Grava cada bind/IGMP join, stats de send/recv, erros engolidos. Fail-safe (NullHandler se IO falhar).
   Acessado via `network._log()` â€” uma unica linha por evento, nunca levanta excecao para caller.

2. **Health dict** em `UDPDiscovery.health` (network.py:201) com `bound_port`, `bind_fallback`,
   `multicast_joined`, `packets_sent`, `packets_received`, `sendto_errors`, `last_peer_seen_at`,
   `started_at`, `bind_errors`. Exposto via `get_health()` que adiciona `uptime` e `peers_count`
   on-the-fly. Todos os contadores sao incrementados nos pontos que antes tinham `except: pass`
   silencioso â€” zero impacto no caminho feliz, instrumentacao pura.

3. **Banner de diagnostico** na janela principal (gui.py `_update_health_banner`). Rearma a cada 30s.
   - **VERMELHO** se `bind_fallback=True` (porta UDP 50100 ocupada, cai em porta aleatoria â€” discovery quebrado)
   - **AMARELO** se uptime>30s, pacotes enviados>0, mas zero recebidos (firewall inbound bloqueado)
   - **AMARELO** se uptime>60s, multicast nao joinado e nenhum peer (rede filtrando)
   - Nos PCs saudaveis o banner NUNCA aparece (condicionais sao `and not healthy`).

4. **Auto-fix de firewall via UAC** (primeira execucao pos-update). `_check_firewall_on_startup`
   roda 4s apos o _deferred_init, em thread background, so em build frozen. Chama
   `network.firewall_rules_present()` (checa regras canonicas "MBChat UDP In" e "MBChat TCP In"
   via `netsh show rule name=X`). Se ausentes, main thread mostra messagebox pedindo permissao;
   se user aceita, `network.request_firewall_rules_elevated()` usa `ctypes.windll.shell32.ShellExecuteW`
   com verbo `runas` para disparar UAC e rodar `cmd /c netsh delete... & netsh add rule...` elevado.
   Cria regras **por porta** (50100,50110,50120 UDP + 50101,50102 TCP). Single-instance roda em loopback per-user, nao precisa regra firewall.
   Deleta primeiro qualquer regra existente para o exe atual (limpa Blocks residuais do Defender).
   Cooldown de 24h em `firewall_prompt_dismissed_at` do DB para nao importunar quem recusa.
   Apos sucesso, `_hide_health_banner()` e messagebox de confirmacao.

5. **Menu Ferramentas > Diagnostico de rede** (`_open_network_diag` em gui.py) abre Toplevel com
   health dict formatado, lista de peers conhecidos, ultimas 60 linhas do `network.log`,
   botoes **Copiar tudo** (clipboard), **Atualizar**, **Fechar**. Reusa `_center_window` e
   `_apply_rounded_corners`.

6. **tools/fix_firewall.bat** â€” Script standalone para casos extremos: executa como admin,
   deleta todas as regras MBChat, recria Allow Inbound por porta, reinicia o MBChat.
   Enviar por WhatsApp se o auto-fix via UAC falhar ou for recusado.

   **Fix manual via Painel de Controle** (se user recusar UAC e nao quiser rodar .bat):
   `Painel de Controle > Sistema e Seguranca > Windows Defender Firewall > Aplicativos permitidos`
   > Alterar configuracoes > marcar **MBChat** em **Particular** e **Publico**. Se nao aparecer
   na lista, `Permitir outro aplicativo... > Procurar... > MBChat.exe` (em `%LOCALAPPDATA%\Programs\MBChat\`
   ou `C:\Program Files\MBChat\`). Documentado na landing (`docs/index.html#doc-firewall`) e
   em `docs/DECISIONS.md`.

7. **tools/sniff_mbchat.py** â€” Sniffer UDP 50100 passivo, standalone, diagnostico remoto.
   Lista todos os peers anunciando na LAN com IP src vs IP declarado (detecta `get_local_ip()` bugado).
   Rodar com MBChat local fechado. Usado para confirmar se PC com problema esta enviando/recebendo.

**Hipotese confirmada v1.4.59**: 2 PCs de 30 ficaram invisiveis (lista vazia) porque nao tinham
regras de firewall inbound. Reinstalacao + apagar `%APPDATA%\.mbchat` nao resolve â€” o Windows
Defender Firewall nao re-pergunta "Permitir?" ao user e o installer roda com `PrivilegesRequired=lowest`
(sem admin, nao consegue criar regras via netsh). O `_add_firewall_rule()` em network.py:40 tambem
falha silenciosamente sem admin. Diagnostico feito via `Test-NetConnection` do PC do Pedro:
TCP 50101 `TcpTestSucceeded: False`, `PingSucceeded: True` â†’ inbound bloqueado, L2/L3 ok.
Sniffer confirmou que PC problematico envia UDP announces normalmente (outbound ok) mas nao recebe
nada (inbound bloqueado). **Nao alfroxar** `_add_firewall_rule()` ou o `except Exception: pass` â€”
o problema nao e o codigo tentar silenciosamente, e a falta de feedback ao user quando falha.
O auto-fix via UAC e a solucao definitiva: pede permissao uma vez, cria regras por porta, resolve.

## Theme Builder + temas dinamicos (v1.5.0)

Janela em **Preferencias > Aparencia > Tema > Criar tema personalizado...** permite ao usuario
montar temas custom (40+ tokens de cor: bg/fg/bordas/bolhas/header/status), persistidos em
`%APPDATA%\.mbchat\user_themes.json`. Ao abrir o app, `gui.py` faz merge aditivo dos temas
salvos no dict global `THEMES` (sem sobrescrever os 3 fixos: Classico, Night Mode, MB
Contabilidade â€” protegidos via `BUILTIN_THEMES`).

Mudancas estruturais que vieram junto:

1. **`apply_theme` propaga globais** (gui.py:8758) â€” `BG_WINDOW`, `BG_WHITE`, `BG_HEADER`,
   `FG_BLACK`, etc. agora sao reescritas globalmente a cada troca de tema. Janelas reabertas
   (Preferences, Builder, Diagnostico) reconstroem com a paleta atual.

2. **`PreferencesWindow` respeita o tema** â€” sidebar/categorias leem `app._theme` no `__init__`
   e usam `_sweep_theme()` recursivo apos cada `_select_category` para forcar `fg/bg` em
   `Label`, `Labelframe`, `Checkbutton`, `Radiobutton`, `Entry` (muitos `_build_*` nao
   passavam `fg` explicito â€” em Night Mode ficavam pretos sobre fundo escuro).

3. **`PreferencesWindow` reabre ao mudar tema** â€” o `_save_all` detecta `theme` mudou,
   chama `apply_theme` e faz `self.destroy() + PreferencesWindow(app, initial_tab=idx)`
   com delay 100ms (preserva aba atual via `_current_idx`). Mesmo comportamento no
   `_open_theme_builder` quando o builder retorna com tema novo aplicado.

4. **`ThemeBuilderWindow` se adapta ao tema do host** â€” le `app._theme` no `__init__` e
   monta dict `self.ui` (panel/window/border/text/muted/accent/etc.) usado em toda a UI
   principal. **Preview interno permanece usando `self.tokens`** (mostra o tema sendo
   construido, nao o tema do host).

5. **Temas fixos completados** â€” Classico e Night Mode ganharam as keys que faltavam
   (`msg_my_bg`, `msg_peer_bg`, `hover`, `accent`, `online`, `away`, `busy`,
   `offline_color`, `select_border`). Night Mode reformulado com contraste serio
   (texto `#e8e8e8` sobre `#1e1e1e`, accent `#7cb8f0`). MB Contabilidade **intacto**
   como tema principal/default.

**Contrato com `app` host (`tools/theme_builder.py`)**: builder chama apenas `app._theme`
(dict â€” opcional), `app.THEMES` (dict global â€” opcional, propaga tema novo) e
`app.apply_theme(name)` (so no Salvar e Aplicar). Se algum nao existir, builder degrada
sem crashar. `LanMessengerApp.__init__` expoe `self.THEMES = THEMES` (gui.py:8419) para
que o builder propague o tema novo no mesmo dict que `apply_theme` consulta.

**Validacao no JSON salvo**: regex `^#[0-9a-fA-F]{6}$` â€” `rgb(...)` ou nomes sao rejeitados.
Chaves ausentes herdam do `MB_DEFAULT` (fallback completo). JSON corrompido nao crasha
(`load_user_themes()` retorna `{}` + log).

## UX fixes v1.5.1

1. **Barra de acoes "Transmitir | Criar Grupo" redesenhada** (gui.py:9115-9175).
   Antes: dois tk.Button pill coloridos (`#1a3f7a`) com emojis ðŸ“¢/ðŸ’¬ acima da caixa de notas.
   Agora: **rodape** abaixo do note_row, duas celulas 50/50 com grid uniforme, divider
   horizontal sutil acima e divider vertical fino entre elas, fundo transparente NAVY, icones
   line (`â€¢))` em `#7cb8f0` para Transmitir como aÃ§Ã£o primaria, `ðŸ‘¥` para Criar Grupo), hover
   em `#1a3f7a`. Layout compacto (fontes 8-10pt, pady=3) pra liberar ~20px verticais e mostrar
   mais contatos na lista sem scroll.

2. **ChatWindow abre direto no centro** (gui.py:3102-3104, fim de `__init__`).
   Janela nasce `withdraw()`, `_center_window` aplica posicao, todos os widgets empacotam
   escondidos, `update_idletasks()` + `deiconify()` no final. Elimina o flash no canto
   superior esquerdo que acontecia quando o WM do Windows mostrava a janela antes da
   geometry final. Se `start_hidden=True` (surfacing via tray), `deiconify` no fim e pulado â€”
   caller continua responsavel.

3. **Emoji picker posicionado dinamicamente acima do input** (gui.py:5531-5559).
   Altura entre 200-300px (calculada via `entry_top - win_top - 60`), gap de 40px acima do
   `self.entry.winfo_rooty()`. `popup.withdraw()` -> setup completo -> `deiconify()` â€” sem
   flash no canto. Grid 8 cols x 34px, rolavel com `bind_all('<MouseWheel>')`.

4. **Theme Builder: scroll global + centralizado** (tools/theme_builder.py:284-308, 388-411).
   Janela nasce `withdraw()`, centraliza com `winfo_screenwidth/height`, mostra pronta.
   Scroll do mouse funciona em qualquer widget do painel esquerdo (swatches, labels, canvas
   area): `_bind_wheel_recursive(left_wrap)` aplica `<MouseWheel>` em todos os descendentes.

5. **Scrollbar minimalista na janela Lembretes** (gui.py:12246-12369). Substituiu
   `ttk.Scrollbar` por Canvas 6px com thumb arredondado (oval + retangulo), hover muda para
   10px em tom `#94a3b8`, auto-hide quando conteudo cabe (`lo<=0 && hi>=1`). MouseWheel
   ignora scroll se nao ha overflow â€” previne "rolar pra vazio" quando tem so 1 item.

## Historico estilo LAN Messenger + fix mensagens sumindo (v1.5.3)

Usuarios relataram que mensagens antigas "sumiam" do chat individual e da janela global de historico.
Investigacao mostrou 2 limites hardcoded + 1 UX confusa:

1. **ChatWindow `_load_history`** (gui.py:3590) carregava so as ultimas 40 msgs ao abrir chat â€”
   contatos com historico mais longo tinham mensagens antigas invisiveis. **Fix**: `limit=None` â€”
   carrega TODAS as mensagens do par ao abrir. `get_chat_history(limit=None)` em database.py
   ja suportava e retornava em ordem ASC.

2. **`search_all_messages`** (database.py:719) com default `limit=500` â€” em escritorio de 30
   pessoas, ~2 semanas de uso ja passam disso e mensagens antigas ficavam fora de busca.
   **Fix**: `limit=None` suportado (SQL sem clausula LIMIT), default subiu pra 5000.

3. **Janela Historico redesenhada estilo LAN Messenger** (gui.py:11088 `_show_all_history`).
   Antes mostrava apenas resumo de contatos (nome + data ultima msg) ate o usuario filtrar â€”
   confuso, parecia que nao tinha mensagens. Agora: 2-pane horizontal (900x600), Treeview
   de contatos a esquerda (320px, ordenado por last_ts DESC), painel de conversa a direita
   com TODAS as mensagens do contato selecionado em ordem cronologica ASC. Busca por palavra
   refiltra lista de contatos + destaca matches em amarelo. Filtros De/Ate com validacao
   visual (fundo `#fee2e2` + label "data invalida" / "periodo invalido" se De > Ate).

4. **Performance da filtragem**: adicionados 2 helpers em database.py que usam SQL DISTINCT/COUNT
   em vez de carregar tudo na memoria:
   - `get_peers_with_match(search_text, date_from, date_to)` â€” retorna set de peer_ids que tem
     match. DISTINCT CASE no SQL, rapido mesmo em DBs com 100k+ msgs.
   - `count_matching_messages(...)` â€” COUNT(*) no SQL, leve.

   Com esses dois, o filtro do Historico **nao tem mais limite** de mensagens inspecionadas â€”
   qualquer mensagem antiga aparece na busca. Zero risco de "sumir".

**Contrato**: `db.get_messages_with_peer(user_a, peer_id, date_from, date_to, search_text)`
ja retornava TODAS as mensagens com o peer sem limite, entao o painel direito sempre mostra
o historico completo. Schema de `messages` intocado, zero migration.

## Documentacao detalhada

Para detalhes alem deste resumo, consultar:
- `docs/ARCHITECTURE.md` - Arquitetura completa, fluxos, classes, protocolo de rede
- `docs/CODESTYLE.md` - Padroes de codigo, nomenclatura, temas, threading
- `docs/DECISIONS.md` - Decisoes tecnicas, troubleshooting, discovery robusto
- `docs/FEATURES.md` - Lista completa de funcionalidades com detalhes de implementacao

## Estabilização de Identidade e Notificações (v1.6.8 / v1.6.9)

1. **Notificações Independentes (v1.6.8)**: 
   - Substituição de focus_displayof() por _window_is_foreground (Win32 API GetForegroundWindow).
   - Garante que cada janela de chat pisque independentemente na barra de tarefas, parando apenas quando aquela janela específica ganha foco real no Windows.

2. **User ID Persistente (v1.6.9)**: 
   - O user_id agora é salvo na tabela local_user do banco de dados SQLite.
   - Em vez de gerar um novo ID a cada troca de interface de rede (Wi-Fi vs Ethernet), o app reutiliza o ID persistente. Isso evita a fragmentação do histórico e o surgimento de usuários fantasmas.

3. **Histórico de Grupos (v1.6.9)**: 
   - Adicionado seletor Contatos / Grupos na janela de histórico global.
   - Carregamento de histórico para grupos fixos com resolução de nomes dos remetentes (armazenados no campo file_path de mensagens de grupo).
   - Correção do bug de mensagens sumidas: Janelas individuais agora carregam o histórico completo ao abrir, garantindo visibilidade total de respostas enviadas anteriormente.

## Fix VPN PPTP + Botão Remover (v1.8.12)

Três bugs de código impediam que o notebook em home-office (PPTP VPN) visse colegas da LAN (`Peers conhecidos: 0`):

1. **Relay quebrado — MCAST_GRP (network.py:790)**
   - Constante `MCAST_GRP` não existe; o nome correto é `MULTICAST_GROUP`.
   - O `NameError` era silenciado pelo `try/except`, então o relay da âncora para a LAN **nunca funcionava**.
   - Fix: substituir por `MULTICAST_GROUP`.

2. **Respostas VPN iam para porta efêmera (network.py:774)**
   - `_sock_send` (socket de envio) não tem bind explícito → OS atribui porta aleatória (ex.: 54321).
   - A âncora respondia com `port=addr[1]` = 54321, mas `_sock_recv` escuta **apenas em 50100**.
   - Resultado: todas as respostas dos 27 PCs da LAN eram perdidas → `Peers conhecidos: 0`.
   - Fix: `port=addr[1]` → `port=UDP_PORT` no VPN handshake reply.

3. **Botão "Remover" invisível na janela VPN (gui.py `_open_vpn_peers`)**
   - `btns.pack(side='bottom')` era chamado **depois** de `body.pack(fill='both', expand=True)`.
   - O `body` com `expand=True` consumia todo o espaço; `btns` ficava com 0px de altura.
   - Fix: separar criação de `body` do `.pack()`, empacotar `btns` antes de `body.pack()`.
   - Adicionado: ao remover o último peer, VPN é desativada automaticamente (`set_vpn_enabled(False)`).

**Limitação de rede (não código):** se o roteador do escritório não rotear `10.0.0.x` de volta ao cliente PPTP, LAN → notebook TCP falha. O notebook sempre consegue iniciar mensagens (via túnel). Não alterar a lógica de relay para contornar isso sem testar.

**Teste automatizado:** `test_vpn_fixes.py` — 11 checks, inclui teste comportamental com sockets reais no localhost que confirma a resposta chegando em `UDP_PORT=50100` e nada na porta efêmera.

## Plano de Hardening de Segurança (v1.8.13 — pendente)

Análise completa da superfície de ataque revelou que qualquer PC na mesma LAN pode forjar mensagens, envenenar roteamento via UDP announce falso e fazer spam sem rate limit. Ameaça realista: funcionário mal-intencionado ou curioso na rede interna.

**9 fixes planejados (NÃO implementados ainda):**

1. **IP Pinning UDP (network.py `_handle_packet`)** — se `ip` declarado no announce diverge do IP real do socket, corrige para o real. Elimina envenenamento de roteamento.

2. **IP Pinning TCP (messenger.py `_on_tcp_message`)** — verifica que `from_user` veio do IP cadastrado para esse user_id. Rejeita silenciosamente se divergir. Exceção: peers VPN com `ts_ip`.

3. **Rate Limiting por IP (network.py)** — janela deslizante 10s/10 pacotes UDP por IP. Máximo 30 conexões TCP/min por IP. Previne DDoS interno.

4. **Replay Protection (network.py / messenger.py)** — rejeita `MT_MESSAGE`, `MT_FILE_OFFER`, `MT_MEETING_INVITE` com timestamp > 120s no passado ou > 30s no futuro. Não aplica a `MT_ANNOUNCE`.

5. **HMAC com Chave de Rede (network.py + database.py + gui.py)** — chave gerada em `secrets.token_hex(32)` na primeira execução, salva em settings `network_hmac_key`. Campo `sig` em cada pacote. Modo degradado (aceita sem `sig`) para rollout gradual. UI em Ferramentas > Segurança de Rede para copiar/colar chave entre PCs.

6. **MT_PEER_LIST Subnet Filter (network.py)** — rejeita IPs fora da subnet /24 local, Tailscale (100.x.x.x) ou manual_peers cadastrado. Usa `ipaddress.ip_network`.

7. **Validação IP em manual_peers (database.py)** — `ipaddress.ip_address(ip)` antes de INSERT. Rejeita hostnames e strings inválidas.

8. **Block List (database.py + messenger.py + gui.py)** — nova tabela `block_list`. Clique direito em contato → "Bloquear usuário". Ferramentas > Usuários Bloqueados para gerenciar. Peer bloqueado some da lista e é ignorado em todos os handlers.

9. **SHA256 no Auto-Update (updater.py + build.py)** — `build.py` publica hash no release body. `updater.py` verifica antes de aplicar. Abort com `showerror` se divergir.

**Fora do escopo:** TLS no TCP, SQLCipher, PKI/ECDSA por usuário.

## Superpoderes Admin + Senha Segura (v1.8.18 — WIP, NÃO lançada ainda)

Commit: `a3a0363` — branch main, aguardando validação e release pelo usuário.

### O que foi implementado (gui.py + network.py)

**Senha admin segura (substituiu hardcode `1234512345`):**
- **Primeiro acesso:** formulário "Defina uma senha para esta instalação" — cada instalação tem senha própria
- Hash SHA256 salvo em `db.get_setting('admin_password_hash')` via `database.py`
- Login normal: compara SHA256(entrada) com hash salvo
- **Reset:** criar arquivo vazio `%APPDATA%\.mbchat\admin_reset` → na próxima abertura do Admin, hash é apagado e volta ao formulário de criação
- Botão "Mudar Senha Admin" visível no painel desbloqueado (seção Segurança)

**Monitor de versões:**
- `network.py`: campo `'version': pkt.get('version', '')` adicionado ao dict `peer_info` nos dois lugares onde ele é montado (announce direto ~linha 864 e peer_list ~linha 808)
- Cada peer card no Admin mostra `v{versão}` em cinza (atualizado) ou **vermelho** (desatualizado vs `APP_VERSION`)

**Auditoria de conversas (por peer card):**
- Botão "Ver conversa" → Toplevel read-only com histórico completo (todos os `get_messages_with_peer`)
- Botão "Exportar" → `filedialog.asksaveasfilename` → TXT com timestamps `[dd/mm/yyyy HH:MM] Remetente: texto`

**Busca global de mensagens:**
- Seção "Busca em Todas as Conversas" após stats row
- Campo Entry + botão Buscar (ou Enter) → `db.search_all_messages(q, limit=200)`
- Resultados agrupados por contato (até 10 peers, até 3 msgs por peer)
- Após renderizar resultados: chama `_bind_wheel(inner)` para manter scroll funcionando

**Superadmin de grupos:**
- Seção "Grupos Ativos": cada grupo tem botões "Ver membros" e "Deletar"
- "Ver membros" → Toplevel com lista (★ = admin)
- "Deletar" → `messenger.delete_group_globally(gid)` — funciona para qualquer grupo, não só os criados pelo admin

### O que FALTA para fechar v1.8.18
- Validação manual completa: senha (primeiro acesso → login → mudar → reset), monitor versão com peer desatualizado, busca, exportar TXT, grupos
- Após validação: `git commit` de qualquer ajuste + `python build.py --version 1.8.18 --release`
- Notas de release humanizadas para o sino do app

## Transferencia de Arquivos — Fixes de file_port + Persistencia da Lista (commit fd9961e)

### Fix file_port dinamico (network.py + messenger.py)

**Problema:** `FileSender` sempre conectava em `peer_ip:50102` (hardcoded `TCP_PORT+1`). Se a porta 50102 estiver ocupada na maquina do destinatario, o `FileReceiver` faz bind em porta fallback (50112, 50122...) e o sender conecta num port errado → "Connection refused" imediato → status "Erro".

**Causa raiz confirmada em producao:** PC de usuario interno — `TcpTestSucceeded: False` na porta 50102, firewall bloqueando inbound TCP 50102.

**Fix implementado:**
1. `network.py _make_packet`: adiciona `'file_port': getattr(self, 'file_port', TCP_PORT+1)` ao announce UDP
2. `network.py _handle_packet` MT_ANNOUNCE e MT_PEER_LIST: armazena `file_port` no `peer_info` em memoria
3. `messenger.py start()`: inicia `_file_receiver` ANTES do discovery, seta `discovery.file_port = receiver.port`
4. `messenger.py send_file()`: usa `discovery.peers[uid].get('file_port', TCP_PORT+1)` em vez de hardcode
5. `network.py FileSender._send`: `sock.connect((ip, self.peer_port))` — `peer_port` ja e a porta de arquivo (sem +1)

**Backward compat:** peers com versao antiga nao enviam `file_port` → fallback para `TCP_PORT+1 = 50102`.

### Persistencia da janela Ferramentas > Transferencia de Arquivos

**Problema:** `_transfer_history` era lista em memoria — ao fechar e reabrir o app a lista ficava em branco. Arquivos recebidos nunca eram salvos no DB (so enviados eram).

**Fix implementado:**
- `database.py`: `get_file_transfers(own_user_id)` e `clear_file_transfers()`
- `messenger.py _on_file_request`: salva arquivo RECEBIDO no DB via `save_file_transfer()` antes de chamar callback
- `gui.py _load_transfer_history_from_db()`: carrega registros do DB em `_transfer_history` no `_deferred_init`. Status `pending` (app fechou antes de completar) vira `error`.
- `gui.py FileTransfersWindow._clear_all()`: chama `db.clear_file_transfers()` alem de limpar memoria
- `gui.py _open_folder_selected()` + `_open_entry_file()`: usa `subprocess.Popen(['explorer', '/select,', normpath])` para abrir Explorer com arquivo marcado (antes abria so a pasta)
- `gui.py _add_entry_widget`: `<Double-Button-1>` chama `_open_entry_file` — duplo clique abre no Explorer

### Fix permanente de firewall no instalador (installer.iss)

**Problema:** `PrivilegesRequired=lowest` = instalador sem admin = nao conseguia criar regras de firewall = alguns PCs ficavam sem as regras (Cassiana foi um caso real).

**Fix:** `PrivilegesRequired=admin` + secao `[Run]` com 4 entradas `netsh` que criam as regras silenciosamente durante a instalacao. `[UninstallRun]` remove as regras ao desinstalar.

**Auto-update NAO afetado:** updater.py baixa zip e substitui arquivos via PowerShell — nunca usa o instalador .exe para updates.

**Para diagnosticar/fixar PC com porta bloqueada remotamente (admin de dominio):**
```powershell
# Testa conectividade
Test-NetConnection -ComputerName IP_DO_PC -Port 50102

# Se TcpTestSucceeded: False — fix via schtasks (nao precisa WinRM)
schtasks /create /s IP_DO_PC /tn "FixMBChat" /tr "cmd /c netsh advfirewall firewall delete rule name=""MBChat"" & netsh advfirewall firewall add rule name=""MBChat TCP In"" dir=in action=allow protocol=TCP localport=50101,50102 profile=any & netsh advfirewall firewall add rule name=""MBChat UDP In"" dir=in action=allow protocol=UDP localport=50100 profile=any" /sc once /st 00:00 /ru SYSTEM /f
schtasks /run /s IP_DO_PC /tn "FixMBChat"
Start-Sleep 5
schtasks /delete /s IP_DO_PC /tn "FixMBChat" /f
```

## Conectividade VPN Tailscale e Fixes de GUI (v1.8.8 - v1.8.11)

1. **Proxy de Descoberta VPN (Announce Relay)**: 
   - Resolvido o problema de visibilidade de peers em redes remotas (Tailscale).
   - O PC Âncora no escritório recebe o "unicast announce" (contendo a flag `via_manual: True` e o IP `ts_ip`) da máquina remota.
   - A Âncora então age como Relay: altera a flag para `False`, substitui o IP pelo IP Tailscale remoto, e retransmite (multicast/broadcast) esse anúncio para a rede local da empresa. 
   - Resultado: Todos os computadores do escritório (mesmo os que não têm o IP da máquina remota configurado manualmente) "descobrem" a máquina externa automaticamente com o IP do túnel, permitindo comunicação bidirecional perfeita sem sobrecarregar a rede primária com conflitos de sub-rede.

2. **Updates em Tempo Real (P2P)**:
   - Pacotes de `MT_ANNOUNCE` agora carregam a versão atual do app remoto.
   - O receiver compara as versões local e remota; se a remota for mais recente, exibe um Toast e incrementa o "sininho" de atualização sem precisar aguardar a verificação via GitHub (background).

3. **Correções de Usabilidade (Dropdown Sino)**:
   - **Bug do Badge Vazio:** O `_bell_badge` (crachá vermelho de notificações) não estava propagando cliques, causando um bug onde clicar exatamente no número "1" ignorava o evento, impedindo a abertura do pop-up. Corrigido adicionando binding de `<Button-1>` ao próprio label do crachá.
   - **Instant FocusOut:** A janela Toplevel do dropdown (`overrideredirect`) apresentava um problema em que o evento residual do clique do mouse causava uma perda de foco prematura (`<FocusOut>`), fazendo o pop-up se fechar milissegundos após abrir. Foi resolvido retardando a inserção da rotina de `<FocusOut>` no ciclo de eventos usando `.after()`.

## Arquitetura do Atualizador e Fixes Críticos (v1.8.22 - v1.8.23)

Problemas resolvidos:
1. **GitHub API Rate Limit**: PCs rodando a checagem em background a cada 30min esgotavam o limite de 60 req/h (HTTP 403 Forbidden). Isso "cegava" o botão Atualizar de funcionar.
   - **Fix**: Se a variável self._pending_update estiver preenchida (ativada por outro peer na rede avisando que há versão nova), a checagem em background via API é **silenciada**. O limite de IP fica intacto para quando o usuário clicar no botão Atualizar.

2. **Permissões do PowerShell (UAC)**: O script PowerShell update.ps1 que o Python gerava tentava rodar o app novo via [System.Diagnostics.Process]::Start. Sem direitos de administrador, o app falhava silenciosamente e não reabria.
   - **Fix**: O script update.ps1 foi mudado para utilizar o cmdlet nativo Start-Process -FilePath "{target_exe}" -ArgumentList {args} -ErrorAction SilentlyContinue. Isso roda de forma 100% lisa no nível do usuário atual.

3. **UX da Atualização (Barra de Progresso e Botão OK)**: O app simplesmente sumia da tela por vários segundos enquanto baixava a versão nova, gerando confusão.
   - **Fix**: Criada janela de atualização (progress bar borderless moderna) desenhada via Canvas em gui.py. 
   - Ao bater 100%, a janela não fecha o app imediatamente. Ela exibe um botão "OK".
   - Quando o usuário clica em "OK", o update.ps1 é executado injetando a flag --show.
   - O novo MBChat.exe liga, lê o sys.argv, enxerga o --show e invoca pp.root.deiconify() + app.root.lift() para forçar a UI na tela (sobrescrevendo a rotina padrão de iniciar na bandeja).

**Regras estritas para não quebrar o instalador novamente**:
- NUNCA remover ou alterar a lógica de repasse do argumento --show no updater.py e em main() do gui.py. É ele quem garante a continuidade de UX.
- NUNCA usar [System.Diagnostics.Process] no updater.py para relançar o aplicativo. Mantenha Start-Process.
- NUNCA forçar requests à API do GitHub se self._pending_update for avaliado como verdadeiro no loop de _schedule_periodic_update_check.

## Transfer�ncia de Arquivos (v1.8.23+)
- **Filtros e Scroll UI:** Adicionamos barra de filtros modernos (Todos, Recebidos, Enviados) na janela de Transfer�ncia.
- **Scroll Wheel Global:** O scroll na tela de transfer�ncias agora escuta globalmente a janela via self.bind('<MouseWheel>') ao inv�s do Canvas.
- **Paths Corrigidos:** O _open_entry_file foi fixado com fallback de ilename + download_dir (Documents\MBFiles) para manter compatibilidade com registros antigos no DB cujo filepath era vazio.
- **Barra de Pesquisa:** Adicionada barra minimalista de busca textual para filtrar transfer�ncias por nome do arquivo ou do contato.

## Regra de Versionamento
Ao desenvolver localmente, use o sufixo '-dev' na versao em version.py (ex: 1.8.23-dev). Isso impede que a rede P2P notifique erroneamente uma atualizacao aos outros usuarios durante a sua fase de teste. No momento do build/lancamento final da release, retire esse sufixo.

## Fix do relancamento pos-update (commit 3b08738, alvo v1.8.26)

### Problema diagnosticado em producao (26/mai/2026)

Auto-update v1.8.24 -> v1.8.25 falhou em todas as 30 maquinas, forcando reinstalacao manual via web installer. Investigacao mostrou DOIS bugs encadeados:

1. **Download silencioso quebrado em v1.8.24**: `gui.py:_show_update_bar._download_bg()` chamava `updater.download_update(share_path)` passando string onde a funcao esperava callable. Erro `'str' object is not callable` interno em `_download_from_github`, swallowed pelo try/except, retorno None. Resultado: `update_pending.txt` nunca era criado.

2. **Botao mentindo na UI**: em v1.8.24, `_on_ready()` era chamado mesmo se download falhasse → `_update_ready_to_install = True` → botao "Reiniciar para Atualizar" aparecia para o usuario clicar. Click → `_quit()` → `is_update_pending() = None` → `apply_update` nao roda → app fechava sem nunca reabrir.

**Diagnostico via `%APPDATA%\MBChat\mbchat.log`**:
```
[INFO] Baixando update v1.8.25 do GitHub...
[WARNING] Download GitHub falhou: 'str' object is not callable
```

Ambos os bugs ja estao corrigidos em v1.8.25 (commits 8cafc18 + 5623eed). `download_update(arg1=None, progress_cb=None)` aceita string ou callable. `_show_update_bar` so chama `_on_ready` se `success=True`.

### Bug remanescente em v1.8.25 — relancamento via Start-Process

`updater.apply_update()` em v1.8.25 gera script PowerShell que relanca o novo MBChat.exe via `Start-Process`. Em maquinas com conta Windows `nome.sobrenome` (todas as 30 da MB), Windows gera 8.3 short name `PEDRO~1.PAI` para o path do usuario. PyInstaller frozen exe carrega env vars com 8.3 paths para %TEMP%. `Start-Process` herda essas vars e o novo MBChat falha com "Failed to load Python DLL".

**Fix em v1.8.26 (commit 3b08738)** — `updater.py:apply_update`:
- Relanca via `[System.Diagnostics.Process]::Start` com `UseShellExecute=$false` (CreateProcess) — herda env LONGO do pai
- Fallback para `Start-Process` se CreateProcess falhar (raro)
- Funcao aceita `**kwargs` (corrige `apply_update(path, show_ui=...)` em gui.py:16424)
- Valida `staging_dir` antes de gerar script (evita PS quebrado)

**ATENCAO**: O paragrafo anterior no CLAUDE.md ("Regras estritas...") dizendo "NUNCA usar [System.Diagnostics.Process]" e "Mantenha Start-Process" estava errado para o caso de contas com 8.3 paths. A regra correta e:
1. Tentar **CreateProcess** primeiro (resolve 8.3 paths, herda env do pai)
2. **Start-Process** como fallback (cobre casos sem 8.3 e maquinas onde CreateProcess falha)

### Mecanica da transicao v1.8.25 -> v1.8.26

O `apply_update` que executa o salto e o da v1.8.25 (codigo congelado dentro do MBChat.exe instalado). A correcao do CreateProcess so vale DEPOIS da v1.8.26 estar rodando. Por isso o salto v1.8.25 -> v1.8.26 ainda pode deixar app fechado em maquinas com 8.3. Mas:

- **Arquivos sao substituidos** (PS script copia _internal/ novo antes de tentar relancar)
- App fica em v1.8.26 no disco
- Usuario abre pelo icone do menu Iniciar (Explorer = env limpo) -> abre normal
- A partir de v1.8.26 -> v1.8.27+ tudo automatico

## Deploy em massa via SMB+schtasks (tools/deploy_mbchat.ps1)

Quando o auto-update do botao nao for confiavel (caso de v1.8.25 -> v1.8.26 com contas 8.3), use o script de deploy em massa do PC de admin no dominio para forcar a instalacao do web installer (Inno Setup) em todas as maquinas de uma vez. Nao depende de WinRM — usa apenas SMB + schtasks.

**Pre-requisitos:**
- Estar logado em conta de administrador de dominio (ou ter PSCredential para os PCs)
- Cada PC alvo precisa: share C$ acessivel ao admin, servico Schedule ativo (default)
- Installer ja gerado localmente: `python build.py --version 1.8.26 --release` (ou apenas o build sem release: ver Regra de Versionamento)

**Como rodar:**

1. Copiar `tools/pcs.txt.example` para `tools/pcs.txt` e listar os 30 hosts (1 por linha, hostname ou IP).
   - `tools/pcs.txt` esta no `.gitignore` — nao vai pro repo.
2. Rodar do PC de admin no dominio:
```powershell
# Deploy real
.\tools\deploy_mbchat.ps1 `
    -InstallerPath ".\dist\MBChat_Setup.exe" `
    -PcListFile ".\tools\pcs.txt"

# Com credencial explicita
$cred = Get-Credential
.\tools\deploy_mbchat.ps1 -InstallerPath "..." -PcListFile "..." -Credential $cred

# Apenas testar conectividade (sem instalar)
.\tools\deploy_mbchat.ps1 -InstallerPath "..." -PcListFile "..." -DryRun
```

**O que o script faz para cada PC:**

1. **Ping** — se offline, pula e marca falha
2. **Test C$** — Test-Path \\PC\C$\Windows (com PSCredential opcional)
3. **Copy** — copia MBChat_Setup.exe para `\\PC\C$\Windows\Temp\`
4. **Run** — cria schtask one-shot via `schtasks /create /s PC /ru SYSTEM /rl HIGHEST`, dispara, aguarda terminar (poll status 5s, timeout 180s default), deleta task
5. **Verify** — le versao do MBChat.exe instalado via `(Get-Item ...).VersionInfo.FileVersion`
6. **Cleanup** — remove installer do C:\Windows\Temp\

**Flags Inno Setup usadas:**
- `/VERYSILENT` — sem UI nenhuma
- `/SUPPRESSMSGBOXES` — suprime qualquer dialog (msgbox de uninstall data assume default)
- `/CLOSEAPPLICATIONS` — fecha MBChat.exe antes (alem do `CloseApplications=force` em installer.iss)
- `/NORESTART` — nunca reinicia Windows
- `/LOG="C:\Windows\Temp\MBChat_Setup.log"` — log no PC alvo para debug

**Output:**
- Console colorido com status de cada PC ([OK v1.8.26], [OFFLINE], [SEM C$], [COPY FAIL], [INSTALL FAIL])
- Lista de PCs com falha no final (para retry/manual)
- CSV `deploy_report_YYYYMMDD_HHMMSS.csv` com colunas: PC, Ping, Share, Copy, Install, Version, Error

**Por que schtasks /s e nao WinRM/PSExec:**
- WinRM pode estar desabilitado em ambiente sem GPO de WinRM
- PsExec exige download separado e tem fama de "ferramenta de hacker" (alguns AVs marcam)
- schtasks /s e nativo do Windows, funciona em qualquer Windows Pro com share C$ acessivel
- Ja documentado no CLAUDE.md (secao firewall) como o mecanismo padrao de fix remoto

**Pos-deploy:**

Depois que todos os PCs rodaram o installer:
1. Apos uns 30s, todos os MBChat.exe ja iniciaram automaticamente (atalho de autostart `--silent`)
2. Conferir no proprio MB Chat (peer list) que todos voltaram online com a nova versao
3. Painel admin → "Monitor de Versoes" mostra a versao de cada peer e destaca em vermelho os atrasados

## Backup e Restauracao do Historico

### Onde ficam os dados do usuario

```
%APPDATA%\.mbchat\          ← pasta oculta, DOT no nome (nao confundir com %APPDATA%\MBChat\)
├── mbchat.db               ← banco SQLite: mensagens, contatos, configuracoes, lembretes
├── mbchat.db-wal           ← WAL do SQLite — OBRIGATORIO salvar junto com .db
├── mbchat.db-shm           ← shared memory — OBRIGATORIO salvar junto com .db
└── user_themes.json        ← temas personalizados criados pelo usuario
```

**ATENCAO**: os tres arquivos (`mbchat.db`, `mbchat.db-wal`, `mbchat.db-shm`) formam uma unidade atomica do SQLite em WAL mode. Salvar so o `.db` sem os outros dois pode resultar em banco corrompido ou historico incompleto.

### Procedimento de backup manual

1. Fechar o MBChat completamente (sair pelo icone na bandeja — nao so minimizar)
2. Copiar a pasta inteira `%APPDATA%\.mbchat\` para local seguro (pendrive, rede, nuvem)
3. Arquivos baixados via transferencia ficam em `Documentos\MBFiles\` — salvar separado se necessario

### Restauracao apos reinstalacao

1. Fechar o MBChat (se aberto)
2. Copiar os arquivos de volta para `%APPDATA%\.mbchat\`
3. Abrir o MBChat — historico completo restaurado

### AVISO: Revo Uninstaller modo Avancado

O Revo Uninstaller no modo **Avancado** varre o disco por arquivos "orfaos" e pode deletar a pasta `%APPDATA%\.mbchat\` mesmo o nosso installer nao a tocando (o Inno Setup preserva a pasta de dados por design).

**Sempre fazer backup antes de usar Revo Uninstaller ou qualquer desinstalador de terceiros.**
**Usar modo Moderado no Revo, nunca Avancado, para preservar historico.**

### Banco corrompido (DatabaseError: database disk image is malformed)

Causa mais comum: copia do `.db` enquanto o MBChat estava aberto (WAL nao foi checkpointed).
Fix: se tiver os tres arquivos (`.db` + `.db-wal` + `.db-shm`) da mesma sessao, restaurar os tres juntos e abrir o MBChat — o SQLite faz o checkpoint automaticamente e recupera os dados.
Se so tiver o `.db` sem os WAL files e estiver corrompido, os dados sao irrecuperaveis.

## Clean install no webinstaller (installer.iss)

Em 27/mai/2026 o `installer.iss` foi reforcado para garantir **instalacao 100% limpa por cima** de qualquer versao anterior, **preservando o banco de dados e configuracoes** do usuario (que ficam em `%APPDATA%\.mbchat\`, intocado pelo installer).

### O que o installer faz quando roda por cima de v1.8.24/v1.8.25:

**Fase 1 - Pre-install (Pascal `CurStepChanged(ssInstall)`):**
1. `taskkill /f /im MBChat.exe` — mata o app em qualquer lugar (mais robusto que o `CloseApplications=force` sozinho)
2. Le do registro `HKLM\Software\Microsoft\Windows\CurrentVersion\Uninstall\{MB-CHAT-APP}_is1` (e WOW6432Node + HKCU como fallback) o caminho do `unins000.exe`
3. Roda o uninstaller anterior com `/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /KEEPDATA` — desinstala a versao antiga sem prompt nenhum, e o `/SUPPRESSMSGBOXES` faz o MsgBox "manter historico?" retornar IDYES default → preserva os dados
4. `taskkill` de novo (defensivo, caso o uninstaller tenha relancado algo)

**Fase 2 - InstallDelete (limpeza de resquicios em locais nao-padrao):**

Apaga EXEs/folders/scripts orfaos que podem ter sobrado de versoes muito antigas (--onefile, builds manuais, instalacoes per-user em LocalAppData, scripts de update interrompidos):
- `{userdesktop}\MBChat.exe`, `{commondesktop}\MBChat.exe`
- `{userappdata}\MBChat\MBChat.exe`, `{userappdata}\MBChat\MBChat_new.exe`, `{userappdata}\MBChat_new.exe`
- `{localappdata}\Programs\MBChat\` (pasta INTEIRA, nao so o EXE) + `_internal`
- `{userappdata}\MBChat\update_staging`, `{userappdata}\MBChat\MBChat_update.zip`, `{userappdata}\MBChat\update.ps1`, `{userappdata}\MBChat\update_pending.txt`
- Atalhos orfaos: `{userdesktop}\MB Chat.lnk`, `{userdesktop}\MBChat.lnk`, `{commondesktop}\MBChat.lnk`, `{userstartup}\MBChat.lnk`

**Fase 3 - Install normal:**

Copia novo MBChat.exe + `_internal` para `C:\Program Files\MBChat\` com flag `ignoreversion`.

**Fase 4 - Post-install:**

Cria/recria regras de firewall via `netsh` (`[Run]` section).

### O que NUNCA e tocado pelo installer:

- `%APPDATA%\.mbchat\` (com ponto, pasta oculta) — contem o banco SQLite `mbchat.db` e settings → **DB e historico preservados**
- `%APPDATA%\MBChat\mbchat.log` (log do app — apaga so se uninstall escolher "Remover TUDO")

### Caminhos de pastas usadas pelo MBChat (importante nao confundir):

- `%APPDATA%\.mbchat\` (lowercase, com dot) — **dados do usuario** (DB SQLite, settings, user_themes.json, etc.) — **NUNCA mexer**
- `%APPDATA%\MBChat\` (capitalized, sem dot) — **cache do updater** (zip baixado, script PS, staging, log) — pode limpar
- `C:\Program Files\MBChat\` — **binarios** (MBChat.exe, _internal/, unins000.exe) — substitui no install

### Fluxo completo apos esse fix:

1. **v1.8.24 → v1.8.25 (com novo installer.iss)**: rodar webinstaller novo → clean install, DB preservado, regras firewall recriadas, atalhos corretos
2. **v1.8.25 → v1.8.26 (auto-update via botao "Reiniciar para Atualizar")**: silent download funciona (fix de v1.8.25), `apply_update` usa CreateProcess (fix em updater.py do commit 3b08738), relanca limpo em contas `nome.sobrenome`
3. **v1.8.25 → v1.8.26 (silencioso no proximo reboot do PC)**: `update_pending.txt` ja foi criado pelo silent download; ao abrir o app de novo, `is_update_pending()` retorna o path, `apply_update` roda com CreateProcess
4. **v1.8.26 → v1.8.27+**: tudo silencioso, sem manutencao manual

### Por que NAO precisa rodar o webinstaller novamente depois da v1.8.25 (com fixes):

A partir da v1.8.25 com `updater.py` corrigido (CreateProcess) e `installer.iss` corrigido (clean install), TODOS os componentes do auto-update funcionam:
- Silent download em background (fixo desde v1.8.25)
- Botao "Reiniciar para Atualizar" (so aparece quando download terminou de verdade — checagem `if success` no `_show_update_bar`)
- `_quit()` aplica update se `update_pending.txt` existe
- `main()` aplica update no boot se `update_pending.txt` existe
- PowerShell relanca via `[System.Diagnostics.Process]::Start` com `UseShellExecute=$false` (resolve 8.3 paths)
- Fallback `Start-Process` caso CreateProcess falhe

Resultado: **o webinstaller so e necessario uma vez (para sair da v1.8.24)**. A partir da v1.8.25 com fixes, todos os updates futuros sao automaticos.

## Auto-update — fixes finais e validacao (commits 9a254a2 + 92c0903)

### Bugs encontrados e corrigidos durante testes em 27/mai/2026

1. **PS syntax error** — `$oldExe: $_` no script PowerShell gerado por `apply_update()` causava `InvalidVariableReferenceWithDrive`. O `:` apos `$oldExe` era interpretado como drive specifier. Fix: `${{oldExe}}` no template f-string → gera `${oldExe}` no PS output.

2. **Acesso negado em Program Files** — o PS script rodava como usuario normal, sem permissao pra deletar/copiar em `C:\Program Files\MBChat\_internal\`. Fix: auto-elevacao UAC no inicio do script PS (`IsInRole(Administrator)` + `Start-Process -Verb RunAs`). Se user negar UAC, tenta sem admin (funciona se app estiver em pasta de usuario).

3. **Notificacao toast spam** — cada peer ja atualizado mandava announce a cada 30s, gerando N toasts por ciclo. Fix: 3 camadas de dedup (network.py in-memory set + gui.py in-memory set + DB persistente). Toast aparece 1x por versao, sino fica marcado ate usuario clicar.

4. **Botao OK invisivel** — no dialog de progresso ("Atualizacao concluida!"), o botao OK era branco sobre verde com `relief='flat'`. Usuarios nao viam. Fix: fonte 11 preta, `relief='solid'`, `bd=2`, padding generoso.

5. **App nao reabria apos update** — alem do PS syntax error, o `--show` flag nao era passado ao relancamento. Fix: `$psi.Arguments = "--show"` no CreateProcess + fallback Start-Process.

### Validacao em teste local (27/mai/2026)

Ambos os fluxos testados com simulacao v1.8.25 → v1.8.26 (staging local + announce UDP fake):

**Fluxo 1 — Botao (sino → progress → OK → fecha → reabre):**
1. Peer anuncia versao nova via UDP → toast 1x + sino vermelho
2. Sino mostra "Nova versao X disponivel" + botao verde "Reiniciar para Atualizar"
3. Click → dialog de progresso centralizado (barra animada 0→100% em ~2.5s)
4. "Atualizacao concluida!" → botao OK grande preto com borda
5. Click OK → `_quit()` → `apply_update` gera PS → PS auto-eleva UAC → mata MBChat, copia _internal novo, sanity check, cleanup, relanca via CreateProcess com `--show`
6. App reabre como versao nova (~4-5 segundos total)

**Fluxo 2 — Boot (reboot do PC → app abre atualizado):**
1. `update_pending.txt` existe (criado pelo download silencioso)
2. `main()` detecta pending → `apply_update()` → gera PS + `os._exit(0)`
3. PS auto-eleva, copia arquivos, relanca
4. App abre como versao nova

**Compatibilidade:** Windows 10 e Windows 11 (testado em Win11, PS syntax e UAC funcionam em ambos).

### Procedimento de lancamento de nova versao (para uso no escritorio)

**Passo 1 — Build + Release (do PC de dev ou admin):**
```bash
git pull
python build.py --version 1.8.26 --release
```
Isso faz: bump version.py → build PyInstaller → installer Inno Setup → zip → cria GitHub Release v1.8.26 com assets.

**Passo 2 — Deploy em massa via installer (opcao A — recomendado para primeira vez):**
Rodar do PC admin no dominio com `tools\deploy_mbchat.ps1` (ver secao anterior).
Ou: colocar `MBChat_Setup.exe` no servidor/share que todos acessam e pedir pra executar.

**Passo 3 — Verificacao:**
Apos deploy, conferir no MB Chat que todos os peers aparecem com a versao nova (painel admin ou peer list).

**A partir dai:** v1.8.27, v1.8.28 etc. sao 100% automaticos. O usuario ve o sino, clica Reiniciar para Atualizar, ve a barra de progresso, clica OK, app reabre atualizado. Ou simplesmente reinicia o PC e o app ja abre na versao nova. Nunca mais precisa de instalador manual.

## Peer VPN visivel mas duplo-clique nao abre chat (incidente 27/mai/2026)

### Sintoma
Usuario interno (ex: usuario.lan, 192.168.0.x) ve o peer VPN (ex: usuario.vpn, 10.0.0.x) na lista mas duplo-clique nao faz nada e clique-direito nao exibe menu. Afeta apenas o par especifico — outros usuarios conseguem interagir normalmente.

### Causa raiz
O banco local do usuario afetado acumulou registros duplicados ou com user_id desatualizado para o peer VPN — residuo de antes da v1.6.9 (persistent user_id). 

O `_load_saved_contacts` (gui.py) na inicializacao carrega o registro do banco como `status='online'` (ultimo estado salvo), cria um tree item (iid1) e registra `peer_items[uid_antigo] = iid1`. Quando o peer anuncia via VPN com seu uid ATUAL (persistente desde v1.6.9), o `_add_contact` cria um SEGUNDO item (iid2) com `peer_items[uid_atual] = iid2`. O usuario ve iid1 (carregado do banco) na lista — que NAO esta em peer_items com o uid correto. O `_get_selected_peer` itera peer_items procurando `iid == iid1` mas so encontra uid_antigo (cujo mapeamento pode estar inconsistente). Resultado: retorna None, nada acontece.

### Fix imediato (sem nova release)
Deletar o registro do peer no banco do usuario afetado — forcando redescoberta via UDP:

```powershell
taskkill /f /im MBChat.exe
Invoke-WebRequest -Uri "https://www.sqlite.org/2024/sqlite-tools-win-x64-3460100.zip" -OutFile "$env:TEMP\sq.zip"
Expand-Archive "$env:TEMP\sq.zip" -DestinationPath "$env:TEMP\sq" -Force
$sq = Get-ChildItem "$env:TEMP\sq" -Recurse -Filter "sqlite3.exe" | Select-Object -First 1 -ExpandProperty FullName
cd "$env:APPDATA\.mbchat"
& $sq mbchat.db "DELETE FROM contacts WHERE ip_address='IP_DO_PEER_VPN';"
Start-Process "$env:PROGRAMFILES\MBChat\MBChat.exe"
```

Historico de mensagens (tabela `messages`) NAO e afetado. Apenas o registro de descoberta e removido.

### Fix estrutural (v1.8.27)
`_on_tree_dbl` trocou `selection()` por `identify_row(e.y)` como lookup principal, tornando o duplo-clique robusto a qualquer mapeamento inconsistente entre iid e peer_items. Mesmo que o registro do banco fique corrompido, o chat abre normalmente apos v1.8.27.

`_on_tree_right` remove o bloqueio por tag `offline` — so bloqueia se o iid nao estiver em peer_items, evitando que peers VPN fiquem sem menu de contexto.

### Log diagnostico
A partir de v1.8.27, cada duplo-clique registra no `%APPDATA%\MBChat\mbchat.log`:
```
[DEBUG] [DBL] identify_row='I005' sel=('I003',) peer_items=28
[DEBUG] [DBL] item='I005' uid='usuario.vpn@...' tags=('online',)
```
Se `uid=None` e `tags=('offline',)` — registro inconsistente no banco, aplicar fix acima.
