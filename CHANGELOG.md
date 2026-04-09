# Changelog

Todas as mudancas notaveis do MB Chat sao documentadas aqui.
Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.0.0/).

## [Unreleased]

## [1.4.20] - 2026-04-09

### Fixed
- Departamento nao exibido no TreeView — campo `department` faltava no parse do UDP announce recebido

## [1.4.19] - 2026-04-09

### Added
- Badge `[Setor]` em azul ao lado do nome no TreeView (departamento visivel para todos os peers)
- Barra de reply estilo WhatsApp: nome do remetente (azul negrito) + preview da mensagem acima do input
- Preview de imagem antes de enviar (Ctrl+V mostra barra com thumbnail + botoes Enviar/Cancelar)
- Fallback clipboard CF_DIBV5/CF_DIB via ctypes para compatibilidade Win10

### Fixed
- Ctrl+V com imagem do clipboard nao funcionava (Win10 e Win11)
- Departamento nao salvava ao clicar OK nas Preferencias (faltava em `_save_all()`)
- Abrir imagem no chat crashava o app (`os.startfile` bloqueava main thread — movido para thread)
- "Mostrar Pasta" em transferencias nao abria Explorer (`explorer /select,` via subprocess.Popen)
- Menu "Responder/Copiar" aparecia ao clicar em imagem no chat (flag `_img_click_handled`)
- Handler para MT_FILE_DEC e MT_FILE_CANCEL no messenger (cancelava sender corretamente)

### Removed
- "Nota Privada" do menu de clique direito nos contatos
- Aba "Historico" vazia das Preferencias
- Botao "Copiar imagem" do chat

### Changed
- Barra verde "Atualizacao concluida" apos auto-update (compara versao no banco)
- Autostart respeita escolha do instalador na primeira execucao

## [1.3.1] - 2026-04-08

### Fixed
- Auto-update: PowerShell script usa CreateProcess (`UseShellExecute=$false`) para herdar TEMP longo
- Resolve caminhos 8.3 (ex: `PEDRO~1.PAI`) via `GetLongPathNameW` antes de gravar no script

## [1.3.0] - 2026-04-07

### Changed
- **Build migrado de `--onefile` para `--onedir`** — corrige "Failed to load Python DLL" no Windows 10
- Auto-update agora baixa zip (`MBChat_update.zip`) e substitui pasta inteira via PowerShell
- Instalador Inno Setup empacota `MBChat.exe` + `_internal/` (sem vc_redist)
- `build.py` reescrito: menu interativo + CLI flags (`--version`, `--deploy`, `--release`)
- `build.py` gera zip para auto-update automaticamente apos build
- `build.py` compila instalador Inno Setup automaticamente
- GitHub Release inclui `MBChat_update.zip` + `MBChat_Setup.exe`

### Fixed
- "Failed to load Python DLL" no Windows 10 — loader de DLLs do Win10 nao resolve cadeia de dependencias em pasta temporaria `_MEI*` do PyInstaller `--onefile`
- Script de update: f-string escaping para format specifiers do PowerShell
- Script de update: creation flags do subprocess (`CREATE_NO_WINDOW` em vez de `DETACHED_PROCESS`)

### Removed
- Dependencia de VC++ Redistributable no instalador
- Batch script de update (substituido por PowerShell)
- Suporte a `--onefile` no build

## [1.2.1] - 2026-04-06

### Fixed
- Resolve caminhos 8.3 no auto-update
- Landing page: navegacao e links corrigidos

## [1.2.0] - 2026-04-05

### Added
- Landing page GitHub Pages com design MB Contabilidade (vermelho + navy)
- Desinstalador com opcao de manter ou remover historico

### Changed
- Redesign do site: layout limpo sem cards

## [1.1.9] - 2026-04-04

### Added
- Auto-update via GitHub Releases (primario) + pasta compartilhada (fallback)
- Instalador Inno Setup com atalhos e desinstalador
- Botao download no site aponta direto para o instalador

### Fixed
- Update path UNC direto, batch com log/taskkill, deploy robusto

## [1.1.8] - 2026-04-03

### Added
- Sistema de auto-update via pasta compartilhada na rede

## [1.1.7] - 2026-04-02

### Added
- Emoji picker completo na nota pessoal (6 categorias, busca, scroll)
- Deduplicacao automatica de contatos offline

### Fixed
- Sair do grupo sem travar UI (thread background)
- Chat exibe mensagens nao lidas ao abrir via notificacao

## [1.1.6] - 2026-04-01

### Fixed
- Emojis na lista de contatos: tamanho 20px (proporcional ao texto)
- Emoji na nota pessoal: 14px (limite do tk.Text height=1)
- Variation selector `\ufe0f` causava emojis cortados em todos os renders

### Added
- Emojis nuvem e chope em todos os pickers
- Filtro por contato no historico global

## [1.0.0] - 2026-03-28

### Added
- Mensagens individuais com emojis coloridos (PIL + seguiemj.ttf)
- Nota pessoal visivel para todos em tempo real
- Transmitir Mensagem (broadcast)
- Grupos temporarios e fixos com mesh networking
- Transferencia de arquivos ponto-a-ponto e para grupos (ate 100MB)
- Historico com busca em tempo real e filtro por data
- 3 temas visuais + design flat moderno
- Notificacoes Windows clicaveis (winotify)
- System tray, instancia unica, auto-start
- Avatares com foto personalizada sincronizada via rede
- Bordas arredondadas DWM (Windows 11+)
