# test_note_emoji_picker.py
# O seletor de emoji do RECADO (LanMessengerApp._show_note_emoji_picker)
# terminava com ep.focus_set() -- linha copiada do seletor da Transmitir,
# onde ep e o popup. Aqui ep nao existia: NameError no log a cada abertura
# (o seletor abria e funcionava, so o erro era gravado).
# Guarda: todo nome GLOBAL que a funcao (e as funcoes internas dela) usa
# precisa existir no modulo gui ou nos builtins -- pega esse tipo de erro
# sem precisar abrir a janela.
# Rodar: python tests/test_note_emoji_picker.py

import os
import sys
import dis
import types
import builtins
import tempfile

here = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(here) if os.path.basename(here) == 'tests' else here
sys.path.insert(0, root_dir)

try:
    sys.stdout.reconfigure(errors='backslashreplace')
except Exception:
    pass

import database
database.get_db_path = lambda *a, **k: os.path.join(tempfile.mkdtemp(), 't.db')

PASS, FAIL = [], []


def ok(msg):
    PASS.append(msg)
    print(f'  PASS  {msg}')


def fail(msg, detail=''):
    FAIL.append(msg)
    print(f'  FAIL  {msg}' + (f': {detail}' if detail else ''))


def global_names(code):
    names = set()
    for ins in dis.get_instructions(code):
        if ins.opname in ('LOAD_GLOBAL', 'LOAD_NAME') and isinstance(ins.argval, str):
            names.add(ins.argval)
    for const in code.co_consts:
        if isinstance(const, types.CodeType):
            names |= global_names(const)
    return names


def main():
    import gui
    print('\n[1] Nomes globais usados pelo seletor de emoji do recado')
    fn = gui.LanMessengerApp._show_note_emoji_picker
    used = global_names(fn.__code__)
    missing = sorted(n for n in used
                     if not hasattr(gui, n) and not hasattr(builtins, n))
    if not missing:
        ok(f'todos os {len(used)} nomes globais existem (sem NameError ao abrir)')
    else:
        fail('nome inexistente usado pela funcao', ', '.join(missing))
    if 'ep' not in used:
        ok('o "ep" copiado do seletor da Transmitir nao voltou')
    else:
        fail('ep voltou a ser usado no seletor do recado')


if __name__ == '__main__':
    main()
    print(f'\n{len(PASS)} PASS, {len(FAIL)} FAIL')
    print(f'{len(PASS)} passou {len(FAIL)} falhou')  # resumo lido pelo gate
    sys.exit(0 if not FAIL else 1)
