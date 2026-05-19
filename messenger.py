# MB Chat - Camada de mensagens (controller)
# Liga network <-> database <-> GUI
#
# Este modulo e o cerebro do app. Orquestra:
# - Discovery de peers (via UDPDiscovery)
# - Envio/recebimento de mensagens (via TCPClient/TCPServer)
# - Transferencia de arquivos (via FileSender/FileReceiver)
# - Gerenciamento de grupos (convites, mensagens, entrada/saida)
# - Persistencia no banco de dados (via Database)
# - Notificacao da GUI via callbacks
#
# A GUI nunca acessa rede ou banco diretamente — tudo passa por aqui.
# Arquitetura: gui.py -> messenger.py -> network.py / database.py

import time       # Timestamps para mensagens
import uuid       # IDs unicos para mensagens e transferencias
import os         # Caminhos de arquivos e diretorios
import threading  # Lock para contadores thread-safe
import base64     # Codificacao de imagens para envio via TCP

# Importa componentes de rede e constantes
from network import (
    UDPDiscovery, TCPServer, TCPClient, FileSender, FileReceiver,
    generate_user_id, get_local_ip, get_machine_info,
    MT_ANNOUNCE, MT_DEPART, MT_MESSAGE, MT_FILE_REQ, MT_FILE_ACC,
    MT_FILE_DEC, MT_FILE_CANCEL, MT_STATUS, MT_TYPING, MT_ACK,
    MT_GROUP_INV, MT_GROUP_MSG, MT_GROUP_LEAVE, MT_GROUP_JOIN, MT_GROUP_KICK,
    MT_GROUP_ADMIN_SET, MT_GROUP_DELETE,
    MT_IMAGE, MT_POLL_CREATE, MT_POLL_VOTE,
    MT_REMINDER_INVITE, MT_REMINDER_ACCEPT, MT_REMINDER_DECLINE, MT_REMINDER_CANCEL,
    MT_REMINDER_COMPLETED,
    MT_MEETING_INVITE, MT_MEETING_ACCEPT, MT_MEETING_DECLINE,
    MT_MEETING_CANCEL, MT_MEETING_SYNC_REQ, MT_MEETING_SYNC_RES,
    TCP_PORT
)
from database import Database  # Banco de dados local


