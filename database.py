"""
MB Chat - Banco de dados local SQLite
Histórico de mensagens, usuários, configurações
"""
import sqlite3
import os
import time
import threading
from pathlib import Path


def get_db_path():
    if os.name == 'nt':
        base = os.environ.get('APPDATA', os.path.expanduser('~'))
    else:
        base = os.path.expanduser('~')
    db_dir = os.path.join(base, '.mbchat')
    os.makedirs(db_dir, exist_ok=True)
    return os.path.join(db_dir, 'mbchat.db')


class Database:
    def __init__(self, db_path=None):
        self.db_path = db_path or get_db_path()
        self._local = threading.local()
        self._init_db()

    @property
    def conn(self):
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            self._local.conn = sqlite3.connect(self.db_path)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA foreign_keys=ON")
        return self._local.conn

    def _init_db(self):
        c = self.conn
        c.executescript("""
            CREATE TABLE IF NOT EXISTS local_user (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                user_id TEXT NOT NULL,
                display_name TEXT NOT NULL,
                status TEXT DEFAULT 'online',
                avatar_index INTEGER DEFAULT 0,
                note TEXT DEFAULT '',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS contacts (
                user_id TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                ip_address TEXT NOT NULL,
                hostname TEXT DEFAULT '',
                os_info TEXT DEFAULT '',
                status TEXT DEFAULT 'offline',
                avatar_index INTEGER DEFAULT 0,
                note TEXT DEFAULT '',
                last_seen REAL NOT NULL,
                first_seen REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                msg_id TEXT NOT NULL,
                from_user TEXT NOT NULL,
                to_user TEXT NOT NULL,
                content TEXT NOT NULL,
                msg_type TEXT DEFAULT 'text',
                timestamp REAL NOT NULL,
                is_sent INTEGER DEFAULT 0,
                is_read INTEGER DEFAULT 0,
                is_delivered INTEGER DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_messages_users
                ON messages(from_user, to_user);
            CREATE INDEX IF NOT EXISTS idx_messages_time
                ON messages(timestamp);

            CREATE TABLE IF NOT EXISTS file_transfers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_id TEXT NOT NULL UNIQUE,
                from_user TEXT NOT NULL,
                to_user TEXT NOT NULL,
                filename TEXT NOT NULL,
                filepath TEXT DEFAULT '',
                filesize INTEGER DEFAULT 0,
                status TEXT DEFAULT 'pending',
                progress REAL DEFAULT 0,
                timestamp REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)
        c.commit()

    # --- Local User ---
    def get_local_user(self):
        row = self.conn.execute("SELECT * FROM local_user WHERE id=1").fetchone()
        return dict(row) if row else None

    def set_local_user(self, user_id, display_name, status='online'):
        now = time.time()
        self.conn.execute("""
            INSERT INTO local_user (id, user_id, display_name, status, created_at, updated_at)
            VALUES (1, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                user_id=excluded.user_id,
                display_name=excluded.display_name,
                status=excluded.status,
                updated_at=?
        """, (user_id, display_name, status, now, now, now))
        self.conn.commit()

    def update_local_status(self, status):
        self.conn.execute(
            "UPDATE local_user SET status=?, updated_at=? WHERE id=1",
            (status, time.time()))
        self.conn.commit()

    def update_local_note(self, note):
        self.conn.execute(
            "UPDATE local_user SET note=?, updated_at=? WHERE id=1",
            (note, time.time()))
        self.conn.commit()

    def get_local_note(self):
        row = self.conn.execute(
            "SELECT note FROM local_user WHERE id=1").fetchone()
        return row['note'] if row and row['note'] else ''

    # --- Contacts ---
    def upsert_contact(self, user_id, display_name, ip_address,
                       hostname='', os_info='', status='online', note=''):
        now = time.time()
        self.conn.execute("""
            INSERT INTO contacts (user_id, display_name, ip_address, hostname,
                                  os_info, status, note, last_seen, first_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                display_name=excluded.display_name,
                ip_address=excluded.ip_address,
                hostname=excluded.hostname,
                os_info=excluded.os_info,
                status=excluded.status,
                note=excluded.note,
                last_seen=excluded.last_seen
        """, (user_id, display_name, ip_address, hostname, os_info, status, note, now, now))
        self.conn.commit()

    def get_contact_note(self, user_id):
        row = self.conn.execute(
            "SELECT note FROM contacts WHERE user_id=?", (user_id,)).fetchone()
        return row['note'] if row and row['note'] else ''

    def set_contact_offline(self, user_id):
        self.conn.execute(
            "UPDATE contacts SET status='offline', last_seen=? WHERE user_id=?",
            (time.time(), user_id))
        self.conn.commit()

    def set_all_contacts_offline(self):
        self.conn.execute(
            "UPDATE contacts SET status='offline', last_seen=?",
            (time.time(),))
        self.conn.commit()

    def get_contacts(self, online_only=False):
        if online_only:
            rows = self.conn.execute(
                "SELECT * FROM contacts WHERE status != 'offline' ORDER BY display_name"
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM contacts ORDER BY status DESC, display_name"
            ).fetchall()
        return [dict(r) for r in rows]

    def get_contact(self, user_id):
        row = self.conn.execute(
            "SELECT * FROM contacts WHERE user_id=?", (user_id,)).fetchone()
        return dict(row) if row else None

    # --- Messages ---
    def save_message(self, msg_id, from_user, to_user, content,
                     msg_type='text', is_sent=False, timestamp=None):
        ts = timestamp or time.time()
        self.conn.execute("""
            INSERT INTO messages (msg_id, from_user, to_user, content,
                                  msg_type, timestamp, is_sent)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (msg_id, from_user, to_user, content, msg_type, ts, int(is_sent)))
        self.conn.commit()

    def get_chat_history(self, user_a, user_b, limit=None, offset=0):
        if limit is not None:
            rows = self.conn.execute("""
                SELECT * FROM messages
                WHERE (from_user=? AND to_user=?) OR (from_user=? AND to_user=?)
                ORDER BY timestamp DESC
                LIMIT ? OFFSET ?
            """, (user_a, user_b, user_b, user_a, limit, offset)).fetchall()
        else:
            rows = self.conn.execute("""
                SELECT * FROM messages
                WHERE (from_user=? AND to_user=?) OR (from_user=? AND to_user=?)
                ORDER BY timestamp ASC
            """, (user_a, user_b, user_b, user_a)).fetchall()
            return [dict(r) for r in rows]
        return [dict(r) for r in reversed(rows)]

    def get_unread_messages(self, local_user_id, from_user_id):
        rows = self.conn.execute("""
            SELECT * FROM messages
            WHERE from_user=? AND to_user=? AND is_read=0
            ORDER BY timestamp ASC
        """, (from_user_id, local_user_id)).fetchall()
        return [dict(r) for r in rows]

    def get_unread_count(self, local_user_id, from_user_id):
        row = self.conn.execute("""
            SELECT COUNT(*) as cnt FROM messages
            WHERE from_user=? AND to_user=? AND is_read=0
        """, (from_user_id, local_user_id)).fetchone()
        return row['cnt'] if row else 0

    def mark_as_read(self, local_user_id, from_user_id):
        self.conn.execute("""
            UPDATE messages SET is_read=1
            WHERE from_user=? AND to_user=? AND is_read=0
        """, (from_user_id, local_user_id))
        self.conn.commit()

    def search_messages(self, query, limit=500):
        rows = self.conn.execute("""
            SELECT * FROM messages
            WHERE content LIKE ?
            ORDER BY timestamp DESC LIMIT ?
        """, (f'%{query}%', limit)).fetchall()
        return [dict(r) for r in rows]

    def get_history_contacts(self):
        """Return distinct contacts with their last message date."""
        rows = self.conn.execute("""
            SELECT
                CASE WHEN is_sent=1 THEN to_user ELSE from_user END as peer,
                MAX(timestamp) as last_ts
            FROM messages
            GROUP BY peer
            ORDER BY last_ts DESC
        """).fetchall()
        return [dict(r) for r in rows]

    def get_messages_with_peer(self, local_user, peer_id,
                               date_from=None, date_to=None,
                               search_text=None):
        """Get all messages with a peer, optionally filtered."""
        sql = """
            SELECT * FROM messages
            WHERE ((from_user=? AND to_user=?) OR (from_user=? AND to_user=?))
        """
        params = [local_user, peer_id, peer_id, local_user]
        if date_from:
            sql += " AND timestamp >= ?"
            params.append(date_from)
        if date_to:
            sql += " AND timestamp <= ?"
            params.append(date_to)
        if search_text:
            sql += " AND content LIKE ?"
            params.append(f'%{search_text}%')
        sql += " ORDER BY timestamp ASC"
        rows = self.conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    # --- File Transfers ---
    def save_file_transfer(self, file_id, from_user, to_user,
                           filename, filesize, filepath=''):
        self.conn.execute("""
            INSERT OR REPLACE INTO file_transfers
                (file_id, from_user, to_user, filename, filepath, filesize, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (file_id, from_user, to_user, filename, filepath, filesize, time.time()))
        self.conn.commit()

    def update_file_transfer(self, file_id, **kwargs):
        sets = ', '.join(f"{k}=?" for k in kwargs)
        vals = list(kwargs.values()) + [file_id]
        self.conn.execute(
            f"UPDATE file_transfers SET {sets} WHERE file_id=?", vals)
        self.conn.commit()

    # --- Settings ---
    def get_setting(self, key, default=None):
        row = self.conn.execute(
            "SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row['value'] if row else default

    def set_setting(self, key, value):
        self.conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, str(value)))
        self.conn.commit()

    def close(self):
        if hasattr(self._local, 'conn') and self._local.conn:
            self._local.conn.close()
            self._local.conn = None
