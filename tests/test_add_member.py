# Smoke test do GroupChatWindow: a janela monta e add_member popula o painel
# de participantes sem levantar excecao.
#
# Cobre a classe de bug da v1.8.35 ("grupo criado sem nenhum participante"):
# uma excecao no __init__ interrompia a montagem ANTES do painel de membros e a
# janela abria muda, sem erro visivel pro usuario.
#
# CUIDADO AO MEXER AQUI (dois problemas que este arquivo ja teve):
#   1. Usava Messenger(), que abre o banco REAL em %APPDATA%\.mbchat\mbchat.db.
#      Teste nao escreve no banco de producao — get_db_path e redirecionado
#      pra um arquivo temporario antes de qualquer import de messenger.
#   2. Engolia toda excecao com traceback.print_exc() e terminava com exit 0:
#      quebrava e continuava verde. Agora reporta PASS/FAIL e sai != 0.

import os
import sys
import tempfile
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS = []
FAIL = []


def ok(msg):
    PASS.append(msg)
    print(f'  PASS  {msg}')


def fail(msg, detail=''):
    FAIL.append(msg)
    print(f'  FAIL  {msg}' + (f': {detail}' if detail else ''))


# Redireciona o banco ANTES de importar messenger/gui — Messenger() chama
# Database() sem argumento, que resolve o caminho por get_db_path().
_TMP_DB = os.path.join(tempfile.mkdtemp(prefix='mbchat_test_'), 'test.db')
import database
database.get_db_path = lambda *a, **k: _TMP_DB

import tkinter  # noqa: F401  (garante que o Tcl carrega antes do gui)
from gui import GroupChatWindow
from messenger import Messenger


class DummyApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()          # nao pisca janela na tela de quem roda
        self.messenger = Messenger()
        self._current_theme = 'MB Contabilidade'

    def _force_taskbar_entry(self, win):
        pass

    def _on_group_window_mapped(self, win):
        pass


def main():
    print('\n[GroupChatWindow] montagem + add_member')
    app = None
    gw = None
    try:
        try:
            app = DummyApp()
        except Exception as e:
            fail('DummyApp/Messenger nao inicializou', repr(e))
            return

        try:
            gw = GroupChatWindow(app, 'test_group_id', 'Test Group', 'temp',
                                 start_hidden=True)
            ok('GroupChatWindow montou sem excecao')
        except Exception as e:
            import traceback
            traceback.print_exc()
            fail('GroupChatWindow.__init__ levantou excecao', repr(e))
            return

        try:
            gw.add_member('user1', 'User One',
                          {'status': 'online', 'note': 'test note'})
            ok('add_member executou sem excecao')
        except Exception as e:
            import traceback
            traceback.print_exc()
            fail('add_member levantou excecao', repr(e))
            return

        # O painel de participantes precisa ter REALMENTE recebido o membro —
        # o bug da v1.8.35 era a janela abrir com o painel vazio.
        widgets = getattr(gw, '_participant_widgets', {})
        if 'user1' in widgets:
            ok('membro aparece em _participant_widgets (painel populado)')
        else:
            fail('membro nao entrou em _participant_widgets — painel ficaria vazio')
    finally:
        for w in (gw, getattr(app, 'root', None)):
            try:
                if w is not None:
                    w.destroy()
            except Exception:
                pass


if __name__ == '__main__':
    main()
    print(f'\n{"=" * 52}')
    print(f'  {len(PASS)} passou   {len(FAIL)} falhou')
    print('=' * 52)
    sys.exit(0 if not FAIL else 1)
