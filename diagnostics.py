# diagnostics.py - Ferramentas > Diagnostico de rede: o que esta errado e o que fazer
#
# Funcao PURA: recebe uma "foto" do app (Messenger.get_diagnostic_snapshot) e
# devolve a lista de achados, do mais grave para o menos grave. Sem Tk, sem
# rede, sem banco -- testavel com dicts (tests/test_diagnostics.py).
#
# Cada achado:
#   {'level': 'erro'|'aviso'|'info'|'ok', 'code': 'UID_CONFLICT_OTHER', ...,
#    'title': uma linha, 'detail': [linhas], 'action': [linhas],
#    'banner': texto curto para a faixa da janela principal (ou None),
#    'banner_severity': 'critical'|'warning'}
#
# O MESMO resultado alimenta a janela de diagnostico e a faixa (banner) da
# janela principal -- uma regra so, nunca duas versoes divergentes.

import time

from identity import uid_belongs_to, uid_login, uid_hostname

# Mesma regra do messenger (IDENTITY_MERGE_MIN_OFFLINE_S); repetida aqui para o
# modulo continuar puro. tests/test_diagnostics.py confere que as duas batem.
MERGE_MIN_OFFLINE_S = 7 * 86400
# Mensagem recebida de alguem que nao esta na lista: so conta se for recente
TCP_RECENT_S = 30 * 60

_LEVEL_ORDER = {'erro': 0, 'aviso': 1, 'info': 2, 'ok': 3}


def _hhmm(ts):
    try:
        return time.strftime('%d/%m %H:%M', time.localtime(float(ts)))
    except (TypeError, ValueError):
        return '?'


def _vtuple(v):
    try:
        v = str(v or '').strip().lstrip('v').split('-')[0]
        return tuple(int(x) for x in v.split('.'))
    except ValueError:
        return ()


def _net24(ip):
    parts = (ip or '').split('.')
    return '.'.join(parts[:3]) if len(parts) == 4 else ''


def _usable_ip(ip):
    return bool(ip) and not ip.startswith('127.') and not ip.startswith('169.254')


def _finding(level, code, title, detail=None, action=None, banner=None,
             banner_severity='warning'):
    return {'level': level, 'code': code, 'title': title,
            'detail': list(detail or []), 'action': list(action or []),
            'banner': banner, 'banner_severity': banner_severity}


