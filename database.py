"""
MB Chat - Banco de dados local SQLite
Histórico de mensagens, usuários, configurações

Este módulo gerencia toda a persistência local do app:
- Dados do usuário local (nome, status, nota pessoal)
- Contatos descobertos na rede (online/offline, avatar, nota)
- Mensagens enviadas e recebidas (histórico completo)
- Transferências de arquivos (status, progresso)
- Grupos de chat (fixos persistem, temporários só em memória)
- Configurações gerais (tema, idioma, diretório de downloads)

Usa WAL mode para melhor desempenho com múltiplas threads
e threading.local() para conexão segura por thread.
"""
import sqlite3  # Banco de dados embutido no Python
import os       # Manipulação de caminhos e diretórios
import time     # Timestamps para registros
import threading  # threading.local() para conexão por thread
from pathlib import Path  # Manipulação moderna de caminhos


def get_db_path():
    """Retorna o caminho do arquivo do banco de dados.

    No Windows: %APPDATA%/.mbchat/mbchat.db
    No Linux/Mac: ~/.mbchat/mbchat.db
    Cria o diretório se não existir.
    """
    if os.name == 'nt':  # Windows
        # Usa APPDATA (ex: C:/Users/pedro/AppData/Roaming)
        base = os.environ.get('APPDATA', os.path.expanduser('~'))
    else:
        # Linux/Mac: pasta home do usuário
        base = os.path.expanduser('~')
    db_dir = os.path.join(base, '.mbchat')  # Subpasta oculta .mbchat
    os.makedirs(db_dir, exist_ok=True)  # Cria se não existir
    return os.path.join(db_dir, 'mbchat.db')  # Arquivo do banco


