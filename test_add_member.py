import sys, os
sys.path.append(os.getcwd())
import tkinter as tk
from gui import GroupChatWindow
from messenger import Messenger

class DummyApp:
    def __init__(self):
        self.root = tk.Tk()
        self.messenger = Messenger()
        self._current_theme = 'MB Contabilidade'
    def _force_taskbar_entry(self, win): pass
    def _on_group_window_mapped(self, win): pass

app = DummyApp()
try:
    gw = GroupChatWindow(app, 'test_group_id', 'Test Group', 'temp')
    print('Window created.')
    try:
        gw.add_member('user1', 'User One', {'status': 'online', 'note': 'test note'})
        print('Member added successfully.')
    except Exception as e:
        import traceback
        print('Error in add_member:')
        traceback.print_exc()
except Exception as e:
    import traceback
    print('Error in __init__:')
    traceback.print_exc()