# ── Rede deste PC ───────────────────────────────────────────────────────────
def _network_findings(s, out):
    h = s.get('health') or {}
    uptime = h.get('uptime') or 0
    sent = h.get('packets_sent') or 0
    recv = h.get('packets_received') or 0
    peers = h.get('peers_count') or 0

    if h.get('bind_fallback'):
        out.append(_finding(
            'erro', 'BIND_FALLBACK',
            'A porta UDP 50100 esta ocupada: este PC nao encontra ninguem e '
            'ninguem encontra este PC.',
            [f'O MB Chat caiu na porta {h.get("bound_port")}, que nenhum colega escuta.'],
            ['Feche outras janelas/instancias do MB Chat e reinicie o computador.',
             'Se continuar: a faixa 50100+ pode estar reservada pelo Windows '
             '(Hyper-V/WSL). Ver "netsh int ipv4 show excludedportrange protocol=udp".'],
            banner='Porta UDP 50100 ocupada. A descoberta de colegas nao funciona. '
                   'Feche outras instancias do MBChat ou reinicie o computador.',
            banner_severity='critical'))

    vpn_stuck = (s.get('vpn_enabled') and s.get('manual_peers')
                 and uptime > 120 and recv == 0)
    if vpn_stuck:
        out.append(_finding(
            'aviso', 'VPN_STUCK',
            'VPN ligada, mas nenhum colega respondeu.',
            [f'IPs cadastrados: {", ".join(s.get("manual_peers") or [])}'],
            ['Confira se a VPN (PPTP/Tailscale) esta conectada e se o PC ancora esta ligado.',
             'O tunel pode estar bloqueando UDP 50100.'],
            banner='VPN ativa mas sem resposta dos colegas. Verifique a conexão '
                   'PPTP/Tailscale — o túnel pode estar bloqueando UDP.'))
    elif uptime > 30 and recv == 0 and sent > 0:
        out.append(_finding(
            'aviso', 'NO_PACKETS_IN',
            'Este PC anuncia, mas nao recebe NADA dos colegas.',
            [f'Enviados: {sent}  Recebidos: 0  (ha {int(uptime)}s)'],
            ['A entrada esta bloqueada neste PC: firewall do Windows ou do antivirus.',
             'Ferramentas > Corrigir firewall, ou liberar UDP 50100 e TCP 50101/50102 '
             'no antivirus (Kaspersky, ESET, Avast...).'],
            banner='Nenhum colega detectado. Verifique firewall e antivirus '
                   '(entrada UDP 50100 / TCP 50101).'))
    elif uptime > 60 and not h.get('multicast_joined') and peers == 0:
        out.append(_finding(
            'aviso', 'MULTICAST_NO_PEERS',
            'Multicast bloqueado e nenhum colega encontrado.',
            [],
            ['A rede (switch/roteador/Wi-Fi) pode estar filtrando a descoberta.'],
            banner='Multicast bloqueado e nenhum colega encontrado. '
                   'Rede pode estar filtrando descoberta.'))

    errs = h.get('sendto_errors') or 0
    if errs:
        out.append(_finding(
            'aviso', 'SENDTO_ERRORS',
            f'O Windows recusou {errs} envio(s) do aviso de presenca deste PC.',
            ['Os colegas podem nao estar vendo este PC na lista.'],
            ['Antivirus com firewall proprio bloqueando a SAIDA UDP: liberar o MBChat.exe.',
             'Ou placa de rede desconectada no momento do envio (cabo/Wi-Fi caiu).']))

    # Placa de rede: o aviso sai pelo IP que o app escolheu. Se os colegas
    # estao em outra rede, o aviso deste PC nao chega neles (mensagens sim,
    # porque vao direto ao IP de cada um).
    local_ip = s.get('local_ip') or ''
    ips = [ip for ip in (s.get('local_ips') or []) if _usable_ip(ip)]
    peer_nets = {}
    for p in (s.get('peers') or {}).values():
        n = _net24(p.get('ip'))
        if n:
            peer_nets[n] = peer_nets.get(n, 0) + 1
    main_net = max(peer_nets, key=peer_nets.get) if peer_nets else ''
    if (main_net and local_ip and _net24(local_ip) != main_net
            and peer_nets[main_net] >= 2
            and not s.get('vpn_enabled')):
        out.append(_finding(
            'aviso', 'WRONG_ADAPTER',
            f'O MB Chat esta usando o IP {local_ip}, mas os colegas estao na rede '
            f'{main_net}.x: o aviso de presenca deste PC pode estar indo para a '
            f'rede errada (os colegas nao o veem, mas mensagens funcionam).',
            [f'Placas com IP neste PC: {", ".join(ips) or local_ip}'],
            ['Desconecte o Wi-Fi/4G/VPN extra ou desative a placa extra em ncpa.cpl.',
             'Se precisar manter (VirtualBox/Hyper-V), de prioridade a placa do '
             'escritorio: Set-NetIPInterface -InterfaceAlias "Ethernet" -InterfaceMetric 5',
             'Depois feche o MB Chat pela bandeja (Sair) e abra de novo.']))
    elif len(ips) > 1:
        out.append(_finding(
            'info', 'MULTI_ADAPTER',
            f'Este PC tem {len(ips)} placas de rede com IP; o MB Chat usa {local_ip}.',
            [f'IPs: {", ".join(ips)}'],
            ['Se algum colega nao enxergar este PC, a placa extra e a primeira suspeita.']))