# Controller principal do MB Chat
# Conecta as 3 camadas: GUI <-> Rede <-> Banco de dados
# A GUI registra callbacks no __init__ e recebe notificacoes
# quando eventos acontecem (nova mensagem, peer encontrado, etc)
class Messenger:

    # Inicializa o messenger com todos os callbacks da GUI
    # display_name: Nome de exibicao (None = usa do banco ou login do OS)
    # on_user_found: Callback(uid, info) - peer descoberto na rede
    # on_user_lost: Callback(uid, info) - peer perdeu conexao
    # on_message: Callback(from_user, content, msg_id, timestamp) - msg recebida
    # on_status: Callback(from_user, status) - peer mudou status
    # on_typing: Callback(from_user, is_typing) - peer digitando
    # on_file_incoming: Callback(file_id, from_user, name, filename, size) - arquivo recebido
    # on_file_progress: Callback(file_id, transferred, total) - progresso
    # on_file_complete: Callback(file_id, filepath) - transferencia completa
    # on_file_error: Callback(file_id, error_msg) - erro na transferencia
    # on_group_invite: Callback(group_id, name, from_user, members, type) - convite grupo
    # on_group_message: Callback(group_id, from_uid, name, content, ts) - msg grupo
    # on_group_leave: Callback(group_id, uid, name) - membro saiu do grupo
    # on_group_join: Callback(group_id, uid, name) - membro entrou no grupo
    # on_image: Callback(from_user, image_path, msg_id, timestamp) - imagem recebida
    # on_poll: Callback(group_id, poll_data) - enquete recebida ou voto atualizado
    def __init__(self, display_name=None, on_user_found=None,
                 on_user_lost=None, on_message=None, on_status=None,
                 on_typing=None, on_file_incoming=None,
                 on_file_progress=None, on_file_complete=None,
                 on_file_error=None, on_group_invite=None,
                 on_group_message=None, on_group_leave=None,
                 on_group_join=None, on_image=None, on_poll=None,
                 on_reminder_invite=None, on_reminder_response=None,
                 on_reminder_cancel=None, on_reminder_completed=None,
                 on_meeting_invite=None, on_meeting_response=None,
                 on_meeting_cancel=None, on_meeting_sync=None,
                 on_group_kick=None, on_group_admin_set=None,
                 on_group_deleted=None):
        self.db = Database()  # Conexao com banco de dados local
        self._msg_counter = 0  # Contador para IDs unicos de mensagem
        self._lock = threading.Lock()  # Lock para operacoes thread-safe
        self._file_senders = {}  # file_id -> FileSender (envios ativos)
        self._file_receiver = None  # FileReceiver (receptor de arquivos)

        # === Callbacks para notificar a GUI ===
        self.on_user_found = on_user_found      # Peer encontrado
        self.on_user_lost = on_user_lost        # Peer perdido
        self.on_message = on_message            # Mensagem recebida
        self.on_status = on_status              # Status mudou
        self.on_typing = on_typing              # Indicador de digitacao
        self.on_file_incoming = on_file_incoming  # Arquivo chegando
        self.on_file_progress = on_file_progress  # Progresso do arquivo
        self.on_file_complete = on_file_complete  # Arquivo completo
        self.on_file_error = on_file_error      # Erro no arquivo
        self.on_group_invite = on_group_invite  # Convite para grupo
        self.on_group_message = on_group_message  # Mensagem de grupo
        self.on_group_leave = on_group_leave    # Membro saiu do grupo
        self.on_group_join = on_group_join      # Membro entrou no grupo
        self.on_image = on_image                # Imagem recebida
        self.on_poll = on_poll                  # Enquete recebida/voto
        self.on_reminder_invite = on_reminder_invite              # Convite lembrete recebido
        self.on_reminder_response = on_reminder_response          # Resposta de convite (accept/decline)
        self.on_reminder_cancel = on_reminder_cancel              # Criador cancelou lembrete compartilhado
        self.on_reminder_completed = on_reminder_completed        # Participante concluiu lembrete compartilhado
        self.on_meeting_invite = on_meeting_invite        # Convite de reunião recebido
        self.on_meeting_response = on_meeting_response    # Resposta de convite de reunião
        self.on_meeting_cancel = on_meeting_cancel        # Reunião cancelada
        self.on_meeting_sync = on_meeting_sync            # Sync de reservas (timegrid atualizar)
        self.on_group_kick = on_group_kick                # Membro removido do grupo pelo criador
        self.on_group_admin_set = on_group_admin_set      # Status de admin de um membro alterado
        self.on_group_deleted = on_group_deleted          # Grupo deletado pelo criador

        # === Grupos em memoria ===
        # Formato: group_id -> {name, group_type, members: [{uid, display_name, ip}]}
        self._groups = {}

        # === Setup do usuario local ===
        local = self.db.get_local_user()   # Tenta carregar do banco

        if local and local.get('user_id'):
            # Se ja temos um ID persistido no banco, USAMOS ELE.
            # Isso evita que o ID mude caso o Windows alterne entre Wi-Fi e Ethernet
            # (o uuid.getnode() pode retornar MACs diferentes).
            self.user_id = local['user_id']
        else:
            # Primeira execucao: gera um ID novo (MAC+hostname+winuser)
            self.user_id = generate_user_id()

        # Migracao: usuarios pre-1.4.60 tem user_id no formato mac_host
        # (sem winuser). Renomeia tudo para o formato novo para que historico,
        # contatos e grupos continuem funcionando pos-update.
        # Idempotente: se ja esta no formato novo, no-op.
        try:
            self.db.migrate_user_ids_add_winuser_suffix(self.user_id)
        except Exception:
            pass

        # Prioridade do nome: argumento > banco > login do OS
        if display_name:
            self.display_name = display_name
        elif local:
            self.display_name = local['display_name']
        else:
            try:
                self.display_name = os.getlogin()
            except Exception:
                self.display_name = 'User'

        self.status = 'online'  # Status inicial
        self.note = self.db.get_local_note()  # Nota pessoal do banco
        self.ramal = self.db.get_local_ramal()  # Ramal (4 digitos) do banco
        self.avatar_index = int(self.db.get_setting('avatar_index', '0'))  # Avatar padrao
        self.avatar_data = self._generate_avatar_thumbnail()  # Thumbnail base64
        self.db.set_local_user(self.user_id, self.display_name, self.status)

        # Marca todos os contatos como offline no startup
        # (nao sabemos quem esta online ate receber announces)
        self.db.set_all_contacts_offline()

        # === Componentes de rede ===

        # Discovery UDP: descobre peers via multicast/broadcast
        self.discovery = UDPDiscovery(
            self.user_id, self.display_name, self.status,
            on_peer_found=self._on_peer_found,  # Callback interno
            on_peer_lost=self._on_peer_lost
        )
        # Configura dados extras no discovery (enviados no announce)
        self.discovery.note = self.note
        self.discovery.avatar_index = self.avatar_index
        self.discovery.avatar_data = self.avatar_data
        self.discovery.department = self.db.get_setting('department', '')
        self.discovery.ramal = self.db.get_local_ramal()

        # Servidor TCP: recebe mensagens de outros peers
        self.tcp_server = TCPServer(
            on_message=self._on_tcp_message,  # Callback para msgs recebidas
            on_file_request=self._on_file_request
        )

        # Receptor de arquivos: salva arquivos recebidos
        downloads = self.db.get_setting('download_dir',
                                        os.path.join(os.path.expanduser('~'),
                                                     'MB_Chat_Files'))
        self._file_receiver = FileReceiver(
            downloads,
            on_incoming=self._on_file_incoming_internal,
            on_progress=self._on_file_progress_internal,
            on_complete=self._on_file_complete_internal,
            on_error=self._on_file_error_internal
        )

    # ========================================
    # LIFECYCLE — Iniciar e parar servicos
    # ========================================

    # Inicia todos os servicos de rede (discovery + TCP + file)
    def start(self):
        self.tcp_server.start()     # Comeca a aceitar conexoes TCP (descobre porta real)
        # Informa o discovery qual foi a porta TCP efetiva (caso tenha usado fallback)
        self.discovery.tcp_port = getattr(self.tcp_server, 'port', TCP_PORT)

        self.discovery.start()      # Comeca a enviar/receber announces UDP
        self._file_receiver.start()  # Comeca a aceitar arquivos

        # Carrega peers manuais persistidos (cenario VPN/fora-da-LAN).
        # Lista vazia = no-op (caminho da LAN intocado, zero overhead).
        try:
            self._reload_manual_peers()
        except Exception:
            pass
        # Loop de auto-cancelamento de reuniões sem quórum
        self._start_meeting_auto_cancel_loop()
        # Boot recovery: se rede não estava pronta ao subir, reinicia sockets após 30s
        self._schedule_boot_recovery()

    # Se após 30s ainda não há peers, recria sockets (rede pode não ter estado pronta no boot)
    def _schedule_boot_recovery(self):
        def _check():
            time.sleep(30)
            if not self.discovery or not self.discovery.running:
                return
            with self.discovery._lock:
                n = len(self.discovery.peers)
            if n == 0:
                try:
                    self.discovery.restart()
                except Exception:
                    pass
        threading.Thread(target=_check, daemon=True).start()

    # Para todos os servicos e limpa estado
    def stop(self):
        self.db.update_local_status('offline')   # Marca como offline no banco
        self.db.set_all_contacts_offline()        # Marca todos os contatos como offline
        self.discovery.stop()      # Para discovery (envia depart)
        self.tcp_server.stop()     # Para servidor TCP
        self._file_receiver.stop()  # Para receptor de arquivos
        self.db.close()            # Fecha conexao do banco

    # Gera um ID unico para mensagem
    # Formato: "user_id_contador_timestamp_ms"
    # Thread-safe gracas ao lock
    def _next_msg_id(self):
        with self._lock:
            self._msg_counter += 1
            return f"{self.user_id}_{self._msg_counter}_{int(time.time()*1000)}"

    # ========================================
    # PEER DISCOVERY — Callbacks do UDP
    # ========================================

    # Callback chamado quando um peer e encontrado/atualizado via UDP
    # Salva no banco e notifica a GUI
    # Chamado a cada announce recebido (nao so novos peers)
    def _on_peer_found(self, uid, info):
        # Merge: se este peer atualizou de mac_host -> mac_host_winuser, traz
        # historico/grupos do contato antigo para o user_id novo. No-op se
        # nao houver contato legado correspondente. peer_winuser e usado
        # como sufixo a remover (preciso, suporta nomes com underscore).
        try:
            self.db.merge_legacy_contact(uid, info.get('winuser', ''))
        except Exception:
            pass
        self.db.upsert_contact(
            uid, info['display_name'], info['ip'],
            hostname=info.get('hostname', ''),
            os_info=info.get('os', ''),
            status=info.get('status', 'online'),
            note=info.get('note', ''),
            avatar_index=info.get('avatar_index', 0),
            avatar_data=info.get('avatar_data', ''),
            winuser=info.get('winuser', '')
        )
        dept = info.get('department', '')
        if dept:
            self.db.set_contact_department(uid, dept)
        ramal = info.get('ramal', '')
        self.db.set_contact_ramal(uid, ramal)
        if self.db.is_blocked(uid):
            return  # Computador bloqueado: nao aparece na GUI nem sincroniza
        if self.on_user_found:
            self.on_user_found(uid, info)  # Notifica GUI
        # Sync de reuniões ao reconectar peer
        peer_ip = info.get('ip', '')
        if peer_ip:
            threading.Thread(
                target=lambda ip=peer_ip: self.sync_meetings_with_peer(ip),
                daemon=True).start()

    # Callback chamado quando um peer e perdido (timeout ou depart)
    # Marca como offline no banco e notifica a GUI
    def _on_peer_lost(self, uid, info):
        self.db.set_contact_offline(uid)
        if self.on_user_lost:
            self.on_user_lost(uid, info)  # Notifica GUI

    # ========================================
    # TCP MESSAGES — Processamento de mensagens
    # ========================================

    # Callback central que roteia todas as mensagens TCP recebidas
    # Tipos tratados:
    # - MT_MESSAGE: mensagem de texto individual
    # - MT_TYPING: indicador de digitacao
    # - MT_STATUS: mudanca de status
    # - MT_ACK: confirmacao de recebimento
    # - MT_GROUP_INV: convite para grupo
    # - MT_GROUP_MSG: mensagem de grupo
    # - MT_GROUP_LEAVE: membro saiu do grupo
    # - MT_GROUP_JOIN: membro entrou no grupo
    def _on_tcp_message(self, msg, addr):
        msg_type = msg.get('type')
        from_user = msg.get('from_user')

        # Filtro de eco: ignora mensagens onde o remetente sou eu mesmo
        if from_user and from_user == self.user_id:
            return

        # Fix 8: bloqueia mensagens de usuarios na block_list
        if from_user and self.db.is_blocked(from_user):
            return

        # Fix 2: IP pinning TCP — warning se IP diverge do cadastrado (não rejeita, VPN pode divergir)
        if from_user:
            try:
                known = self.db.get_contact(from_user)
                if known and known.get('ip_address'):
                    expected = known['ip_address']
                    ts_ip = known.get('ts_ip', '') or ''
                    sender_ip = addr[0] if addr else ''
                    if sender_ip and sender_ip not in (expected, ts_ip):
                        import logging as _logging
                        _logging.getLogger('mbchat.messenger').warning(
                            'IP mismatch from %s: expected %s got %s',
                            from_user, expected, sender_ip)
            except Exception:
                pass

        # --- Mensagem de texto individual ---
        if msg_type == MT_MESSAGE:
            msg_id = msg.get('msg_id', str(uuid.uuid4()))
            content = msg.get('content', '')
            timestamp = msg.get('timestamp', time.time())
            reply_to = msg.get('reply_to', '')

            self.db.save_message(msg_id, from_user, self.user_id,
                                content, 'text', is_sent=False,
                                timestamp=timestamp, reply_to_id=reply_to)

            contact = self.db.get_contact(from_user)
            if contact:
                TCPClient.send_message(contact['ip_address'], TCP_PORT, {
                    'type': MT_ACK,
                    'from_user': self.user_id,
                    'msg_id': msg_id
                })

            if self.on_message:
                self.on_message(from_user, content, msg_id, timestamp,
                               reply_to=reply_to,
                               is_broadcast=msg.get('is_broadcast', False))

        # --- Indicador de digitacao ---
        elif msg_type == MT_TYPING:
            if self.on_typing:
                self.on_typing(from_user, msg.get('is_typing', False))

        # --- Mudanca de status ---
        elif msg_type == MT_STATUS:
            new_status = msg.get('status', 'online')
            self.db.upsert_contact(
                from_user, msg.get('display_name', ''),
                addr[0], status=new_status)
            if self.on_status:
                self.on_status(from_user, new_status)

        # --- Confirmacao de recebimento ---
        elif msg_type == MT_ACK:
            pass  # Pode ser usado para marcar entrega (nao implementado)

        # --- Recusa/cancelamento de arquivo (reservados, fluxo via FileReceiver) ---
        elif msg_type in (MT_FILE_DEC, MT_FILE_CANCEL):
            file_id = msg.get('file_id', '')
            if file_id and file_id in self._file_senders:
                self._file_senders[file_id].cancel()
                if self.on_file_error:
                    reason = 'Arquivo recusado' if msg_type == MT_FILE_DEC else 'Transferência cancelada'
                    self.on_file_error(file_id, reason)

        # --- Imagem inline (clipboard) ---
        elif msg_type == MT_IMAGE:
            msg_id = msg.get('msg_id', str(uuid.uuid4()))
            timestamp = msg.get('timestamp', time.time())
            b64 = msg.get('image_data', '')
            group_id = msg.get('group_id')

            try:
                image_bytes = base64.b64decode(b64)
            except Exception:
                return
            image_path = self._save_image_to_disk(image_bytes, msg_id)

            if group_id:
                # Imagem de grupo — notifica via on_group_message com marcador especial
                display_name = msg.get('display_name', '')
                if not display_name or display_name == from_user:
                    _c = self.db.get_contact(from_user)
                    display_name = (_c.get('display_name') if _c else '') or from_user
                # Persiste imagem no historico do grupo (idempotente por msg_id)
                try:
                    if msg_id and not self.db.has_group_message(msg_id):
                        self.db.save_group_message(
                            group_id, msg_id, from_user, image_path,
                            sender_name=display_name, msg_type='image',
                            is_sent=False, timestamp=timestamp)
                except Exception:
                    pass
                if self.on_image:
                    self.on_image(from_user, image_path, msg_id, timestamp,
                                  group_id=group_id, display_name=display_name)
            else:
                # Imagem individual
                self.db.save_message(msg_id, from_user, self.user_id,
                                    image_path, 'image', is_sent=False,
                                    timestamp=timestamp)
                # ACK
                contact = self.db.get_contact(from_user)
                if contact:
                    TCPClient.send_message(contact['ip_address'], TCP_PORT, {
                        'type': MT_ACK,
                        'from_user': self.user_id,
                        'msg_id': msg_id
                    })
                if self.on_image:
                    self.on_image(from_user, image_path, msg_id, timestamp)

        # --- Convite para grupo ---
        elif msg_type == MT_GROUP_INV:
            group_id = msg.get('group_id')
            group_name = msg.get('group_name', 'Grupo')
            group_type = msg.get('group_type', 'temp')  # temp ou fixed
            members = msg.get('members', [])
            creator_uid = msg.get('creator_uid', from_user)
            admins = msg.get('admins', [creator_uid])

            # Salva grupo em memoria
            self._groups[group_id] = {'name': group_name, 'members': members,
                                       'group_type': group_type,
                                       'creator_uid': creator_uid,
                                       'admins': admins}

            # Se fixo, persiste no banco
            if group_type == 'fixed':
                self.db.save_group(group_id, group_name, 'fixed',
                                   creator_uid=creator_uid)
                for m in members:
                    is_admin = 1 if m['uid'] in admins else 0
                    self.db.save_group_member(group_id, m['uid'],
                                              m['display_name'],
                                              m.get('ip', ''), is_admin=is_admin)

            # Notifica GUI para abrir janela do grupo
            if self.on_group_invite:
                self.on_group_invite(group_id, group_name, from_user,
                                     members, group_type)

        # --- Mensagem de grupo ---
        elif msg_type == MT_GROUP_MSG:
            group_id = msg.get('group_id')
            content = msg.get('content', '')
            timestamp = msg.get('timestamp', time.time())
            display_name = msg.get('display_name', '')
            if not display_name or display_name == from_user:
                _c = self.db.get_contact(from_user)
                display_name = (_c.get('display_name') if _c else '') or from_user
            reply_to = msg.get('reply_to', '')
            mentions = msg.get('mentions', [])
            msg_id = msg.get('msg_id', '')
            # Recovery: se o grupo nao esta em memoria, e provavel que o
            # MT_GROUP_INV tenha sido perdido (peer offline na hora da criacao
            # do grupo, ou grupo criado antes do peer abrir o app). Reconstroi
            # um stub com o que veio na propria mensagem para o usuario ver
            # o grupo aparecer e poder continuar a conversa.
            group_name = msg.get('group_name', '') or 'Grupo'
            group_type = msg.get('group_type', 'temp')
            recovered = False
            if group_id and group_id not in self._groups:
                # Tenta carregar do DB (caso seja fixo ja salvo)
                rows = self.db.get_groups()
                db_g = next((g for g in rows if g['group_id'] == group_id), None)
                if db_g:
                    members = self.db.get_group_members(group_id)
                    creator_uid = db_g.get('creator_uid', '')
                    admins = [m['uid'] for m in members if m.get('is_admin')]
                    self._groups[group_id] = {
                        'name': db_g['name'],
                        'group_type': db_g['group_type'],
                        'creator_uid': creator_uid,
                        'admins': admins,
                        'members': [{'uid': m['uid'],
                                     'display_name': m['display_name'],
                                     'ip': m['ip']} for m in members],
                    }
                    group_name = db_g['name']
                    group_type = db_g['group_type']
                else:
                    # Stub minimo: dois membros conhecidos (eu + remetente).
                    # Se mais membros existirem, vao se materializando via
                    # mensagens subsequentes (ainda da pra responder).
                    sender_ip = addr[0] if addr else ''
                    self._groups[group_id] = {
                        'name': group_name,
                        'group_type': group_type,
                        'members': [
                            {'uid': self.user_id,
                             'display_name': self.display_name,
                             'ip': get_local_ip()},
                            {'uid': from_user,
                             'display_name': display_name,
                             'ip': sender_ip},
                        ],
                    }
                    if group_type == 'fixed':
                        self.db.save_group(group_id, group_name, 'fixed')
                        self.db.save_group_member(group_id, self.user_id,
                                                  self.display_name,
                                                  get_local_ip())
                        self.db.save_group_member(group_id, from_user,
                                                  display_name, sender_ip)
                    recovered = True
            # Persiste a mensagem no historico do grupo (idempotente por msg_id)
            try:
                if msg_id and not self.db.has_group_message(msg_id):
                    self.db.save_group_message(
                        group_id, msg_id, from_user, content,
                        sender_name=display_name, msg_type='text',
                        is_sent=False, timestamp=timestamp,
                        reply_to_id=reply_to)
            except Exception:
                pass

            if self.on_group_message:
                self.on_group_message(group_id, from_user, display_name,
                                      content, timestamp, reply_to=reply_to,
                                      mentions=mentions, msg_id=msg_id,
                                      group_name=group_name,
                                      group_type=group_type,
                                      recovered=recovered)

        # --- Membro saiu do grupo ---
        elif msg_type == MT_GROUP_LEAVE:
            group_id = msg.get('group_id')
            display_name = msg.get('display_name', from_user)

            # Remove membro da lista em memoria
            group = self._groups.get(group_id)
            if group:
                group['members'] = [m for m in group['members']
                                    if m['uid'] != from_user]
                # Se grupo fixo, atualiza o banco tambem
                if group.get('group_type') == 'fixed':
                    self.db.delete_group_member(group_id, from_user)

            # Notifica GUI para exibir "X saiu do grupo"
            if self.on_group_leave:
                self.on_group_leave(group_id, from_user, display_name)

        # --- Membro entrou no grupo ---
        elif msg_type == MT_GROUP_JOIN:
            group_id = msg.get('group_id')
            display_name = msg.get('display_name', from_user)
            new_ip = msg.get('ip', '')

            # Adiciona membro a lista em memoria (evita duplicata)
            group = self._groups.get(group_id)
            if group:
                if not any(m['uid'] == from_user for m in group['members']):
                    group['members'].append({
                        'uid': from_user,
                        'display_name': display_name,
                        'ip': new_ip
                    })
                # Se fixo, persiste no banco
                if group.get('group_type') == 'fixed':
                    self.db.save_group_member(group_id, from_user,
                                              display_name, new_ip)

            # Notifica GUI para exibir "X entrou no grupo"
            if self.on_group_join:
                self.on_group_join(group_id, from_user, display_name)

        # --- Membro removido do grupo pelo criador ---
        elif msg_type == MT_GROUP_KICK:
            group_id = msg.get('group_id')
            target_uid = msg.get('target_uid', '')
            group = self._groups.get(group_id)
            if group and target_uid:
                group['members'] = [m for m in group['members']
                                    if m['uid'] != target_uid]
                if group.get('group_type') == 'fixed':
                    self.db.delete_group_member(group_id, target_uid)
                # Se eu fui kickado, limpa o grupo completamente da memória e banco
                if target_uid == self.user_id:
                    if group_id in self._groups:
                        del self._groups[group_id]
                    self.db.delete_group(group_id)
            if self.on_group_kick:
                self.on_group_kick(group_id, target_uid)

        # --- Atualizacao de Status de Admin ---
        elif msg_type == MT_GROUP_ADMIN_SET:
            group_id = msg.get('group_id')
            target_uid = msg.get('target_uid', '')
            is_admin = msg.get('is_admin', False)
            group = self._groups.get(group_id)
            if group and target_uid:
                admins = group.get('admins', [])
                if is_admin and target_uid not in admins:
                    admins.append(target_uid)
                elif not is_admin and target_uid in admins:
                    admins.remove(target_uid)
                group['admins'] = admins
                if group.get('group_type') == 'fixed':
                    # Atualizar no banco
                    members = group.get('members', [])
                    for m in members:
                        if m['uid'] == target_uid:
                            self.db.save_group_member(group_id, target_uid, m['display_name'], m.get('ip', ''), is_admin=1 if is_admin else 0)
                            break
            if hasattr(self, 'on_group_admin_set') and self.on_group_admin_set:
                self.on_group_admin_set(group_id, target_uid, is_admin)

        # --- Grupo deletado pelo criador ---
        elif msg_type == MT_GROUP_DELETE:
            group_id = msg.get('group_id')
            if group_id in self._groups:
                del self._groups[group_id]
            # Apaga o grupo e seus membros do banco local sempre (se existirem)
            self.db.delete_group(group_id)
            if hasattr(self, 'on_group_deleted') and self.on_group_deleted:
                self.on_group_deleted(group_id)

        # --- Enquete criada ---
        elif msg_type == MT_POLL_CREATE:
            group_id = msg.get('group_id')
            poll_id = msg.get('poll_id')
            question = msg.get('question', '')
            options = msg.get('options', [])
            self.db.save_poll(poll_id, group_id, from_user, question, options)
            if self.on_poll:
                self.on_poll(group_id, {
                    'action': 'create', 'poll_id': poll_id,
                    'question': question, 'options': options,
                    'creator': msg.get('display_name', from_user)
                })

        # --- Voto em enquete ---
        elif msg_type == MT_POLL_VOTE:
            poll_id = msg.get('poll_id')
            group_id = msg.get('group_id')
            option_index = msg.get('option_index', 0)
            self.db.save_poll_vote(poll_id, from_user, option_index)
            if self.on_poll:
                self.on_poll(group_id, {
                    'action': 'vote', 'poll_id': poll_id,
                    'voter': msg.get('display_name', from_user),
                    'option_index': option_index
                })

        # --- Convite de lembrete compartilhado ---
        elif msg_type == MT_REMINDER_INVITE:
            external_id = msg.get('external_id', '')
            if not external_id:
                return
            # Idempotencia: se ja recebi este invite antes, ignora
            existing = self.db.get_reminder_by_external_id(external_id)
            if existing:
                return
            text = msg.get('text', '')
            remind_at = float(msg.get('remind_at', 0))
            recurrence_rule = msg.get('recurrence_rule', '') or ''
            recurrence_int = int(msg.get('recurrence_interval_seconds', 0) or 0)
            creator_uid = msg.get('from_user', '')
            creator_name = msg.get('display_name', '') or msg.get('creator_name', '')
            invited_uids = msg.get('invited_uids', []) or []
            self.db.add_shared_reminder(
                text=text, remind_at=remind_at,
                creator_uid=creator_uid, creator_name=creator_name,
                external_id=external_id,
                invited_uids=invited_uids,
                recurrence_rule=recurrence_rule,
                recurrence_interval_seconds=recurrence_int,
                share_status='pending_accept')
            # Grava cartao "Lembrete recebido" no historico do chat com o criador
            try:
                card_text = self._format_reminder_card(
                    text, remind_at, recurrence_rule)
                msg_id = f'rem_{external_id}_in'
                self.db.save_message(msg_id, creator_uid, self.user_id,
                                     card_text, 'reminder_card',
                                     is_sent=False)
            except Exception:
                pass
            if self.on_reminder_invite:
                self.on_reminder_invite({
                    'external_id': external_id,
                    'text': text, 'remind_at': remind_at,
                    'creator_uid': creator_uid,
                    'creator_name': creator_name,
                })

        # --- Resposta de convite (aceitar/recusar) — chega no criador ---
        elif msg_type in (MT_REMINDER_ACCEPT, MT_REMINDER_DECLINE):
            external_id = msg.get('external_id', '')
            if not external_id:
                return
            responder_uid = msg.get('from_user', '')
            responder_name = msg.get('display_name', '')
            if msg_type == MT_REMINDER_ACCEPT:
                self.db.mark_reminder_accepted(external_id, responder_uid)
            if self.on_reminder_response:
                self.on_reminder_response({
                    'external_id': external_id,
                    'responder_uid': responder_uid,
                    'responder_name': responder_name,
                    'accepted': msg_type == MT_REMINDER_ACCEPT,
                })

        # --- Criador cancelou lembrete compartilhado ---
        elif msg_type == MT_REMINDER_CANCEL:
            ext_id = msg.get('external_id', '')
            if ext_id:
                rem = self.db.get_reminder_by_external_id(ext_id)
                if rem:
                    self.db.delete_reminder(rem['id'])
            if self.on_reminder_cancel:
                self.on_reminder_cancel(ext_id)

        # --- Participante concluiu lembrete compartilhado ---
        elif msg_type == MT_REMINDER_COMPLETED:
            ext_id = msg.get('external_id', '')
            if ext_id:
                self.db.update_reminder_completed_by(ext_id, msg.get('from_user', ''))
            if self.on_reminder_completed:
                self.on_reminder_completed({
                    'external_id': ext_id,
                    'from_user': msg.get('from_user', ''),
                    'display_name': msg.get('display_name', ''),
                    'reminder_text': msg.get('reminder_text', ''),
                })

        # --- Convite de reunião de sala ---
        elif msg_type == MT_MEETING_INVITE:
            self._handle_meeting_invite(msg)

        # --- Convidado aceitou reunião ---
        elif msg_type == MT_MEETING_ACCEPT:
            booking_id = msg.get('booking_id', '')
            responder_uid = msg.get('from_user', '')
            responder_name = msg.get('display_name', '')
            if booking_id and responder_uid:
                self.db.update_booking_participant_response(
                    booking_id, responder_uid, 'accepted')
                if self.db.get_booking_confirmed_count(booking_id) >= 2:
                    self.db.update_booking_status(booking_id, 'confirmed')
                if self.on_meeting_response:
                    self.on_meeting_response({
                        'booking_id': booking_id,
                        'responder_uid': responder_uid,
                        'responder_name': responder_name,
                        'accepted': True,
                    })

        # --- Convidado recusou reunião ---
        elif msg_type == MT_MEETING_DECLINE:
            booking_id = msg.get('booking_id', '')
            responder_uid = msg.get('from_user', '')
            responder_name = msg.get('display_name', '')
            if booking_id and responder_uid:
                self.db.update_booking_participant_response(
                    booking_id, responder_uid, 'declined')
                if self.on_meeting_response:
                    self.on_meeting_response({
                        'booking_id': booking_id,
                        'responder_uid': responder_uid,
                        'responder_name': responder_name,
                        'accepted': False,
                    })

        # --- Criador cancelou reunião ---
        elif msg_type == MT_MEETING_CANCEL:
            booking_id = msg.get('booking_id', '')
            if booking_id:
                self.db.soft_delete_booking(booking_id)
                # Remove lembrete associado à reunião
                try:
                    rem = self.db.get_reminder_by_external_id(booking_id)
                    if rem:
                        self.db.delete_reminder(rem['id'])
                except Exception:
                    pass
                if self.on_meeting_cancel:
                    self.on_meeting_cancel({
                        'booking_id': booking_id,
                        'title': msg.get('title', ''),
                        'reason': msg.get('reason', 'creator'),
                        'cancelled_by': msg.get('display_name', ''),
                    })

        # --- Pedido de sync de reservas ---
        elif msg_type == MT_MEETING_SYNC_REQ:
            try:
                bookings = self.db.get_all_bookings_for_sync()
                participants = {}
                for b in bookings:
                    participants[b['booking_id']] = \
                        self.db.get_booking_participants(b['booking_id'])
                contact = self.db.get_contact(from_user)
                if contact:
                    TCPClient.send_message(contact['ip_address'], TCP_PORT, {
                        'type': MT_MEETING_SYNC_RES,
                        'from_user': self.user_id,
                        'bookings': bookings,
                        'participants': participants,
                    })
            except Exception:
                pass

        # --- Resposta de sync — Last Write Wins merge ---
        elif msg_type == MT_MEETING_SYNC_RES:
            try:
                for b in (msg.get('bookings') or []):
                    bid = b.get('booking_id')
                    if not bid:
                        continue
                    local = self.db.get_booking(bid)
                    if not local or float(b.get('updated_at', 0)) > float(local.get('updated_at', 0)):
                        self.db.save_booking(
                            bid, b['room_id'], b['title'],
                            b['creator_uid'], b['creator_name'],
                            b['start_ts'], b['end_ts'], b.get('status', 'pending'))
                        if b.get('is_deleted'):
                            self.db.soft_delete_booking(bid)
                parts = msg.get('participants') or {}
                for bid, plist in parts.items():
                    for p in plist:
                        self.db.save_booking_participant(
                            bid, p['uid'], p['display_name'], p['response'])
                if self.on_meeting_sync:
                    self.on_meeting_sync()
            except Exception:
                pass

    # ========================================
    # SEND — Acoes de envio
    # ========================================

    # Envia uma mensagem de texto para um peer
    # Salva no banco local e envia via TCP
    # to_user_id: user_id do destinatario
    # content: Texto da mensagem
    # Retorna True se enviou com sucesso, False se falhou
    def send_message(self, to_user_id, content, reply_to_id='', is_broadcast=False):
        contact = self.db.get_contact(to_user_id)
        if not contact:
            return False, None

        msg_id = self._next_msg_id()
        timestamp = time.time()

        self.db.save_message(msg_id, self.user_id, to_user_id,
                            content, 'text', is_sent=True,
                            timestamp=timestamp, reply_to_id=reply_to_id)

        payload = {
            'type': MT_MESSAGE,
            'from_user': self.user_id,
            'to_user': to_user_id,
            'display_name': self.display_name,
            'msg_id': msg_id,
            'content': content,
            'timestamp': timestamp
        }
        if reply_to_id:
            payload['reply_to'] = reply_to_id
        if is_broadcast:
            payload['is_broadcast'] = True
        ok = TCPClient.send_message(contact['ip_address'], TCP_PORT, payload)
        return ok, msg_id

    # Envia imagem (bytes JPEG) para um peer
    # image_bytes: bytes JPEG da imagem ja comprimida
    # Retorna (success, image_path) — image_path e o caminho salvo localmente
    def send_image(self, to_user_id, image_bytes):
        contact = self.db.get_contact(to_user_id)
        if not contact:
            return False, None

        msg_id = self._next_msg_id()
        timestamp = time.time()
        image_path = self._save_image_to_disk(image_bytes, msg_id)
        b64 = base64.b64encode(image_bytes).decode('ascii')

        self.db.save_message(msg_id, self.user_id, to_user_id,
                            image_path, 'image', is_sent=True,
                            timestamp=timestamp)

        ok = TCPClient.send_message(contact['ip_address'], TCP_PORT, {
            'type': MT_IMAGE,
            'from_user': self.user_id,
            'to_user': to_user_id,
            'display_name': self.display_name,
            'msg_id': msg_id,
            'image_data': b64,
            'timestamp': timestamp
        })
        return ok, image_path

    # Envia imagem para todos os membros de um grupo (mesh)
    def send_group_image(self, group_id, image_bytes):
        group = self._groups.get(group_id)
        if not group:
            return None
        msg_id = self._next_msg_id()
        timestamp = time.time()
        image_path = self._save_image_to_disk(image_bytes, msg_id)
        b64 = base64.b64encode(image_bytes).decode('ascii')

        # Persiste a imagem no historico local do grupo (content = caminho)
        try:
            self.db.save_group_message(
                group_id, msg_id, self.user_id, image_path,
                sender_name=self.display_name, msg_type='image',
                is_sent=True, timestamp=timestamp)
        except Exception:
            pass

        for member in group['members']:
            uid = member['uid']
            if uid == self.user_id:
                continue
            TCPClient.send_message(member['ip'], TCP_PORT, {
                'type': MT_IMAGE,
                'from_user': self.user_id,
                'display_name': self.display_name,
                'group_id': group_id,
                'group_name': group.get('name', 'Grupo'),
                'group_type': group.get('group_type', 'temp'),
                'msg_id': msg_id,
                'image_data': b64,
                'timestamp': timestamp,
            })
        return image_path

    # Salva bytes de imagem em disco (%APPDATA%/.mbchat/images/)
    def _save_image_to_disk(self, image_bytes, msg_id):
        base = os.environ.get('APPDATA', os.path.expanduser('~'))
        img_dir = os.path.join(base, '.mbchat', 'images')
        os.makedirs(img_dir, exist_ok=True)
        filename = f'{msg_id}.jpg'
        path = os.path.join(img_dir, filename)
        with open(path, 'wb') as f:
            f.write(image_bytes)
        return path

    # Envia indicador de digitacao para um peer
    def send_typing(self, to_user_id, is_typing=True):
        contact = self.db.get_contact(to_user_id)
        if not contact:
            return
        TCPClient.send_message(contact['ip_address'], TCP_PORT, {
            'type': MT_TYPING,
            'from_user': self.user_id,
            'is_typing': is_typing
        })

    # Altera status do usuario (online/away/busy) e propaga
    def change_status(self, status):
        self.status = status
        self.db.update_local_status(status)   # Salva no banco
        self.discovery.update_status(status)   # Propaga via UDP announce

    # Altera nome de exibicao e propaga
    def change_name(self, name):
        self.display_name = name
        self.db.set_local_user(self.user_id, name, self.status)  # Salva
        self.discovery.update_name(name)  # Propaga

    # Altera nota pessoal e propaga
    def change_note(self, note):
        self.note = note
        self.db.update_local_note(note)   # Salva no banco
        self.discovery.update_note(note)  # Propaga via announce

    # Altera ramal (4 digitos) e propaga para todos os peers
    def change_ramal(self, ramal):
        # Aceita vazio ou exatamente 4 digitos numericos
        ramal = (ramal or '').strip()
        if ramal and (not ramal.isdigit() or len(ramal) != 4):
            return False
        self.ramal = ramal
        self.db.update_local_ramal(ramal)
        self.discovery.update_ramal(ramal)
        return True

    # Altera avatar e propaga para todos os peers
    # index: Indice do avatar padrao
    # custom_path: Caminho da foto custom (vazio = avatar padrao)
    def change_avatar(self, index, custom_path=''):
        self.avatar_index = index
        self.db.set_setting('avatar_index', str(index))    # Salva indice
        self.db.set_setting('custom_avatar', custom_path)  # Salva caminho
        self.avatar_data = self._generate_avatar_thumbnail()  # Gera thumbnail
        self.discovery.update_avatar(index, self.avatar_data)  # Propaga

    # Gera thumbnail base64 JPEG do avatar custom para envio via rede
    # Reduz a imagem para 48x48 pixels com qualidade 70% (~1-2KB)
    # Esse thumbnail e incluido no pacote UDP announce
    # Retorna string vazia se nao ha avatar custom
    def _generate_avatar_thumbnail(self):
        custom = self.db.get_setting('custom_avatar', '')
        if not custom or not os.path.exists(custom):
            return ''  # Sem avatar custom
        try:
            import base64
            from PIL import Image
            from io import BytesIO
            img = Image.open(custom)
            img.thumbnail((48, 48), Image.LANCZOS)  # Reduz mantendo proporcao
            buf = BytesIO()
            img.convert('RGB').save(buf, format='JPEG', quality=70)
            return base64.b64encode(buf.getvalue()).decode('ascii')
        except Exception:
            return ''  # PIL nao disponivel ou erro na imagem

    # ========================================
    # FILE TRANSFER — Transferencia de arquivos
    # ========================================

    # Inicia envio de arquivo para um peer
    # 1. Registra transferencia no banco
    # 2. Envia pedido (MT_FILE_REQ) via TCP
    # 3. Cria FileSender que conecta na porta de arquivo
    # 4. Aguarda aceitacao e comeca a enviar
    # to_user_id: user_id do destinatario
    # filepath: Caminho completo do arquivo
    # Retorna file_id se sucesso, None se contato nao encontrado
    def send_file(self, to_user_id, filepath):
        contact = self.db.get_contact(to_user_id)
        if not contact:
            return None

        file_id = str(uuid.uuid4()).replace('-', '')  # ID unico sem hifens
        filename = os.path.basename(filepath)
        filesize = os.path.getsize(filepath)

        # Registra no banco de dados
        self.db.save_file_transfer(file_id, self.user_id, to_user_id,
                                   filename, filesize, filepath)

        # Envia pedido de transferencia via mensagem TCP
        TCPClient.send_message(contact['ip_address'], TCP_PORT, {
            'type': MT_FILE_REQ,
            'from_user': self.user_id,
            'display_name': self.display_name,
            'to_user': to_user_id,
            'file_id': file_id,
            'filename': filename,
            'filesize': filesize
        })

        # Cria sender que conecta na porta de arquivo (TCP_PORT + 1)
        sender = FileSender(
            filepath, contact['ip_address'], TCP_PORT, file_id,
            on_progress=self._on_file_progress_internal,
            on_complete=lambda fid: self._on_file_complete_internal(fid, filepath),
            on_error=self._on_file_error_internal
        )
        self._file_senders[file_id] = sender  # Rastreia sender ativo
        sender.start()  # Inicia thread de envio
        return file_id

    # Cancela envio de arquivo em andamento
    def cancel_file(self, file_id):
        if file_id in self._file_senders:
            self._file_senders[file_id].cancel()

    # Callback quando recebe pedido de arquivo via TCP
    def _on_file_request(self, msg, addr):
        if self.on_file_incoming:
            self.on_file_incoming(
                msg.get('file_id'),
                msg.get('from_user'),
                msg.get('display_name', 'Unknown'),
                msg.get('filename'),
                msg.get('filesize', 0)
            )

    # Callback interno do FileReceiver (nao usado, tratado via TCP)
    def _on_file_incoming_internal(self, file_id, filename, filesize, ip):
        pass

    # Callback de progresso — repassa para GUI
    def _on_file_progress_internal(self, file_id, transferred, total):
        if self.on_file_progress:
            self.on_file_progress(file_id, transferred, total)

    # Callback de conclusao — atualiza banco e notifica GUI
    def _on_file_complete_internal(self, file_id, filepath=''):
        self.db.update_file_transfer(file_id, status='completed', progress=100)
        if self.on_file_complete:
            self.on_file_complete(file_id, filepath)

    # Callback de erro — atualiza banco e notifica GUI
    def _on_file_error_internal(self, file_id, error):
        self.db.update_file_transfer(file_id, status='error')
        if self.on_file_error:
            self.on_file_error(file_id, error)

    # ========================================
    # GROUP CHAT — Grupos de conversa
    # ========================================

    # Cria grupo e envia convite para todos os membros
    # group_id: ID unico do grupo
    # group_name: Nome do grupo
    # member_ids: Lista de user_ids dos membros convidados
    # group_type: 'temp' (temporario) ou 'fixed' (fixo/persistente)
    def send_group_invite(self, group_id, group_name, member_ids,
                          group_type='temp'):
        # Monta lista de membros comecando pelo proprio usuario
        members_info = [{'uid': self.user_id, 'display_name': self.display_name,
                         'ip': get_local_ip()}]
        for uid in member_ids:
            contact = self.db.get_contact(uid)
            if contact:
                members_info.append({'uid': uid,
                                     'display_name': contact['display_name'],
                                     'ip': contact['ip_address']})

        # Salva grupo em memoria
        self._groups[group_id] = {'name': group_name, 'members': members_info,
                                   'group_type': group_type,
                                   'creator_uid': self.user_id,
                                   'admins': [self.user_id]}

        # Se fixo, persiste no banco de dados
        if group_type == 'fixed':
            self.db.save_group(group_id, group_name, 'fixed',
                               creator_uid=self.user_id)
            for m in members_info:
                is_admin = 1 if m['uid'] == self.user_id else 0
                self.db.save_group_member(group_id, m['uid'],
                                          m['display_name'], m.get('ip', ''), is_admin=is_admin)

        # Envia convite TCP para cada membro convidado
        for uid in member_ids:
            contact = self.db.get_contact(uid)
            if contact:
                pkt = {
                    'type': MT_GROUP_INV,
                    'from_user': self.user_id,
                    'display_name': self.display_name,
                    'group_id': group_id,
                    'group_name': group_name,
                    'group_type': group_type,
                    'creator_uid': self.user_id,
                    'admins': [self.user_id],
                    'members': members_info,  # Lista completa de membros
                }
                threading.Thread(target=TCPClient.send_message,
                                 args=(contact['ip_address'], TCP_PORT, pkt),
                                 daemon=True).start()

    def set_group_admin(self, group_id, target_uid, is_admin):
        group = self._groups.get(group_id)
        if not group:
            return
        admins = group.get('admins', [])
        if is_admin and target_uid not in admins:
            admins.append(target_uid)
        elif not is_admin and target_uid in admins:
            admins.remove(target_uid)
        group['admins'] = admins
        
        if group.get('group_type') == 'fixed':
            # Atualizar no banco
            members = group.get('members', [])
            for m in members:
                if m['uid'] == target_uid:
                    self.db.save_group_member(group_id, target_uid, m['display_name'], m.get('ip', ''), is_admin=1 if is_admin else 0)
                    break
                    
        # Propaga para todos os membros
        pkt = {
            'type': MT_GROUP_ADMIN_SET,
            'from_user': self.user_id,
            'group_id': group_id,
            'target_uid': target_uid,
            'is_admin': is_admin,
        }
        for member in group['members']:
            if member['uid'] == self.user_id:
                continue
            contact = self.db.get_contact(member['uid'])
            ip = contact['ip_address'] if contact else member.get('ip', '')
            if ip:
                threading.Thread(target=TCPClient.send_message,
                                 args=(ip, TCP_PORT, pkt),
                                 daemon=True).start()

    def delete_group_globally(self, group_id):
        group = self._groups.get(group_id)
        if not group:
            return
        # Salva membros para notificar antes de apagar
        members = group.get('members', [])
        
        # Apaga localmente
        if group_id in self._groups:
            del self._groups[group_id]
        self.db.delete_group(group_id)
        
        # Propaga
        pkt = {
            'type': MT_GROUP_DELETE,
            'from_user': self.user_id,
            'group_id': group_id,
        }
        for member in members:
            if member['uid'] == self.user_id:
                continue
            contact = self.db.get_contact(member['uid'])
            ip = contact['ip_address'] if contact else member.get('ip', '')
            if ip:
                threading.Thread(target=TCPClient.send_message,
                                 args=(ip, TCP_PORT, pkt),
                                 daemon=True).start()

    # Remove participante do grupo (apenas criador pode chamar).
    # Envia MT_GROUP_KICK para todos os membros e atualiza estado local.
    def kick_group_member(self, group_id, target_uid):
        group = self._groups.get(group_id)
        if not group:
            return
        # Localiza o membro antes de remover da lista (precisamos do IP)
        target_member = next((m for m in group['members'] if m['uid'] == target_uid), None)
        pkt = {
            'type': MT_GROUP_KICK,
            'from_user': self.user_id,
            'group_id': group_id,
            'target_uid': target_uid,
        }
        # Envia para o KICKADO primeiro (antes de remover da lista)
        if target_member:
            contact = self.db.get_contact(target_uid)
            ip = contact['ip_address'] if contact else target_member.get('ip', '')
            if ip:
                try:
                    TCPClient.send_message(ip, TCP_PORT, pkt)
                except Exception:
                    pass
        # Remove localmente
        group['members'] = [m for m in group['members'] if m['uid'] != target_uid]
        if group.get('group_type') == 'fixed':
            self.db.delete_group_member(group_id, target_uid)
        # Broadcast para membros restantes
        for member in group['members']:
            if member['uid'] == self.user_id:
                continue
            contact = self.db.get_contact(member['uid'])
            ip = contact['ip_address'] if contact else member.get('ip', '')
            if ip:
                try:
                    TCPClient.send_message(ip, TCP_PORT, pkt)
                except Exception:
                    pass

    # Notifica membros existentes que alguem entrou no grupo
    # Envia MT_GROUP_JOIN para todos os membros (exceto nos mesmos)
    def notify_group_join(self, group_id, new_uid, new_display_name):
        group = self._groups.get(group_id)
        if not group:
            return
        for member in group['members']:
            if member['uid'] == self.user_id:
                continue  # Nao envia para si mesmo
            TCPClient.send_message(member['ip'], TCP_PORT, {
                'type': MT_GROUP_JOIN,
                'from_user': new_uid,
                'display_name': new_display_name,
                'group_id': group_id,
                'ip': get_local_ip() if new_uid == self.user_id else '',
            })

    # Envia arquivo para todos os membros do grupo (individualmente)
    # Como nao ha servidor central, cada membro recebe uma copia
    # direta via ponto-a-ponto
    # Retorna lista de file_ids criados
    def send_file_to_group(self, group_id, filepath):
        group = self._groups.get(group_id)
        if not group:
            return []
        file_ids = []
        for member in group['members']:
            uid = member['uid']
            if uid == self.user_id:
                continue  # Nao envia para si mesmo
            fid = self.send_file(uid, filepath)
            if fid:
                file_ids.append(fid)
        return file_ids

    # Envia mensagem de texto para todos os membros do grupo
    # Usa mesh: cada membro envia diretamente para todos os outros
    # Nao ha servidor central intermediando
    def send_group_message(self, group_id, content, reply_to_id='',
                           mentions=None):
        group = self._groups.get(group_id)
        if not group:
            return
        timestamp = time.time()
        msg_id = self._next_msg_id()

        # Persiste a mensagem enviada no historico local do grupo
        try:
            self.db.save_group_message(
                group_id, msg_id, self.user_id, content,
                sender_name=self.display_name, msg_type='text',
                is_sent=True, timestamp=timestamp,
                reply_to_id=reply_to_id)
        except Exception:
            pass

        # Inclui group_name e group_type no payload — assim o receptor que
        # nao recebeu o MT_GROUP_INV (peer offline na criacao) consegue
        # reconstruir o grupo localmente e ver a conversa imediatamente.
        for member in group['members']:
            uid = member['uid']
            if uid == self.user_id:
                continue
            payload = {
                'type': MT_GROUP_MSG,
                'from_user': self.user_id,
                'display_name': self.display_name,
                'group_id': group_id,
                'group_name': group.get('name', 'Grupo'),
                'group_type': group.get('group_type', 'temp'),
                'msg_id': msg_id,
                'content': content,
                'timestamp': timestamp,
            }
            if reply_to_id:
                payload['reply_to'] = reply_to_id
            if mentions:
                payload['mentions'] = mentions
            TCPClient.send_message(member['ip'], TCP_PORT, payload)

    # Cria enquete em grupo e envia para todos os membros
    def create_poll(self, group_id, question, options):
        group = self._groups.get(group_id)
        if not group:
            return None
        poll_id = self._next_msg_id()
        self.db.save_poll(poll_id, group_id, self.user_id, question, options)
        for member in group['members']:
            if member['uid'] == self.user_id:
                continue
            TCPClient.send_message(member['ip'], TCP_PORT, {
                'type': MT_POLL_CREATE,
                'from_user': self.user_id,
                'display_name': self.display_name,
                'group_id': group_id,
                'poll_id': poll_id,
                'question': question,
                'options': options,
            })
        return poll_id

    # Vota numa enquete e propaga para membros do grupo
    def vote_poll(self, group_id, poll_id, option_index):
        self.db.save_poll_vote(poll_id, self.user_id, option_index)
        group = self._groups.get(group_id)
        if not group:
            return
        for member in group['members']:
            if member['uid'] == self.user_id:
                continue
            TCPClient.send_message(member['ip'], TCP_PORT, {
                'type': MT_POLL_VOTE,
                'from_user': self.user_id,
                'display_name': self.display_name,
                'group_id': group_id,
                'poll_id': poll_id,
                'option_index': option_index,
            })

    # Carrega grupos fixos do banco para memoria
    # Chamado no startup para restaurar grupos persistidos
    # Temporarios nao sao salvos no banco, existem so em memoria
    # Retorna lista de dicts dos grupos carregados
    def load_saved_groups(self):
        groups = self.db.get_groups('fixed')  # Busca apenas fixos
        for g in groups:
            gid = g['group_id']
            members = self.db.get_group_members(gid)
            creator_uid = g.get('creator_uid', '')
            admins = [m['uid'] for m in members if m.get('is_admin')]
            self._groups[gid] = {
                'name': g['name'],
                'group_type': 'fixed',
                'creator_uid': creator_uid,
                'admins': admins,
                'members': [{'uid': m['uid'], 'display_name': m['display_name'],
                             'ip': m['ip']} for m in members]
            }
        return groups

    # Sai de um grupo: notifica membros e remove dados
    # 1. Envia MT_GROUP_LEAVE para todos os membros
    # 2. Remove grupo da memoria
    # 3. Remove grupo do banco (se fixo)
    def leave_group(self, group_id):
        group = self._groups.get(group_id)
        if group:
            # Notifica todos os membros antes de sair
            for member in group['members']:
                if member['uid'] == self.user_id:
                    continue
                TCPClient.send_message(member['ip'], TCP_PORT, {
                    'type': MT_GROUP_LEAVE,
                    'from_user': self.user_id,
                    'display_name': self.display_name,
                    'group_id': group_id,
                })
            del self._groups[group_id]  # Remove da memoria
        self.db.delete_group(group_id)  # Remove do banco (CASCADE nos membros)

    # ========================================
    # HISTORY — Acesso ao historico
    # ========================================

    # Retorna historico de conversa com um peer
    def get_chat_history(self, peer_id, limit=None):
        return self.db.get_chat_history(self.user_id, peer_id, limit)

    # Retorna historico completo de um grupo (texto + imagens), ordem ASC
    def get_group_history(self, group_id, limit=None):
        return self.db.get_group_history(group_id, limit)

    # Retorna lista de contatos do banco
    def get_contacts(self, online_only=False):
        return self.db.get_contacts(online_only)

    # Busca mensagens por texto
    def search_messages(self, query):
        return self.db.search_messages(query)

    # Retorna contagem de mensagens nao lidas de um peer
    def get_unread_count(self, from_user_id):
        return self.db.get_unread_count(self.user_id, from_user_id)

    # Retorna mensagens nao lidas de um peer
    def get_unread_messages(self, from_user_id):
        return self.db.get_unread_messages(self.user_id, from_user_id)

    # Marca todas as mensagens de um peer como lidas
    def mark_as_read(self, from_user_id):
        self.db.mark_as_read(self.user_id, from_user_id)

    # ========================================
    # MANUAL PEERS / VPN — Acesso para a GUI
    # ========================================
    # Cenario: usuario fora da LAN (home-office com VPN). Multicast/broadcast nao
    # cruzam VPN, entao discovery normal falha. Solucao: cadastrar manualmente o
    # IP de UM peer "ancora" do escritorio. Daquele peer, peer-exchange propaga
    # a LAN inteira automaticamente. Lista vazia = caminho da LAN intocado.

    def add_manual_peer(self, ip, note=''):
        ok = self.db.add_manual_peer(ip, note)
        if ok:
            self._reload_manual_peers()
        return ok

    def remove_manual_peer(self, ip):
        self.db.remove_manual_peer(ip)
        self._reload_manual_peers()

    def get_manual_peers(self):
        return self.db.get_manual_peers()

    # Toggle on/off persistente. Default OFF — a lista fica salva mas so aplica
    # em discovery.set_manual_peers quando ativado. Assim o usuario cadastra
    # uma vez e liga/desliga conforme esta no escritorio ou em VPN.
    def is_vpn_enabled(self):
        val = self.db.get_setting('vpn_enabled', '0')
        return str(val) in ('1', 'true', 'True')

    def set_vpn_enabled(self, enabled):
        self.db.set_setting('vpn_enabled', '1' if enabled else '0')
        self._reload_manual_peers()

    # ========================================
    # SHARED REMINDERS — Convite, accept, decline
    # ========================================

    # Cria lembrete compartilhado localmente (status='active' para o criador)
    # e envia MT_REMINDER_INVITE pra cada uid em invited_uids.
    # Retorna external_id (uuid) gerado.
    def create_shared_reminder(self, text, remind_at, invited_uids,
                                recurrence_rule='',
                                recurrence_interval_seconds=0):
        external_id = self.db.add_shared_reminder(
            text=text, remind_at=remind_at,
            creator_uid=self.user_id,
            creator_name=self.display_name,
            invited_uids=invited_uids,
            recurrence_rule=recurrence_rule,
            recurrence_interval_seconds=recurrence_interval_seconds,
            share_status='active')
        # Envia convite para cada peer + grava cartao no historico do chat
        card_text = self._format_reminder_card(text, remind_at, recurrence_rule)
        for uid in (invited_uids or []):
            if uid == self.user_id:
                continue
            contact = self.db.get_contact(uid)
            if not contact:
                continue
            payload = {
                'type': MT_REMINDER_INVITE,
                'from_user': self.user_id,
                'display_name': self.display_name,
                'creator_name': self.display_name,
                'external_id': external_id,
                'text': text,
                'remind_at': remind_at,
                'recurrence_rule': recurrence_rule or '',
                'recurrence_interval_seconds': recurrence_interval_seconds or 0,
                'invited_uids': invited_uids,
            }
            try:
                TCPClient.send_message(contact['ip_address'], TCP_PORT, payload)
            except Exception:
                pass
            # Grava cartao "Lembrete enviado" no historico (lado criador)
            try:
                msg_id = f'rem_{external_id}_{uid}'
                self.db.save_message(msg_id, self.user_id, uid,
                                     card_text, 'reminder_card',
                                     is_sent=True)
            except Exception:
                pass
        return external_id

    # Formata um cartao de lembrete para exibir no historico do chat.
    def _format_reminder_card(self, text, remind_at, recurrence_rule=''):
        from datetime import datetime as _dt
        if remind_at and remind_at > 0:
            try:
                dt = _dt.fromtimestamp(float(remind_at))
                when = dt.strftime('%d/%m/%Y %H:%M')
            except Exception:
                when = ''
        else:
            when = 'sem data'
        suffix = ''
        if recurrence_rule:
            suffix = ' (recorrente)'
        return f'📌 Lembrete compartilhado: "{text}" — {when}{suffix}'

    # Aceita um convite recebido. Atualiza status localmente para 'active'
    # (lembrete passa a disparar) + notifica o criador.
    def accept_reminder_invite(self, external_id):
        rem = self.db.get_reminder_by_external_id(external_id)
        if not rem:
            return False
        self.db.update_reminder_share_status(external_id, 'active')
        creator_uid = rem.get('creator_uid', '')
        if creator_uid:
            contact = self.db.get_contact(creator_uid)
            if contact:
                try:
                    TCPClient.send_message(contact['ip_address'], TCP_PORT, {
                        'type': MT_REMINDER_ACCEPT,
                        'from_user': self.user_id,
                        'display_name': self.display_name,
                        'external_id': external_id,
                    })
                except Exception:
                    pass
        return True

    def decline_reminder_invite(self, external_id):
        rem = self.db.get_reminder_by_external_id(external_id)
        if not rem:
            return False
        self.db.update_reminder_share_status(external_id, 'declined')
        creator_uid = rem.get('creator_uid', '')
        if creator_uid:
            contact = self.db.get_contact(creator_uid)
            if contact:
                try:
                    TCPClient.send_message(contact['ip_address'], TCP_PORT, {
                        'type': MT_REMINDER_DECLINE,
                        'from_user': self.user_id,
                        'display_name': self.display_name,
                        'external_id': external_id,
                    })
                except Exception:
                    pass
        return True

    def cancel_shared_reminder(self, external_id):
        rem = self.db.get_reminder_by_external_id(external_id)
        if not rem or rem.get('creator_uid') != self.user_id:
            return
        try:
            invited = json.loads(rem.get('invited_uids', '[]'))
        except Exception:
            invited = []
        payload = {
            'type': MT_REMINDER_CANCEL,
            'from_user': self.user_id,
            'display_name': self.display_name,
            'external_id': external_id,
        }
        for uid in invited:
            contact = self.db.get_contact(uid)
            if contact:
                try:
                    TCPClient.send_message(contact['ip_address'], TCP_PORT, payload)
                except Exception:
                    pass
        self.db.delete_reminder(rem['id'])

    def mark_reminder_completed_shared(self, reminder_id):
        # Marca como concluído localmente e notifica o criador (se for lembrete compartilhado)
        rem = self.db.conn.execute(
            "SELECT * FROM reminders WHERE id=?", (reminder_id,)).fetchone()
        if not rem:
            return
        rem = dict(rem)
        self.db.mark_reminder_completed(reminder_id)
        ext_id = rem.get('external_id', '')
        creator_uid = rem.get('creator_uid', '')
        if not ext_id or not creator_uid or creator_uid == self.user_id:
            return
        creator_contact = self.db.get_contact(creator_uid)
        if creator_contact:
            try:
                TCPClient.send_message(creator_contact['ip_address'], TCP_PORT, {
                    'type': MT_REMINDER_COMPLETED,
                    'from_user': self.user_id,
                    'display_name': self.display_name,
                    'external_id': ext_id,
                    'reminder_text': rem.get('text', ''),
                })
            except Exception:
                pass

    def _reload_manual_peers(self):
        # Se VPN desligada, envia lista vazia para o discovery (zero overhead,
        # os IPs ficam salvos no DB mas nao sao anunciados).
        if not self.is_vpn_enabled():
            try:
                self.discovery.set_manual_peers([])
            except Exception:
                pass
            return
        peers = self.db.get_manual_peers()
        ips = [p['ip'] for p in peers]
        try:
            self.discovery.set_manual_peers(ips)
        except Exception:
            pass

    # ========================================
    # MEETING ROOMS — Reserva de Salas
    # ========================================

    def _handle_meeting_invite(self, msg):
        booking_id = msg.get('booking_id', '')
        if not booking_id:
            return
        # Idempotente: se já recebi este convite, ignora
        if self.db.get_booking(booking_id):
            return
        self.db.save_booking(
            booking_id, msg['room_id'], msg['title'],
            msg['creator_uid'], msg['creator_name'],
            msg['start_ts'], msg['end_ts'], 'pending')
        for p in (msg.get('participants') or []):
            self.db.save_booking_participant(
                booking_id, p['uid'], p['display_name'], p['response'])
        if self.on_meeting_invite:
            self.on_meeting_invite(msg)

    def create_meeting(self, room_id, title, start_ts, end_ts, participant_uids):
        import json as _json
        if self.db.has_booking_conflict(room_id, start_ts, end_ts):
            return {'error': 'conflict'}
        booking_id = str(uuid.uuid4())
        self.db.save_booking(booking_id, room_id, title,
                             self.user_id, self.display_name,
                             start_ts, end_ts, 'pending')
        self.db.save_booking_participant(
            booking_id, self.user_id, self.display_name, 'accepted')
        participants = [{'uid': self.user_id,
                         'display_name': self.display_name,
                         'response': 'accepted'}]
        for uid in (participant_uids or []):
            contact = self.db.get_contact(uid)
            if not contact:
                continue
            name = contact['display_name']
            self.db.save_booking_participant(booking_id, uid, name, 'pending')
            participants.append({'uid': uid, 'display_name': name,
                                 'response': 'pending'})
        room_map = {r['id']: r['name'] for r in self.db.get_rooms()}
        payload = {
            'type': MT_MEETING_INVITE,
            'from_user': self.user_id,
            'display_name': self.display_name,
            'booking_id': booking_id,
            'room_id': room_id,
            'room_name': room_map.get(room_id, 'Sala'),
            'title': title,
            'creator_uid': self.user_id,
            'creator_name': self.display_name,
            'start_ts': start_ts,
            'end_ts': end_ts,
            'participants': participants,
        }
        sent_any = False
        for uid in (participant_uids or []):
            contact = self.db.get_contact(uid)
            if contact:
                try:
                    TCPClient.send_message(contact['ip_address'], TCP_PORT, payload)
                    sent_any = True
                except Exception:
                    pass
        if not sent_any and participant_uids:
            self.db.update_booking_status(booking_id, 'local_only')
        return {'booking_id': booking_id}

    def accept_meeting(self, booking_id):
        import json as _json
        self.db.update_booking_participant_response(
            booking_id, self.user_id, 'accepted')
        booking = self.db.get_booking(booking_id)
        if not booking:
            return
        if self.db.get_booking_confirmed_count(booking_id) >= 2:
            self.db.update_booking_status(booking_id, 'confirmed')
        # Notifica o criador
        creator_uid = booking.get('creator_uid', '')
        if creator_uid and creator_uid != self.user_id:
            contact = self.db.get_contact(creator_uid)
            if contact:
                try:
                    TCPClient.send_message(contact['ip_address'], TCP_PORT, {
                        'type': MT_MEETING_ACCEPT,
                        'from_user': self.user_id,
                        'display_name': self.display_name,
                        'booking_id': booking_id,
                    })
                except Exception:
                    pass
        # Cria lembrete 15min antes
        try:
            rooms = {r['id']: r['name'] for r in self.db.get_rooms()}
            room_name = rooms.get(booking.get('room_id'), 'Sala')
            parts = self.db.get_booking_participants(booking_id)
            remind_text = _json.dumps({
                'type': 'meeting',
                'title': booking['title'],
                'room_name': room_name,
                'start_ts': booking['start_ts'],
                'end_ts': booking['end_ts'],
                'participants': [p['display_name'] for p in parts],
                'creator': booking['creator_name'],
            }, ensure_ascii=False)
            self.db.add_shared_reminder(
                text=remind_text,
                remind_at=booking['start_ts'] - 900,
                creator_uid=self.user_id,
                external_id=booking_id,
                share_status='active')
        except Exception:
            pass

    def decline_meeting(self, booking_id):
        self.db.update_booking_participant_response(
            booking_id, self.user_id, 'declined')
        booking = self.db.get_booking(booking_id)
        if not booking:
            return
        creator_uid = booking.get('creator_uid', '')
        if creator_uid and creator_uid != self.user_id:
            contact = self.db.get_contact(creator_uid)
            if contact:
                try:
                    TCPClient.send_message(contact['ip_address'], TCP_PORT, {
                        'type': MT_MEETING_DECLINE,
                        'from_user': self.user_id,
                        'display_name': self.display_name,
                        'booking_id': booking_id,
                    })
                except Exception:
                    pass

    def cancel_meeting(self, booking_id, reason='creator'):
        booking = self.db.get_booking(booking_id)
        if not booking or booking.get('creator_uid') != self.user_id:
            return
        title = booking.get('title', '')
        self.db.soft_delete_booking(booking_id)
        # Remove lembrete associado
        try:
            rem = self.db.get_reminder_by_external_id(booking_id)
            if rem:
                self.db.delete_reminder(rem['id'])
        except Exception:
            pass
        parts = self.db.get_booking_participants(booking_id)
        for p in parts:
            if p['uid'] == self.user_id:
                continue
            contact = self.db.get_contact(p['uid'])
            if contact:
                try:
                    TCPClient.send_message(contact['ip_address'], TCP_PORT, {
                        'type': MT_MEETING_CANCEL,
                        'from_user': self.user_id,
                        'display_name': self.display_name,
                        'booking_id': booking_id,
                        'title': title,
                        'reason': reason,
                    })
                except Exception:
                    pass

    def edit_meeting(self, booking_id, title, room_id, start_ts, end_ts):
        if self.db.has_booking_conflict(room_id, start_ts, end_ts,
                                        exclude_booking_id=booking_id):
            return {'error': 'conflict'}
        self.db.update_booking_fields(booking_id, title, room_id, start_ts, end_ts)
        booking = self.db.get_booking(booking_id)
        if not booking:
            return {}
        parts = self.db.get_booking_participants(booking_id)
        room_map = {r['id']: r['name'] for r in self.db.get_rooms()}
        payload = {
            'type': MT_MEETING_SYNC_RES,
            'from_user': self.user_id,
            'bookings': [dict(booking)],
        }
        for p in parts:
            if p['uid'] == self.user_id:
                continue
            contact = self.db.get_contact(p['uid'])
            if contact:
                try:
                    TCPClient.send_message(contact['ip_address'], TCP_PORT, payload)
                except Exception:
                    pass
        return {}

    def remove_participant(self, booking_id, uid):
        self.db.remove_booking_participant(booking_id, uid)
        contact = self.db.get_contact(uid)
        if contact:
            try:
                TCPClient.send_message(contact['ip_address'], TCP_PORT, {
                    'type': MT_MEETING_CANCEL,
                    'from_user': self.user_id,
                    'display_name': self.display_name,
                    'booking_id': booking_id,
                })
            except Exception:
                pass

    def add_participants(self, booking_id, uids):
        booking = self.db.get_booking(booking_id)
        if not booking:
            return
        parts = self.db.get_booking_participants(booking_id)
        participants = [{'uid': p['uid'], 'display_name': p['display_name'],
                         'response': p['response']} for p in parts]
        room_map = {r['id']: r['name'] for r in self.db.get_rooms()}
        for uid in (uids or []):
            contact = self.db.get_contact(uid)
            if not contact:
                continue
            name = contact['display_name']
            self.db.save_booking_participant(booking_id, uid, name, 'pending')
            participants.append({'uid': uid, 'display_name': name, 'response': 'pending'})
            try:
                TCPClient.send_message(contact['ip_address'], TCP_PORT, {
                    'type': MT_MEETING_INVITE,
                    'from_user': self.user_id,
                    'display_name': self.display_name,
                    'booking_id': booking_id,
                    'room_id': booking['room_id'],
                    'room_name': room_map.get(booking['room_id'], 'Sala'),
                    'title': booking['title'],
                    'creator_uid': booking['creator_uid'],
                    'creator_name': booking['creator_name'],
                    'start_ts': booking['start_ts'],
                    'end_ts': booking['end_ts'],
                    'participants': participants,
                })
            except Exception:
                pass

    def sync_meetings_with_peer(self, peer_ip):
        try:
            TCPClient.send_message(peer_ip, TCP_PORT, {
                'type': MT_MEETING_SYNC_REQ,
                'from_user': self.user_id,
            })
        except Exception:
            pass

    def _start_meeting_auto_cancel_loop(self):
        CANCEL_TOLERANCE = 120  # 2 min de tolerância
        def _loop():
            while True:
                try:
                    now = time.time()
                    bookings = self.db.get_bookings(date_from=0, date_to=now)
                    for b in bookings:
                        if (b.get('status') == 'pending' and
                                b['start_ts'] + CANCEL_TOLERANCE <= now):
                            if self.db.get_booking_confirmed_count(b['booking_id']) < 2:
                                self.cancel_meeting(b['booking_id'], reason='auto')
                except Exception:
                    pass
                time.sleep(60)
        threading.Thread(target=_loop, daemon=True).start()
