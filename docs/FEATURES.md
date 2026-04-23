# MB Chat - Funcionalidades (v1.4.56)

## Mensagens
- Mensagens individuais com emojis coloridos (PIL + seguiemj.ttf)
- Responder mensagem (Reply/Quote) — clique direito > "Responder", barra preview, quote com fundo destacado. Campo `reply_to_id` no banco, `reply_to` no payload
- Colar imagem do clipboard (Ctrl+V) — PIL ImageGrab + fallback ctypes CF_DIBV5/CF_DIB, comprime JPEG quality=85, preview bar, envia base64 via MT_IMAGE, receptor salva em %APPDATA%/.mbchat/images/, thumbnail 300px clicavel
- Links clicaveis (v1.4.53) — regex `_URL_RE` detecta URLs, tag com foreground azul + underline + hand2, `_open_url` via webbrowser.open
- Transmitir Mensagem (broadcast para contatos selecionados) com emojis coloridos
- Modo selecao multi-mensagem (v1.4.53) — long-press 500ms, barra top-docked com Copiar/Encaminhar/Cancelar
- Copiar rapido no hover (v1.4.53, ampliado v1.4.54/v1.4.55) — icone MDL2 reusado, delay 600ms

## Grupos
- Criar Grupo com 2 tipos: Temporario e Fixo
  - Temporario: fechar janela pergunta se quer sair
  - Fixo: fechar apenas esconde, sair via botao "Sair do Grupo"
- Notificacoes de entrada/saida para todos os membros
- Mensagem de grupo NAO abre janela automaticamente: pisca taskbar + notificacao Windows
- Mencoes em grupo (@fulano) — digitar @ abre popup de membros, highlight azul negrito
- Enquete em grupo — botao na toolbar, votacao em tempo real via MT_POLL_VOTE, tabelas polls/poll_votes
- Topologia mesh: cada membro envia para todos via TCP

## Transferencia de arquivos
- Ponto-a-ponto e para grupos (ate 100MB, chunks 256KB)
- Dialogo com progresso em MB, velocidade, estado visual
- Drag and Drop via windnd

## Interface
- 3 temas visuais (Classico, Night Mode, MB Contabilidade) + UI flat design
- Dois estilos de mensagem: linear (LAN Messenger) e bolhas (WhatsApp)
- Bordas arredondadas DWM (Win11+)
- Avatares circulares sincronizados via rede (thumbnail JPEG 48x48 no UDP announce)
- Nota pessoal visivel para todos em tempo real com emojis coloridos
- Emoji picker completo com 6 categorias, busca PT, scroll
- Input adaptativo (v1.4.54) — cresce ate 8 linhas conforme digitacao
- Contatos online em "Geral", offline em secao "Offline" recolhida
- Deduplicacao automatica de contatos por display_name
- Departamentos/Equipes em Preferencias > Conta (10 opcoes)
- Ramal (v1.4.53) — campo 4 digitos, badge azul no TreeView
- Dialog About modular (v1.4.56) — botao Autor abre pedropaivaf.dev

## Historico e busca
- Busca em tempo real com highlight amarelo e filtro por data De/Ate
- Chat individual: busca dentro da conversa
- Global (menu Ferramentas): busca em TODOS os chats, agrupados por contato

## Lembretes
- Tres tipos: Simples (sem data), Programado (calendario + HH:MM), Recorrente pattern-based (diario/semanal/mensal/anual)
- `recurrence_rule` JSON com type, interval, weekdays, end, occurrences_done
- Timer de 10s `_check_reminders`, notif winotify + sound + flash taskbar
- Date picker reusavel com flip-up automatico

## Preferencias
- Aba Alertas: Notificacoes (5 toggles), Sons (mestre + 6 individuais), Piscar taskbar (3 toggles)
- Aba Transferencia: pasta de salvamento
- Aba Geral: show_main_on_start, tray_icon, minimize_on_close, balloon_notify
- Migracao automatica de chaves antigas

## Notificacoes
- Winotify com protocolo mbchat:// para click-to-open
- v1.4.55: notificacao abre apenas janela do chat, nao root
- System tray com pystray

## Sistema
- Instancia unica via TCP socket loopback **por usuario** (v1.4.64+): porta deterministica por login Windows em [50200, 51200). Multi-user na mesma maquina nao colide.
- Auto-update via GitHub Releases (barra amarela + download + PowerShell restart)
- Auto-start, popups fecham com Escape
- Taskbar LAN Messenger-style com AppUserModelID

## Tipos de mensagem de rede
- `MT_MESSAGE`, `MT_TYPING`, `MT_STATUS`, `MT_ACK` - individuais
- `MT_FILE_REQ`, `MT_FILE_ACC`, `MT_FILE_DEC`, `MT_FILE_CANCEL` - arquivos
- `MT_GROUP_INV`, `MT_GROUP_MSG`, `MT_GROUP_LEAVE`, `MT_GROUP_JOIN` - grupos
- `MT_IMAGE` - imagem inline base64
- `MT_POLL_CREATE`, `MT_POLL_VOTE` - enquetes

## Build
- Menu interativo: build normal, build+versao+deploy, somente deploy, build+GitHub release
- Gera: dist/MBChat/ (exe + _internal), MBChat_update.zip (auto-update), MBChat_Setup.exe (Inno Setup)
- `_set_version()` atualiza version.py + installer.iss + docs/index.html

## Assets
- `assets/mbchat_icon.png` - Logo 1024x1024
- `assets/mbchat.ico` - Multi-resolucao (16-256px)
- `assets/icon_*.png` - Icones toolbar

## Testes (manuais)
1. Descoberta automatica de peers (2+ maquinas)
2. Enviar/receber mensagens e arquivos
3. Notificacao clicavel
4. Transmitir Mensagem com emojis
5. Grupos: temp/fixo, entrada/saida, mencoes, enquete
6. Reply/Quote em chat e grupo
7. Auto-update: barra amarela, atualizar, restart
8. Lembretes: simples, programado, recorrente
9. Drag and Drop de arquivos
10. Departamentos e Ramal