# ── Identidade (quem e quem na rede) ────────────────────────────────────────
def _identity_findings(s, out):
    me = s.get('user_id') or ''
    login = s.get('login') or ''
    h = s.get('health') or {}

    if login and me and not s.get('instance') and not uid_belongs_to(me, login):
        out.append(_finding(
            'erro', 'UID_NOT_MINE',
            f'O ID deste MB Chat ({me}) nao e do login {login}.',
            ['O banco veio de outra conta do Windows.'],
            ['Feche e abra o MB Chat: ao abrir ele cria o ID deste login sozinho.']))

    prev = s.get('identity_previous_uid') or ''
    if prev:
        when = s.get('identity_changed_at')
        quando = f' em {_hhmm(when)}' if when else ''
        out.append(_finding(
            'info', 'ID_CHANGED',
            f'Este PC trocou de ID{quando}: o banco era de outra conta '
            f'({uid_login(prev) or prev}).',
            [f'ID antigo: {prev}', f'ID atual:  {me}',
             'O historico deste PC foi mantido no ID novo. O dono do ID antigo '
             'nao foi afetado.'],
            []))

    sources = list((h.get('uid_conflict_sources') or {}).values())
    if not sources and h.get('uid_conflict_last'):
        sources = [h['uid_conflict_last']]
    for c in sorted(sources, key=lambda c: c.get('at') or 0, reverse=True):
        host = c.get('hostname') or '?'
        other = c.get('winuser') or ''
        ver = c.get('version') or '?'
        quando = _hhmm(c.get('at'))
        if other and login and other.lower() != login.lower():
            out.append(_finding(
                'erro', 'UID_CONFLICT_OTHER',
                f'O PC {host} (login {other}) esta usando o SEU ID do MB Chat.',
                [f'IP {c.get("ip") or "?"}, versao {ver}, nome "{c.get("display_name") or "?"}", '
                 f'visto em {quando}.',
                 'Para os colegas voces dois viram UM contato so: um de voces some da '
                 'lista quando os dois estao online, e mensagem pode cair no PC errado.',
                 'Causa: a pasta .mbchat deste perfil foi copiada para o perfil dele '
                 '(backup restaurado, perfil migrado).'],
                [f'Quem precisa agir e o PC {host}: abrir o MB Chat 1.8.39 ou mais novo '
                 '(ele cria um ID proprio sozinho, sem perder historico).',
                 f'Se {host} estiver em versao antiga ({ver}), atualizar.',
                 'Neste PC nao precisa fazer nada.'],
                banner=f'O PC {host} está usando o seu ID do MB Chat (um de vocês some '
                       f'da lista). Atualize o MB Chat dele.'))
        else:
            out.append(_finding(
                'aviso', 'UID_CONFLICT_SAME_LOGIN',
                f'A sua conta ({login or other}) esta aberta no PC {host} com o MESMO ID.',
                [f'IP {c.get("ip") or "?"}, versao {ver}, visto em {quando}.',
                 'Para a rede voces sao o mesmo contato: mensagem cai no PC que '
                 'anunciou por ultimo.'],
                ['Feche o MB Chat em um dos PCs (bandeja > Sair).',
                 'Se o outro PC nao for mais usado por voce: apagar a pasta '
                 '%APPDATA%\\.mbchat dele com o MB Chat fechado.'],
                banner=f'A sua conta está aberta no PC {host} com o mesmo ID do MB Chat.'))

    own = s.get('own_uid_tcp') or {}
    if own.get('count'):
        out.append(_finding(
            'erro', 'OWN_UID_TCP',
            f'Chegaram {own["count"]} mensagem(ns) com o SEU ID vindas do IP '
            f'{own.get("last_ip") or "?"}: foram descartadas.',
            [f'Ultima em {_hhmm(own.get("last_at"))}. O app trata como eco de si mesmo.',
             'E o mesmo problema de ID repetido: outro PC usa o seu ID.'],
            ['Ver o achado de ID acima; atualizar o MB Chat do PC desse IP.']))


