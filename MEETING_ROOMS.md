# Reserva de Salas — Plano de Implementação Futura

> Status: **Planejado** — não implementado. Pronto para execução quando priorizado.
> Planejado em: 2026-05-06

---

## Visão Geral

Módulo de reserva de salas de reunião integrado ao MB Chat LAN. Permite que os 30+ usuários visualizem disponibilidade em tempo real (3 salas: Vidro, MB, Certificado), criem reservas, convites e recebam notificações — tudo persistido em SQLite local e sincronizado via TCP com a mesma arquitetura do sistema de reminders existente.

---

## Arquivos Modificados / Criados

| Arquivo | Tipo | Estimativa |
|---------|------|-----------|
| `database.py` | Modificado | +130 linhas |
| `network.py` | Modificado | +35 linhas |
| `messenger.py` | Modificado | +180 linhas |
| `meeting_gui.py` | **Novo** | ~900 linhas |
| `gui.py` | Modificado | +230 linhas |

---

## Fase 1 — database.py

### Novas tabelas (inserir em `_init_db`, antes dos índices)

```sql
CREATE TABLE IF NOT EXISTS rooms (
    id   INTEGER PRIMARY KEY,
    name TEXT    NOT NULL
);
-- Seed estático: 1=Sala de Vidro, 2=Sala MB, 3=Certificado
-- Inserido via INSERT OR IGNORE após CREATE

CREATE TABLE IF NOT EXISTS bookings (
    booking_id   TEXT PRIMARY KEY,          -- UUID v4
    room_id      INTEGER NOT NULL,
    title        TEXT    NOT NULL,
    creator_uid  TEXT    NOT NULL,
    creator_name TEXT    NOT NULL,
    start_ts     REAL    NOT NULL,          -- Unix float
    end_ts       REAL    NOT NULL,
    created_at   REAL    NOT NULL,
    updated_at   REAL    NOT NULL,          -- Last Write Wins key
    is_deleted   INTEGER DEFAULT 0,         -- soft delete
    status       TEXT    DEFAULT 'pending', -- pending|confirmed|cancelled|local_only
    FOREIGN KEY(room_id) REFERENCES rooms(id)
);

CREATE TABLE IF NOT EXISTS participants (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    booking_id   TEXT NOT NULL,
    uid          TEXT NOT NULL,
    display_name TEXT NOT NULL,
    response     TEXT DEFAULT 'pending',    -- pending|accepted|declined
    FOREIGN KEY(booking_id) REFERENCES bookings(booking_id) ON DELETE CASCADE,
    UNIQUE(booking_id, uid)
);
```

### Índice de performance
```sql
CREATE INDEX IF NOT EXISTS idx_bookings_room_time ON bookings(room_id, start_ts, end_ts);
```

### Novos métodos em `Database`

- `get_rooms()` → lista de dicts `{id, name}`
- `save_booking(booking_id, room_id, title, creator_uid, creator_name, start_ts, end_ts, status='pending')` → INSERT OR REPLACE, sets `created_at`/`updated_at = time.time()`
- `update_booking_status(booking_id, status, updated_at=None)` → UPDATE com `updated_at = now`
- `soft_delete_booking(booking_id)` → `is_deleted=1, updated_at=now`
- `get_bookings(date_from=None, date_to=None)` → retorna bookings não deletados no intervalo
- `get_booking(booking_id)` → único booking
- `get_all_bookings_for_sync()` → todos (inclusive deletados) para sync delta
- `save_participant(booking_id, uid, display_name, response='pending')` → INSERT OR REPLACE
- `update_participant_response(booking_id, uid, response)` → UPDATE
- `get_participants(booking_id)` → lista de dicts
- `has_conflict(room_id, start_ts, end_ts, exclude_booking_id=None)` → bool; SQL: `start_ts < end_ts_arg AND end_ts > start_ts_arg AND is_deleted=0 AND status NOT IN ('cancelled')`
- `get_confirmed_count(booking_id)` → COUNT accepted

---

## Fase 2 — network.py

### Novos MT_ constants (após linha 206, bloco existente)

```python
MT_MEETING_INVITE   = 'meeting_invite'    # TCP: convite de reunião
MT_MEETING_ACCEPT   = 'meeting_accept'    # TCP: aceitou convite
MT_MEETING_DECLINE  = 'meeting_decline'   # TCP: recusou convite
MT_MEETING_CANCEL   = 'meeting_cancel'    # TCP: criador cancelou
MT_MEETING_SYNC_REQ = 'meeting_sync_req'  # TCP: pedido de sync ao reconectar
MT_MEETING_SYNC_RES = 'meeting_sync_res'  # TCP: dump de bookings como resposta
```

### Roteamento em `TCPServer._process_message()`

