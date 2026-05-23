# Changelog

Todas as mudancas notaveis do MB Chat sao documentadas aqui.
Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.0.0/).

## [Unreleased]

## [1.8.17] - 2026-05-19

### Added
- **Admins em Grupos**: Múltiplos administradores podem ser definidos por grupo. O criador original (sempre Adm) e outros Adms podem promover ou rebaixar participantes através de um clique com o botão direito no nome do membro.
- **Remover Participantes**: O botão de remover (`−`) agora fica disponível para todos os Administradores.
- **Deletar Grupo**: Adicionado botão exclusivo para o criador deletar o grupo inteiro. A exclusão apaga o histórico de todos os membros e impede novas mensagens no grupo deletado.

### Changed
- A tag `(Criador)` foi substituída por `(Adm)` na interface para refletir o novo sistema de permissões hierárquicas.
## [1.8.12] - 2026-05-15

### Fixed
- Relay VPN nunca funcionava: constante `MCAST_GRP` inexistente substituída por `MULTICAST_GROUP` — o NameError era silenciado pelo try/except, impedindo que a âncora retransmitisse a presença do notebook remoto para a LAN.
- Notebook em VPN ficava com "Peers conhecidos: 0": respostas dos PCs da LAN iam para a porta efêmera do socket de envio (não escutada), em vez de UDP_PORT=50100 onde `_sock_recv` escuta. Corrigido `port=addr[1]` → `port=UDP_PORT` no VPN handshake reply.
- Botão "Remover selecionado" invisível na janela VPN: `btns.pack(side='bottom')` era chamado depois de `body.pack(expand=True)`, deixando o frame com 0px. Corrigido reordenando o pack.
- Notificação de atualização removida da barra superior (amarela) — avisos de nova versão agora aparecem exclusivamente no sininho.

### Added
- Ao remover o último peer cadastrado na janela VPN, a conexão VPN é desativada automaticamente.
- Histórico de mensagens: botão `↗` inline em cada resultado de busca — clicar carrega a conversa completa com scroll até aquela mensagem e fundo azul na linha alvo.
- `test_vpn_fixes.py`: 11 testes automatizados (análise de código + sockets reais no localhost) que validam os 3 fixes sem precisar de dois PCs em redes diferentes.

## [1.8.11] - 2026-05-15

### Fixed
- Corrigido um bug onde clicar exatamente no número (crachá vermelho) de notificações ignorava o clique.
- Resolvido um problema no Windows onde abrir o menu de notificações enquanto o evento de clique estava sendo processado fechava o menu instantaneamente (FocusOut instantâneo).
- Documentação da funcionalidade "Proxy de Descoberta VPN / Tailscale" adicionada à página principal, detalhando os passos para usar a VPN de fora do escritório.

## [1.8.9] - 2026-05-13

### Added
- Proxy de Descoberta VPN: O Âncora (Escritório) agora retransmite (relay) os anúncios recebidos via Tailscale para a rede local, permitindo que a rede inteira descubra conexões de fora de forma transparente.

### Fixed
- Correção de interface na janela "Manual Peers" garantindo que os botões do rodapé não sumam em telas pequenas.

## [1.8.8] - 2026-05-13

### Added
- Notificações de atualização "Realtime": O app agora avisa instantaneamente via rede P2P quando há uma versão nova disponível, sem precisar aguardar checagem automática.

### Fixed
- Handshake Bidirecional VPN: Correção na lógica de descoberta VPN onde respostas Unicast agora garantem status bidirecional 100% preciso.
- Resolvido um problema silencioso onde clicar no sino de notificações não abria o pop-up (conflitos de coordenadas negativas e bubbling de eventos GUI).

## [1.8.7] - 2026-05-13

### Fixed
- Melhoria na conexão via VPN (Tailscale): priorização de IPs na faixa `100.x.x.x` para resolução de conflitos de sub-rede idêntica sem afetar descoberta em LAN local via Multicast.

## [1.8.6] - 2026-05-13