# ── Pessoas que nao aparecem / duplicadas ───────────────────────────────────
def _people_findings(s, out):
    me = s.get('user_id') or ''
    now = s.get('now') or time.time()
    peers = s.get('peers') or {}
    contacts = s.get('contacts') or []
    by_uid = {c.get('user_id'): c for c in contacts}

    if s.get('status') == 'invisible':
        out.append(_finding(
            'aviso', 'STATUS_INVISIBLE',
            'Voce esta como "Offline": some da lista de todos os colegas.',
            ['Mensagens continuam chegando e saindo normalmente.'],
            ['Troque o status para "Disponivel" no topo da janela principal.']))

    for uid, info in sorted((s.get('tcp_recent') or {}).items(),
                            key=lambda kv: kv[1].get('at') or 0, reverse=True):
        if uid == me or uid in peers:
            continue
        if now - (info.get('at') or 0) > TCP_RECENT_S:
            continue
        c = by_uid.get(uid) or {}
        name = info.get('name') or c.get('display_name') or uid_login(uid) or uid
        out.append(_finding(
            'aviso', 'TCP_BUT_NOT_LISTED',
            f'{name} mandou mensagem em {_hhmm(info.get("at"))}, mas NAO aparece '
            f'na lista: o aviso de presenca dele nao chega a este PC.',
            [f'IP de onde a mensagem veio: {info.get("ip") or "?"}  (ID {uid})',
             'Mensagens funcionam porque vao direto ao IP; a lista depende do '
             'aviso UDP 50100, que esta se perdendo no caminho.'],
            ['No PC dele: Ferramentas > Diagnostico de rede.',
             'Causas mais comuns: antivirus bloqueando a SAIDA UDP; aviso saindo pela '
             'placa errada (Wi-Fi + cabo, VPN, VirtualBox/Hyper-V); status "Offline".',
             'Se ele usar o mesmo ID de outra pessoa, o PC dela mostra "esta usando '
             'o SEU ID".']))

    names = {}
    for uid, p in peers.items():
        if uid == me:
            continue
        nm = (p.get('display_name') or '').strip().lower()
        if nm:
            names.setdefault(nm, []).append((uid, p))
    for nm, lst in sorted(names.items()):
        if len(lst) < 2:
            continue
        logins = {uid_login(u).lower() for u, _ in lst if uid_login(u)}
        hosts = ', '.join(f'{p.get("hostname") or "?"} ({p.get("ip") or "?"})' for _, p in lst)
        shown = lst[0][1].get('display_name') or nm
        if len(logins) == 1:
            out.append(_finding(
                'info', 'SAME_PERSON_TWO_PCS',
                f'{shown} esta online em {len(lst)} PCs (mesma conta, IDs diferentes).',
                [f'PCs: {hosts}',
                 'Cada PC recebe as mensagens mandadas para ele; o historico fica '
                 'dividido entre as duas entradas enquanto as duas estiverem em uso.'],
                ['Normal se a pessoa usa dois PCs. Quando um deixar de ser usado, o '
                 'historico dele junta no outro depois de 7 dias.']))
        else:
            out.append(_finding(
                'aviso', 'SAME_NAME',
                f'{len(lst)} pessoas diferentes online com o mesmo nome "{shown}".',
                [f'PCs: {hosts}'],
                ['Para nao confundir, uma delas pode mudar o nome em Preferencias > Conta.']))

    # ID antigo da mesma pessoa (PC novo sem a pasta): vai ou nao juntar?
    since = s.get('tracking_since') or now
    for uid, p in peers.items():
        lg = (p.get('winuser') or '').strip()
        if uid == me or not lg or not uid_belongs_to(uid, lg):
            continue
        for c in contacts:
            old = c.get('user_id') or ''
            if old in (uid, me) or old in peers or not uid_belongs_to(old, lg):
                continue
            name = p.get('display_name') or lg
            old_host = uid_hostname(old, lg) or c.get('hostname') or '?'
            if p.get('login_scope') != 'domain' and \
                    old_host.lower() != (p.get('hostname') or '').lower():
                out.append(_finding(
                    'info', 'OLD_ID_NO_MERGE',
                    f'{name} tem um ID antigo (PC {old_host}) que NAO sera juntado.',
                    ['Conta local do Windows (ou versao antiga): o mesmo login em outro '
                     'PC pode ser outra pessoa, entao o app nao arrisca.'],
                    ['A conversa antiga continua em Ferramentas > Historico, com o mesmo nome.']))
                continue
            last = c.get('last_announce_at') or since
            falta = MERGE_MIN_OFFLINE_S - (now - last)
            if falta <= 0:
                quando = 'na proxima checagem (ate 6h)'
            else:
                quando = f'em ~{int(falta // 86400) + 1} dia(s)'
            out.append(_finding(
                'info', 'OLD_ID_PENDING',
                f'{name}: historico do ID antigo (PC {old_host}) junta no atual '
                f'{quando}.',
                ['O ID antigo precisa ficar 7 dias sem aparecer (evita mover historico '
                 'de quem so usou outro PC por algumas horas).'],
                ['Nada a fazer. Ate la, a conversa antiga aparece em Ferramentas > '
                 'Historico com o mesmo nome.']))

    for m in s.get('merges') or []:
        out.append(_finding(
            'info', 'MERGED',
            f'Historico juntado: {m.get("name") or m.get("login")} (ID antigo do PC '
            f'{uid_hostname(m.get("old", ""), m.get("login", "")) or "?"}) agora '
            f'esta no ID atual.',
            [f'{m.get("old")} -> {m.get("new")} em {_hhmm(m.get("at"))}'],
            []))

    mine = _vtuple(s.get('version'))
    old = sorted({(p.get('display_name') or uid_login(u) or u)
                  for u, p in peers.items()
                  if p.get('version') and mine and _vtuple(p.get('version')) < mine})
    if old:
        out.append(_finding(
            'info', 'OLD_VERSIONS',
            f'{len(old)} colega(s) em versao anterior a {s.get("version")}.',
            [', '.join(old[:12]) + (' ...' if len(old) > 12 else '')],
            ['Eles atualizam sozinhos. Correcoes de ID so valem depois que o PC '
             'com problema estiver na versao nova.']))