Adicionar ao bloco de `elif msg_type == ...` (padrão existente linha ~993):

```python
elif msg_type in (MT_MEETING_INVITE, MT_MEETING_ACCEPT, MT_MEETING_DECLINE,
                  MT_MEETING_CANCEL, MT_MEETING_SYNC_REQ, MT_MEETING_SYNC_RES):
    if self.on_message:
        self.on_message(msg, addr)
```

Nenhuma nova porta — tudo via TCP 50101 existente.

---

## Fase 3 — messenger.py

### Novos callbacks no `__init__`

```python
on_meeting_invite=None,
on_meeting_response=None,   # accept/decline
on_meeting_cancel=None,
on_meeting_sync=None,       # GUI redraws timegrid
```

### Novos métodos públicos

**`create_meeting(room_id, title, start_ts, end_ts, participant_uids)`**
1. Gera `booking_id = str(uuid.uuid4())`
2. Verifica conflito local via `db.has_conflict()`; se houver, retorna `{'error': 'conflict'}`
3. `db.save_booking(...)` com `status='pending'`
4. `db.save_participant(booking_id, self.user_id, self.display_name, 'accepted')` — criador auto-aceita
5. Para cada uid em participant_uids: `db.save_participant(booking_id, uid, name, 'pending')`
6. Envia `MT_MEETING_INVITE` via TCP a cada participante online
7. Se nenhum peer estava online: `db.update_booking_status(booking_id, 'local_only')`
8. Retorna `{'booking_id': booking_id}`

**`accept_meeting(booking_id)`**
1. `db.update_participant_response(booking_id, self.user_id, 'accepted')`
2. Envia `MT_MEETING_ACCEPT` ao creator_uid
3. Verifica `get_confirmed_count()`: se >= 2, `db.update_booking_status(booking_id, 'confirmed')`; notifica todos com `MT_MEETING_SYNC_RES` parcial
4. Cria lembrete via `db.add_reminder()` com texto formatado como card, `remind_at = start_ts - 900` (15min antes)

**`decline_meeting(booking_id)`**
1. `db.update_participant_response(booking_id, self.user_id, 'declined')`
2. Envia `MT_MEETING_DECLINE` ao creator_uid

**`cancel_meeting(booking_id)`**
1. Verifica se `self.user_id == booking['creator_uid']`; se não, retorna
2. `db.soft_delete_booking(booking_id)` + `db.update_booking_status(booking_id, 'cancelled')`
3. Envia `MT_MEETING_CANCEL` a todos os participantes online

**`sync_meetings_with_peer(peer_ip)`**
1. Envia `MT_MEETING_SYNC_REQ` via TCP ao peer
2. Peer responde com `MT_MEETING_SYNC_RES` contendo dump completo

**`_on_tcp_message()` — novos elif handlers:**

```python
elif msg_type == MT_MEETING_INVITE:
    # Salva booking + participantes no DB local (idempotente via booking_id)
    # Chama on_meeting_invite callback → GUI mostra popup

elif msg_type == MT_MEETING_ACCEPT:
    # Atualiza response do uid no DB
    # Verifica se atingiu 2 confirmados → muda status para 'confirmed'
    # Chama on_meeting_response

elif msg_type == MT_MEETING_DECLINE:
    # Atualiza response no DB
    # Chama on_meeting_response

elif msg_type == MT_MEETING_CANCEL:
    # soft_delete_booking, status='cancelled'
    # Remove lembrete associado (external_id matching)
    # Chama on_meeting_cancel

elif msg_type == MT_MEETING_SYNC_REQ:
    # Responde com dump de get_all_bookings_for_sync() via MT_MEETING_SYNC_RES

elif msg_type == MT_MEETING_SYNC_RES:
    # Last Write Wins merge:
    # Para cada booking no payload:
    #   local = db.get_booking(booking_id)
    #   if not local OR remote['updated_at'] > local['updated_at']:
    #       db.save_booking(...) + salvar participants
    # Chama on_meeting_sync → GUI.update_timegrid()
```

**`_on_peer_found()` — append:**
```python
# Peer reconectou → sincroniza reuniões pendentes
threading.Thread(target=lambda: self.sync_meetings_with_peer(peer_ip), daemon=True).start()
```

**Startup deferred (4s após init, em thread):**
- Para cada peer online em `self.discovery.get_peers()`: envia `MT_MEETING_SYNC_REQ`

**Auto-cancel check (loop a cada 60s):**
- Busca bookings com `start_ts <= time.time()` e `status='pending'`
- Se `get_confirmed_count() < 2`: chama `cancel_meeting(booking_id)` automaticamente

---

## Fase 4 — meeting_gui.py (Novo arquivo)

### Classe `MeetingWindow(tk.Toplevel)`

**Dimensões:** 1020×640, centrada

**Layout (3 zonas):**

