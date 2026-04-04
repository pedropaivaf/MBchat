"""
Build script - Gera o executavel do MB Chat via PyInstaller.
Uso: python build.py
"""
import subprocess
import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ICON = os.path.join(HERE, 'assets', 'mbchat.ico')
MAIN = os.path.join(HERE, 'gui.py')


def build():
    print('Gerando icone...')
    from create_icon import save_icon
    save_icon(ICON)

    cmd = [
        sys.executable, '-m', 'PyInstaller',
        '--noconfirm',
        '--onefile',
        '--windowed',           # Sem console / terminal
        f'--icon={ICON}',
        f'--add-data={ICON};assets',  # Inclui o ICO no bundle
        '--paths=.',            # Encontrar modulos locais
        '--hidden-import=messenger',
        '--hidden-import=network',
        '--hidden-import=database',
        '--hidden-import=winotify',
        '--hidden-import=pystray',
        '--hidden-import=pystray._win32',
        '--hidden-import=PIL',
        '--hidden-import=PIL._imagingtk',
        '--hidden-import=PIL._tkinter_finder',
        '--name=MBChat',
        '--clean',
        MAIN,
    ]

    print('Executando PyInstaller...')
    print(' '.join(cmd))
    result = subprocess.run(cmd, cwd=HERE)

    if result.returncode == 0:
        exe = os.path.join(HERE, 'dist', 'MBChat.exe')
        print(f'\nBuild concluido com sucesso!')
        print(f'Executavel: {exe}')
    else:
        print(f'\nErro no build (codigo {result.returncode})')
        sys.exit(1)


if __name__ == '__main__':
    build()