def build_findings(s):
    out = []
    _network_findings(s, out)
    _identity_findings(s, out)
    _people_findings(s, out)
    if not any(f['level'] in ('erro', 'aviso') for f in out):
        n = (s.get('health') or {}).get('peers_count') or 0
        out.insert(0, _finding(
            'ok', 'OK',
            f'Nenhum problema encontrado: {n} colega(s) visivel(is) e anuncios '
            f'chegando normalmente.',
            [], []))
    out.sort(key=lambda f: _LEVEL_ORDER.get(f['level'], 9))
    return out


# Achado que vai para a faixa da janela principal (o mais grave com banner)
def banner_finding(findings):
    for f in findings:
        if f.get('banner') and f['banner_severity'] == 'critical':
            return f
    for f in findings:
        if f.get('banner'):
            return f
    return None


_LABEL = {'erro': 'PROBLEMA', 'aviso': 'ATENCAO', 'info': 'INFO', 'ok': 'OK'}


# Texto puro de um achado (janela de diagnostico e "Copiar tudo")
def format_finding(f):
    lines = [f'[{_LABEL.get(f["level"], f["level"].upper())}] {f["title"]}']
    for d in f.get('detail') or []:
        lines.append(f'    {d}')
    acts = f.get('action') or []
    if acts:
        lines.append(f'    O que fazer: {acts[0]}')
        for a in acts[1:]:
            lines.append(f'                 {a}')
    return lines


_STATUS_LABEL = {'online': 'Disponivel', 'away': 'Ausente', 'busy': 'Ocupado',
                 'invisible': 'Offline (invisivel para os colegas)'}
_SCOPE_LABEL = {'domain': 'conta de dominio', 'local': 'conta local deste PC',
                '': 'desconhecido'}


