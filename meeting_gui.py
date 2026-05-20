# MB Chat - Janela de Reserva de Salas
# Interface estilo Google Agenda: mini-calendário + visão do dia por sala

import tkinter as tk
from tkinter import messagebox, ttk
import time
import json
import calendar
from datetime import datetime, timedelta

NAVY     = '#0f2a5c'
ACCENT   = '#7cb8f0'
BG_WIN   = '#f5f7fa'
BG_WHITE = '#ffffff'
FG_BLACK = '#1a202c'
FG_GRAY  = '#4a5568'
FG_MUTED = '#94a3b8'
BORDER   = '#e2e8f0'
FONT     = ('Segoe UI', 9)
FONT_B   = ('Segoe UI', 9, 'bold')
FONT_SM  = ('Segoe UI', 8)
FONT_HDR = ('Segoe UI', 10, 'bold')

# Cores de status dos bookings
COLOR_PENDING   = '#94a3b8'
COLOR_CONFIRMED = '#16a34a'
COLOR_CANCELLED = '#ef4444'
COLOR_LOCAL     = '#f59e0b'

TIME_START = 7    # 07:00
TIME_END   = 20   # 20:00
PX_PER_MIN = 2    # 1 minuto = 2 pixels no canvas
TIME_AXIS_W = 48  # largura do eixo de horas


