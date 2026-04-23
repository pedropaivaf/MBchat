# CLAUDE.md - Contexto do Projeto MB Chat

## O que e este projeto

MB Chat e um mensageiro de rede local (LAN) para MB Contabilidade. Executavel standalone (MBChat.exe) roda em 30+ maquinas Windows simultaneamente sem servidor central. Python + tkinter. Versao atual: 1.5.0.

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
- NUNCA perguntar "quer que eu faca X?" — ja faz
- Respostas curtas e diretas
- Se screenshot de erro, corrigir direto

## Workflow de changelog (ao lancar nova versao)

Apos o build+release, atualizar o changelog no cofre Obsidian:
1. Abrir ~/obsidian-cofre/Projetos/MB-Contabilidade/MB Chat - Changelog.md
2. Adicionar entrada no topo (abaixo do separador ---) no formato:
   ## vX.Y.Z � DD/MMM/AAAA � EMOJI Tipo
   Descricao curta da mudanca
3. Atualizar campo versao-atual no frontmatter
4. Atualizar estatisticas (total de versoes, por tipo)
5. O plugin Obsidian Git faz commit+push automatico a cada 5 min

Tipos: Major Feature, Feature, Bugfix, Refactor, Build, Docs, UI, Performance, QA, Hotfix, UX
Emojis: ver legenda no proprio changelog

## Blindagem de rede e auto-fix de firewall (v1.4.59)

Tres camadas foram adicionadas para tornar falhas de discovery visiveis e auto-recuperaveis:

1. **Log rotativo de rede** em `%APPDATA%\.mbchat\network.log` — RotatingFileHandler 1MB x 3 backups.
   Grava cada bind/IGMP join, stats de send/recv, erros engolidos. Fail-safe (NullHandler se IO falhar).
   Acessado via `network._log()` — uma unica linha por evento, nunca levanta excecao para caller.

2. **Health dict** em `UDPDiscovery.health` (network.py:201) com `bound_port`, `bind_fallback`,
   `multicast_joined`, `packets_sent`, `packets_received`, `sendto_errors`, `last_peer_seen_at`,
   `started_at`, `bind_errors`. Exposto via `get_health()` que adiciona `uptime` e `peers_count`
   on-the-fly. Todos os contadores sao incrementados nos pontos que antes tinham `except: pass`
   silencioso — zero impacto no caminho feliz, instrumentacao pura.

3. **Banner de diagnostico** na janela principal (gui.py `_update_health_banner`). Rearma a cada 30s.
   - **VERMELHO** se `bind_fallback=True` (porta UDP 50100 ocupada, cai em porta aleatoria — discovery quebrado)
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