```
┌─────────────────────────────────────────────────────────────┐
│ Header NAVY: "📅 Agendar Reunião"  [← Semana]  [Data]  [→]  │
├──────────────┬──────────────────────────────┬───────────────┤
│ LEFT 260px   │ CENTER (TimeGrid Canvas)      │ RIGHT 280px   │
│              │                               │               │
│ Formulário   │  Sala de Vidro | Sala MB | Cert│ Convites     │
│ de criação:  │  ─────────────────────────────│ pendentes     │
│  • Título    │  08:00 ░░░░░░░ ░░░░░░░ ░░░░░░░│               │
│  • Sala      │  09:00 ████... ░░░░░░░ ░░░░░░░│ [✓][✗] cada  │
│  • Data      │  10:00 ░░░░░░░ ░░░░░░░ ░░░░░░░│               │
│  • Hora ini  │  ...até 20:00                 │ ── Histórico ─│
│  • Hora fim  │                               │ Tabela de     │
│  • Partici-  │  Legenda: ▓ pendente  █ conf. │ reservas      │
│    pantes    │           ░ livre     ╳ cancel│ (busca)       │
│ [Criar Reunião]│                            │               │
└──────────────┴──────────────────────────────┴───────────────┘
```

**TimeGrid (Canvas):**
- Eixo Y: 07:00–20:00 (1px = 2min → 780px de altura, rolável)
- 3 colunas separadas por linhas verticais (uma por sala)
- Cores dos bookings:
  - Cinza `#94a3b8` = pending
  - Verde `#16a34a` = confirmed (≥2 aceitos)
  - Vermelho `#ef4444` com linha diagonal = cancelled
  - Laranja `#f59e0b` = local_only
- Click em slot vazio → preenche formulário com sala/hora
- Click em booking → abre `_show_booking_detail(booking_id)` Toplevel
- `refresh_timegrid(date)` redesenha canvas completo (thread-safe via `root.after()`)

**Formulário esquerdo:**
- Entry: título
- OptionMenu: sala (3 opções carregadas de `db.get_rooms()`)
- DatePicker: 3 Spinbox (dia/mês/ano)
- TimePicker: 2 Combobox (início e fim) com slots de 30min
- Validação: `end - start <= 10800` (3h máx), sem conflito
- Lista pesquisável de participantes (peers online via `messenger.discovery.get_peers()`)
- Botão "Criar Reunião" → `messenger.create_meeting()`

**Inbox direito:**
- Para cada booking onde `uid == me AND response == 'pending'`:
  - Card com: título, criador, data/hora, sala, participantes
  - Botão ✓ verde / ✗ vermelho
  - Ao aceitar: lembrete criado automaticamente

**Histórico:**
- `ttk.Treeview` com colunas: Nº, Título, Sala, Data, Hora, Criador, Status
- Campo de busca por título ou número
- Click na linha → detalhe

**`_show_booking_detail(booking_id)`:** Toplevel 400×320, lista participantes com ✓/✗/⏳. Se criador: botão "Cancelar Reunião".

### Padrões reutilizados de gui.py
- `_center_window(win, w, h)` — gui.py:885
- `_apply_rounded_corners(win)` — gui.py:898
- `_safe()` wrapper para thread safety
- Cores: NAVY `#0f2a5c`, accent `#7cb8f0`, fontes `Segoe UI`
- Padrão withdraw → build → deiconify (sem flash)
- Estilo de cards de convite igual ao de `_render_pending_invite_row()` — gui.py:13603

---

## Fase 5 — gui.py

### 5a. Menu "Agendar" (entre Ferramentas e Sobre)

**Localização:** linhas 9366–9368 (e espelho em 9125–9128 para `_rebuild_ui_language`)

```python
m_agenda = tk.Menu(menubar, tearoff=0, font=FONT)
m_agenda.add_command(label='Reunião', command=self._open_meeting_window)
menubar.add_cascade(label='Agendar', menu=m_agenda)
# inserir antes do add_command('Sobre')
```

Resultado: `Messenger | Ferramentas | Agendar | Sobre`

**Método `_open_meeting_window()`:**
```python
def _open_meeting_window(self):
    if hasattr(self, '_meeting_window') and self._meeting_window.winfo_exists():
        self._meeting_window.lift(); return
    from meeting_gui import MeetingWindow
    self._meeting_window = MeetingWindow(self)
```

### 5b. Sino de Notificações

**Posição:** dentro de `user_inner` (~linha 9382), packed `side='right'` antes de `name_status`.
Aparece no canto superior direito do header NAVY, acima do campo RAMAL.

