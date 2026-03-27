"""
Build script - Gera o executavel do MB Chat via PyInstaller.
Uso: python build.py
"""
import subprocess
import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ICON = os.path.join(HERE, 'mbchat.ico')
MAIN = os.path.join(HERE, 'gui.py')


def build():
    # Gera o icone se nao existir
    if not os.path.exists(ICON):
        print('Gerando icone...')
        from create_icon import save_icon
        save_icon(ICON)

    cmd = [
        'pyinstaller',
        '--noconfirm',
        '--onefile',
        '--windowed',           # Sem console / terminal
        f'--icon={ICON}',
        f'--add-data={ICON};.',  # Inclui o ICO no bundle
        '--paths=.',            # Encontrar modulos locais
        '--hidden-import=messenger',
        '--hidden-import=network',
        '--hidden-import=database',
        '--hidden-import=winotify',
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