### Fixed
- Corrigido problema de recepção de pacotes via VPN/Tailscale em Windows (isolamento de interface).
- Unificado diretório padrão de arquivos para `MB_Chat_Files` com migração automática dos arquivos antigos de `LanMessenger_Files`.

## [1.8.5] - 2026-05-13

### Fixed
- Filtro de eco no recebimento de mensagens TCP (`_on_tcp_message`), ignorando mensagens vindas do próprio ID para evitar duplicidade causada por loopback (ex: Peer fantasma com mesmo IP).
- Fallback robusto para o nome de exibição do contato (`display_name`) ao abrir uma janela de chat individual (`_open_chat`). Se não estiver em cache (`peer_info`), consulta no banco de dados (`get_contact`) antes de usar o UID como fallback.

## [1.8.4] - 2026-05-13

### Added
- Verificação periódica automática de novas versões (a cada 30 minutos) e verificação em background ao clicar no ícone de notificações (sino).

### Fixed
- Ajuste na janela de Transmitir Mensagem para que apenas contatos atualmente online sejam pré-selecionados, evitando disparos acidentais para usuários offline ou do histórico.

## [1.8.3] - 2026-05-13

### Added
- Criador de reunião recebe toast quando convidado aceita ou recusa o convite.
- Cancelamento de reunião informa o motivo: nome do organizador ou automático (sem confirmações no prazo).
- Lembrete compartilhado: botão ✓ envia notificação ao criador quando participante conclui a tarefa.
- Prazo de lembrete compartilhado exibe status de conclusão no toast do criador (X/Y concluíram).
- Seção de atualização no sino com fundo azul destacado, botão "Atualizar agora" proeminente e "Mais tarde" discreto.
- Novo campo `completed_by_uids` no banco para rastrear conclusões por participante.
- Novo tipo de mensagem TCP `MT_REMINDER_COMPLETED` para propagação de conclusão entre peers.

## [1.7.0] - 2026-05-05

### Added
- Nova aba **"Utilitários"** nas Preferências, centralizando o botão para **"Testar piscar barra de tarefas"**.
- Link clicável para mensagens de arquivos recebidos/enviados na janela de Histórico de Mensagens (`Ferramentas > Histórico de mensagens`), permitindo abrir a pasta correspondente no Windows Explorer com o clique esquerdo.

### Changed
- Preferências de Conexão VPN / Conectar fora da LAN movidas para a aba **"Rede"** nas Preferências.
- Remoção de itens redundantes (VPN e teste de piscamento) do menu superior "Ferramentas" para uma interface mais limpa.
- Alteração do texto do botão de seleção de pasta de transferência de "Procurar..." para "Selecionar".

### Fixed
- Correção no botão "Selecionar" da pasta de downloads nas Preferências para que o diálogo do sistema sempre abra na pasta atual configurada (`initialdir`), evitando a abertura genérica na pasta "Downloads".
- Correção de erro ao agendar o piscamento de tela (`after`) em classes que não herdam de Tkinter widgets (`LanMessengerApp`), corrigido para `self.root.after`.
- Ajuste e correção de tipos e ponteiros `ctypes` de 64 bits para resolução confiável de HWNDs no Windows 11.

## [1.6.9] - 2026-05-05

### Added
- Suporte a histórico de grupos na janela de histórico global, permitindo alternar entre mensagens privadas e de grupos fixos.
- Persistência estável de ID de usuário: o `user_id` agora é salvo localmente no banco de dados para evitar duplicidade ao alternar interfaces de rede (Wi-Fi/Cabo).

### Fixed
- Bug onde mensagens enviadas "sumiam" ao fechar e reabrir a janela de chat individual. Agora o histórico completo é carregado ao abrir qualquer conversa.
- Resolução de nomes de remetentes no histórico de grupos para usuários que não estão na lista de contatos principal.


## [1.6.8] - 2026-05-05

### Fixed
- Janelas de chat não piscavam na barra de tarefas quando o aplicativo tinha outra janela (como a lista principal) em foco.
- Implementado helper `_window_is_foreground` para verificação real de janela ativa no sistema operacional via Win32 API.

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
