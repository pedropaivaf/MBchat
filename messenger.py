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
    MT_FILE_DEC, MT_FILE_CANCEL, MT_STATUS, MT_TYPING, MT_ACK, TCP_PORT
)
from database import Database


class Messenger:
    """Controller principal do LAN Messenger."""

    def __init__(self, display_name=None, on_user_found=None,
                 on_user_lost=None, on_message=None, on_status=None,
                 on_typing=None, on_file_incoming=None,
                 on_file_progress=None, on_file_complete=None,
                 on_file_error=None):
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
        self.db.set_local_user(self.user_id, self.display_name, self.status)

        # Mark all contacts offline on start
        self.db.set_all_contacts_offline()

        # Network components
        self.discovery = UDPDiscovery(
            self.user_id, self.display_name, self.status,
            on_peer_found=self._on_peer_found,
            on_peer_lost=self._on_peer_lost
        )
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
            status=info.get('status', 'online')
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

    # --- History ---
    def get_chat_history(self, peer_id, limit=None):
        return self.db.get_chat_history(self.user_id, peer_id, limit)

    def get_contacts(self, online_only=False):
        return self.db.get_contacts(online_only)

    def search_messages(self, query):
        return self.db.search_messages(query)

    def get_unread_count(self, from_user_id):
        return self.db.get_unread_count(self.user_id, from_user_id)

    def mark_as_read(self, from_user_id):
        self.db.mark_as_read(self.user_id, from_user_id)
