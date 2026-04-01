"""
LAN Messenger - Camada de mensagens (controller)
Liga network <-> database <-> GUI
"""
import time
import uuid
import os
import threading
from network import (
    UDPDiscovery, TCPServer, TCPClient, FileSender, FileReceiver,
    generate_user_id, get_local_ip, get_machine_info,
    MT_ANNOUNCE, MT_DEPART, MT_MESSAGE, MT_FILE_REQ, MT_FILE_ACC,
    MT_FILE_DEC, MT_FILE_CANCEL, MT_STATUS, MT_TYPING, MT_ACK,
    MT_GROUP_INV, MT_GROUP_MSG, MT_GROUP_LEAVE, MT_GROUP_JOIN, TCP_PORT
)
from database import Database


class Messenger:
    """Controller principal do LAN Messenger."""

    def __init__(self, display_name=None, on_user_found=None,
                 on_user_lost=None, on_message=None, on_status=None,
                 on_typing=None, on_file_incoming=None,
                 on_file_progress=None, on_file_complete=None,
                 on_file_error=None, on_group_invite=None,
                 on_group_message=None, on_group_leave=None,
                 on_group_join=None):
        self.db = Database()
        self._msg_counter = 0
        self._lock = threading.Lock()
        self._file_senders = {}
        self._file_receiver = None

        # Callbacks para GUI
        self.on_user_found = on_user_found
        self.on_user_lost = on_user_lost
        self.on_message = on_message
        self.on_status = on_status
        self.on_typing = on_typing
        self.on_file_incoming = on_file_incoming
        self.on_file_progress = on_file_progress
        self.on_file_complete = on_file_complete
        self.on_file_error = on_file_error
        self.on_group_invite = on_group_invite
        self.on_group_message = on_group_message
        self.on_group_leave = on_group_leave
        self.on_group_join = on_group_join
        self._groups = {}  # group_id -> {name, members: [{uid, display_name, ip}]}

        # Setup user
        self.user_id = generate_user_id()
        local = self.db.get_local_user()
        if display_name:
            self.display_name = display_name
        elif local:
            self.display_name = local['display_name']
        else:
            self.display_name = os.getlogin() if hasattr(os, 'getlogin') else 'User'

        self.status = 'online'
        self.note = self.db.get_local_note()
        self.avatar_index = int(self.db.get_setting('avatar_index', '0'))
        self.avatar_data = self._generate_avatar_thumbnail()
        self.db.set_local_user(self.user_id, self.display_name, self.status)

        # Mark all contacts offline on start
        self.db.set_all_contacts_offline()

        # Network components
        self.discovery = UDPDiscovery(
            self.user_id, self.display_name, self.status,
            on_peer_found=self._on_peer_found,
            on_peer_lost=self._on_peer_lost
        )
        self.discovery.note = self.note
        self.discovery.avatar_index = self.avatar_index
        self.discovery.avatar_data = self.avatar_data
        self.tcp_server = TCPServer(
            on_message=self._on_tcp_message,
            on_file_request=self._on_file_request
        )

        # File receiver
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

    def start(self):
        self.discovery.start()
        self.tcp_server.start()
        self._file_receiver.start()

    def stop(self):
        self.db.update_local_status('offline')
        self.db.set_all_contacts_offline()
        self.discovery.stop()
        self.tcp_server.stop()
        self._file_receiver.stop()
        self.db.close()

    def _next_msg_id(self):
        with self._lock:
            self._msg_counter += 1
            return f"{self.user_id}_{self._msg_counter}_{int(time.time()*1000)}"

    # --- Peer discovery callbacks ---
    def _on_peer_found(self, uid, info):
        self.db.upsert_contact(
            uid, info['display_name'], info['ip'],
            hostname=info.get('hostname', ''),
            os_info=info.get('os', ''),
            status=info.get('status', 'online'),
            note=info.get('note', ''),
            avatar_index=info.get('avatar_index', 0),
            avatar_data=info.get('avatar_data', '')
        )
        if self.on_user_found:
            self.on_user_found(uid, info)

    def _on_peer_lost(self, uid, info):
        self.db.set_contact_offline(uid)
        if self.on_user_lost:
            self.on_user_lost(uid, info)

    # --- TCP message callbacks ---
    def _on_tcp_message(self, msg, addr):
        msg_type = msg.get('type')
        from_user = msg.get('from_user')

        if msg_type == MT_MESSAGE:
            msg_id = msg.get('msg_id', str(uuid.uuid4()))
            content = msg.get('content', '')
            timestamp = msg.get('timestamp', time.time())

            self.db.save_message(msg_id, from_user, self.user_id,
                                content, 'text', is_sent=False,
                                timestamp=timestamp)

            # Send ACK
            contact = self.db.get_contact(from_user)
            if contact:
                TCPClient.send_message(contact['ip_address'], TCP_PORT, {
                    'type': MT_ACK,
                    'from_user': self.user_id,
                    'msg_id': msg_id
                })

            if self.on_message:
                self.on_message(from_user, content, msg_id, timestamp)

        elif msg_type == MT_TYPING:
            if self.on_typing:
                self.on_typing(from_user, msg.get('is_typing', False))

        elif msg_type == MT_STATUS:
            new_status = msg.get('status', 'online')
            self.db.upsert_contact(
                from_user, msg.get('display_name', ''),
                addr[0], status=new_status)
            if self.on_status:
                self.on_status(from_user, new_status)

        elif msg_type == MT_ACK:
            pass  # Could update delivery status

        elif msg_type == MT_GROUP_INV:
            group_id = msg.get('group_id')
            group_name = msg.get('group_name', 'Grupo')
            group_type = msg.get('group_type', 'temp')
            members = msg.get('members', [])
            self._groups[group_id] = {'name': group_name, 'members': members,
                                       'group_type': group_type}
            if group_type == 'fixed':
                self.db.save_group(group_id, group_name, 'fixed')
                for m in members:
                    self.db.save_group_member(group_id, m['uid'],
                                              m['display_name'],
                                              m.get('ip', ''))
            if self.on_group_invite:
                self.on_group_invite(group_id, group_name, from_user,
                                     members, group_type)

        elif msg_type == MT_GROUP_MSG:
            group_id = msg.get('group_id')
            content = msg.get('content', '')
            timestamp = msg.get('timestamp', time.time())
            display_name = msg.get('display_name', from_user)
            if self.on_group_message:
                self.on_group_message(group_id, from_user, display_name,
                                      content, timestamp)

        elif msg_type == MT_GROUP_LEAVE:
            group_id = msg.get('group_id')
            display_name = msg.get('display_name', from_user)
            # Remover membro da lista local
            group = self._groups.get(group_id)
            if group:
                group['members'] = [m for m in group['members']
                                    if m['uid'] != from_user]
                # Atualizar DB se fixo
                if group.get('group_type') == 'fixed':
                    self.db.delete_group_member(group_id, from_user)
            if self.on_group_leave:
                self.on_group_leave(group_id, from_user, display_name)

        elif msg_type == MT_GROUP_JOIN:
            group_id = msg.get('group_id')
            display_name = msg.get('display_name', from_user)
            new_ip = msg.get('ip', '')
            group = self._groups.get(group_id)
            if group:
                # Evitar duplicata
                if not any(m['uid'] == from_user for m in group['members']):
                    group['members'].append({
                        'uid': from_user,
                        'display_name': display_name,
                        'ip': new_ip
                    })
                if group.get('group_type') == 'fixed':
                    self.db.save_group_member(group_id, from_user,
                                              display_name, new_ip)
            if self.on_group_join:
                self.on_group_join(group_id, from_user, display_name)

    # --- Send actions ---
    def send_message(self, to_user_id, content):
        contact = self.db.get_contact(to_user_id)
        if not contact:
            return False

        msg_id = self._next_msg_id()
        timestamp = time.time()

        self.db.save_message(msg_id, self.user_id, to_user_id,
                            content, 'text', is_sent=True,
                            timestamp=timestamp)

        return TCPClient.send_message(contact['ip_address'], TCP_PORT, {
            'type': MT_MESSAGE,
            'from_user': self.user_id,
            'to_user': to_user_id,
            'display_name': self.display_name,
            'msg_id': msg_id,
            'content': content,
            'timestamp': timestamp
        })

    def send_typing(self, to_user_id, is_typing=True):
        contact = self.db.get_contact(to_user_id)
        if not contact:
            return
        TCPClient.send_message(contact['ip_address'], TCP_PORT, {
            'type': MT_TYPING,
            'from_user': self.user_id,
            'is_typing': is_typing
        })

    def change_status(self, status):
        self.status = status
        self.db.update_local_status(status)
        self.discovery.update_status(status)

    def change_name(self, name):
        self.display_name = name
        self.db.set_local_user(self.user_id, name, self.status)
        self.discovery.update_name(name)

    def change_note(self, note):
        self.note = note
        self.db.update_local_note(note)
        self.discovery.update_note(note)

    def change_avatar(self, index, custom_path=''):
        self.avatar_index = index
        self.db.set_setting('avatar_index', str(index))
        self.db.set_setting('custom_avatar', custom_path)
        self.avatar_data = self._generate_avatar_thumbnail()
        self.discovery.update_avatar(index, self.avatar_data)

    def _generate_avatar_thumbnail(self):
        """Gera thumbnail base64 JPEG do avatar custom para envio via rede."""
        custom = self.db.get_setting('custom_avatar', '')
        if not custom or not os.path.exists(custom):
            return ''
        try:
            import base64
            from PIL import Image
            from io import BytesIO
            img = Image.open(custom)
            img.thumbnail((48, 48), Image.LANCZOS)
            buf = BytesIO()
            img.convert('RGB').save(buf, format='JPEG', quality=70)
            return base64.b64encode(buf.getvalue()).decode('ascii')
        except Exception:
            return ''

    # --- File transfer ---
    def send_file(self, to_user_id, filepath):
        contact = self.db.get_contact(to_user_id)
        if not contact:
            return None

        file_id = str(uuid.uuid4()).replace('-', '')
        filename = os.path.basename(filepath)
        filesize = os.path.getsize(filepath)

        self.db.save_file_transfer(file_id, self.user_id, to_user_id,
                                   filename, filesize, filepath)

        # Send file request via TCP message
        TCPClient.send_message(contact['ip_address'], TCP_PORT, {
            'type': MT_FILE_REQ,
            'from_user': self.user_id,
            'display_name': self.display_name,
            'to_user': to_user_id,
            'file_id': file_id,
            'filename': filename,
            'filesize': filesize
        })

        # Create sender (will connect when accept received)
        sender = FileSender(
            filepath, contact['ip_address'], TCP_PORT, file_id,
            on_progress=self._on_file_progress_internal,
            on_complete=lambda fid: self._on_file_complete_internal(fid, filepath),
            on_error=self._on_file_error_internal
        )
        self._file_senders[file_id] = sender
        sender.start()
        return file_id

    def accept_file(self, file_id):
        self._file_receiver.accept_file(file_id)

    def decline_file(self, file_id):
        self._file_receiver.decline_file(file_id)

    def cancel_file(self, file_id):
        if file_id in self._file_senders:
            self._file_senders[file_id].cancel()

    def _on_file_request(self, msg, addr):
        if self.on_file_incoming:
            self.on_file_incoming(
                msg.get('file_id'),
                msg.get('from_user'),
                msg.get('display_name', 'Unknown'),
                msg.get('filename'),
                msg.get('filesize', 0)
            )

    def _on_file_incoming_internal(self, file_id, filename, filesize, ip):
        # Handled by _on_file_request via TCP message
        pass

    def _on_file_progress_internal(self, file_id, transferred, total):
        if self.on_file_progress:
            self.on_file_progress(file_id, transferred, total)

    def _on_file_complete_internal(self, file_id, filepath=''):
        self.db.update_file_transfer(file_id, status='completed', progress=100)
        if self.on_file_complete:
            self.on_file_complete(file_id, filepath)

    def _on_file_error_internal(self, file_id, error):
        self.db.update_file_transfer(file_id, status='error')
        if self.on_file_error:
            self.on_file_error(file_id, error)

    # --- Group chat ---
    def send_group_invite(self, group_id, group_name, member_ids,
                          group_type='temp'):
        """Cria grupo e convida membros."""
        members_info = [{'uid': self.user_id, 'display_name': self.display_name,
                         'ip': get_local_ip()}]
        for uid in member_ids:
            contact = self.db.get_contact(uid)
            if contact:
                members_info.append({'uid': uid,
                                     'display_name': contact['display_name'],
                                     'ip': contact['ip_address']})
        self._groups[group_id] = {'name': group_name, 'members': members_info,
                                   'group_type': group_type}
        if group_type == 'fixed':
            self.db.save_group(group_id, group_name, 'fixed')
            for m in members_info:
                self.db.save_group_member(group_id, m['uid'],
                                          m['display_name'], m.get('ip', ''))
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
                    'members': members_info,
                })

    def notify_group_join(self, group_id, new_uid, new_display_name):
        """Notifica membros existentes que alguém entrou no grupo."""
        group = self._groups.get(group_id)
        if not group:
            return
        for member in group['members']:
            if member['uid'] == self.user_id:
                continue
            TCPClient.send_message(member['ip'], TCP_PORT, {
                'type': MT_GROUP_JOIN,
                'from_user': new_uid,
                'display_name': new_display_name,
                'group_id': group_id,
                'ip': get_local_ip() if new_uid == self.user_id else '',
            })

    def send_file_to_group(self, group_id, filepath):
        """Envia arquivo para todos os membros do grupo (individualmente)."""
        group = self._groups.get(group_id)
        if not group:
            return []
        file_ids = []
        for member in group['members']:
            uid = member['uid']
            if uid == self.user_id:
                continue
            fid = self.send_file(uid, filepath)
            if fid:
                file_ids.append(fid)
        return file_ids

    def send_group_message(self, group_id, content):
        """Envia mensagem para todos os membros do grupo."""
        group = self._groups.get(group_id)
        if not group:
            return
        timestamp = time.time()
        msg_id = self._next_msg_id()
        for member in group['members']:
            uid = member['uid']
            if uid == self.user_id:
                continue
            TCPClient.send_message(member['ip'], TCP_PORT, {
                'type': MT_GROUP_MSG,
                'from_user': self.user_id,
                'display_name': self.display_name,
                'group_id': group_id,
                'msg_id': msg_id,
                'content': content,
                'timestamp': timestamp,
            })

    def load_saved_groups(self):
        """Carrega grupos fixos salvos no DB para memória."""
        groups = self.db.get_groups('fixed')
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

    def leave_group(self, group_id):
        """Sai de um grupo, notifica membros e remove do DB."""
        group = self._groups.get(group_id)
        if group:
            # Notificar todos os membros antes de sair
            for member in group['members']:
                if member['uid'] == self.user_id:
                    continue
                TCPClient.send_message(member['ip'], TCP_PORT, {
                    'type': MT_GROUP_LEAVE,
                    'from_user': self.user_id,
                    'display_name': self.display_name,
                    'group_id': group_id,
                })
            del self._groups[group_id]
        self.db.delete_group(group_id)

    # --- History ---
    def get_chat_history(self, peer_id, limit=None):
        return self.db.get_chat_history(self.user_id, peer_id, limit)

    def get_contacts(self, online_only=False):
        return self.db.get_contacts(online_only)

    def search_messages(self, query):
        return self.db.search_messages(query)

    def get_unread_count(self, from_user_id):
        return self.db.get_unread_count(self.user_id, from_user_id)

    def get_unread_messages(self, from_user_id):
        return self.db.get_unread_messages(self.user_id, from_user_id)

    def mark_as_read(self, from_user_id):
        self.db.mark_as_read(self.user_id, from_user_id)
