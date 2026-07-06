
path = "C:/Users/pedro.paiva/Documents/MBchat/gui.py"
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

replacements = []

# 1. _insert_text_with_emojis inline comments (ChatWindow) + _append_message docstring
old1 = (
    "        parts = _EMOJI_RE.split(text)    # fragmentos de texto entre os emojis\n"
    "        emojis = _EMOJI_RE.findall(text)\n"
    "        for i, part in enumerate(parts):\n"
    "            if part:\n"
    "                self.chat_text.insert('end', part, tag)\n"
    "            if i < len(emojis):\n"
    "                img = self._get_chat_emoji(emojis[i])\n"
    "                if img:\n"
    "                    self.chat_text.image_create('end', image=img, padx=1)\n"
    "                else:\n"
    "                    self.chat_text.insert('end', emojis[i], tag)\n"
    "\n"
    "    def _append_message(self, sender, text, is_mine, timestamp=None):\n"
    "        ts = datetime.fromtimestamp(timestamp or time.time()).strftime('%H:%M')\n"
    "        self.chat_text.configure(state='normal')"
)
new1 = (
    "        parts = _EMOJI_RE.split(text)    # fragmentos de texto entre os emojis\n"
    "        emojis = _EMOJI_RE.findall(text)  # lista dos emojis encontrados\n"
    "        for i, part in enumerate(parts):\n"
    "            if part:\n"
    "                self.chat_text.insert('end', part, tag)  # texto puro com estilo da tag\n"
    "            if i < len(emojis):\n"
    "                img = self._get_chat_emoji(emojis[i])  # busca imagem colorida no cache\n"
    "                if img:\n"
    "                    self.chat_text.image_create('end', image=img, padx=1)  # emoji como imagem\n"
    "                else:\n"
    "                    self.chat_text.insert('end', emojis[i], tag)  # fallback texto\n"
    "\n"
    "    def _append_message(self, sender, text, is_mine, timestamp=None):\n"
    '        """Adiciona uma mensagem na área de chat.\n'
    "        Suporta dois estilos: 'bubble' (WhatsApp) e 'linear' (padrão LAN Messenger).\n"
    "        O widget Text é desbloqueado para escrita e bloqueado novamente ao final.\n"
    '        """\n'
    "        ts = datetime.fromtimestamp(timestamp or time.time()).strftime('%H:%M')  # hora HH:MM\n"
    "        self.chat_text.configure(state='normal')  # habilita escrita temporariamente"
)
replacements.append((old1, new1))