```python
self._bell_frame = tk.Frame(user_inner, bg=NAVY, cursor='hand2')
self._bell_frame.pack(side='right', padx=(0, 2))

self._bell_lbl = tk.Label(self._bell_frame, text='🔔',
    font=('Segoe UI Symbol', 13), bg=NAVY, fg='#7cb8f0', cursor='hand2')
self._bell_lbl.pack()

self._bell_badge = tk.Label(self._bell_frame, text='',
    font=('Segoe UI', 7, 'bold'), bg='#ef4444', fg='white', width=2, height=1)
# Badge só aparece (pack/forget) quando _bell_unread > 0

self._bell_unread = 0
self._bell_lbl.bind('<Button-1>', lambda e: self._open_meeting_window())
```

`_update_bell_badge(count)`: exibe ou oculta badge vermelho com número.

### 5c. Popup de Convite

**`_show_meeting_invite_popup(booking)`** — Toplevel 420×340:

```
┌─────────────────────────────────────────┐
│  📅 Convite de Reunião                  │
├─────────────────────────────────────────┤
│  Reunião: [título]                      │
│  Criado por: [nome]                     │
│  Sala: [nome da sala]                   │
│  Data: DD/MM/YYYY                       │
│  Horário: HH:MM – HH:MM                 │
│  Participantes: [lista]                 │
├─────────────────────────────────────────┤
│      [✓ Aceitar]    [✗ Recusar]         │
└─────────────────────────────────────────┘
```

**`_on_meeting_invite(booking_info)`** — callback registrado no Messenger:
```python
def _on_meeting_invite(self, booking_info):
    self._bell_unread += 1
    self._safe(lambda: self._update_bell_badge(self._bell_unread))
    self._safe(lambda: self._show_meeting_invite_popup(booking_info))
    if HAS_WINOTIFY:
        n = WinNotification(app_id=APP_AUMID,
            title='Nova Reunião Agendada',
            msg=f"{booking_info['creator_name']}: {booking_info['title']}",
            icon=self._icon_path or '')
        n.show()
```

### 5d. Integração com Lembretes (ao aceitar)

`messenger.accept_meeting()` cria lembrete com JSON:
```python
remind_text = json.dumps({
    'type': 'meeting',
    'title': booking['title'],
    'room': room_name,
    'start_ts': booking['start_ts'],
    'end_ts': booking['end_ts'],
    'participants': [p['display_name'] for p in participants],
    'creator': booking['creator_name'],
})
db.add_reminder(text=remind_text, remind_at=booking['start_ts'] - 900,
                external_id=booking_id, creator_uid=..., creator_name=...)
```

Em `_render_reminder_row()` (gui.py:13675), detectar `type == 'meeting'` no JSON e renderizar card compacto:
```
⚡ Reunião: [título]        [data/hora]
   📍 [sala]  👥 [nomes]
```

### 5e. Callbacks no Messenger (em `_start_messenger()` de gui.py)

```python
on_meeting_invite=self._on_meeting_invite,
on_meeting_response=self._on_meeting_response,
on_meeting_cancel=self._on_meeting_cancel,
on_meeting_sync=self._on_meeting_sync,
```

---

## Regras de Negócio

| Regra | Implementação |
|-------|--------------|
| Sem sobreposição | `db.has_conflict()` antes de salvar; erro visual no formulário |
| Máx 3 horas | `end_ts - start_ts > 10800` → bloqueia salvamento |
| Mínimo 2 confirmados | `get_confirmed_count() >= 2` → status muda para 'confirmed' |
| Somente criador cancela | Check `creator_uid == self.user_id` em `cancel_meeting()` |
| Auto-cancelamento | Loop 60s: se `start_ts <= now` e `confirmed < 2` → cancela e notifica |
| Conflito offline | Last Write Wins via `updated_at`; booking local perde se timestamp remoto maior |
| Local Only | Se nenhum peer online ao criar: `status='local_only'`, envia ao peer ao reconectar |

---

## Ordem de Execução

1. `database.py` — tabelas + seed + métodos
2. `network.py` — constants + roteamento em `_process_message`
3. `messenger.py` — callbacks + métodos + auto-cancel loop + sync on connect
4. `meeting_gui.py` — arquivo novo completo
5. `gui.py` — menu, bell, callbacks, popup, reminder card

## Verificação

```bash
python -c "import gui; import messenger; import network; import database; import meeting_gui"
```

Testes manuais:
1. Abrir MBChat → verificar menu "Agendar > Reunião" aparece entre Ferramentas e Sobre
2. Criar reunião → TimeGrid atualiza, registro salvo no DB
3. No segundo PC: popup de convite aparece, sino mostra badge
4. Aceitar convite → Lembretes tem card de Reunião com 15min de antecedência
5. Criador cancela → todos recebem toast, lembrete some
6. Tentar reserva sobreposta → bloqueio visual com mensagem de erro
7. Reunião com < 2 confirmados no horário → auto-cancel disparado