6. **tools/fix_firewall.bat** — Script standalone para casos extremos: executa como admin,
   deleta todas as regras MBChat, recria Allow Inbound por porta, reinicia o MBChat.
   Enviar por WhatsApp se o auto-fix via UAC falhar ou for recusado.

   **Fix manual via Painel de Controle** (se user recusar UAC e nao quiser rodar .bat):
   `Painel de Controle > Sistema e Seguranca > Windows Defender Firewall > Aplicativos permitidos`
   > Alterar configuracoes > marcar **MBChat** em **Particular** e **Publico**. Se nao aparecer
   na lista, `Permitir outro aplicativo... > Procurar... > MBChat.exe` (em `%LOCALAPPDATA%\Programs\MBChat\`
   ou `C:\Program Files\MBChat\`). Documentado na landing (`docs/index.html#doc-firewall`) e
   em `docs/DECISIONS.md`.

7. **tools/sniff_mbchat.py** — Sniffer UDP 50100 passivo, standalone, diagnostico remoto.
   Lista todos os peers anunciando na LAN com IP src vs IP declarado (detecta `get_local_ip()` bugado).
   Rodar com MBChat local fechado. Usado para confirmar se PC com problema esta enviando/recebendo.

**Hipotese confirmada v1.4.59**: 2 PCs de 30 ficaram invisiveis (lista vazia) porque nao tinham
regras de firewall inbound. Reinstalacao + apagar `%APPDATA%\.mbchat` nao resolve — o Windows
Defender Firewall nao re-pergunta "Permitir?" ao user e o installer roda com `PrivilegesRequired=lowest`
(sem admin, nao consegue criar regras via netsh). O `_add_firewall_rule()` em network.py:40 tambem
falha silenciosamente sem admin. Diagnostico feito via `Test-NetConnection` do PC do Pedro:
TCP 50101 `TcpTestSucceeded: False`, `PingSucceeded: True` → inbound bloqueado, L2/L3 ok.
Sniffer confirmou que PC problematico envia UDP announces normalmente (outbound ok) mas nao recebe
nada (inbound bloqueado). **Nao alfroxar** `_add_firewall_rule()` ou o `except Exception: pass` —
o problema nao e o codigo tentar silenciosamente, e a falta de feedback ao user quando falha.
O auto-fix via UAC e a solucao definitiva: pede permissao uma vez, cria regras por porta, resolve.

## Theme Builder + temas dinamicos (v1.5.0)

Janela em **Preferencias > Aparencia > Tema > Criar tema personalizado...** permite ao usuario
montar temas custom (40+ tokens de cor: bg/fg/bordas/bolhas/header/status), persistidos em
`%APPDATA%\.mbchat\user_themes.json`. Ao abrir o app, `gui.py` faz merge aditivo dos temas
salvos no dict global `THEMES` (sem sobrescrever os 3 fixos: Classico, Night Mode, MB
Contabilidade — protegidos via `BUILTIN_THEMES`).

Mudancas estruturais que vieram junto:

1. **`apply_theme` propaga globais** (gui.py:8758) — `BG_WINDOW`, `BG_WHITE`, `BG_HEADER`,
   `FG_BLACK`, etc. agora sao reescritas globalmente a cada troca de tema. Janelas reabertas
   (Preferences, Builder, Diagnostico) reconstroem com a paleta atual.

2. **`PreferencesWindow` respeita o tema** — sidebar/categorias leem `app._theme` no `__init__`
   e usam `_sweep_theme()` recursivo apos cada `_select_category` para forcar `fg/bg` em
   `Label`, `Labelframe`, `Checkbutton`, `Radiobutton`, `Entry` (muitos `_build_*` nao
   passavam `fg` explicito — em Night Mode ficavam pretos sobre fundo escuro).

3. **`PreferencesWindow` reabre ao mudar tema** — o `_save_all` detecta `theme` mudou,
   chama `apply_theme` e faz `self.destroy() + PreferencesWindow(app, initial_tab=idx)`
   com delay 100ms (preserva aba atual via `_current_idx`). Mesmo comportamento no
   `_open_theme_builder` quando o builder retorna com tema novo aplicado.

4. **`ThemeBuilderWindow` se adapta ao tema do host** — le `app._theme` no `__init__` e
   monta dict `self.ui` (panel/window/border/text/muted/accent/etc.) usado em toda a UI
   principal. **Preview interno permanece usando `self.tokens`** (mostra o tema sendo
   construido, nao o tema do host).

5. **Temas fixos completados** — Classico e Night Mode ganharam as keys que faltavam
   (`msg_my_bg`, `msg_peer_bg`, `hover`, `accent`, `online`, `away`, `busy`,
   `offline_color`, `select_border`). Night Mode reformulado com contraste serio
   (texto `#e8e8e8` sobre `#1e1e1e`, accent `#7cb8f0`). MB Contabilidade **intacto**
   como tema principal/default.

**Contrato com `app` host (`tools/theme_builder.py`)**: builder chama apenas `app._theme`
(dict — opcional), `app.THEMES` (dict global — opcional, propaga tema novo) e
`app.apply_theme(name)` (so no Salvar e Aplicar). Se algum nao existir, builder degrada
sem crashar. `LanMessengerApp.__init__` expoe `self.THEMES = THEMES` (gui.py:8419) para
que o builder propague o tema novo no mesmo dict que `apply_theme` consulta.

**Validacao no JSON salvo**: regex `^#[0-9a-fA-F]{6}$` — `rgb(...)` ou nomes sao rejeitados.
Chaves ausentes herdam do `MB_DEFAULT` (fallback completo). JSON corrompido nao crasha
(`load_user_themes()` retorna `{}` + log).

## Documentacao detalhada

Para detalhes alem deste resumo, consultar:
- `docs/ARCHITECTURE.md` - Arquitetura completa, fluxos, classes, protocolo de rede
- `docs/CODESTYLE.md` - Padroes de codigo, nomenclatura, temas, threading
- `docs/DECISIONS.md` - Decisoes tecnicas, troubleshooting, discovery robusto
- `docs/FEATURES.md` - Lista completa de funcionalidades com detalhes de implementacao