class Database:
    """Gerenciador do banco de dados SQLite local.

    Cada thread recebe sua própria conexão (threading.local)
    para evitar conflitos de acesso concorrente.
    WAL mode permite leituras simultâneas com escritas.
    """

    def __init__(self, db_path=None):
        """Inicializa o banco de dados.

        Args:
            db_path: Caminho customizado para o DB (opcional, usa padrão se None)
        """
        self.db_path = db_path or get_db_path()  # Usa caminho padrão se não especificado
        self._local = threading.local()  # Storage thread-local para conexões
        self._init_db()  # Cria tabelas se não existirem

    @property
    def conn(self):
        """Retorna a conexão SQLite da thread atual.

        Cria uma nova conexão se a thread ainda não tem uma.
        Configura row_factory para retornar dicts ao invés de tuples.
        Habilita WAL mode e foreign keys.
        """
        # Verifica se esta thread já tem uma conexão ativa
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            self._local.conn = sqlite3.connect(self.db_path)  # Nova conexão
            self._local.conn.row_factory = sqlite3.Row  # Acesso por nome de coluna
            self._local.conn.execute("PRAGMA journal_mode=WAL")  # Write-Ahead Logging
            self._local.conn.execute("PRAGMA foreign_keys=ON")  # Ativa chaves estrangeiras
        return self._local.conn

    def _init_db(self):
        """Cria todas as tabelas necessárias se não existirem.

        Tabelas:
        - local_user: dados do usuário local (apenas 1 registro, id=1)
        - contacts: peers descobertos na rede
        - messages: todas as mensagens enviadas/recebidas
        - file_transfers: registro de transferências de arquivos
        - settings: configurações chave-valor
        - groups: grupos de chat (fixos persistidos)
        - group_members: membros de cada grupo
        """
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
                ON messages(from_user, to_user);  -- Busca por par de usuários
            CREATE INDEX IF NOT EXISTS idx_messages_time
                ON messages(timestamp);           -- Busca por data

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
                key TEXT PRIMARY KEY,    -- Nome da configuração
                value TEXT NOT NULL      -- Valor (sempre string, converter ao ler)
            );

            -- Tabela de grupos de chat
            CREATE TABLE IF NOT EXISTS groups (
                group_id TEXT PRIMARY KEY,              -- ID único do grupo
                name TEXT NOT NULL,                     -- Nome do grupo
                group_type TEXT NOT NULL DEFAULT 'temp', -- temp ou fixed
                created_at REAL NOT NULL                -- Quando foi criado
            );

            -- Tabela de membros dos grupos
            CREATE TABLE IF NOT EXISTS group_members (
                group_id TEXT NOT NULL,      -- FK para groups
                uid TEXT NOT NULL,           -- user_id do membro
                display_name TEXT NOT NULL,  -- Nome de exibição
                ip TEXT DEFAULT '',          -- IP do membro
                PRIMARY KEY (group_id, uid), -- Chave composta
                FOREIGN KEY (group_id) REFERENCES groups(group_id) ON DELETE CASCADE
            );
        """)
        c.commit()  # Salva as criações de tabela

        # Migration: adiciona coluna avatar_data se não existir
        # avatar_data armazena thumbnail base64 JPEG do avatar custom
        # Usa try/except pois ALTER TABLE falha se coluna já existe
        try:
            c.execute("ALTER TABLE contacts ADD COLUMN avatar_data TEXT DEFAULT ''")
            c.commit()
        except Exception:
            pass  # Coluna já existe, ignora o erro

    # ========================================
    # LOCAL USER — Dados do usuário local
    # ========================================

    def get_local_user(self):
        """Retorna dados do usuário local ou None se não configurado."""
        row = self.conn.execute("SELECT * FROM local_user WHERE id=1").fetchone()
        return dict(row) if row else None  # Converte sqlite3.Row para dict

    def set_local_user(self, user_id, display_name, status='online'):
        """Cria ou atualiza o registro do usuário local.

        Usa UPSERT (INSERT ON CONFLICT UPDATE) para criar na primeira vez
        e atualizar nas seguintes, pois id=1 é fixo.
        """
        now = time.time()  # Timestamp atual
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
        """Atualiza o status do usuário local (online/away/busy/offline)."""
        self.conn.execute(
            "UPDATE local_user SET status=?, updated_at=? WHERE id=1",
            (status, time.time()))
        self.conn.commit()

    def update_local_note(self, note):
        """Atualiza a nota pessoal do usuário local."""
        self.conn.execute(
            "UPDATE local_user SET note=?, updated_at=? WHERE id=1",
            (note, time.time()))
        self.conn.commit()

    def get_local_note(self):
        """Retorna a nota pessoal do usuário local (string vazia se não tem)."""
        row = self.conn.execute(
            "SELECT note FROM local_user WHERE id=1").fetchone()
        return row['note'] if row and row['note'] else ''

    # ========================================
    # CONTACTS — Peers descobertos na rede
    # ========================================

    def upsert_contact(self, user_id, display_name, ip_address,
                       hostname='', os_info='', status='online', note='',
                       avatar_index=0, avatar_data=''):
        """Insere ou atualiza um contato.

        Chamado pelo discovery quando um peer é encontrado/atualizado.
        Usa UPSERT para criar novos e atualizar existentes.
        Não atualiza first_seen em updates (mantém data original).

        Args:
            user_id: ID único do peer (MAC_hostname)
            display_name: Nome de exibição
            ip_address: IP atual na rede
            hostname: Nome da máquina
            os_info: Sistema operacional
            status: online/away/busy/offline
            note: Nota pessoal do peer
            avatar_index: Índice do avatar padrão
            avatar_data: Thumbnail base64 JPEG do avatar custom
        """
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

    def get_contact_note(self, user_id):
        """Retorna a nota pessoal de um contato específico."""
        row = self.conn.execute(
            "SELECT note FROM contacts WHERE user_id=?", (user_id,)).fetchone()
        return row['note'] if row and row['note'] else ''

    def set_contact_offline(self, user_id):
        """Marca um contato como offline (peer perdido)."""
        self.conn.execute(
            "UPDATE contacts SET status='offline', last_seen=? WHERE user_id=?",
            (time.time(), user_id))
        self.conn.commit()

    def set_all_contacts_offline(self):
        """Marca todos os contatos como offline.

        Chamado na inicialização e ao encerrar o app,
        pois não sabemos o estado real dos peers nesse momento.
        """
        self.conn.execute(
            "UPDATE contacts SET status='offline', last_seen=?",
            (time.time(),))
        self.conn.commit()

    def get_contacts(self, online_only=False):
        """Retorna lista de contatos.

        Args:
            online_only: Se True, retorna apenas contatos não-offline

        Returns:
            Lista de dicts com dados de cada contato
        """
        if online_only:
            rows = self.conn.execute(
                "SELECT * FROM contacts WHERE status != 'offline' ORDER BY display_name"
            ).fetchall()
        else:
            # Ordena por status (online primeiro) e depois por nome
            rows = self.conn.execute(
                "SELECT * FROM contacts ORDER BY status DESC, display_name"
            ).fetchall()
        return [dict(r) for r in rows]  # Converte cada Row para dict

    def get_contact(self, user_id):
        """Retorna dados de um contato específico ou None."""
        row = self.conn.execute(
            "SELECT * FROM contacts WHERE user_id=?", (user_id,)).fetchone()
        return dict(row) if row else None

    # ========================================
    # MESSAGES — Histórico de mensagens
    # ========================================

    def save_message(self, msg_id, from_user, to_user, content,
                     msg_type='text', is_sent=False, timestamp=None):
        """Salva uma mensagem no histórico.

        Args:
            msg_id: ID único da mensagem
            from_user: user_id do remetente
            to_user: user_id do destinatário
            content: Conteúdo textual da mensagem
            msg_type: Tipo (text, file, system)
            is_sent: True se enviada por nós (False se recebida)
            timestamp: Timestamp customizado (usa time.time() se None)
        """
        ts = timestamp or time.time()
        self.conn.execute("""
            INSERT INTO messages (msg_id, from_user, to_user, content,
                                  msg_type, timestamp, is_sent)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (msg_id, from_user, to_user, content, msg_type, ts, int(is_sent)))
        self.conn.commit()

    def get_chat_history(self, user_a, user_b, limit=None, offset=0):
        """Retorna histórico de conversa entre dois usuários.

        Args:
            user_a: Primeiro usuário (geralmente o local)
            user_b: Segundo usuário (peer)
            limit: Máximo de mensagens (None = todas)
            offset: Pular N mensagens mais recentes (paginação)

        Returns:
            Lista de mensagens ordenadas cronologicamente (ASC)
        """
        if limit is not None:
            # Com limit: busca as N mais recentes (DESC), depois inverte
            rows = self.conn.execute("""
                SELECT * FROM messages
                WHERE (from_user=? AND to_user=?) OR (from_user=? AND to_user=?)
                ORDER BY timestamp DESC
                LIMIT ? OFFSET ?
            """, (user_a, user_b, user_b, user_a, limit, offset)).fetchall()
        else:
            # Sem limit: todas as mensagens em ordem cronológica
            rows = self.conn.execute("""
                SELECT * FROM messages
                WHERE (from_user=? AND to_user=?) OR (from_user=? AND to_user=?)
                ORDER BY timestamp ASC
            """, (user_a, user_b, user_b, user_a)).fetchall()
            return [dict(r) for r in rows]
        return [dict(r) for r in reversed(rows)]  # Inverte DESC para ASC

    def get_unread_messages(self, local_user_id, from_user_id):
        """Retorna mensagens não lidas de um peer específico."""
        rows = self.conn.execute("""
            SELECT * FROM messages
            WHERE from_user=? AND to_user=? AND is_read=0
            ORDER BY timestamp ASC
        """, (from_user_id, local_user_id)).fetchall()
        return [dict(r) for r in rows]

    def get_unread_count(self, local_user_id, from_user_id):
        """Retorna contagem de mensagens não lidas de um peer."""
        row = self.conn.execute("""
            SELECT COUNT(*) as cnt FROM messages
            WHERE from_user=? AND to_user=? AND is_read=0
        """, (from_user_id, local_user_id)).fetchone()
        return row['cnt'] if row else 0

    def mark_as_read(self, local_user_id, from_user_id):
        """Marca todas as mensagens de um peer como lidas."""
        self.conn.execute("""
            UPDATE messages SET is_read=1
            WHERE from_user=? AND to_user=? AND is_read=0
        """, (from_user_id, local_user_id))
        self.conn.commit()

    def search_messages(self, query, limit=500):
        """Busca mensagens por texto (LIKE %query%).

        Retorna até 500 resultados mais recentes.
        """
        rows = self.conn.execute("""
            SELECT * FROM messages
            WHERE content LIKE ?
            ORDER BY timestamp DESC LIMIT ?
        """, (f'%{query}%', limit)).fetchall()
        return [dict(r) for r in rows]

    def get_history_contacts(self):
        """Retorna peers com quem houve conversa, com data da última msg.

        Usado na tela de Histórico para listar contatos com conversas.
        """
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
        """Retorna mensagens com um peer, com filtros opcionais.

        Args:
            local_user: user_id do usuário local
            peer_id: user_id do peer
            date_from: Timestamp mínimo (filtro data início)
            date_to: Timestamp máximo (filtro data fim)
            search_text: Texto para buscar no conteúdo
        """
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

        sql += " ORDER BY timestamp ASC"  # Ordem cronológica
        rows = self.conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    # ========================================
    # FILE TRANSFERS — Transferências de arquivos
    # ========================================

    def save_file_transfer(self, file_id, from_user, to_user,
                           filename, filesize, filepath=''):
        """Registra uma transferência de arquivo no banco."""
        self.conn.execute("""
            INSERT OR REPLACE INTO file_transfers
                (file_id, from_user, to_user, filename, filepath, filesize, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (file_id, from_user, to_user, filename, filepath, filesize, time.time()))
        self.conn.commit()

    def update_file_transfer(self, file_id, **kwargs):
        """Atualiza campos arbitrários de uma transferência.

        Usa **kwargs para flexibilidade (ex: status='completed', progress=100)
        """
        sets = ', '.join(f"{k}=?" for k in kwargs)  # Monta SET k1=?, k2=?
        vals = list(kwargs.values()) + [file_id]  # Valores + WHERE file_id
        self.conn.execute(
            f"UPDATE file_transfers SET {sets} WHERE file_id=?", vals)
        self.conn.commit()

    # ========================================
    # GROUPS — Grupos de chat
    # ========================================

    def save_group(self, group_id, name, group_type='temp'):
        """Salva ou atualiza um grupo no banco.

        Apenas grupos fixos são persistidos no DB.
        Temporários existem somente em memória (messenger._groups).
        """
        self.conn.execute("""
            INSERT OR REPLACE INTO groups (group_id, name, group_type, created_at)
            VALUES (?, ?, ?, ?)
        """, (group_id, name, group_type, time.time()))
        self.conn.commit()

    def get_groups(self, group_type=None):
        """Retorna lista de grupos, filtrados por tipo se especificado."""
        if group_type:
            rows = self.conn.execute(
                "SELECT * FROM groups WHERE group_type=? ORDER BY created_at DESC",
                (group_type,)).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM groups ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]

    def delete_group(self, group_id):
        """Remove um grupo do banco (CASCADE deleta membros também)."""
        self.conn.execute("DELETE FROM groups WHERE group_id=?", (group_id,))
        self.conn.commit()

    def save_group_member(self, group_id, uid, display_name, ip=''):
        """Adiciona ou atualiza um membro em um grupo."""
        self.conn.execute("""
            INSERT OR REPLACE INTO group_members (group_id, uid, display_name, ip)
            VALUES (?, ?, ?, ?)
        """, (group_id, uid, display_name, ip))
        self.conn.commit()

    def get_group_members(self, group_id):
        """Retorna lista de membros de um grupo."""
        rows = self.conn.execute(
            "SELECT * FROM group_members WHERE group_id=?",
            (group_id,)).fetchall()
        return [dict(r) for r in rows]

    def delete_group_member(self, group_id, uid):
        """Remove um membro de um grupo."""
        self.conn.execute(
            "DELETE FROM group_members WHERE group_id=? AND uid=?",
            (group_id, uid))
        self.conn.commit()

    # ========================================
    # SETTINGS — Configurações chave-valor
    # ========================================

    def get_setting(self, key, default=None):
        """Lê uma configuração pelo nome. Retorna default se não existe."""
        row = self.conn.execute(
            "SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row['value'] if row else default

    def set_setting(self, key, value):
        """Salva uma configuração (cria ou atualiza)."""
        self.conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, str(value)))  # Sempre converte para string
        self.conn.commit()

    def close(self):
        """Fecha a conexão da thread atual."""
        if hasattr(self._local, 'conn') and self._local.conn:
            self._local.conn.close()
            self._local.conn = None
