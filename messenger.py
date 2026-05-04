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
    MT_GROUP_INV, MT_GROUP_MSG, MT_GROUP_LEAVE, MT_GROUP_JOIN,
    MT_IMAGE, MT_POLL_CREATE, MT_POLL_VOTE,
    MT_REMINDER_INVITE, MT_REMINDER_ACCEPT, MT_REMINDER_DECLINE,
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
                 on_reminder_invite=None, on_reminder_response=None):
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
        self.on_reminder_invite = on_reminder_invite      # Convite lembrete recebido
        self.on_reminder_response = on_reminder_response  # Resposta de convite (accept/decline)

        # === Grupos em memoria ===
        # Formato: group_id -> {name, group_type, members: [{uid, display_name, ip}]}
        self._groups = {}

        # === Setup do usuario local ===
        self.user_id = generate_user_id()  # ID = MAC+hostname+winuser
        # Migracao: usuarios pre-1.4.60 tem user_id no formato mac_host
        # (sem winuser). Renomeia tudo para o formato novo para que historico,
        # contatos e grupos continuem funcionando pos-update.
        # Idempotente: se ja esta no formato novo, no-op.
        try:
            self.db.migrate_user_ids_add_winuser_suffix(self.user_id)
        except Exception:
            pass
        local = self.db.get_local_user()   # Tenta carregar do banco

        # Prioridade do nome: argumento > banco > login do OS
        if display_name:
            self.display_name = display_name
        elif local:
            self.display_name = local['display_name']
        else:
            self.display_name = os.getlogin() if hasattr(os, 'getlogin') else 'User'

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
                                                     'LanMessenger_Files'))
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
        if self.on_user_found:
            self.on_user_found(uid, info)  # Notifica GUI

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
                display_name = msg.get('display_name', from_user)
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

            # Salva grupo em memoria
            self._groups[group_id] = {'name': group_name, 'members': members,
                                       'group_type': group_type}

            # Se fixo, persiste no banco
            if group_type == 'fixed':
                self.db.save_group(group_id, group_name, 'fixed')
                for m in members:
                    self.db.save_group_member(group_id, m['uid'],
                                              m['display_name'],
                                              m.get('ip', ''))

            # Notifica GUI para abrir janela do grupo
            if self.on_group_invite:
                self.on_group_invite(group_id, group_name, from_user,
                                     members, group_type)

        # --- Mensagem de grupo ---
        elif msg_type == MT_GROUP_MSG:
            group_id = msg.get('group_id')
            content = msg.get('content', '')
            timestamp = msg.get('timestamp', time.time())
            display_name = msg.get('display_name', from_user)
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
                    self._groups[group_id] = {
                        'name': db_g['name'],
                        'group_type': db_g['group_type'],
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
                                   'group_type': group_type}

        # Se fixo, persiste no banco de dados
        if group_type == 'fixed':
            self.db.save_group(group_id, group_name, 'fixed')
            for m in members_info:
                self.db.save_group_member(group_id, m['uid'],
                                          m['display_name'], m.get('ip', ''))

        # Envia convite TCP para cada membro convidado
        for uid in member_ids:
            contact = self.db.get_contact(uid)
            if contact:
                TCPClient.send_message(contact['ip_address'], TCP_PORT, {
                    'type': MT_GROUP_INV,
                    'from_user': self.user_id,
                    'display_name': self.display_name,
                    'group_id': group_id,
                    'group_name': group_name,
                    'group_type': group_type,
                    'members': members_info,  # Lista completa de membros
                })

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
            self._groups[gid] = {
                'name': g['name'],
                'group_type': 'fixed',
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
