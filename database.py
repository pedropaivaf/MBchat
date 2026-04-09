# MB Chat - Banco de dados local SQLite
# Histórico de mensagens, usuários, configurações
#
# Gerencia toda a persistência local do app:
# - Dados do usuário local (nome, status, nota pessoal)
# - Contatos descobertos na rede (online/offline, avatar, nota)
# - Mensagens enviadas e recebidas (histórico completo)
# - Transferências de arquivos (status, progresso)
# - Grupos de chat (fixos persistem, temporários só em memória)
# - Configurações gerais (tema, idioma, diretório de downloads)
#
# Usa WAL mode para melhor desempenho com múltiplas threads
# e threading.local() para conexão segura por thread.

import sqlite3    # Banco de dados embutido no Python
import os         # Manipulação de caminhos e diretórios
import time       # Timestamps para registros
import threading  # threading.local() para conexão por thread
from pathlib import Path  # Manipulação moderna de caminhos


# Retorna caminho do banco: Windows=%APPDATA%/.mbchat/mbchat.db, Linux/Mac=~/.mbchat/mbchat.db
def get_db_path():
    if os.name == 'nt':  # Windows
        base = os.environ.get('APPDATA', os.path.expanduser('~'))  # ex: C:/Users/pedro/AppData/Roaming
    else:
        base = os.path.expanduser('~')  # Linux/Mac: pasta home
    db_dir = os.path.join(base, '.mbchat')  # Subpasta oculta .mbchat
    os.makedirs(db_dir, exist_ok=True)  # Cria se não existir
    return os.path.join(db_dir, 'mbchat.db')