# 2. _append_message body + receive_message + set_typing (ChatWindow)
old2 = (
    "        style = self.messenger.db.get_setting('msg_style', 'linear')\n"
    "\n"
    "        if style == 'bubble':\n"
    "            # Modo bolha (WhatsApp)\n"
    "            if is_mine:\n"
    "                name_tag = 'my_bubble_name'\n"
    "                time_tag = 'my_bubble_time'\n"
    "                msg_tag = 'my_bubble'\n"
    "            else:\n"
    "                name_tag = 'peer_bubble_name'\n"
    "                time_tag = 'peer_bubble_time'\n"
    "                msg_tag = 'peer_bubble'\n"
    "            self.chat_text.insert('end', f'{sender}', name_tag)\n"
    "            self.chat_text.insert('end', f'  {ts}\\n', time_tag)\n"
    "            self._insert_text_with_emojis(text, msg_tag)\n"
    "            self.chat_text.insert('end', '\\n', msg_tag)\n"
    "        else:\n"
    "            # Modo linear (padrão)\n"
    "            tag = 'my_name' if is_mine else 'peer_name'\n"
    "            self.chat_text.insert('end', f'{sender}', tag)\n"
    "            self.chat_text.insert('end', f'  {ts}\\n', 'time')\n"
    "            self._insert_text_with_emojis(text, 'msg')\n"
    "            self.chat_text.insert('end', '\\n', 'msg')\n"
    "\n"
    "        self._msg_ranges.append(text)\n"
    "        msg_idx = len(self._msg_ranges) - 1\n"
    "        self.chat_text.insert('end', '\\n')\n"
    "        self.chat_text.configure(state='disabled')\n"
    "        self.chat_text.see('end')\n"
    "\n"
    "    def _on_copy_click(self, event):\n"
    '        """Copia texto da mensagem clicada."""\n'
    "        try:\n"
    "            idx = self.chat_text.index(f'@{event.x},{event.y}')\n"
    "            # Pega a linha atual e copia\n"
    "            line_start = self.chat_text.index(f'{idx} linestart')\n"
    "            line_end = self.chat_text.index(f'{idx} lineend')\n"
    "            text = self.chat_text.get(line_start, line_end).strip()\n"
    "            if text:\n"
    "                self.clipboard_clear()\n"
    "                self.clipboard_append(text)\n"
    "        except Exception:\n"
    "            log.exception('Erro ao copiar mensagem')\n"
    "\n"
    "    def receive_message(self, content, timestamp=None):\n"
    "        self._append_message(self.peer_name, content, False, timestamp=timestamp)\n"
    "        self.messenger.mark_as_read(self.peer_id)\n"
    "        if self.focus_get() is None:\n"
    "            self.bell()\n"
    "\n"
    "    def set_typing(self, is_typing):\n"
    "        self.lbl_typing.config(\n"
    "            text=f'{self.peer_name} {_t(\"typing\")}' if is_typing else '')"
)
new2 = (
    "        style = self.messenger.db.get_setting('msg_style', 'linear')  # lê estilo preferido\n"
    "\n"
    "        if style == 'bubble':\n"
    "            # Modo bolha: próprias à direita, do contato à esquerda\n"
    "            if is_mine:\n"
    "                name_tag = 'my_bubble_name'   # nome azul, alinhado à direita\n"
    "                time_tag = 'my_bubble_time'   # horário na bolha própria\n"
    "                msg_tag = 'my_bubble'          # fundo azul claro\n"
    "            else:\n"
    "                name_tag = 'peer_bubble_name'  # nome vermelho, alinhado à esquerda\n"
    "                time_tag = 'peer_bubble_time'  # horário na bolha do contato\n"
    "                msg_tag = 'peer_bubble'         # fundo cinza\n"
    "            self.chat_text.insert('end', f'{sender}', name_tag)   # nome do remetente\n"
    "            self.chat_text.insert('end', f'  {ts}\\n', time_tag)   # horário ao lado\n"
    "            self._insert_text_with_emojis(text, msg_tag)           # conteúdo + emojis\n"
    "            self.chat_text.insert('end', '\\n', msg_tag)            # fecha bolha\n"
    "        else:\n"
    "            # Modo linear: nome em negrito colorido + texto logo abaixo\n"
    "            tag = 'my_name' if is_mine else 'peer_name'  # azul=próprio, vermelho=contato\n"
    "            self.chat_text.insert('end', f'{sender}', tag)    # nome do remetente\n"
    "            self.chat_text.insert('end', f'  {ts}\\n', 'time')   # horário discreto\n"
    "            self._insert_text_with_emojis(text, 'msg')            # texto + emojis\n"
    "            self.chat_text.insert('end', '\\n', 'msg')              # separação\n"
    "\n"
    "        self._msg_ranges.append(text)        # histórico local da janela\n"
    "        msg_idx = len(self._msg_ranges) - 1  # índice desta mensagem\n"
    "        self.chat_text.insert('end', '\\n')   # espaço extra entre mensagens\n"
    "        self.chat_text.configure(state='disabled')  # bloqueia edição manual\n"
    "        self.chat_text.see('end')  # rola para a mensagem mais recente\n"
    "\n"
    "    def _on_copy_click(self, event):\n"
    '        """Copia o texto da linha clicada para a área de transferência.\n'
    "        Usa coordenadas x,y do clique para localizar a linha no Text widget.\n"
    '        """\n'
    "        try:\n"
    "            idx = self.chat_text.index(f'@{event.x},{event.y}')  # posição no clique\n"
    "            # Limites da linha clicada\n"
    "            line_start = self.chat_text.index(f'{idx} linestart')\n"
    "            line_end = self.chat_text.index(f'{idx} lineend')\n"
    "            text = self.chat_text.get(line_start, line_end).strip()  # texto da linha\n"
    "            if text:\n"
    "                self.clipboard_clear()     # limpa clipboard anterior\n"
    "                self.clipboard_append(text)  # copia para área de transferência\n"
    "        except Exception:\n"
    "            log.exception('Erro ao copiar mensagem')\n"
    "\n"
    "    def receive_message(self, content, timestamp=None):\n"
    '        """Chamado pela rede ao receber mensagem do contato. Exibe, marca como lida e toca sino."""\n'
    "        self._append_message(self.peer_name, content, False, timestamp=timestamp)\n"
    "        self.messenger.mark_as_read(self.peer_id)  # atualiza contador de não-lidos\n"
    "        if self.focus_get() is None:\n"
    "            self.bell()  # sino do sistema para alertar o usuário\n"
    "\n"
    "    def set_typing(self, is_typing):\n"
    '        """Atualiza o indicador de digitação no cabeçalho do chat."""\n'
    "        self.lbl_typing.config(\n"
    "            text=f'{self.peer_name} {_t(\"typing\")}' if is_typing else '')"
)
replacements.append((old2, new2))

