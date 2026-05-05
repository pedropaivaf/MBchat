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
import getpass    # Username Windows para migracao de user_id
import calendar as _cal_mod
from datetime import datetime as _dt, timedelta as _td
from pathlib import Path  # Manipulação moderna de caminhos


def _compute_next_occurrence(last_ts, rule, now_ts):
    # rule: {"type":"daily|weekly|monthly|yearly","interval":N,
    #        "weekdays":[0..6] (weekly, 0=Seg),
    #        "end":{"kind":"never|count|date","count":N,"date":ts},
    #        "occurrences_done":N}
    kind = rule.get('type', 'daily')
    interval = max(1, int(rule.get('interval', 1)))
    end = rule.get('end', {'kind': 'never'})
    end_kind = end.get('kind', 'never')
    done = int(rule.get('occurrences_done', 0)) + 1  # a que acabou de disparar
    if end_kind == 'count' and done >= int(end.get('count', 0)):
        return None
    last_dt = _dt.fromtimestamp(last_ts)
    if kind == 'daily':
        next_dt = last_dt + _td(days=interval)
    elif kind == 'weekly':
        weekdays = sorted(set(int(w) for w in rule.get('weekdays', [last_dt.weekday()])))
        if not weekdays:
            weekdays = [last_dt.weekday()]
        # Proxima ocorrencia: busca o proximo weekday na lista, avancando dia a dia;
        # se chegar a uma nova semana sem dias remanescentes, pula (interval-1) semanas.
        cur = last_dt + _td(days=1)
        week_start = last_dt - _td(days=last_dt.weekday())
        found = None
        for _ in range(7 * (interval + 1)):
            if cur.weekday() in weekdays:
                cur_week_start = cur - _td(days=cur.weekday())
                weeks_diff = (cur_week_start.date() - week_start.date()).days // 7
                if weeks_diff == 0 or weeks_diff >= interval:
                    found = cur
                    break
            cur += _td(days=1)
        next_dt = found or (last_dt + _td(days=7 * interval))
    elif kind == 'monthly':
        y, m = last_dt.year, last_dt.month + interval
        while m > 12:
            m -= 12
            y += 1
        day = min(last_dt.day, _cal_mod.monthrange(y, m)[1])
        next_dt = last_dt.replace(year=y, month=m, day=day)
    elif kind == 'yearly':
        y = last_dt.year + interval
        try:
            next_dt = last_dt.replace(year=y)
        except ValueError:
            next_dt = last_dt.replace(year=y, day=28)
    else:
        return None
    next_ts = next_dt.timestamp()
    if end_kind == 'date' and next_ts > float(end.get('date', 0)):
        return None
    return next_ts


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

        # Migration: file_path em messages (clique no chat abre a pasta do arquivo)
        try:
            c.execute("ALTER TABLE messages ADD COLUMN file_path TEXT DEFAULT ''")
            c.commit()
        except Exception:
            pass

        # Migration: department e private_note em contacts
        for col in ('department', 'private_note', 'ramal', 'winuser'):
            try:
                c.execute(f"ALTER TABLE contacts ADD COLUMN {col} TEXT DEFAULT ''")
                c.commit()
            except Exception:
                pass

        # Migration: ramal em local_user
        try:
            c.execute("ALTER TABLE local_user ADD COLUMN ramal TEXT DEFAULT ''")
            c.commit()
        except Exception:
            pass

        # Migration: completed em reminders
        try:
            c.execute("ALTER TABLE reminders ADD COLUMN completed INTEGER DEFAULT 0")
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
                completed INTEGER DEFAULT 0,
                created_at REAL NOT NULL
            );
        """)
        c.commit()
        # Migracao: colunas para lembretes recorrentes
        for col, default in [('is_recurring', '0'), ('recurrence_interval_seconds', '0'), ('is_active', '1')]:
            try:
                c.execute(f"ALTER TABLE reminders ADD COLUMN {col} INTEGER DEFAULT {default}")
                c.commit()
            except Exception:
                pass  # coluna ja existe
        # Migracao: regra de recorrencia baseada em padrao (JSON: daily/weekly/monthly/yearly)
        try:
            c.execute("ALTER TABLE reminders ADD COLUMN recurrence_rule TEXT DEFAULT ''")
            c.commit()
        except Exception:
            pass

        # Migracoes para lembretes compartilhados (Pessoal vs Compartilhado).
        # Aditivas: lembretes existentes (Pessoal) ficam com creator_uid='' e
        # status='active' por default — comportamento intocado.
        for _col, _default in [
            ('creator_uid', "''"),       # uid do criador (vazio = lembrete pessoal local)
            ('external_id', "''"),       # UUID cross-machine para identificar lembrete em todos os peers
            ('invited_uids', "''"),      # JSON array de uids convidados
            ('accepted_uids', "''"),     # JSON array de uids que aceitaram
            ('share_status', "'active'"),  # 'active' (pessoal/aceito) | 'pending_accept' (convite recebido) | 'declined'
            ('creator_name', "''"),      # nome cacheado do criador (para exibir convite mesmo se peer offline)
        ]:
            try:
                c.execute(f"ALTER TABLE reminders ADD COLUMN {_col} TEXT DEFAULT {_default}")
                c.commit()
            except Exception:
                pass

        # Tabela de peers manuais (VPN/fora-da-LAN). Lista vazia = no-op.
        # Aditivo: nao afeta os 28+ usuarios na LAN local.
        c.executescript("""
            CREATE TABLE IF NOT EXISTS manual_peers (
                ip TEXT PRIMARY KEY,
                note TEXT DEFAULT '',
                created_at REAL NOT NULL
            );
        """)
        c.commit()

    # ========================================
    # LOCAL USER — Dados do usuário local
    # ========================================

    # Renomeia um user_id em todas as tabelas que tem referencias a usuarios.
    # Usado tanto pela migracao do local_user (mac_host -> mac_host_winuser)
    # quanto pelo merge de contatos quando um peer atualiza.
    def _rename_user_id_everywhere(self, old_uid, new_uid):
        if not old_uid or not new_uid or old_uid == new_uid:
            return
        c = self.conn
        try:
            # local_user
            try:
                c.execute("UPDATE local_user SET user_id=? WHERE user_id=?",
                          (new_uid, old_uid))
            except Exception:
                pass
            # contacts: se ja existe entry para new_uid, deletar a antiga
            # (preservando ip/last_seen/note do mais recente). Senao, renomeia.
            try:
                row_new = c.execute(
                    "SELECT 1 FROM contacts WHERE user_id=?", (new_uid,)
                ).fetchone()
                if row_new:
                    c.execute("DELETE FROM contacts WHERE user_id=?", (old_uid,))
                else:
                    c.execute(
                        "UPDATE contacts SET user_id=? WHERE user_id=?",
                        (new_uid, old_uid)
                    )
            except Exception:
                pass
            # messages
            try:
                c.execute("UPDATE messages SET from_user=? WHERE from_user=?",
                          (new_uid, old_uid))
                c.execute("UPDATE messages SET to_user=? WHERE to_user=?",
                          (new_uid, old_uid))
            except Exception:
                pass
            # file_transfers
            try:
                c.execute("UPDATE file_transfers SET from_user=? WHERE from_user=?",
                          (new_uid, old_uid))
                c.execute("UPDATE file_transfers SET to_user=? WHERE to_user=?",
                          (new_uid, old_uid))
            except Exception:
                pass
            # group_members: se ja existe (group_id, new_uid) na PK, apaga old
            try:
                rows = c.execute(
                    "SELECT group_id FROM group_members WHERE uid=?", (old_uid,)
                ).fetchall()
                for r in rows:
                    gid = r['group_id']
                    exist = c.execute(
                        "SELECT 1 FROM group_members WHERE group_id=? AND uid=?",
                        (gid, new_uid)
                    ).fetchone()
                    if exist:
                        c.execute(
                            "DELETE FROM group_members WHERE group_id=? AND uid=?",
                            (gid, old_uid)
                        )
                    else:
                        c.execute(
                            "UPDATE group_members SET uid=? WHERE group_id=? AND uid=?",
                            (new_uid, gid, old_uid)
                        )
            except Exception:
                pass
            # polls / poll_votes
            try:
                c.execute("UPDATE polls SET creator_uid=? WHERE creator_uid=?",
                          (new_uid, old_uid))
            except Exception:
                pass
            try:
                rows = c.execute(
                    "SELECT poll_id FROM poll_votes WHERE voter_uid=?", (old_uid,)
                ).fetchall()
                for r in rows:
                    pid = r['poll_id']
                    exist = c.execute(
                        "SELECT 1 FROM poll_votes WHERE poll_id=? AND voter_uid=?",
                        (pid, new_uid)
                    ).fetchone()
                    if exist:
                        c.execute(
                            "DELETE FROM poll_votes WHERE poll_id=? AND voter_uid=?",
                            (pid, old_uid)
                        )
                    else:
                        c.execute(
                            "UPDATE poll_votes SET voter_uid=? WHERE poll_id=? AND voter_uid=?",
                            (new_uid, pid, old_uid)
                        )
            except Exception:
                pass
            c.commit()
        except Exception:
            pass

    # Migra user_id do local_user de versoes antigas (mac_host, sem winuser)
    # para o formato atual (mac_host_winuser). Sem essa migracao, mensagens,
    # contatos e grupos ficam orfaos pos-update porque a query usa o NOVO
    # user_id mas os dados estao gravados com o ANTIGO.
    # Idempotente: se ja esta no formato novo, nao faz nada.
    # Cobre dois cenarios:
    #  (a) v1.4.59 -> v1.4.61: local_user tem mac_host, novo e mac_host_win.
    #      Renomeia local_user + mensagens + grupos.
    #  (b) v1.4.60 -> v1.4.61: local_user ja tem mac_host_win, MAS mensagens
    #      antigas ficaram com from/to=mac_host (v1.4.60 nao migrou). Detecta
    #      orfas e renomeia.
    def migrate_user_ids_add_winuser_suffix(self, new_uid):
        try:
            row = self.conn.execute(
                "SELECT user_id FROM local_user WHERE id=1"
            ).fetchone()
            if not row:
                return
            stored = row['user_id']
            # Caso (a): local_user no formato antigo
            if stored != new_uid and new_uid.startswith(stored + '_'):
                self._rename_user_id_everywhere(stored, new_uid)
                return
            # Caso (b): local_user ja no formato novo, mas mensagens/grupos
            # antigos podem ter referencias ao formato sem suffix. Usa o
            # getpass.getuser() atual para descobrir qual sufixo remover
            # (assim username com underscore tipo "pedro_paiva" funciona).
            if stored == new_uid:
                try:
                    winuser = (getpass.getuser() or '').strip()
                except Exception:
                    winuser = ''
                if winuser and new_uid.endswith('_' + winuser):
                    old_uid = new_uid[:-(len(winuser) + 1)]
                    if old_uid and old_uid != new_uid:
                        # So renomeia se houver pelo menos uma orfa para evitar
                        # falsos positivos (hostname com underscore proprio)
                        has_orphan = False
                        for q in (
                            "SELECT 1 FROM messages WHERE from_user=? LIMIT 1",
                            "SELECT 1 FROM messages WHERE to_user=? LIMIT 1",
                            "SELECT 1 FROM file_transfers WHERE from_user=? LIMIT 1",
                            "SELECT 1 FROM file_transfers WHERE to_user=? LIMIT 1",
                            "SELECT 1 FROM group_members WHERE uid=? LIMIT 1",
                        ):
                            try:
                                r = self.conn.execute(q, (old_uid,)).fetchone()
                                if r:
                                    has_orphan = True
                                    break
                            except Exception:
                                pass
                        if has_orphan:
                            self._rename_user_id_everywhere(old_uid, new_uid)
        except Exception:
            pass

    # Quando um peer anuncia com user_id no formato novo (mac_host_winuser)
    # e ja temos um contato no formato antigo (mac_host) sem o suffix, faz
    # merge: renomeia todas as referencias do antigo para o novo. Roda em
    # _on_peer_found do Messenger. peer_winuser vem do announce do peer.
    def merge_legacy_contact(self, new_uid, peer_winuser=''):
        try:
            if not new_uid or not peer_winuser:
                return
            tail = '_' + peer_winuser
            if not new_uid.endswith(tail):
                return
            old_uid = new_uid[:-len(tail)]
            if not old_uid or old_uid == new_uid:
                return
            row = self.conn.execute(
                "SELECT 1 FROM contacts WHERE user_id=?", (old_uid,)
            ).fetchone()
            if not row:
                return
            self._rename_user_id_everywhere(old_uid, new_uid)
        except Exception:
            pass

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

    # Atualiza ramal (4 dígitos) do usuário local
    def update_local_ramal(self, ramal):
        self.conn.execute(
            "UPDATE local_user SET ramal=?, updated_at=? WHERE id=1",
            (ramal, time.time()))
        self.conn.commit()

    # Retorna ramal do usuário local (string vazia se não tem)
    def get_local_ramal(self):
        try:
            row = self.conn.execute(
                "SELECT ramal FROM local_user WHERE id=1").fetchone()
            return row['ramal'] if row and row['ramal'] else ''
        except Exception:
            return ''

    # ========================================
    # CONTACTS — Peers descobertos na rede
    # ========================================

    # Insere ou atualiza contato (chamado pelo discovery quando peer é encontrado)
    # UPSERT: cria novos e atualiza existentes. Não atualiza first_seen em updates
    def upsert_contact(self, user_id, display_name, ip_address,
                       hostname='', os_info='', status='online', note='',
                       avatar_index=0, avatar_data='', winuser=''):
        now = time.time()
        self.conn.execute("""
            INSERT INTO contacts (user_id, display_name, ip_address, hostname,
                                  os_info, status, note, avatar_index,
                                  avatar_data, winuser, last_seen, first_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                display_name=excluded.display_name,
                ip_address=excluded.ip_address,
                hostname=excluded.hostname,
                os_info=excluded.os_info,
                status=excluded.status,
                note=excluded.note,
                avatar_index=excluded.avatar_index,
                avatar_data=excluded.avatar_data,
                winuser=excluded.winuser,
                last_seen=excluded.last_seen
        """, (user_id, display_name, ip_address, hostname, os_info, status,
              note, avatar_index, avatar_data, winuser or '', now, now))
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

    # Tenta descobrir o nome de um usuario buscando em todas as tabelas (contacts, group_members)
    # Útil para resolver nomes no histórico de usuários que não estão na lista de contatos principal.
    def find_user_name(self, uid):
        try:
            # 1. Tabela de contatos principal
            row = self.conn.execute(
                "SELECT display_name FROM contacts WHERE user_id=?", (uid,)
            ).fetchone()
            if row and row['display_name']:
                return row['display_name']
            
            # 2. Tabela de membros de grupos (caso seja alguém que só falou em grupos)
            row = self.conn.execute(
                "SELECT display_name FROM group_members WHERE uid=? LIMIT 1", (uid,)
            ).fetchone()
            if row and row['display_name']:
                return row['display_name']
        except Exception:
            pass
        return None

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

    # Busca global em todas as mensagens com filtros opcionais.
    # limit=None retorna tudo (sem limite) — usado no Historico para garantir que mensagens antigas nao sumam.
    def search_all_messages(self, search_text=None, date_from=None, date_to=None, limit=5000):
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
        sql += " ORDER BY timestamp DESC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        rows = self.conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    # Retorna set de peer_ids que tem mensagens batendo com os filtros (busca por palavra/data).
    # Usa DISTINCT — rapido mesmo em DBs com 100k+ mensagens. Usado pelo Historico para
    # popular a lista de contatos filtrados sem precisar carregar todas as mensagens na memoria.
    def get_peers_with_match(self, search_text=None, date_from=None, date_to=None):
        sql = """
            SELECT DISTINCT CASE WHEN is_sent=1 THEN to_user ELSE from_user END as peer
            FROM messages
            WHERE 1=1
        """
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
        rows = self.conn.execute(sql, params).fetchall()
        return {r[0] for r in rows}

    # Retorna total de mensagens que batem com os filtros. Leve (COUNT no SQL, nao traz rows).
    def count_matching_messages(self, search_text=None, date_from=None, date_to=None):
        sql = "SELECT COUNT(*) FROM messages WHERE 1=1"
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
        row = self.conn.execute(sql, params).fetchone()
        return row[0] if row else 0

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
    # GROUP MESSAGES — Historico de mensagens de grupo
    # ========================================
    # Reusa a tabela messages com a convencao to_user='group:GROUP_ID'.
    # Evita criar nova tabela e mantem schema existente. msg_type pode ser
    # 'text' ou 'image'. from_user = uid do remetente (proprio uid se enviada).

    # Salva uma mensagem de grupo no historico local. group_id sem prefixo.
    def save_group_message(self, group_id, msg_id, from_user, content,
                           sender_name='', msg_type='text',
                           is_sent=False, timestamp=None,
                           reply_to_id=''):
        ts = timestamp or time.time()
        # Codifica nome do remetente no campo file_path (string livre, vazio
        # por default) para nao depender da tabela contacts ao reabrir grupo
        # — peer pode ter saido ou ainda nao ter sido descoberto.
        self.conn.execute("""
            INSERT INTO messages (msg_id, from_user, to_user, content,
                                  msg_type, timestamp, is_sent, reply_to_id,
                                  file_path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (msg_id, from_user, f'group:{group_id}', content, msg_type, ts,
              int(is_sent), reply_to_id or '', sender_name or ''))
        self.conn.commit()

    # Retorna historico completo de um grupo em ordem cronologica ASC.
    def get_group_history(self, group_id, limit=None):
        target = f'group:{group_id}'
        if limit is not None:
            rows = self.conn.execute("""
                SELECT * FROM messages WHERE to_user=?
                ORDER BY timestamp DESC LIMIT ?
            """, (target, limit)).fetchall()
            return [dict(r) for r in reversed(rows)]
        rows = self.conn.execute("""
            SELECT * FROM messages WHERE to_user=?
            ORDER BY timestamp ASC
        """, (target,)).fetchall()
        return [dict(r) for r in rows]

    # Idempotencia: verifica se um msg_id de grupo ja existe (evita dup)
    def has_group_message(self, msg_id):
        if not msg_id:
            return False
        row = self.conn.execute(
            "SELECT 1 FROM messages WHERE msg_id=? LIMIT 1",
            (msg_id,)).fetchone()
        return row is not None

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
                     reply_to_id='', file_path=''):
        ts = timestamp or time.time()
        self.conn.execute("""
            INSERT INTO messages (msg_id, from_user, to_user, content,
                                  msg_type, timestamp, is_sent, reply_to_id,
                                  file_path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (msg_id, from_user, to_user, content, msg_type, ts,
              int(is_sent), reply_to_id or '', file_path or ''))
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

    def set_contact_ramal(self, user_id, ramal):
        self.conn.execute(
            "UPDATE contacts SET ramal=? WHERE user_id=?",
            (ramal, user_id))
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

    def add_reminder(self, text, remind_at=0):
        self.conn.execute("""
            INSERT INTO reminders (text, remind_at, created_at, notified)
            VALUES (?, ?, ?, ?)
        """, (text, remind_at, time.time(), 1 if remind_at == 0 else 0))
        self.conn.commit()

    def add_recurring_reminder(self, text, interval_seconds):
        now = time.time()
        self.conn.execute("""
            INSERT INTO reminders (text, remind_at, created_at, notified,
                                   is_recurring, recurrence_interval_seconds, is_active)
            VALUES (?, ?, ?, 0, 1, ?, 1)
        """, (text, now + interval_seconds, now, interval_seconds))
        self.conn.commit()

    def add_pattern_reminder(self, text, start_ts, rule_json):
        self.conn.execute("""
            INSERT INTO reminders (text, remind_at, created_at, notified,
                                   is_recurring, recurrence_interval_seconds,
                                   is_active, recurrence_rule)
            VALUES (?, ?, ?, 0, 1, 0, 1, ?)
        """, (text, start_ts, time.time(), rule_json))
        self.conn.commit()

    def reschedule_recurring_reminder(self, reminder_id):
        row = self.conn.execute(
            "SELECT remind_at, recurrence_interval_seconds, recurrence_rule FROM reminders WHERE id=?",
            (reminder_id,)).fetchone()
        if not row:
            return
        rule_json = row['recurrence_rule'] if 'recurrence_rule' in row.keys() else ''
        now = time.time()
        if rule_json:
            import json as _json
            from datetime import datetime as _dt
            try:
                rule = _json.loads(rule_json)
            except Exception:
                rule = {}
            next_at = _compute_next_occurrence(row['remind_at'], rule, now)
            if next_at is None:
                # Sem proximas ocorrencias: desativa
                self.conn.execute(
                    "UPDATE reminders SET is_active=0, notified=1 WHERE id=?",
                    (reminder_id,))
                self.conn.commit()
                return
            rule['occurrences_done'] = int(rule.get('occurrences_done', 0)) + 1
            self.conn.execute(
                "UPDATE reminders SET remind_at=?, notified=0, recurrence_rule=? WHERE id=?",
                (next_at, _json.dumps(rule), reminder_id))
            self.conn.commit()
            return
        interval = row['recurrence_interval_seconds']
        if not interval:
            return
        next_at = row['remind_at'] + interval
        while next_at <= now:
            next_at += interval
        self.conn.execute(
            "UPDATE reminders SET remind_at=?, notified=0 WHERE id=?",
            (next_at, reminder_id))
        self.conn.commit()

    def toggle_reminder_active(self, reminder_id):
        row = self.conn.execute(
            "SELECT is_active FROM reminders WHERE id=?",
            (reminder_id,)).fetchone()
        if row:
            new_val = 0 if row['is_active'] else 1
            self.conn.execute(
                "UPDATE reminders SET is_active=? WHERE id=?",
                (new_val, reminder_id))
            if new_val == 1:
                # Reagenda para o proximo intervalo futuro ao reativar
                self.reschedule_recurring_reminder(reminder_id)
            self.conn.commit()

    def get_pending_reminders(self):
        now = time.time()
        # Lembretes 'pending_accept' (convites nao aceitos) nao disparam.
        # Declined idem. Apenas 'active' ou compatibilidade com lembretes
        # antigos (share_status NULL/vazio = pessoal antigo, dispara).
        rows = self.conn.execute("""
            SELECT * FROM reminders
            WHERE notified=0 AND remind_at > 0 AND remind_at <= ?
              AND (is_recurring=0 OR is_active=1)
              AND (share_status IS NULL OR share_status='' OR share_status='active')
            ORDER BY remind_at ASC
        """, (now,)).fetchall()
        return [dict(r) for r in rows]

    def get_all_reminders(self):
        # Pendentes: nao concluidos. Normais (remind_at=0) primeiro, depois por data.
        # Inclui invites (share_status='pending_accept') no topo para o usuario
        # ver e poder aceitar/recusar.
        rows = self.conn.execute("""
            SELECT * FROM reminders WHERE completed=0
            ORDER BY (CASE WHEN share_status='pending_accept' THEN 0
                           WHEN remind_at=0 THEN 1 ELSE 2 END),
                     remind_at ASC
        """).fetchall()
        return [dict(r) for r in rows]

    def get_completed_reminders(self):
        # Concluidos nas ultimas 24h (normais usam created_at como referencia)
        cutoff = time.time() - 86400
        rows = self.conn.execute("""
            SELECT * FROM reminders WHERE completed=1
            AND (CASE WHEN remind_at=0 THEN created_at ELSE remind_at END) >= ?
            ORDER BY created_at DESC
        """, (cutoff,)).fetchall()
        return [dict(r) for r in rows]

    def mark_reminder_notified(self, reminder_id):
        self.conn.execute(
            "UPDATE reminders SET notified=1 WHERE id=?", (reminder_id,))
        self.conn.commit()

    def mark_reminder_completed(self, reminder_id):
        self.conn.execute(
            "UPDATE reminders SET completed=1 WHERE id=?", (reminder_id,))
        self.conn.commit()

    def delete_reminder(self, reminder_id):
        self.conn.execute(
            "DELETE FROM reminders WHERE id=?", (reminder_id,))
        self.conn.commit()

    # ========================================
    # SHARED REMINDERS — Lembretes compartilhados
    # ========================================
    # Cenario: Pedro cria um lembrete e marca @iuri. Iuri recebe convite,
    # pode aceitar/recusar. Apos aceitar, ambos recebem notificacao no horario.
    # external_id (UUID) identifica o mesmo lembrete em todas as maquinas.

    def add_shared_reminder(self, text, remind_at, creator_uid, creator_name='',
                            external_id='', invited_uids=None,
                            recurrence_rule='', recurrence_interval_seconds=0,
                            share_status='active'):
        import json as _json, uuid as _uuid
        if not external_id:
            external_id = _uuid.uuid4().hex
        invited_json = _json.dumps(invited_uids or [], ensure_ascii=False)
        accepted_json = _json.dumps([], ensure_ascii=False)
        is_recurring = 1 if (recurrence_rule or recurrence_interval_seconds) else 0
        is_active = 1
        # Se ainda nao foi notificado: notified=0
        notified = 0 if remind_at and remind_at > 0 else 1
        self.conn.execute("""
            INSERT INTO reminders
                (text, remind_at, created_at, notified, completed,
                 is_recurring, recurrence_interval_seconds, is_active,
                 recurrence_rule, creator_uid, external_id,
                 invited_uids, accepted_uids, share_status, creator_name)
            VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (text, remind_at, time.time(), notified,
              is_recurring, recurrence_interval_seconds, is_active,
              recurrence_rule, creator_uid, external_id,
              invited_json, accepted_json, share_status, creator_name))
        self.conn.commit()
        return external_id

    def get_reminder_by_external_id(self, external_id):
        if not external_id:
            return None
        try:
            row = self.conn.execute(
                "SELECT * FROM reminders WHERE external_id=? LIMIT 1",
                (external_id,)).fetchone()
            return dict(row) if row else None
        except Exception:
            return None

    def update_reminder_share_status(self, external_id, share_status):
        try:
            self.conn.execute(
                "UPDATE reminders SET share_status=? WHERE external_id=?",
                (share_status, external_id))
            self.conn.commit()
        except Exception:
            pass

    # Adiciona um uid a accepted_uids (para o criador rastrear quem aceitou).
    def mark_reminder_accepted(self, external_id, uid):
        import json as _json
        try:
            row = self.conn.execute(
                "SELECT accepted_uids FROM reminders WHERE external_id=?",
                (external_id,)).fetchone()
            if not row:
                return
            try:
                lst = _json.loads(row['accepted_uids'] or '[]')
            except Exception:
                lst = []
            if uid not in lst:
                lst.append(uid)
            self.conn.execute(
                "UPDATE reminders SET accepted_uids=? WHERE external_id=?",
                (_json.dumps(lst, ensure_ascii=False), external_id))
            self.conn.commit()
        except Exception:
            pass

    # Lista lembretes pendentes de aceitar (recebidos como convite).
    def get_pending_invites(self):
        try:
            rows = self.conn.execute("""
                SELECT * FROM reminders
                WHERE share_status='pending_accept' AND completed=0
                ORDER BY created_at DESC
            """).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

    # ========================================
    # MANUAL PEERS — VPN / fora-da-LAN
    # ========================================
    # Lista de IPs manualmente cadastrados para receber announce UDP unicast.
    # Usado quando o discovery normal (multicast/broadcast) nao funciona, tipico
    # de cenario VPN/home-office onde tunel L3 nao propaga multicast/broadcast.
    # Lista vazia = comportamento default da LAN (zero overhead).

    def add_manual_peer(self, ip, note=''):
        ip = (ip or '').strip()
        if not ip:
            return False
        self.conn.execute("""
            INSERT OR REPLACE INTO manual_peers (ip, note, created_at)
            VALUES (?, ?, ?)
        """, (ip, note or '', time.time()))
        self.conn.commit()
        return True

    def remove_manual_peer(self, ip):
        self.conn.execute("DELETE FROM manual_peers WHERE ip=?", ((ip or '').strip(),))
        self.conn.commit()

    def get_manual_peers(self):
        try:
            rows = self.conn.execute(
                "SELECT * FROM manual_peers ORDER BY created_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

    # Fecha conexão da thread atual
    def close(self):
        if hasattr(self._local, 'conn') and self._local.conn:
            self._local.conn.close()
            self._local.conn = None