# Gerenciador do banco SQLite local
# Cada thread recebe sua própria conexão (threading.local) para evitar conflitos
# WAL mode permite leituras simultâneas com escritas
class Database:

    def __init__(self, db_path=None):
        self.db_path = db_path or get_db_path()  # Usa caminho padrão se não especificado
        self._local = threading.local()  # Storage thread-local para conexões
        self._init_db()  # Cria tabelas se não existirem

    @property
    def conn(self):
        # Retorna conexão da thread atual, cria nova se não existe
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            self._local.conn = sqlite3.connect(self.db_path)
            self._local.conn.row_factory = sqlite3.Row  # Acesso por nome de coluna
            self._local.conn.execute("PRAGMA journal_mode=WAL")  # Write-Ahead Logging
            self._local.conn.execute("PRAGMA foreign_keys=ON")  # Ativa chaves estrangeiras
        return self._local.conn

    def _init_db(self):
        # Cria todas as tabelas necessárias se não existirem
        c = self.conn
        c.executescript("""
            -- Tabela do usuário local (singleton: sempre id=1)
            CREATE TABLE IF NOT EXISTS local_user (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                user_id TEXT NOT NULL,         -- ID único baseado em MAC+hostname
                display_name TEXT NOT NULL,     -- Nome de exibição escolhido
                status TEXT DEFAULT 'online',   -- online/away/busy/offline
                avatar_index INTEGER DEFAULT 0, -- Índice do avatar padrão
                note TEXT DEFAULT '',           -- Nota pessoal visível para todos
                created_at REAL NOT NULL,       -- Timestamp de criação
                updated_at REAL NOT NULL        -- Timestamp da última atualização
            );

            -- Tabela de contatos descobertos na rede
            CREATE TABLE IF NOT EXISTS contacts (
                user_id TEXT PRIMARY KEY,        -- ID único do peer
                display_name TEXT NOT NULL,      -- Nome de exibição do peer
                ip_address TEXT NOT NULL,        -- Último IP conhecido
                hostname TEXT DEFAULT '',        -- Nome da máquina
                os_info TEXT DEFAULT '',         -- Sistema operacional
                status TEXT DEFAULT 'offline',   -- Status atual
                avatar_index INTEGER DEFAULT 0,  -- Índice do avatar
                note TEXT DEFAULT '',            -- Nota pessoal do peer
                last_seen REAL NOT NULL,         -- Último avistamento
                first_seen REAL NOT NULL         -- Primeira descoberta
            );

            -- Tabela de mensagens (histórico completo)
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                msg_id TEXT NOT NULL,         -- ID único da mensagem
                from_user TEXT NOT NULL,      -- Remetente (user_id)
                to_user TEXT NOT NULL,        -- Destinatário (user_id)
                content TEXT NOT NULL,        -- Conteúdo da mensagem
                msg_type TEXT DEFAULT 'text', -- Tipo: text, file, system
                timestamp REAL NOT NULL,      -- Quando foi enviada
                is_sent INTEGER DEFAULT 0,    -- 1 se enviada por nós
                is_read INTEGER DEFAULT 0,    -- 1 se lida pelo destinatário
                is_delivered INTEGER DEFAULT 0 -- 1 se entregue (ACK recebido)
            );

            -- Índices para busca rápida de mensagens
            CREATE INDEX IF NOT EXISTS idx_messages_users
                ON messages(from_user, to_user);
            CREATE INDEX IF NOT EXISTS idx_messages_time
                ON messages(timestamp);

            -- Tabela de transferências de arquivos
            CREATE TABLE IF NOT EXISTS file_transfers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_id TEXT NOT NULL UNIQUE,  -- ID único da transferência
                from_user TEXT NOT NULL,       -- Quem enviou
                to_user TEXT NOT NULL,         -- Quem recebeu
                filename TEXT NOT NULL,        -- Nome do arquivo
                filepath TEXT DEFAULT '',      -- Caminho completo no disco
                filesize INTEGER DEFAULT 0,    -- Tamanho em bytes
                status TEXT DEFAULT 'pending', -- pending/completed/error
                progress REAL DEFAULT 0,       -- Progresso 0-100
                timestamp REAL NOT NULL        -- Quando foi iniciada
            );

            -- Tabela de configurações (chave-valor genérica)
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            -- Tabela de grupos de chat
            CREATE TABLE IF NOT EXISTS groups (
                group_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                group_type TEXT NOT NULL DEFAULT 'temp',  -- temp ou fixed
                created_at REAL NOT NULL
            );

            -- Tabela de membros dos grupos
            CREATE TABLE IF NOT EXISTS group_members (
                group_id TEXT NOT NULL,
                uid TEXT NOT NULL,
                display_name TEXT NOT NULL,
                ip TEXT DEFAULT '',
                PRIMARY KEY (group_id, uid),  -- Chave composta
                FOREIGN KEY (group_id) REFERENCES groups(group_id) ON DELETE CASCADE
            );
        """)
        c.commit()

        # Migration: adiciona coluna avatar_data se não existir
        try:
            c.execute("ALTER TABLE contacts ADD COLUMN avatar_data TEXT DEFAULT ''")
            c.commit()
        except Exception:
            pass

        # Migration: reply_to_id em messages
        try:
            c.execute("ALTER TABLE messages ADD COLUMN reply_to_id TEXT DEFAULT ''")
            c.commit()
        except Exception:
            pass

        # Migration: department e private_note em contacts
        for col in ('department', 'private_note'):
            try:
                c.execute(f"ALTER TABLE contacts ADD COLUMN {col} TEXT DEFAULT ''")
                c.commit()
            except Exception:
                pass

        # Tabelas novas: polls, poll_votes, reminders
        c.executescript("""
            CREATE TABLE IF NOT EXISTS polls (
                poll_id TEXT PRIMARY KEY,
                group_id TEXT NOT NULL,
                creator_uid TEXT NOT NULL,
                question TEXT NOT NULL,
                options TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS poll_votes (
                poll_id TEXT NOT NULL,
                voter_uid TEXT NOT NULL,
                option_index INTEGER NOT NULL,
                timestamp REAL NOT NULL,
                PRIMARY KEY (poll_id, voter_uid)
            );
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                remind_at REAL NOT NULL,
                notified INTEGER DEFAULT 0,
                created_at REAL NOT NULL
            );
        """)
        c.commit()

    # ========================================
    # LOCAL USER — Dados do usuário local
    # ========================================

    # Retorna dados do usuário local ou None se não configurado
    def get_local_user(self):
        row = self.conn.execute("SELECT * FROM local_user WHERE id=1").fetchone()
        return dict(row) if row else None

    # Cria ou atualiza registro do usuário local (UPSERT: INSERT ON CONFLICT UPDATE)
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

    # Atualiza status do usuário local (online/away/busy/offline)
    def update_local_status(self, status):
        self.conn.execute(
            "UPDATE local_user SET status=?, updated_at=? WHERE id=1",
            (status, time.time()))
        self.conn.commit()

    # Atualiza nota pessoal do usuário local
    def update_local_note(self, note):
        self.conn.execute(
            "UPDATE local_user SET note=?, updated_at=? WHERE id=1",
            (note, time.time()))
        self.conn.commit()

    # Retorna nota pessoal do usuário local (string vazia se não tem)
    def get_local_note(self):
        row = self.conn.execute(
            "SELECT note FROM local_user WHERE id=1").fetchone()
        return row['note'] if row and row['note'] else ''

    # ========================================
    # CONTACTS — Peers descobertos na rede
    # ========================================

    # Insere ou atualiza contato (chamado pelo discovery quando peer é encontrado)
    # UPSERT: cria novos e atualiza existentes. Não atualiza first_seen em updates
    def upsert_contact(self, user_id, display_name, ip_address,
                       hostname='', os_info='', status='online', note='',
                       avatar_index=0, avatar_data=''):
        now = time.time()
        self.conn.execute("""
            INSERT INTO contacts (user_id, display_name, ip_address, hostname,
                                  os_info, status, note, avatar_index,
                                  avatar_data, last_seen, first_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                display_name=excluded.display_name,
                ip_address=excluded.ip_address,
                hostname=excluded.hostname,
                os_info=excluded.os_info,
                status=excluded.status,
                note=excluded.note,
                avatar_index=excluded.avatar_index,
                avatar_data=excluded.avatar_data,
                last_seen=excluded.last_seen
        """, (user_id, display_name, ip_address, hostname, os_info, status,
              note, avatar_index, avatar_data, now, now))
        self.conn.commit()

    # Retorna nota pessoal de um contato específico
    def get_contact_note(self, user_id):
        row = self.conn.execute(
            "SELECT note FROM contacts WHERE user_id=?", (user_id,)).fetchone()
        return row['note'] if row and row['note'] else ''

    # Remove contato do banco (usado para limpar registros obsoletos/duplicados)
    def delete_contact(self, user_id):
        self.conn.execute("DELETE FROM contacts WHERE user_id=?", (user_id,))
        self.conn.commit()

    # Marca contato como offline (peer perdido/desconectou)
    def set_contact_offline(self, user_id):
        self.conn.execute(
            "UPDATE contacts SET status='offline', last_seen=? WHERE user_id=?",
            (time.time(), user_id))
        self.conn.commit()

    # Marca TODOS os contatos como offline (chamado no startup e ao encerrar)
    def set_all_contacts_offline(self):
        self.conn.execute(
            "UPDATE contacts SET status='offline', last_seen=?",
            (time.time(),))
        self.conn.commit()

    # Retorna lista de contatos (online_only=True filtra apenas não-offline)
    def get_contacts(self, online_only=False):
        if online_only:
            rows = self.conn.execute(
                "SELECT * FROM contacts WHERE status != 'offline' ORDER BY display_name"
            ).fetchall()
        else:
            # Ordena: online primeiro, depois por nome
            rows = self.conn.execute(
                "SELECT * FROM contacts ORDER BY status DESC, display_name"
            ).fetchall()
        return [dict(r) for r in rows]

    # Retorna dados de um contato específico ou None
    def get_contact(self, user_id):
        row = self.conn.execute(
            "SELECT * FROM contacts WHERE user_id=?", (user_id,)).fetchone()
        return dict(row) if row else None

    # ========================================
    # MESSAGES — Histórico de mensagens
    # ========================================

    # Retorna histórico entre dois usuários (limit=None = todas, com limit inverte DESC→ASC)
    def get_chat_history(self, user_a, user_b, limit=None, offset=0):
        if limit is not None:
            # Com limit: busca as N mais recentes (DESC), depois inverte para ASC
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

    # Retorna mensagens não lidas de um peer
    def get_unread_messages(self, local_user_id, from_user_id):
        rows = self.conn.execute("""
            SELECT * FROM messages
            WHERE from_user=? AND to_user=? AND is_read=0
            ORDER BY timestamp ASC
        """, (from_user_id, local_user_id)).fetchall()
        return [dict(r) for r in rows]

    # Retorna contagem de mensagens não lidas de um peer
    def get_unread_count(self, local_user_id, from_user_id):
        row = self.conn.execute("""
            SELECT COUNT(*) as cnt FROM messages
            WHERE from_user=? AND to_user=? AND is_read=0
        """, (from_user_id, local_user_id)).fetchone()
        return row['cnt'] if row else 0

    # Marca todas as mensagens de um peer como lidas
    def mark_as_read(self, local_user_id, from_user_id):
        self.conn.execute("""
            UPDATE messages SET is_read=1
            WHERE from_user=? AND to_user=? AND is_read=0
        """, (from_user_id, local_user_id))
        self.conn.commit()

    # Busca mensagens por texto (LIKE %query%), até 500 resultados
    def search_messages(self, query, limit=500):
        rows = self.conn.execute("""
            SELECT * FROM messages
            WHERE content LIKE ?
            ORDER BY timestamp DESC LIMIT ?
        """, (f'%{query}%', limit)).fetchall()
        return [dict(r) for r in rows]

    # Retorna peers com quem houve conversa + data da última mensagem (para tela Histórico)
    def get_history_contacts(self):
        rows = self.conn.execute("""
            SELECT
                CASE WHEN is_sent=1 THEN to_user ELSE from_user END as peer,
                MAX(timestamp) as last_ts
            FROM messages
            GROUP BY peer
            ORDER BY last_ts DESC
        """).fetchall()
        return [dict(r) for r in rows]

    # Retorna mensagens com um peer, com filtros opcionais de data e texto
    def get_messages_with_peer(self, local_user, peer_id,
                               date_from=None, date_to=None,
                               search_text=None):
        # Query base: mensagens entre os dois usuários (ambas direções)
        sql = """
            SELECT * FROM messages
            WHERE ((from_user=? AND to_user=?) OR (from_user=? AND to_user=?))
        """
        params = [local_user, peer_id, peer_id, local_user]
        # Filtros opcionais adicionados dinamicamente
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

    # Busca global em todas as mensagens com filtros opcionais
    def search_all_messages(self, search_text=None, date_from=None, date_to=None, limit=500):
        sql = "SELECT * FROM messages WHERE 1=1"
        params = []
        if search_text:
            sql += " AND content LIKE ?"
            params.append(f'%{search_text}%')
        if date_from:
            sql += " AND timestamp >= ?"
            params.append(date_from)
        if date_to:
            sql += " AND timestamp <= ?"
            params.append(date_to)
        sql += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        rows = self.conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    # ========================================
    # FILE TRANSFERS — Transferências de arquivos
    # ========================================

    # Registra uma transferência de arquivo no banco
    def save_file_transfer(self, file_id, from_user, to_user,
                           filename, filesize, filepath=''):
        self.conn.execute("""
            INSERT OR REPLACE INTO file_transfers
                (file_id, from_user, to_user, filename, filepath, filesize, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (file_id, from_user, to_user, filename, filepath, filesize, time.time()))
        self.conn.commit()

    # Atualiza campos de uma transferência (kwargs: status='completed', progress=100, etc)
    def update_file_transfer(self, file_id, **kwargs):
        sets = ', '.join(f"{k}=?" for k in kwargs)
        vals = list(kwargs.values()) + [file_id]
        self.conn.execute(
            f"UPDATE file_transfers SET {sets} WHERE file_id=?", vals)
        self.conn.commit()

    # ========================================
    # GROUPS — Grupos de chat
    # ========================================

    # Salva grupo no banco (apenas fixos são persistidos, temporários só em memória)
    def save_group(self, group_id, name, group_type='temp'):
        self.conn.execute("""
            INSERT OR REPLACE INTO groups (group_id, name, group_type, created_at)
            VALUES (?, ?, ?, ?)
        """, (group_id, name, group_type, time.time()))
        self.conn.commit()

    # Retorna lista de grupos (filtrados por tipo se especificado)
    def get_groups(self, group_type=None):
        if group_type:
            rows = self.conn.execute(
                "SELECT * FROM groups WHERE group_type=? ORDER BY created_at DESC",
                (group_type,)).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM groups ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]

    # Remove grupo do banco (CASCADE deleta membros também)
    def delete_group(self, group_id):
        self.conn.execute("DELETE FROM groups WHERE group_id=?", (group_id,))
        self.conn.commit()

    # Adiciona ou atualiza membro em um grupo
    def save_group_member(self, group_id, uid, display_name, ip=''):
        self.conn.execute("""
            INSERT OR REPLACE INTO group_members (group_id, uid, display_name, ip)
            VALUES (?, ?, ?, ?)
        """, (group_id, uid, display_name, ip))
        self.conn.commit()

    # Retorna lista de membros de um grupo
    def get_group_members(self, group_id):
        rows = self.conn.execute(
            "SELECT * FROM group_members WHERE group_id=?",
            (group_id,)).fetchall()
        return [dict(r) for r in rows]

    # Remove membro de um grupo
    def delete_group_member(self, group_id, uid):
        self.conn.execute(
            "DELETE FROM group_members WHERE group_id=? AND uid=?",
            (group_id, uid))
        self.conn.commit()

    # ========================================
    # SETTINGS — Configurações chave-valor
    # ========================================

    # Lê configuração pelo nome (retorna default se não existe)
    def get_setting(self, key, default=None):
        row = self.conn.execute(
            "SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row['value'] if row else default

    # Salva configuração (cria ou atualiza)
    def set_setting(self, key, value):
        self.conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, str(value)))
        self.conn.commit()

    # ========================================
    # MESSAGES — reply_to_id
    # ========================================

    def save_message(self, msg_id, from_user, to_user, content,
                     msg_type='text', is_sent=False, timestamp=None,
                     reply_to_id=''):
        ts = timestamp or time.time()
        self.conn.execute("""
            INSERT INTO messages (msg_id, from_user, to_user, content,
                                  msg_type, timestamp, is_sent, reply_to_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (msg_id, from_user, to_user, content, msg_type, ts,
              int(is_sent), reply_to_id or ''))
        self.conn.commit()

    def get_message_by_id(self, msg_id):
        row = self.conn.execute(
            "SELECT * FROM messages WHERE msg_id=?", (msg_id,)).fetchone()
        return dict(row) if row else None

    # ========================================
    # CONTACTS — department, private_note
    # ========================================

    def set_contact_department(self, user_id, department):
        self.conn.execute(
            "UPDATE contacts SET department=? WHERE user_id=?",
            (department, user_id))
        self.conn.commit()

    def set_contact_private_note(self, user_id, note):
        self.conn.execute(
            "UPDATE contacts SET private_note=? WHERE user_id=?",
            (note, user_id))
        self.conn.commit()

    # ========================================
    # POLLS — Enquetes de grupo
    # ========================================

    def save_poll(self, poll_id, group_id, creator_uid, question, options):
        import json
        self.conn.execute("""
            INSERT OR REPLACE INTO polls (poll_id, group_id, creator_uid,
                                           question, options, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (poll_id, group_id, creator_uid, question,
              json.dumps(options, ensure_ascii=False), time.time()))
        self.conn.commit()

    def get_poll(self, poll_id):
        import json
        row = self.conn.execute(
            "SELECT * FROM polls WHERE poll_id=?", (poll_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d['options'] = json.loads(d['options'])
        return d

    def save_poll_vote(self, poll_id, voter_uid, option_index):
        self.conn.execute("""
            INSERT OR REPLACE INTO poll_votes (poll_id, voter_uid,
                                                option_index, timestamp)
            VALUES (?, ?, ?, ?)
        """, (poll_id, voter_uid, option_index, time.time()))
        self.conn.commit()

    def get_poll_votes(self, poll_id):
        rows = self.conn.execute(
            "SELECT * FROM poll_votes WHERE poll_id=?",
            (poll_id,)).fetchall()
        return [dict(r) for r in rows]

    # ========================================
    # REMINDERS — Lembretes
    # ========================================

    def add_reminder(self, text, remind_at):
        self.conn.execute("""
            INSERT INTO reminders (text, remind_at, created_at)
            VALUES (?, ?, ?)
        """, (text, remind_at, time.time()))
        self.conn.commit()

    def get_pending_reminders(self):
        now = time.time()
        rows = self.conn.execute("""
            SELECT * FROM reminders
            WHERE notified=0 AND remind_at <= ?
            ORDER BY remind_at ASC
        """, (now,)).fetchall()
        return [dict(r) for r in rows]

    def get_all_reminders(self):
        rows = self.conn.execute("""
            SELECT * FROM reminders WHERE notified=0
            ORDER BY remind_at ASC
        """).fetchall()
        return [dict(r) for r in rows]

    def get_completed_reminders(self):
        rows = self.conn.execute("""
            SELECT * FROM reminders WHERE notified=1
            AND remind_at >= ? ORDER BY remind_at DESC
        """, (time.time() - 86400,)).fetchall()
        return [dict(r) for r in rows]

    def mark_reminder_notified(self, reminder_id):
        self.conn.execute(
            "UPDATE reminders SET notified=1 WHERE id=?", (reminder_id,))
        self.conn.commit()

    def delete_reminder(self, reminder_id):
        self.conn.execute(
            "DELETE FROM reminders WHERE id=?", (reminder_id,))
        self.conn.commit()

    # Fecha conexão da thread atual
    def close(self):
        if hasattr(self._local, 'conn') and self._local.conn:
            self._local.conn.close()
            self._local.conn = None