class MeetingWindow(tk.Toplevel):

    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.messenger = app.messenger
        self.withdraw()

        self.title('Reuniões')
        self.resizable(True, True)
        self.configure(bg=BG_WIN)

        self._selected_date = datetime.today().replace(
            hour=0, minute=0, second=0, microsecond=0)
        self._cal_year  = self._selected_date.year
        self._cal_month = self._selected_date.month
        self._selected_participants = []  # [(uid, display_name)]
        self._room_var = tk.IntVar(value=1)
        self._start_var = tk.StringVar(value=self._next_time_slot(0))
        self._end_var   = tk.StringVar(value=self._next_time_slot(1))
        self._title_var = tk.StringVar()

        self._build()
        self._center()
        self.deiconify()
        self.lift()
        self.refresh_timegrid()
        self._refresh_invites_panel()
        self._start_realtime_refresh()

    # ========================================
    # BUILD
    # ========================================

    def _build(self):
        # Header NAVY
        hdr = tk.Frame(self, bg=NAVY, height=44)
        hdr.pack(fill='x')
        hdr.pack_propagate(False)
        tk.Label(hdr, text='📅  Reuniões', font=('Segoe UI', 12, 'bold'),
                 bg=NAVY, fg='white').pack(side='left', padx=14, pady=10)

        # Body: 3 painéis
        body = tk.Frame(self, bg=BG_WIN)
        body.pack(fill='both', expand=True)

        # LEFT — mini calendário (210px)
        left = tk.Frame(body, bg=BG_WIN, width=210)
        left.pack(side='left', fill='y')
        left.pack_propagate(False)
        self._build_calendar(left)

        # Divisor vertical
        tk.Frame(body, bg=BORDER, width=1).pack(side='left', fill='y')

        # RIGHT — convites + formulário (290px)
        right = tk.Frame(body, bg=BG_WIN, width=290)
        right.pack(side='right', fill='y')
        right.pack_propagate(False)
        self._build_right_panel(right)

        # Divisor vertical
        tk.Frame(body, bg=BORDER, width=1).pack(side='right', fill='y')

        # CENTER — timegrid (expansível)
        center = tk.Frame(body, bg=BG_WHITE)
        center.pack(side='left', fill='both', expand=True)
        self._build_timegrid(center)

    # ========================================
    # MINI-CALENDÁRIO (left panel)
    # ========================================

    def _build_calendar(self, parent):
        self._cal_frame = tk.Frame(parent, bg=BG_WIN)
        self._cal_frame.pack(fill='x', padx=8, pady=8)
        self._draw_calendar()

        # Legenda
        leg = tk.Frame(parent, bg=BG_WIN)
        leg.pack(fill='x', padx=10, pady=(4, 0))
        for color, label in [
            (COLOR_PENDING,   'pendente'),
            (COLOR_CONFIRMED, 'confirmado'),
            (COLOR_CANCELLED, 'cancelado'),
            (COLOR_LOCAL,     'convite não enviado'),
        ]:
            row = tk.Frame(leg, bg=BG_WIN)
            row.pack(anchor='w', pady=1)
            tk.Label(row, text='●', font=('Segoe UI', 10), bg=BG_WIN,
                     fg=color).pack(side='left')
            tk.Label(row, text=label, font=FONT_SM, bg=BG_WIN,
                     fg=FG_GRAY).pack(side='left', padx=(3, 0))

    def _draw_calendar(self):
        for w in self._cal_frame.winfo_children():
            w.destroy()

        months_pt = ['', 'Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio',
                     'Junho', 'Julho', 'Agosto', 'Setembro', 'Outubro',
                     'Novembro', 'Dezembro']

        # Header mês/ano
        nav = tk.Frame(self._cal_frame, bg=BG_WIN)
        nav.pack(fill='x', pady=(0, 4))
        tk.Button(nav, text='‹', font=FONT_B, bg=BG_WIN, fg=NAVY,
                  relief='flat', bd=0, cursor='hand2',
                  command=self._prev_month).pack(side='left')
        tk.Label(nav, text=f'{months_pt[self._cal_month]} {self._cal_year}',
                 font=FONT_B, bg=BG_WIN, fg=FG_BLACK).pack(side='left', expand=True)
        tk.Button(nav, text='›', font=FONT_B, bg=BG_WIN, fg=NAVY,
                  relief='flat', bd=0, cursor='hand2',
                  command=self._next_month).pack(side='right')

        # Cabeçalho dias da semana
        day_hdr = tk.Frame(self._cal_frame, bg=BG_WIN)
        day_hdr.pack(fill='x')
        for d in ['D', 'S', 'T', 'Q', 'Q', 'S', 'S']:
            tk.Label(day_hdr, text=d, font=FONT_SM, bg=BG_WIN,
                     fg=FG_MUTED, width=3).pack(side='left')

        # Grid de dias
        today = datetime.today()
        cal = calendar.monthcalendar(self._cal_year, self._cal_month)
        for week in cal:
            row = tk.Frame(self._cal_frame, bg=BG_WIN)
            row.pack(fill='x')
            for day in week:
                if day == 0:
                    tk.Label(row, text='', bg=BG_WIN, width=3,
                             font=FONT_SM).pack(side='left')
                    continue
                dt = datetime(self._cal_year, self._cal_month, day)
                is_today    = (dt.date() == today.date())
                is_selected = (dt.date() == self._selected_date.date())
                bg  = NAVY   if is_selected else (ACCENT if is_today else BG_WIN)
                fg  = 'white' if (is_selected or is_today) else FG_BLACK
                btn = tk.Label(row, text=str(day), font=FONT_SM, width=3,
                               bg=bg, fg=fg, cursor='hand2', relief='flat')
                btn.pack(side='left', pady=1)
                btn.bind('<Button-1>',
                         lambda e, d=dt: self._select_day(d))

    def _prev_month(self):
        if self._cal_month == 1:
            self._cal_month = 12
            self._cal_year -= 1
        else:
            self._cal_month -= 1
        self._draw_calendar()

    def _next_month(self):
        if self._cal_month == 12:
            self._cal_month = 1
            self._cal_year += 1
        else:
            self._cal_month += 1
        self._draw_calendar()

    def _select_day(self, dt):
        self._selected_date = dt
        self._cal_year  = dt.year
        self._cal_month = dt.month
        self._draw_calendar()
        self.refresh_timegrid()
        # Atualiza label de data no formulário
        try:
            self._date_lbl.config(text=dt.strftime('%d/%m/%Y'))
        except Exception:
            pass

    # ========================================
    # TIMEGRID (center panel)
    # ========================================

    def _build_timegrid(self, parent):
        # Header da data com navegação ← →
        nav = tk.Frame(parent, bg=BG_WHITE)
        nav.pack(fill='x')
        tk.Button(nav, text='←', font=FONT, bg=BG_WHITE, fg=NAVY,
                  relief='flat', bd=0, cursor='hand2',
                  command=lambda: self._select_day(
                      self._selected_date - timedelta(days=1))
                  ).pack(side='left', padx=4, pady=6)
        self._date_nav_lbl = tk.Label(nav, text='', font=FONT_B,
                                      bg=BG_WHITE, fg=FG_BLACK)
        self._date_nav_lbl.pack(side='left', expand=True)
        tk.Button(nav, text='→', font=FONT, bg=BG_WHITE, fg=NAVY,
                  relief='flat', bd=0, cursor='hand2',
                  command=lambda: self._select_day(
                      self._selected_date + timedelta(days=1))
                  ).pack(side='right', padx=4)

        tk.Frame(parent, bg=BORDER, height=1).pack(fill='x')

        # Faixa fixa de status realtime por sala
        self._status_bar_frame = tk.Frame(parent, bg=BG_WHITE)
        self._status_bar_frame.pack(fill='x')
        self._status_cells = []
        rooms_seed = self.messenger.db.get_rooms()
        for _ in rooms_seed:
            cell = tk.Frame(self._status_bar_frame, bg=BG_WHITE)
            cell.pack(side='left', expand=True, fill='x')
            name_lbl = tk.Label(cell, text='', font=FONT_B, bg=BG_WHITE, fg=NAVY)
            name_lbl.pack(anchor='center', pady=(4, 0))
            pill_lbl = tk.Label(cell, text='', font=('Segoe UI', 8), bg=BG_WHITE)
            pill_lbl.pack(anchor='center', pady=(0, 4))
            self._status_cells.append({'name': name_lbl, 'pill': pill_lbl})
        tk.Frame(parent, bg=BORDER, height=1).pack(fill='x')

        # Canvas scrollável
        grid_frame = tk.Frame(parent, bg=BG_WHITE)
        grid_frame.pack(fill='both', expand=True)

        total_h = (TIME_END - TIME_START) * 60 * PX_PER_MIN

        self._grid_canvas = tk.Canvas(grid_frame, bg=BG_WHITE,
                                      highlightthickness=0, bd=0)
        self._grid_canvas.pack(side='left', fill='both', expand=True)

        # Scrollbar minimalista (padrão do app)
        self._sb_canvas = tk.Canvas(grid_frame, width=6,
                                    highlightthickness=0, bd=0, bg=BG_WIN)
        self._sb_canvas.pack(side='right', fill='y')
        self._sb_state = {'lo': 0.0, 'hi': 1.0, 'dragging': False,
                          'drag_y': 0, 'wide': False}

        def _sb_redraw():
            self._sb_canvas.delete('all')
            h = self._sb_canvas.winfo_height()
            w = self._sb_canvas.winfo_width()
            if h < 2 or w < 2:
                return
            y1 = max(int(self._sb_state['lo'] * h), 0)
            y2 = min(int(self._sb_state['hi'] * h), h)
            if y2 - y1 < 20:
                mid = (y1 + y2) // 2
                y1, y2 = max(mid - 10, 0), min(mid + 10, h)
            color = '#94a3b8' if self._sb_state['wide'] else '#cbd5e1'
            r = max((w - 2) // 2, 1)
            self._sb_canvas.create_oval(1, y1, w-1, y1+2*r,
                                        fill=color, outline='')
            self._sb_canvas.create_oval(1, y2-2*r, w-1, y2,
                                        fill=color, outline='')
            if y2 - 2*r > y1 + r:
                self._sb_canvas.create_rectangle(1, y1+r, w-1, y2-r,
                                                 fill=color, outline='')

        def _sb_set(lo, hi):
            lo, hi = float(lo), float(hi)
            self._sb_state['lo'] = lo
            self._sb_state['hi'] = hi
            if lo <= 0.0 and hi >= 1.0:
                self._sb_canvas.pack_forget()
            else:
                if not self._sb_canvas.winfo_ismapped():
                    self._sb_canvas.pack(side='right', fill='y')
                _sb_redraw()

        def _sb_enter(e):
            self._sb_state['wide'] = True
            self._sb_canvas.configure(width=10)
            _sb_redraw()

        def _sb_leave(e):
            if not self._sb_state['dragging']:
                self._sb_state['wide'] = False
                self._sb_canvas.configure(width=6)
                _sb_redraw()

        def _sb_press(e):
            self._sb_state['dragging'] = True
            self._sb_state['drag_y'] = e.y
            h = self._sb_canvas.winfo_height()
            if h > 0:
                frac = e.y / h
                lo, hi = self._sb_state['lo'], self._sb_state['hi']
                if frac < lo or frac > hi:
                    span = hi - lo
                    self._grid_canvas.yview_moveto(
                        max(0.0, frac - span / 2))

        def _sb_drag(e):
            if not self._sb_state['dragging']:
                return
            h = self._sb_canvas.winfo_height()
            if h < 1:
                return
            dy = (e.y - self._sb_state['drag_y']) / h
            self._sb_state['drag_y'] = e.y
            self._grid_canvas.yview_moveto(
                max(0.0, min(1.0, self._sb_state['lo'] + dy)))

        def _sb_release(e):
            self._sb_state['dragging'] = False
            if not self._sb_state['wide']:
                self._sb_canvas.configure(width=6)
                _sb_redraw()

        self._sb_canvas.bind('<Enter>', _sb_enter)
        self._sb_canvas.bind('<Leave>', _sb_leave)
        self._sb_canvas.bind('<Button-1>', _sb_press)
        self._sb_canvas.bind('<B1-Motion>', _sb_drag)
        self._sb_canvas.bind('<ButtonRelease-1>', _sb_release)
        self._sb_canvas.bind('<Configure>', lambda e: _sb_redraw())

        self._grid_canvas.configure(yscrollcommand=_sb_set,
                                    scrollregion=(0, 0, 2000, total_h))
        self._grid_canvas.bind('<Configure>', self._on_grid_resize)
        self._grid_canvas.bind('<MouseWheel>', self._on_grid_scroll)
        self._grid_canvas.bind('<Button-1>', self._on_grid_click)

        # Scroll inicial: hora atual se hoje, senão 07:00
        def _initial_scroll():
            total = (TIME_END - TIME_START) * 60 * PX_PER_MIN
            now = datetime.now()
            if (self._selected_date.date() == now.date() and
                    TIME_START <= now.hour < TIME_END):
                y = ((now.hour - TIME_START) * 60 + now.minute) * PX_PER_MIN
                frac = max(0.0, (y - 60) / total)  # 30min de margem acima
            else:
                frac = 0.0
            self._grid_canvas.yview_moveto(frac)
        self.after(120, _initial_scroll)

    def _on_grid_resize(self, event):
        self.refresh_timegrid()

    def _on_grid_scroll(self, event):
        self._grid_canvas.yview_scroll(int(-1 * (event.delta / 120)), 'units')

    def refresh_timegrid(self):
        cv = self._grid_canvas
        cv.delete('all')

        w = cv.winfo_width()
        if w < 10:
            w = 600
        total_h = (TIME_END - TIME_START) * 60 * PX_PER_MIN
        cv.configure(scrollregion=(0, 0, w, total_h))

        rooms = self.messenger.db.get_rooms()
        n_rooms = len(rooms)
        col_w = max((w - TIME_AXIS_W) // n_rooms, 80) if n_rooms else (w - TIME_AXIS_W)

        # Atualiza label de data
        days_pt = ['Segunda', 'Terça', 'Quarta', 'Quinta',
                   'Sexta', 'Sábado', 'Domingo']
        months_pt = ['', 'Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun',
                     'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez']
        wd = self._selected_date.weekday()  # 0=Seg
        day_name = days_pt[wd]
        self._date_nav_lbl.config(
            text=f'{day_name}, {self._selected_date.day:02d} '
                 f'{months_pt[self._selected_date.month]} '
                 f'{self._selected_date.year}')

        # Cabeçalho de salas
        for i, room in enumerate(rooms):
            x = TIME_AXIS_W + i * col_w + col_w // 2
            cv.create_text(x, 10, text=room['name'], font=FONT_B,
                           fill=NAVY, anchor='n')
            if i > 0:
                cv.create_line(TIME_AXIS_W + i * col_w, 0,
                               TIME_AXIS_W + i * col_w, total_h,
                               fill=BORDER, width=1)

        # Grid de horas
        for h in range(TIME_START, TIME_END + 1):
            y = (h - TIME_START) * 60 * PX_PER_MIN
            cv.create_line(TIME_AXIS_W, y, w, y, fill=BORDER, width=1)
            cv.create_text(TIME_AXIS_W - 4, y + 2,
                           text=f'{h:02d}:00', font=FONT_SM,
                           fill=FG_MUTED, anchor='ne')
            # Linha de meia hora (mais sutil)
            if h < TIME_END:
                yh = y + 30 * PX_PER_MIN
                cv.create_line(TIME_AXIS_W, yh, w, yh,
                               fill='#f1f5f9', width=1)

        # Linha do eixo de horas
        cv.create_line(TIME_AXIS_W, 0, TIME_AXIS_W, total_h,
                       fill=BORDER, width=1)

        # Bookings do dia
        day_start = self._selected_date.timestamp()
        day_end   = day_start + 86400
        bookings  = self.messenger.db.get_bookings(day_start, day_end)
        room_idx  = {r['id']: i for i, r in enumerate(rooms)}

        for b in bookings:
            rid = b['room_id']
            if rid not in room_idx:
                continue
            col_i = room_idx[rid]
            x0 = TIME_AXIS_W + col_i * col_w + 2
            x1 = TIME_AXIS_W + (col_i + 1) * col_w - 2

            start_dt = datetime.fromtimestamp(b['start_ts'])
            end_dt   = datetime.fromtimestamp(b['end_ts'])
            y0 = ((start_dt.hour - TIME_START) * 60 + start_dt.minute) * PX_PER_MIN
            y1 = ((end_dt.hour   - TIME_START) * 60 + end_dt.minute)   * PX_PER_MIN
            y0 = max(y0, 0)
            y1 = min(y1, total_h)
            if y1 <= y0:
                continue

            status = b.get('status', 'pending')
            color  = {
                'pending':   COLOR_PENDING,
                'confirmed': COLOR_CONFIRMED,
                'cancelled': COLOR_CANCELLED,
                'local_only': COLOR_LOCAL,
            }.get(status, COLOR_PENDING)

            rect_id = cv.create_rectangle(x0, y0, x1, y1,
                                          fill=color, outline='white',
                                          width=1)
            h_block = y1 - y0
            if h_block >= 52:
                label = (f'Título: {b["title"]}'
                         f'\nHorário: {start_dt.strftime("%H:%M")}–{end_dt.strftime("%H:%M")}'
                         f'\nParticipante(s): {b["creator_name"]}')
            elif h_block >= 28:
                label = f'{b["title"]}\nHorário: {start_dt.strftime("%H:%M")}–{end_dt.strftime("%H:%M")}'
            else:
                label = b['title']
            txt_id = cv.create_text(
                (x0 + x1) // 2, (y0 + y1) // 2,
                text=label, font=FONT_SM, fill='white',
                width=col_w - 8, anchor='center')

            bid = b['booking_id']
            cv.tag_bind(rect_id, '<Button-1>',
                        lambda e, b=bid: self._show_booking_detail(b))
            cv.tag_bind(txt_id, '<Button-1>',
                        lambda e, b=bid: self._show_booking_detail(b))

        # Linha vermelha: "agora" (se for o dia de hoje)
        today = datetime.today()
        if (today.date() == self._selected_date.date() and
                TIME_START <= today.hour < TIME_END):
            y_now = ((today.hour - TIME_START) * 60 + today.minute) * PX_PER_MIN
            cv.create_line(TIME_AXIS_W, y_now, w, y_now,
                           fill='#ef4444', width=2)

        self._refresh_room_status()

    def _refresh_room_status(self):
        try:
            rooms = self.messenger.db.get_rooms()
            now = time.time()
            day_start = self._selected_date.replace(
                hour=0, minute=0, second=0, microsecond=0).timestamp()
            day_end = day_start + 86400
            bookings = self.messenger.db.get_bookings(day_start, day_end)
            is_today = (datetime.today().date() == self._selected_date.date())

            for i, room in enumerate(rooms):
                if i >= len(self._status_cells):
                    break
                cell = self._status_cells[i]
                cell['name'].config(text=room['name'])

                if not is_today:
                    cell['pill'].config(text='', bg=BG_WHITE)
                    continue

                active = next((
                    b for b in bookings
                    if b['room_id'] == room['id']
                    and b.get('status', '') not in ('cancelled',)
                    and b['start_ts'] <= now < b['end_ts']
                ), None)

                if active:
                    end_str = datetime.fromtimestamp(active['end_ts']).strftime('%H:%M')
                    cell['pill'].config(text=f'● Ocupada até {end_str}',
                                        fg='#ef4444', bg='#fef2f2')
                else:
                    cell['pill'].config(text='● Livre',
                                        fg='#16a34a', bg='#f0fdf4')
        except Exception:
            pass

    def _start_realtime_refresh(self):
        def _tick():
            try:
                if self.winfo_exists():
                    self.refresh_timegrid()
                    self.after(60_000, _tick)
            except Exception:
                pass
        self.after(60_000, _tick)

    def _on_grid_click(self, event):
        cv = self._grid_canvas
        # Converte coordenada de tela para canvas
        y_canvas = cv.canvasy(event.y)
        x_canvas = cv.canvasx(event.x)

        if x_canvas < TIME_AXIS_W:
            return

        rooms = self.messenger.db.get_rooms()
        n_rooms = len(rooms)
        w = cv.winfo_width()
        col_w = max((w - TIME_AXIS_W) // n_rooms, 80) if n_rooms else (w - TIME_AXIS_W)

        # Descobre qual coluna (sala)
        col_i = int((x_canvas - TIME_AXIS_W) // col_w)
        if not (0 <= col_i < n_rooms):
            return
        room = rooms[col_i]

        # Descobre o horário pelo y
        total_mins = int(y_canvas / PX_PER_MIN)
        hour = TIME_START + total_mins // 60
        minute = (total_mins % 60) // 30 * 30  # arredonda para meia hora
        hour = max(TIME_START, min(TIME_END - 1, hour))

        start_str = f'{hour:02d}:{minute:02d}'
        end_hour  = hour + 1
        end_min   = minute
        if end_hour > TIME_END:
            end_hour = TIME_END
            end_min  = 0
        end_str   = f'{end_hour:02d}:{end_min:02d}'

        # Preenche formulário
        self._room_var.set(room['id'])
        try:
            self._room_menu.set(room['name'])
        except Exception:
            pass
        self._start_var.set(start_str)
        self._end_var.set(end_str)

    # ========================================
    # RIGHT PANEL: convites + formulário
    # ========================================

    def _build_right_panel(self, parent):
        # --- Convites pendentes ---
        self._invites_frame = tk.LabelFrame(
            parent, text='Convites', font=FONT_SM, bg=BG_WIN,
            fg=NAVY, padx=6, pady=6)
        self._invites_content = tk.Frame(self._invites_frame, bg=BG_WIN)
        self._invites_content.pack(fill='x')

        # --- Formulário Nova Reserva ---
        lf = tk.LabelFrame(parent, text='Nova Reserva', font=FONT_SM,
                           bg=BG_WIN, fg=NAVY, padx=8, pady=8)
        lf.pack(fill='x', padx=8, pady=(0, 8))

        # Título
        tk.Label(lf, text='Título:', font=FONT_SM, bg=BG_WIN,
                 fg=FG_GRAY).grid(row=0, column=0, sticky='w', pady=2)
        tk.Entry(lf, textvariable=self._title_var, font=FONT,
                 width=22).grid(row=0, column=1, sticky='ew', pady=2)

        # Sala
        tk.Label(lf, text='Sala:', font=FONT_SM, bg=BG_WIN,
                 fg=FG_GRAY).grid(row=1, column=0, sticky='w', pady=2)
        rooms = self.messenger.db.get_rooms()
        room_names = [r['name'] for r in rooms]
        self._room_name_var = tk.StringVar(value=room_names[0] if room_names else '')
        self._room_menu = ttk.Combobox(lf, textvariable=self._room_name_var,
                                       values=room_names, state='readonly',
                                       width=24, font=FONT_SM)
        self._room_menu.grid(row=1, column=1, sticky='ew', pady=2)
        self._room_map = {r['name']: r['id'] for r in rooms}

        # Data (label — segue calendário)
        tk.Label(lf, text='Data:', font=FONT_SM, bg=BG_WIN,
                 fg=FG_GRAY).grid(row=2, column=0, sticky='w', pady=2)
        self._date_lbl = tk.Label(
            lf, text=self._selected_date.strftime('%d/%m/%Y'),
            font=FONT, bg=BG_WIN, fg=FG_BLACK)
        self._date_lbl.grid(row=2, column=1, sticky='w', pady=2)

        # Início / Fim
        time_slots = [f'{h:02d}:{m:02d}'
                      for h in range(TIME_START, TIME_END)
                      for m in (0, 30)]
        end_slots = [f'{h:02d}:{m:02d}'
                     for h in range(TIME_START, TIME_END + 1)
                     for m in (0, 30)][1:]

        tk.Label(lf, text='Início:', font=FONT_SM, bg=BG_WIN,
                 fg=FG_GRAY).grid(row=3, column=0, sticky='w', pady=2)
        cb_start = ttk.Combobox(lf, textvariable=self._start_var, values=time_slots,
                                state='readonly', width=10, font=FONT_SM)
        cb_start.grid(row=3, column=1, sticky='w', pady=2)

        tk.Label(lf, text='Fim:', font=FONT_SM, bg=BG_WIN,
                 fg=FG_GRAY).grid(row=4, column=0, sticky='w', pady=2)
        cb_end = ttk.Combobox(lf, textvariable=self._end_var, values=end_slots,
                              state='readonly', width=10, font=FONT_SM)
        cb_end.grid(row=4, column=1, sticky='w', pady=2)

        # Ao abrir o dropdown, posiciona na seleção atual (mostra horário próximo no topo)
        def _scroll_combo_to_selection(cb, var, slots):
            try:
                idx = slots.index(var.get())
                cb.current(idx)
            except (ValueError, Exception):
                pass
        cb_start.bind('<<ComboboxSelected>>', lambda e: None)
        cb_start.bind('<ButtonPress>', lambda e: _scroll_combo_to_selection(
            cb_start, self._start_var, time_slots))
        cb_end.bind('<ButtonPress>', lambda e: _scroll_combo_to_selection(
            cb_end, self._end_var, end_slots))

        # Validação
        self._form_err = tk.Label(lf, text='', font=FONT_SM, bg=BG_WIN,
                                  fg='#ef4444', wraplength=200)
        self._form_err.grid(row=5, column=0, columnspan=2, sticky='w')

        # Participantes
        tk.Label(lf, text='Participantes:', font=FONT_SM, bg=BG_WIN,
                 fg=FG_GRAY).grid(row=6, column=0, sticky='nw', pady=(6, 2))
        self._part_frame = tk.Frame(lf, bg=BG_WIN)
        self._part_frame.grid(row=6, column=1, sticky='ew', pady=(6, 2))
        tk.Button(self._part_frame, text='+ Selecionar...',
                  font=FONT_SM, bg=BG_WIN, fg=NAVY,
                  relief='flat', bd=0, cursor='hand2',
                  command=self._open_participant_picker
                  ).pack(anchor='w')
        self._part_list_lbl = tk.Label(self._part_frame, text='',
                                       font=FONT_SM, bg=BG_WIN,
                                       fg=FG_GRAY, justify='left')
        self._part_list_lbl.pack(anchor='w')

        lf.grid_columnconfigure(1, weight=1)

        # Botão Criar
        tk.Button(parent, text='Criar Reunião', font=FONT_B,
                  bg=NAVY, fg='white', relief='flat', bd=0,
                  padx=10, pady=6, cursor='hand2',
                  command=self._create_meeting
                  ).pack(padx=12, pady=(0, 8), anchor='e')

    def _refresh_invites_panel(self):
        for w in self._invites_content.winfo_children():
            w.destroy()
        invites = [b for b in self.messenger.db.get_bookings(0, time.time() + 31536000)
                   if not self._is_creator(b)]
        # Filtra só os que eu sou participante pendente
        pending = []
        for b in self.messenger.db.get_all_bookings_for_sync():
            if b.get('is_deleted') or b.get('creator_uid') == self.messenger.user_id:
                continue
            parts = self.messenger.db.get_booking_participants(b['booking_id'])
            me = next((p for p in parts
                       if p['uid'] == self.messenger.user_id), None)
            if me and me['response'] == 'pending':
                pending.append(b)

        if not pending:
            self._invites_frame.pack_forget()
            return

        self._invites_frame.pack(fill='x', padx=8, pady=(8, 4))
        rooms = {r['id']: r['name'] for r in self.messenger.db.get_rooms()}

        for b in pending[:5]:  # max 5 cards
            card = tk.Frame(self._invites_content, bg='#eef2ff',
                            relief='flat', bd=0)
            card.pack(fill='x', pady=3)
            start_dt = datetime.fromtimestamp(b['start_ts'])
            end_dt   = datetime.fromtimestamp(b['end_ts'])
            tk.Label(card, text=f"📅 {b['title']}",
                     font=FONT_B, bg='#eef2ff', fg=FG_BLACK
                     ).pack(anchor='w', padx=6, pady=(4, 0))
            tk.Label(card, text=f"👤 {b['creator_name']}  •  📍 {rooms.get(b['room_id'], '?')}",
                     font=FONT_SM, bg='#eef2ff', fg=FG_GRAY
                     ).pack(anchor='w', padx=6)
            tk.Label(card, text=f"🗓 {start_dt.strftime('%d/%m  %H:%M')}–{end_dt.strftime('%H:%M')}",
                     font=FONT_SM, bg='#eef2ff', fg=FG_GRAY
                     ).pack(anchor='w', padx=6, pady=(0, 2))
            btn_row = tk.Frame(card, bg='#eef2ff')
            btn_row.pack(anchor='e', padx=6, pady=(0, 4))
            bid = b['booking_id']
            tk.Button(btn_row, text='✓ Aceitar', font=FONT_SM,
                      bg='#16a34a', fg='white', relief='flat', bd=0,
                      cursor='hand2', padx=6,
                      command=lambda b=bid: self._accept_invite(b)
                      ).pack(side='left', padx=(0, 4))
            tk.Button(btn_row, text='✗ Recusar', font=FONT_SM,
                      bg='#ef4444', fg='white', relief='flat', bd=0,
                      cursor='hand2', padx=6,
                      command=lambda b=bid: self._decline_invite(b)
                      ).pack(side='left')

    def _is_creator(self, booking):
        return booking.get('creator_uid') == self.messenger.user_id

    def _accept_invite(self, booking_id):
        self.messenger.accept_meeting(booking_id)
        self._refresh_invites_panel()
        self.refresh_timegrid()
        # Atualiza badge do sino
        try:
            invites = self.app._bell_pending_invites
            self.app._bell_pending_invites = [
                x for x in invites if x.get('booking_id') != booking_id]
            self.app._update_bell_badge(len(self.app._bell_pending_invites))
        except Exception:
            pass

    def _decline_invite(self, booking_id):
        self.messenger.decline_meeting(booking_id)
        self._refresh_invites_panel()
        try:
            invites = self.app._bell_pending_invites
            self.app._bell_pending_invites = [
                x for x in invites if x.get('booking_id') != booking_id]
            self.app._update_bell_badge(len(self.app._bell_pending_invites))
        except Exception:
            pass

    # ========================================
    # HELPERS DE HORÁRIO
    # ========================================

    @staticmethod
    def _next_time_slot(offset_slots=0):
        now = datetime.now()
        mins = now.hour * 60 + now.minute
        slot = ((mins + 29) // 30) * 30 + offset_slots * 30
        slot = max(slot, TIME_START * 60)
        slot = min(slot, (TIME_END - 1) * 60 + 30)
        h, m = divmod(slot, 60)
        if h >= TIME_END:
            h, m = TIME_END - 1, 30
        return f'{h:02d}:{m:02d}'

    # ========================================
    # PICKER DE PARTICIPANTES
    # ========================================

    def _open_participant_picker(self):
        win = tk.Toplevel(self)
        win.title('Selecionar Participantes')
        win.configure(bg='#f5f7fa')
        win.resizable(False, True)

        # Centraliza na tela (não na janela pai)
        W, H = 260, 420
        win.update_idletasks()
        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
        win.geometry(f'{W}x{H}+{(sw - W) // 2}+{(sh - H) // 2}')

        tk.Label(win, text='Selecionar Participantes', font=FONT_B,
                 bg=NAVY, fg='white').pack(fill='x', ipady=8)

        # Campo de busca por nome
        sf = tk.Frame(win, bg='#f5f7fa')
        sf.pack(fill='x', padx=8, pady=(6, 2))
        sv_search = tk.StringVar()
        se = tk.Entry(sf, textvariable=sv_search, font=FONT,
                      bg='white', fg=FG_MUTED, relief='solid', bd=1)
        se.insert(0, 'Buscar...')
        se.pack(fill='x')

        def _sf_in(e):
            if se.get() == 'Buscar...':
                se.delete(0, 'end')
                se.config(fg=FG_BLACK)
        def _sf_out(e):
            if not se.get():
                se.insert(0, 'Buscar...')
                se.config(fg=FG_MUTED)
        se.bind('<FocusIn>', _sf_in)
        se.bind('<FocusOut>', _sf_out)

        # Lista com scrollbar minimalista
        list_outer = tk.Frame(win, bg='#f5f7fa')
        list_outer.pack(fill='both', expand=True, padx=8, pady=(4, 4))

        canvas = tk.Canvas(list_outer, bg='#f5f7fa',
                           highlightthickness=0, bd=0)
        inner  = tk.Frame(canvas, bg='#f5f7fa')
        win_id = canvas.create_window((0, 0), window=inner, anchor='nw')

        # Scrollbar minimalista (padrão do app)
        sb = tk.Canvas(list_outer, width=6, bg='#f5f7fa',
                       highlightthickness=0, bd=0)
        sb_state = {'lo': 0.0, 'hi': 1.0, 'drag': False, 'dy': 0}

        def _sb_draw():
            sb.delete('all')
            h = sb.winfo_height()
            if h < 2:
                return
            y1 = max(int(sb_state['lo'] * h), 0)
            y2 = min(int(sb_state['hi'] * h), h)
            if y2 - y1 < 16:
                mid = (y1 + y2) // 2
                y1, y2 = max(mid - 8, 0), min(mid + 8, h)
            sb.create_rectangle(1, y1, 5, y2, fill='#cbd5e1', outline='')

        def _sb_set(lo, hi):
            sb_state['lo'], sb_state['hi'] = float(lo), float(hi)
            if float(lo) <= 0 and float(hi) >= 1:
                sb.pack_forget()
            else:
                if not sb.winfo_ismapped():
                    sb.pack(side='right', fill='y')
                _sb_draw()

        sb.bind('<Configure>', lambda e: _sb_draw())
        sb.bind('<Button-1>', lambda e: (
            sb_state.update({'drag': True, 'dy': e.y})))
        sb.bind('<B1-Motion>', lambda e: (
            canvas.yview_moveto(
                max(0.0, sb_state['lo'] + (e.y - sb_state['dy']) / max(sb.winfo_height(), 1)))
            or sb_state.update({'dy': e.y})))
        sb.bind('<ButtonRelease-1>', lambda e: sb_state.update({'drag': False}))

        canvas.configure(yscrollcommand=_sb_set)
        canvas.pack(side='left', fill='both', expand=True)

        canvas.bind('<Configure>', lambda e: canvas.itemconfig(win_id, width=e.width))
        inner.bind('<Configure>',
                   lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<MouseWheel>',
                    lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), 'units'))
        inner.bind('<MouseWheel>',
                   lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), 'units'))

        # Peers online em ordem alfabética
        peer_vars = {}
        peers = sorted(
            ((uid, info) for uid, info in self.app.peer_info.items()
             if info.get('status', 'offline') != 'offline'),
            key=lambda kv: kv[1].get('display_name', kv[0]).lower())

        already = {uid for uid, _ in self._selected_participants}
        peer_rows = {}

        for uid, info in peers:
            if uid == self.messenger.user_id:
                continue
            name = info.get('display_name', uid)
            var = tk.BooleanVar(value=uid in already)
            peer_vars[uid] = (var, name)
            row = tk.Frame(inner, bg='#ffffff',
                           highlightthickness=1, highlightbackground='#f1f5f9')
            row.pack(fill='x', pady=1)
            cb = tk.Checkbutton(row, text=f'  {name}', variable=var,
                                font=FONT, bg='#ffffff', fg=FG_BLACK,
                                activebackground='#f0f4ff', anchor='w',
                                selectcolor='#ffffff', cursor='hand2')
            cb.pack(fill='x', padx=4, pady=3)
            cb.bind('<MouseWheel>',
                    lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), 'units'))
            peer_rows[uid] = row

        _empty_peer_lbl = tk.Label(inner, text='Nenhum contato online', font=FONT,
                                   bg='#f5f7fa', fg=FG_MUTED)
        if not peer_vars:
            _empty_peer_lbl.pack(pady=20)

        def _apply_peer_filter(*_):
            q = sv_search.get().strip().lower()
            if q == 'buscar...':
                q = ''
            visible = 0
            for uid, r in peer_rows.items():
                name = peer_vars[uid][1].lower()
                if q in name:
                    r.pack(fill='x', pady=1)
                    visible += 1
                else:
                    r.pack_forget()
            if visible == 0 and peer_vars:
                _empty_peer_lbl.config(text='Nenhum resultado')
                _empty_peer_lbl.pack(pady=20)
            else:
                _empty_peer_lbl.pack_forget()

        sv_search.trace_add('write', _apply_peer_filter)

        # Botões
        btn_row = tk.Frame(win, bg='#f5f7fa')
        btn_row.pack(fill='x', padx=8, pady=8)

        def _ok():
            self._selected_participants = [
                (uid, name)
                for uid, (var, name) in peer_vars.items()
                if var.get()]
            self._update_part_label()
            win.destroy()

        tk.Button(btn_row, text='OK', font=FONT_B, bg=NAVY, fg='white',
                  relief='flat', bd=0, padx=12, pady=4,
                  cursor='hand2', command=_ok).pack(side='left')
        tk.Button(btn_row, text='Cancelar', font=FONT,
                  bg='#e2e8f0', fg=FG_GRAY, relief='flat', bd=0,
                  padx=12, pady=4, cursor='hand2',
                  command=win.destroy).pack(side='left', padx=(6, 0))

    def _update_part_label(self):
        if not self._selected_participants:
            self._part_list_lbl.config(text='')
        else:
            names = '\n'.join(f'• {n}' for _, n in self._selected_participants)
            self._part_list_lbl.config(text=names)

    # ========================================
    # CRIAR REUNIÃO
    # ========================================

    def _create_meeting(self):
        title = self._title_var.get().strip()
        if not title:
            self._form_err.config(text='Informe um título.')
            return

        room_name = self._room_name_var.get()
        room_id   = self._room_map.get(room_name)
        if not room_id:
            self._form_err.config(text='Selecione uma sala.')
            return

        try:
            sh, sm = map(int, self._start_var.get().split(':'))
            eh, em = map(int, self._end_var.get().split(':'))
        except Exception:
            self._form_err.config(text='Horário inválido.')
            return

        start_dt = self._selected_date.replace(hour=sh, minute=sm, second=0)
        end_dt   = self._selected_date.replace(hour=eh, minute=em, second=0)
        start_ts = start_dt.timestamp()
        end_ts   = end_dt.timestamp()

        if end_ts <= start_ts:
            self._form_err.config(text='Fim deve ser após o início.')
            return
        if end_ts - start_ts > 10800:
            self._form_err.config(text='Máximo 3 horas por reserva.')
            return
        if start_ts < time.time():
            self._form_err.config(text='Não é possível reservar horário no passado.')
            return

        self._form_err.config(text='')
        participant_uids = [uid for uid, _ in self._selected_participants]
        result = self.messenger.create_meeting(
            room_id, title, start_ts, end_ts, participant_uids)

        if result.get('error') == 'conflict':
            messagebox.showwarning(
                'Sala ocupada',
                'Já existe uma reserva neste horário para esta sala.',
                parent=self)
            return

        self._title_var.set('')
        self._selected_participants = []
        self._update_part_label()
        self.refresh_timegrid()

    # ========================================
    # DETALHE DO BOOKING
    # ========================================

    def _show_booking_detail(self, booking_id):
        booking = self.messenger.db.get_booking(booking_id)
        if not booking:
            return
        parts    = self.messenger.db.get_booking_participants(booking_id)
        rooms    = self.messenger.db.get_rooms()
        room_map = {r['id']: r['name'] for r in rooms}
        is_creator = booking.get('creator_uid') == self.messenger.user_id
        editable   = is_creator and booking.get('status') not in ('cancelled',)

        win = tk.Toplevel(self)
        win.title('Detalhes da Reunião')
        win.configure(bg=BG_WIN)
        win.resizable(True, True)
        try:
            self.app._center_window(win, 480, 520)
        except Exception:
            win.geometry('480x520')

        # Header
        tk.Label(win, text='Detalhes da Reunião', font=FONT_HDR,
                 bg=NAVY, fg='white').pack(fill='x', ipady=10)

        body = tk.Frame(win, bg=BG_WIN)
        body.pack(fill='both', expand=True, padx=16, pady=10)
        body.columnconfigure(1, weight=1)

        start_dt = datetime.fromtimestamp(booking['start_ts'])
        end_dt   = datetime.fromtimestamp(booking['end_ts'])

        # ── Campos editáveis ──────────────────────────────────
        def _lbl(text, row):
            tk.Label(body, text=text, font=FONT_SM, bg=BG_WIN,
                     fg=FG_MUTED, anchor='w').grid(
                row=row, column=0, sticky='w', pady=3, padx=(0, 8))

        # Título
        _lbl('Título:', 0)
        _title_var = tk.StringVar(value=booking['title'])
        title_entry = tk.Entry(body, textvariable=_title_var, font=FONT,
                               bg='#ffffff' if editable else BG_WIN,
                               fg=FG_BLACK, relief='solid' if editable else 'flat',
                               bd=1 if editable else 0,
                               state='normal' if editable else 'readonly')
        title_entry.grid(row=0, column=1, sticky='ew', pady=3)

        # Sala
        _lbl('Sala:', 1)
        room_names  = [r['name'] for r in rooms]
        _room_var   = tk.StringVar(value=room_map.get(booking['room_id'], ''))
        room_combo  = ttk.Combobox(body, textvariable=_room_var,
                                   values=room_names, font=FONT,
                                   state='readonly' if editable else 'disabled',
                                   width=22)
        room_combo.grid(row=1, column=1, sticky='w', pady=3)

        # Data
        _lbl('Data:', 2)
        tk.Label(body, text=start_dt.strftime('%d/%m/%Y'),
                 font=FONT, bg=BG_WIN, fg=FG_BLACK, anchor='w').grid(
            row=2, column=1, sticky='w', pady=3)

        # Horários
        time_slots = [f'{h:02d}:{m:02d}'
                      for h in range(TIME_START, TIME_END)
                      for m in (0, 30)]
        end_slots  = [f'{h:02d}:{m:02d}'
                      for h in range(TIME_START, TIME_END + 1)
                      for m in (0, 30)][1:]

        _lbl('Início:', 3)
        _start_var = tk.StringVar(value=start_dt.strftime('%H:%M'))
        ttk.Combobox(body, textvariable=_start_var, values=time_slots,
                     font=FONT, state='readonly' if editable else 'disabled',
                     width=10).grid(row=3, column=1, sticky='w', pady=3)

        _lbl('Fim:', 4)
        _end_var = tk.StringVar(value=end_dt.strftime('%H:%M'))
        ttk.Combobox(body, textvariable=_end_var, values=end_slots,
                     font=FONT, state='readonly' if editable else 'disabled',
                     width=10).grid(row=4, column=1, sticky='w', pady=3)

        # Criador + Status
        _lbl('Criador:', 5)
        tk.Label(body, text=booking['creator_name'],
                 font=FONT, bg=BG_WIN, fg=FG_BLACK, anchor='w').grid(
            row=5, column=1, sticky='w', pady=3)

        _lbl('Status:', 6)
        STATUS_PT = {'pending': 'Pendente', 'confirmed': 'Confirmado',
                     'cancelled': 'Cancelado', 'local_only': 'Convite não enviado'}
        STATUS_INFO = {'local_only': ' (participantes estavam offline ao criar)'}
        STATUS_COL  = {'pending': '#f59e0b', 'confirmed': '#16a34a',
                       'cancelled': '#ef4444', 'local_only': '#64748b'}
        st     = booking.get('status', 'pending')
        st_txt = STATUS_PT.get(st, st.capitalize()) + STATUS_INFO.get(st, '')
        tk.Label(body, text=st_txt, font=FONT_B, bg=BG_WIN,
                 fg=STATUS_COL.get(st, FG_BLACK), anchor='w').grid(
            row=6, column=1, sticky='w', pady=3)

        # ── Separador ────────────────────────────────────────
        tk.Frame(body, bg=BORDER, height=1).grid(
            row=7, column=0, columnspan=2, sticky='ew', pady=(8, 4))

        # ── Cabeçalho participantes ───────────────────────────
        parts_hdr = tk.Frame(body, bg=BG_WIN)
        parts_hdr.grid(row=8, column=0, columnspan=2, sticky='ew', pady=(0, 4))
        parts_hdr.columnconfigure(0, weight=1)
        self._parts_count_lbl = tk.Label(parts_hdr, text='', font=FONT_B,
                                         bg=BG_WIN, fg=FG_BLACK)
        self._parts_count_lbl.grid(row=0, column=0, sticky='w')

        # ── Lista de participantes (scrollável) ───────────────
        part_outer = tk.Frame(body, bg=BG_WIN)
        part_outer.grid(row=9, column=0, columnspan=2, sticky='nsew', pady=(0, 4))
        body.rowconfigure(9, weight=1)

        part_canvas = tk.Canvas(part_outer, bg=BG_WIN,
                                highlightthickness=0, bd=0, height=180)
        part_inner  = tk.Frame(part_canvas, bg=BG_WIN)
        part_sb     = tk.Canvas(part_outer, width=6, bg=BG_WIN,
                                highlightthickness=0, bd=0)

        part_canvas.pack(side='left', fill='both', expand=True)
        part_win_id = part_canvas.create_window((0, 0), window=part_inner, anchor='nw')
        part_canvas.bind('<Configure>',
                         lambda e: part_canvas.itemconfig(part_win_id, width=e.width))
        part_inner.bind('<Configure>',
                        lambda e: part_canvas.configure(
                            scrollregion=part_canvas.bbox('all')))
        part_canvas.bind('<MouseWheel>',
                         lambda e: part_canvas.yview_scroll(
                             int(-1*(e.delta/120)), 'units'))
        part_sb.bind('<Configure>', lambda e: None)

        def _sb_show(lo, hi):
            lo, hi = float(lo), float(hi)
            if lo <= 0 and hi >= 1:
                part_sb.pack_forget()
                return
            if not part_sb.winfo_ismapped():
                part_sb.pack(side='right', fill='y')
            h = part_sb.winfo_height()
            if h < 2:
                return
            part_sb.delete('all')
            y1 = max(int(lo * h), 0)
            y2 = min(int(hi * h), h)
            if y2 - y1 < 16:
                mid = (y1 + y2) // 2
                y1, y2 = max(mid - 8, 0), min(mid + 8, h)
            part_sb.create_rectangle(1, y1, 5, y2, fill='#cbd5e1', outline='')

        part_canvas.configure(yscrollcommand=_sb_show)

        def _sort_key(p):
            return (0 if p['uid'] == booking['creator_uid'] else 1,
                    p['display_name'].lower())

        def _render_part_list():
            for w in part_inner.winfo_children():
                w.destroy()
            current_parts = self.messenger.db.get_booking_participants(booking_id)
            self._parts_count_lbl.config(
                text=f'Participantes ({len(current_parts)})')
            for p in sorted(current_parts, key=_sort_key):
                resp = p['response']
                icon = {'accepted': '✓', 'declined': '✗',
                        'pending': '⏳'}.get(resp, '⏳')
                fgc  = {'accepted': '#16a34a', 'declined': '#ef4444',
                        'pending': FG_MUTED}.get(resp, FG_MUTED)
                bgc  = {'accepted': '#f0fdf4', 'declined': '#fef2f2',
                        'pending': '#f8fafc'}.get(resp, '#f8fafc')
                name = p['display_name']
                is_creator_p = (p['uid'] == booking['creator_uid'])
                if is_creator_p:
                    name += ' (criador)'

                prow = tk.Frame(part_inner, bg=bgc,
                                highlightthickness=1, highlightbackground=BORDER)
                prow.pack(fill='x', pady=1, padx=2)
                tk.Label(prow, text=icon, font=FONT, bg=bgc, fg=fgc,
                         width=2).pack(side='left', padx=(4, 2), pady=4)
                tk.Label(prow, text=name, font=FONT, bg=bgc,
                         fg=FG_BLACK, anchor='w').pack(side='left', pady=4,
                                                       fill='x', expand=True)
                resp_txt = {'accepted': 'Confirmado', 'declined': 'Recusou',
                            'pending': 'Pendente'}.get(resp, '')
                tk.Label(prow, text=resp_txt, font=('Segoe UI', 7),
                         bg=bgc, fg=fgc).pack(side='right', padx=(4, 8))

                # Botão re-convidar (só criador, só quem recusou)
                if editable and not is_creator_p and resp == 'declined':
                    uid_p = p['uid']
                    def _reinvite(u=uid_p):
                        self.messenger.add_participants(booking_id, [u])
                        _render_part_list()
                    tk.Button(prow, text='↺ Re-convidar', font=('Segoe UI', 7),
                              bg='#eff6ff', fg=NAVY, relief='flat', bd=0,
                              padx=6, pady=1, cursor='hand2',
                              command=_reinvite).pack(side='right', padx=(0, 4))

                # Botão remover (só criador, não pode remover a si mesmo)
                if editable and not is_creator_p:
                    uid_p = p['uid']
                    def _remove(u=uid_p):
                        self.messenger.remove_participant(booking_id, u)
                        _render_part_list()
                    tk.Button(prow, text='✕', font=('Segoe UI', 7),
                              bg=bgc, fg='#ef4444', relief='flat', bd=0,
                              cursor='hand2', command=_remove).pack(
                        side='right', padx=(0, 2))

        _render_part_list()

        # Botão adicionar participantes (só criador)
        if editable:
            def _open_add_picker():
                pick = tk.Toplevel(win)
                pick.title('Adicionar Participantes')
                pick.configure(bg='#f5f7fa')
                pick.resizable(False, True)
                W, H = 260, 420
                pick.update_idletasks()
                sw = pick.winfo_screenwidth()
                sh = pick.winfo_screenheight()
                pick.geometry(f'{W}x{H}+{(sw-W)//2}+{(sh-H)//2}')

                tk.Label(pick, text='Adicionar Participantes', font=FONT_B,
                         bg=NAVY, fg='white').pack(fill='x', ipady=8)

                # Campo de busca por nome
                search_frame = tk.Frame(pick, bg='#f5f7fa')
                search_frame.pack(fill='x', padx=8, pady=(6, 2))
                sv = tk.StringVar()
                search_entry = tk.Entry(search_frame, textvariable=sv, font=FONT,
                                        bg='white', fg=FG_MUTED, relief='solid', bd=1)
                search_entry.insert(0, 'Buscar...')
                search_entry.pack(fill='x')

                def _on_focus_in(e):
                    if search_entry.get() == 'Buscar...':
                        search_entry.delete(0, 'end')
                        search_entry.config(fg=FG_BLACK)
                def _on_focus_out(e):
                    if not search_entry.get():
                        search_entry.insert(0, 'Buscar...')
                        search_entry.config(fg=FG_MUTED)
                search_entry.bind('<FocusIn>', _on_focus_in)
                search_entry.bind('<FocusOut>', _on_focus_out)

                lo = tk.Frame(pick, bg='#f5f7fa')
                lo.pack(fill='both', expand=True, padx=8, pady=(4, 4))
                cv2  = tk.Canvas(lo, bg='#f5f7fa', highlightthickness=0, bd=0)
                inn2 = tk.Frame(cv2, bg='#f5f7fa')
                wid2 = cv2.create_window((0, 0), window=inn2, anchor='nw')
                cv2.pack(fill='both', expand=True)
                cv2.bind('<Configure>', lambda e: cv2.itemconfig(wid2, width=e.width))
                inn2.bind('<Configure>',
                          lambda e: cv2.configure(scrollregion=cv2.bbox('all')))
                cv2.bind('<MouseWheel>',
                         lambda e: cv2.yview_scroll(int(-1*(e.delta/120)), 'units'))

                already = {p['uid'] for p in
                           self.messenger.db.get_booking_participants(booking_id)}
                pvars = {}
                peers = sorted(
                    ((uid, info) for uid, info in self.app.peer_info.items()
                     if info.get('status', 'offline') != 'offline'
                     and uid != self.messenger.user_id
                     and uid not in already),
                    key=lambda kv: kv[1].get('display_name', kv[0]).lower())

                row_widgets = {}
                for uid, info in peers:
                    name = info.get('display_name', uid)
                    var  = tk.BooleanVar(value=False)
                    pvars[uid] = (var, name)
                    r = tk.Frame(inn2, bg='#ffffff',
                                 highlightthickness=1, highlightbackground='#f1f5f9')
                    r.pack(fill='x', pady=1)
                    tk.Checkbutton(r, text=f'  {name}', variable=var,
                                   font=FONT, bg='#ffffff', fg=FG_BLACK,
                                   activebackground='#f0f4ff', anchor='w',
                                   selectcolor='#ffffff', cursor='hand2'
                                   ).pack(fill='x', padx=4, pady=3)
                    row_widgets[uid] = r

                _empty_lbl = tk.Label(inn2, text='Nenhum contato novo disponível',
                                      font=FONT, bg='#f5f7fa', fg=FG_MUTED)
                if not pvars:
                    _empty_lbl.pack(pady=20)

                def _apply_filter(*_):
                    q = sv.get().strip().lower()
                    if q == 'buscar...':
                        q = ''
                    visible = 0
                    for uid, r in row_widgets.items():
                        name = pvars[uid][1].lower()
                        if q in name:
                            r.pack(fill='x', pady=1)
                            visible += 1
                        else:
                            r.pack_forget()
                    if visible == 0 and pvars:
                        _empty_lbl.config(text='Nenhum resultado')
                        _empty_lbl.pack(pady=20)
                    else:
                        _empty_lbl.pack_forget()

                sv.trace_add('write', _apply_filter)

                br = tk.Frame(pick, bg='#f5f7fa')
                br.pack(fill='x', padx=8, pady=8)

                def _ok_add():
                    to_add = [uid for uid, (var, _) in pvars.items() if var.get()]
                    if to_add:
                        self.messenger.add_participants(booking_id, to_add)
                        _render_part_list()
                    pick.destroy()

                tk.Button(br, text='Adicionar', font=FONT_B,
                          bg=NAVY, fg='white', relief='flat', bd=0,
                          padx=10, pady=4, cursor='hand2',
                          command=_ok_add).pack(side='left')
                tk.Button(br, text='Cancelar', font=FONT,
                          bg='#e2e8f0', fg=FG_GRAY, relief='flat', bd=0,
                          padx=10, pady=4, cursor='hand2',
                          command=pick.destroy).pack(side='left', padx=(6, 0))

            tk.Button(body, text='+ Adicionar participante', font=FONT_SM,
                      bg=BG_WIN, fg=NAVY, relief='flat', bd=0,
                      cursor='hand2', command=_open_add_picker).grid(
                row=10, column=0, columnspan=2, sticky='w', pady=(2, 0))

        # ── Erro ─────────────────────────────────────────────
        err_lbl = tk.Label(win, text='', font=FONT_SM,
                           bg=BG_WIN, fg='#ef4444')
        err_lbl.pack(fill='x', padx=16)

        # ── Botões ────────────────────────────────────────────
        btn_bar = tk.Frame(win, bg=BG_WIN)
        btn_bar.pack(fill='x', padx=16, pady=(0, 12))

        if editable:
            def _save():
                new_title = _title_var.get().strip()
                if not new_title:
                    err_lbl.config(text='Título não pode ser vazio.')
                    return
                new_room_name = _room_var.get()
                new_room_id   = {r['name']: r['id'] for r in rooms}.get(new_room_name)
                if not new_room_id:
                    err_lbl.config(text='Selecione uma sala válida.')
                    return
                try:
                    sh, sm = map(int, _start_var.get().split(':'))
                    eh, em = map(int, _end_var.get().split(':'))
                except Exception:
                    err_lbl.config(text='Horário inválido.')
                    return
                base = start_dt.replace(hour=0, minute=0, second=0, microsecond=0)
                new_start = base.replace(hour=sh, minute=sm).timestamp()
                new_end   = base.replace(hour=eh, minute=em).timestamp()
                if new_end <= new_start:
                    err_lbl.config(text='Fim deve ser após o início.')
                    return
                if new_end - new_start > 10800:
                    err_lbl.config(text='Máximo 3 horas.')
                    return
                result = self.messenger.edit_meeting(
                    booking_id, new_title, new_room_id, new_start, new_end)
                if result and result.get('error') == 'conflict':
                    err_lbl.config(text='Sala ocupada nesse horário.')
                    return
                win.destroy()
                self.refresh_timegrid()

            tk.Button(btn_bar, text='Salvar alterações', font=FONT_B,
                      bg=NAVY, fg='white', relief='flat', bd=0,
                      padx=10, pady=5, cursor='hand2',
                      command=_save).pack(side='left', padx=(0, 8))

            def _cancel():
                if messagebox.askyesno('Cancelar Reunião',
                                       'Cancelar esta reunião para todos?',
                                       parent=win):
                    self.messenger.cancel_meeting(booking_id)
                    win.destroy()
                    self.refresh_timegrid()
                    self._refresh_invites_panel()

            tk.Button(btn_bar, text='Cancelar Reunião', font=FONT_SM,
                      bg='#ef4444', fg='white', relief='flat', bd=0,
                      padx=10, pady=5, cursor='hand2',
                      command=_cancel).pack(side='left')

        tk.Button(btn_bar, text='Fechar', font=FONT_SM,
                  bg='#e2e8f0', fg=FG_GRAY, relief='flat', bd=0,
                  padx=10, pady=5, cursor='hand2',
                  command=win.destroy).pack(side='right')

    # ========================================
    # HELPERS
    # ========================================

    def _center(self):
        self.update_idletasks()
        w, h = 1060, 660
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 2
        self.geometry(f'{w}x{h}+{x}+{y}')
        self.minsize(800, 500)
