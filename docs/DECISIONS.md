# MB Chat - Decisoes Tecnicas e Troubleshooting

## Descoberta de peers (por que MBChat e mais confiavel que LAN Messenger)

LAN Messenger tem bug onde peers somem em redes com VPN, Hyper-V, switches gerenciados ou filtros de multicast. MBChat resolveu com 5 decisoes que trabalham juntas — NAO afrouxar nenhuma sem entender o impacto:

1. **Tri-broadcast** em `_send_announce()` (network.py:348): cada announce sai por 3 caminhos — multicast `239.255.100.200`, broadcast global `255.255.255.255` e subnet-directed broadcast (`_get_subnet_broadcast()`). Se multicast for filtrado, os broadcasts garantem entrega.
2. **Anuncio imediato em eventos** (network.py:295-316): `update_status`/`update_name`/`update_note`/`update_avatar` chamam `_send_announce()` na hora, sem esperar o ciclo.
3. **Anuncio no startup** (network.py:283): primeiro announce sai antes do loop periodico.
4. **Deteccao correta de NIC** em `get_local_ip()`: rota real pro 8.8.8.8 + enumeracao + filtro de interfaces virtuais.
5. **Ciclo curto** (`DISCOVERY_INTERVAL = 15`, `PING_TIMEOUT = 45`): NAO aumentar para 60s estilo LAN Messenger.

## Troubleshooting de rede

Se um PC nao descobre peers:
1. **Firewall**: verificar regra de entrada UDP+TCP 50100-50102. Comando: `netsh advfirewall firewall add rule name=MBChat dir=in action=allow protocol=UDP localport=50100,50101,50102 profile=any`
2. **Antivirus**: Kaspersky, Norton podem bloquear. Adicionar excecao.
3. **Multiplas NICs**: VPN, Hyper-V, Docker criam interfaces virtuais. get_local_ip() tenta detectar a correta, mas pode pegar a errada. Desativar NICs virtuais resolve.
4. **Subnet diferente**: PC deve estar na mesma subnet /24.
5. **Porta ocupada**: Se 50100 ocupada, app tenta +10, +20, depois aleatoria. Porta aleatoria nao recebe broadcasts. Verificar com `netstat -an | findstr 50100`.

## Decisoes de build

- **--onedir** (NAO --onefile): --onefile causa "Failed to load Python DLL" no Win10 porque o loader de DLLs nao resolve dependencias dentro da pasta temporaria _MEI*.
- **--noupx**: evita compressao que corrompe DLLs do VC runtime.
- **PowerShell no auto-update**: usar `[Diagnostics.Process]::Start` com `UseShellExecute=$false` (CreateProcess herda env vars do pai). NUNCA usar `Start-Process`, `start ""` ou `explorer.exe` — usam ShellExecute que ignora env e causa "Failed to load Python DLL" em maquinas com caminho 8.3 no %TEMP%.
- **_apply_and_restart()**: NAO pode ter messagebox antes de `os._exit()` — bloqueia o script e o move falha porque o exe fica travado.

## Decisoes de arquitetura

1. **1 usuario por maquina**: user_id = MAC + hostname, sem login/senha
2. **Portas independentes do LAN Messenger**: 50100-50102 (LAN Messenger usa 50000-50002)
3. **SQLite local, sem servidor central**: cada maquina e independente
4. **tkinter nativo**: zero dependencias de GUI externas
5. **Dependencias opcionais com graceful degradation**: PIL, pystray, winotify
6. **Thread-safe by design**: root.after(), conexao SQL por thread, I/O em threads daemon
7. **Chat limpo ao abrir**: historico via botao History
8. **Contatos offline persistidos**: PCs ja vistos aparecem como offline
9. **Firewall auto-config**: netsh na importacao de network.py
10. **Protocolo URL customizado**: mbchat:// registrado em HKCU
11. **Grupo mesh**: sem servidor de grupo, cada membro envia para todos via TCP
12. **Emojis coloridos via PIL**: seguiemj.ttf com embedded_color=True

## Ponto unico de entrega de mensagens

### Chat individual
`messenger._on_tcp_message` chama `db.save_message()` ANTES de disparar o callback `on_message`. Quando `_open_chat(surface_only=True)` cria a janela, ja carrega a mensagem via `get_unread_messages`. O callback `gui._on_message`/`_on_image` NAO deve chamar `cw.receive_message()` depois de `_open_chat(surface_only=True)` — duplica a msg. No branch "janela ja existe", chamar `receive_message` e correto.

### Grupos
Usam buffer `_pending_group_msgs` em memoria (nao DB). `_open_group` pop'a esse buffer ao criar a janela. `_on_group_message` NAO deve empurrar para o buffer antes do surface e DEVE chamar `gw.receive_message` na lambda `_create` apos o surface. Nao misturar os dois padroes.

## Taskbar LAN Messenger-style

AppUserModelID (`MBContabilidade.MBChat`) agrupa todas as janelas sob o mesmo icone na taskbar. Cada Toplevel recebe `WS_EX_APPWINDOW` via `_force_taskbar_entry()`. `_force_taskbar_entry` so faz o ciclo `SW_HIDE`+`SW_SHOWNA` se `winfo_ismapped()` — em janela withdrawn pula o SW_SHOWNA para evitar flash visivel.

Quando mensagem chega com app no tray, `_surface_chat_from_tray()` cria janela oculta, aplica estilo sem SW_SHOWNA, minimiza via `SW_SHOWMINNOACTIVE` e pisca SOMENTE a propria janela. Root NAO pisca.

## Notificacoes Windows (winotify)

v1.4.54: para o clique no toast dispatchar o `launch`, Windows exige AUMID registrado via atalho Start Menu. `_ensure_start_menu_shortcut()` cria atalho em `%APPDATA%\Microsoft\Windows\Start Menu\Programs\MB Chat.lnk` com `System.AppUserModel.ID = APP_AUMID` via `IPropertyStore`. Roda so em frozen, idempotente.

v1.4.55: clique no toast abre apenas a janela do chat alvo sem restaurar root. `_open_from_notification(peer)` substitui `_restore_and_open` para notificacoes.
