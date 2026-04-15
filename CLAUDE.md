# CLAUDE.md - Contexto do Projeto MB Chat

## O que e este projeto

MB Chat e um mensageiro de rede local (LAN) para MB Contabilidade. Executavel standalone (MBChat.exe) roda em 30+ maquinas Windows simultaneamente sem servidor central. Python + tkinter. Versao atual: 1.4.56.

## Arquitetura (4 camadas)

```
gui.py -> messenger.py -> network.py / database.py
```

- **gui.py** (~5400 linhas) - Apresentacao tkinter (janelas, temas, treeview, tray, emojis coloridos)
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
- TCP 50199: Single-instance lock (loopback)

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

## Regras gerais

- Ser AUTONOMO. Fazer tudo sem perguntar, sem esperar confirmacao
- NUNCA perguntar "quer que eu faca X?" â€” ja faz
- Respostas curtas e diretas
- Se screenshot de erro, corrigir direto

## Workflow de changelog (ao lancar nova versao)

Apos o build+release, atualizar o changelog no cofre Obsidian:
1. Abrir ~/obsidian-cofre/Projetos/MB-Contabilidade/MB Chat - Changelog.md
2. Adicionar entrada no topo (abaixo do separador ---) no formato:
   ## vX.Y.Z — DD/MMM/AAAA — EMOJI Tipo
   Descricao curta da mudanca
3. Atualizar campo versao-atual no frontmatter
4. Atualizar estatisticas (total de versoes, por tipo)
5. O plugin Obsidian Git faz commit+push automatico a cada 5 min

Tipos: Major Feature, Feature, Bugfix, Refactor, Build, Docs, UI, Performance, QA, Hotfix, UX
Emojis: ver legenda no proprio changelog

## Documentacao detalhada

Para detalhes alem deste resumo, consultar:
- `docs/ARCHITECTURE.md` - Arquitetura completa, fluxos, classes, protocolo de rede
- `docs/CODESTYLE.md` - Padroes de codigo, nomenclatura, temas, threading
- `docs/DECISIONS.md` - Decisoes tecnicas, troubleshooting, discovery robusto
- `docs/FEATURES.md` - Lista completa de funcionalidades com detalhes de implementacao