# 3. _on_enter + _on_key (ChatWindow)
old3 = (
    "    def _on_enter(self, event):\n"
    "        if not (event.state & 0x1):\n"
    "            self._send_message()\n"
    "            return 'break'"
)
new3 = (
    "    def _on_enter(self, event):\n"
    "        \"\"\"Envia a mensagem ao pressionar Enter (sem Shift). Shift+Enter = nova linha.\"\"\"\n"
    "        if not (event.state & 0x1):  # 0x1 = bit do Shift — se não pressionado, envia\n"
    "            self._send_message()\n"
    "            return 'break'  # consome evento para não inserir nova linha"
)
replacements.append((old3, new3))

# 4. _on_key (ChatWindow)
old4 = (
    "    def _on_key(self, event):\n"
    "        try:\n"
    "            # Detectar emoji digitado via teclado e substituir por imagem colorida\n"
    "            idx = self.entry.index('insert')\n"
    "            if idx != '1.0':\n"
    "                prev_idx = self.entry.index(f'{idx}-1c')\n"
    "                char = self.entry.get(prev_idx, idx)\n"
    "                if char and _EMOJI_RE.match(char):\n"
    "                    self.entry.delete(prev_idx, idx)\n"
    "                    self._entry_insert_emoji(char, prev_idx)\n"
    "        except Exception:\n"
    "            pass\n"
    "        try:\n"
    "            if not self._was_typing:\n"
    "                self._was_typing = True\n"
    "                threading.Thread(target=self.messenger.send_typing,\n"
    "                                 args=(self.peer_id, True),\n"
    "                                 daemon=True).start()\n"
    "            if self._typing_timer:\n"
    "                self.after_cancel(self._typing_timer)\n"
    "            self._typing_timer = self.after(2000, self._stop_typing)\n"
    "        except Exception:\n"
    "            log.exception('Erro em _on_key')"
)
new4 = (
    "    def _on_key(self, event):\n"
    "        \"\"\"Callback de teclado: detecta emojis digitados e gerencia indicador de digitação.\n"
    "        Se o último caractere digitado for um emoji, substitui por imagem colorida.\n"
    "        Envia notificação 'digitando' para o contato e agenda cancelamento após 2s de inatividade.\n"
    "        \"\"\"\n"
    "        try:\n"
    "            # Detectar emoji digitado via teclado e substituir por imagem colorida\n"
    "            idx = self.entry.index('insert')  # posição atual do cursor\n"
    "            if idx != '1.0':\n"
    "                prev_idx = self.entry.index(f'{idx}-1c')  # posição do char anterior\n"
    "                char = self.entry.get(prev_idx, idx)       # obtém o caractere\n"
    "                if char and _EMOJI_RE.match(char):  # é um emoji?\n"
    "                    self.entry.delete(prev_idx, idx)             # remove o texto\n"
    "                    self._entry_insert_emoji(char, prev_idx)     # substitui por imagem\n"
    "        except Exception:\n"
    "            pass\n"
    "        try:\n"
    "            # Gerencia indicador 'digitando...' para o contato\n"
    "            if not self._was_typing:\n"
    "                self._was_typing = True\n"
    "                # Notifica o contato que estamos digitando (em thread separada)\n"
    "                threading.Thread(target=self.messenger.send_typing,\n"
    "                                 args=(self.peer_id, True),\n"
    "                                 daemon=True).start()\n"
    "            if self._typing_timer:\n"
    "                self.after_cancel(self._typing_timer)  # cancela timer anterior\n"
    "            # Agenda parar indicador após 2 segundos sem digitar\n"
    "            self._typing_timer = self.after(2000, self._stop_typing)\n"
    "        except Exception:\n"
    "            log.exception('Erro em _on_key')"
)
replacements.append((old4, new4))

