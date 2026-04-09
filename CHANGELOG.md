# Changelog

Todas as mudancas notaveis do MB Chat sao documentadas aqui.
Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.0.0/).

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