# Relatorio completo da janela Ferramentas > Diagnostico de rede.
# Devolve [(linha, tag)]: tag = 'h' (titulo de secao), nivel do achado
# ('erro'/'aviso'/'info'/'ok', so na 1a linha de cada achado) ou None.
def build_report(s, findings, log_tail=None):
    rows = []

    def add(line='', tag=None):
        rows.append((line, tag))

    h = s.get('health') or {}
    peers = s.get('peers') or {}
    me = s.get('user_id') or ''
    login = s.get('login') or ''
    add(f'MB Chat v{s.get("version") or "?"}  -  {s.get("display_name") or "?"}  '
        f'({s.get("hostname") or "?"})', 'h')
    add(f'Gerado em {_hhmm(s.get("now") or time.time())}')

    add()
    add('=== VERIFICACAO AUTOMATICA ===', 'h')
    for f in findings:
        lines = format_finding(f)
        add(lines[0], f['level'])
        for ln in lines[1:]:
            add(ln)
        add()

    add('=== IDENTIDADE ===', 'h')
    add(f'Usuario:          {s.get("display_name") or "?"}')
    add(f'User ID:          {me}')
    add(f'Login Windows:    {login or "?"} ({_SCOPE_LABEL.get(s.get("login_scope") or "", "?")})')
    if s.get('instance'):
        add(f'ID e deste login: (instancia de teste "{s["instance"]}")')
    else:
        add(f'ID e deste login: {"sim" if uid_belongs_to(me, login) else "NAO"}')
    if s.get('identity_previous_uid'):
        add(f'ID anterior:      {s["identity_previous_uid"]}')
    add(f'Status:           {_STATUS_LABEL.get(s.get("status") or "", s.get("status") or "?")}')
    add(f'Hostname:         {s.get("hostname") or "?"}')
    add(f'IP usado:         {s.get("local_ip") or "?"}')
    add(f'Placas com IP:    {", ".join(s.get("local_ips") or []) or "?"}')

    add()
    add('=== REDE (DESCOBERTA) ===', 'h')
    add(f'Porta UDP:        {h.get("bound_port")}'
        + ('  <-- PORTA DE EMERGENCIA, DESCOBERTA QUEBRADA' if h.get('bind_fallback') else ''))
    add(f'Multicast:        {"sim" if h.get("multicast_joined") else "nao"}')
    add(f'Aberto ha:        {int(h.get("uptime") or 0)}s')
    add(f'Avisos enviados:  {h.get("packets_sent")}')
    add(f'Avisos recebidos: {h.get("packets_received")}')
    add(f'Erros de envio:   {h.get("sendto_errors")}')
    add(f'Colegas na lista: {h.get("peers_count")}')
    add(f'Conflitos de ID:  {h.get("uid_conflicts") or 0}')
    own = s.get('own_uid_tcp') or {}
    if own.get('count'):
        add(f'Msgs c/ meu ID:   {own["count"]} (descartadas; ultima do IP {own.get("last_ip")})')
    if s.get('vpn_enabled'):
        add(f'VPN:              ligada ({", ".join(s.get("manual_peers") or []) or "sem IPs"})')
    for p, e in h.get('bind_errors') or []:
        add(f'Erro de porta:    {p}  {e}')

    add()
    add(f'=== COLEGAS NA LISTA ({len(peers)}) ===', 'h')
    add(f'{"Nome":24} {"IP":15} {"PC":16} {"Versao":9} Login')
    counts = {}
    for p in peers.values():
        k = (p.get('display_name') or '').strip().lower()
        counts[k] = counts.get(k, 0) + 1
    for uid, p in sorted(peers.items(), key=lambda kv: (kv[1].get('display_name') or '').lower()):
        name = (p.get('display_name') or '?')[:24]
        mark = '  <-- nome repetido' if counts.get(name.strip().lower(), 0) > 1 else ''
        add(f'{name:24} {(p.get("ip") or "?"):15} {(p.get("hostname") or "?")[:16]:16} '
            f'{(p.get("version") or "?")[:9]:9} {p.get("winuser") or uid_login(uid) or "?"}{mark}')

    add()
    add('=== ULTIMAS LINHAS DO LOG (network.log) ===', 'h')
    if log_tail:
        for ln in log_tail:
            add(ln.rstrip('\r\n'))
    else:
        add('(vazio)')
    return rows