# 5. _stop_typing + _send_message + _send_file + _show_history (ChatWindow)
old5 = (
    "    def _stop_typing(self):\n"
    "        self._was_typing = False\n"
    "        threading.Thread(target=self.messenger.send_typing,\n"
    "                         args=(self.peer_id, False),\n"
    "                         daemon=True).start()\n"
    "\n"
    "    def _send_message(self):\n"
    "        content = self._get_entry_content()\n"
    "        if not content:\n"
    "            return\n"
    "        self.entry.delete('1.0', 'end')\n"
    "        self._entry_img_map.clear()\n"
    "        self._append_message(self.messenger.display_name, content, True)\n"
    "        threading.Thread(target=self.messenger.send_message,\n"
    "                         args=(self.peer_id, content), daemon=True).start()\n"
    "\n"
    "    def _send_file(self):\n"
    "        filepath = filedialog.askopenfilename(parent=self, title='Enviar arquivo')\n"
    "        if filepath:\n"
    "            self.app._start_file_send(self.peer_id, filepath)"
)
new5 = (
    "    def _stop_typing(self):\n"
    "        \"\"\"Para o indicador de digitação e notifica o contato.\"\"\"\n"
    "        self._was_typing = False  # redefine flag\n"
    "        # Notifica o contato que paramos de digitar (em thread separada)\n"
    "        threading.Thread(target=self.messenger.send_typing,\n"
    "                         args=(self.peer_id, False),\n"
    "                         daemon=True).start()\n"
    "\n"
    "    def _send_message(self):\n"
    "        \"\"\"Envia o conteúdo do campo de entrada para o contato.\n"
    "        Reconstrói emojis das imagens, limpa o campo e dispara envio em thread.\n"
    "        \"\"\"\n"
    "        content = self._get_entry_content()  # reconstrói texto + emojis do campo\n"
    "        if not content:\n"
    "            return  # não envia mensagens vazias\n"
    "        self.entry.delete('1.0', 'end')  # limpa o campo de entrada\n"
    "        self._entry_img_map.clear()       # limpa mapa de imagens\n"
    "        self._append_message(self.messenger.display_name, content, True)  # exibe localmente\n"
    "        # Envia via rede em thread separada para não travar a UI\n"
    "        threading.Thread(target=self.messenger.send_message,\n"
    "                         args=(self.peer_id, content), daemon=True).start()\n"
    "\n"
    "    def _send_file(self):\n"
    "        \"\"\"Abre diálogo de seleção de arquivo e inicia transferência p2p para o contato.\"\"\"\n"
    "        filepath = filedialog.askopenfilename(parent=self, title='Enviar arquivo')\n"
    "        if filepath:\n"
    "            self.app._start_file_send(self.peer_id, filepath)  # inicia transferência"
)
replacements.append((old5, new5))

count = 0
for i, (old, new) in enumerate(replacements):
    if old in content:
        content = content.replace(old, new, 1)
        count += 1
        print(f"OK: replacement {i+1}")
    else:
        print(f"MISS: replacement {i+1}")

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)

print(f"Done. {count}/{len(replacements)} replacements made.")
