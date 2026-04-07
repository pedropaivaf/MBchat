# Build script - Gera o executavel do MB Chat via PyInstaller.
#
# Modos de uso:
#   python build.py              -> menu interativo
#   python build.py --version X.Y.Z --deploy PATH  -> direto via CLI
import subprocess
import sys
import os
import shutil
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))
ICON = os.path.join(HERE, 'assets', 'mbchat.ico')
MAIN = os.path.join(HERE, 'gui.py')
VERSION_FILE = os.path.join(HERE, 'version.py')
DEFAULT_DEPLOY = r'V:\Publico\mbchat-update'
PYTHON_DIR = os.path.dirname(sys.executable)


def _read_version():
    try:
        with open(VERSION_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                if line.startswith('APP_VERSION'):
                    return line.split('=')[1].strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return '1.0.0'


def _set_version(version):
    with open(VERSION_FILE, 'w', encoding='utf-8') as f:
        f.write(f'APP_VERSION = "{version}"\n')
    print(f'Versao definida: {version}')


def _deploy(deploy_path, version):
    exe_src = os.path.join(HERE, 'dist', 'MBChat.exe')
    if not os.path.isfile(exe_src):
        print(f'Erro: {exe_src} nao encontrado.')
        return False

    os.makedirs(deploy_path, exist_ok=True)

    exe_dst = os.path.join(deploy_path, 'MBChat.exe')
    ver_dst = os.path.join(deploy_path, 'version.txt')

    print(f'Copiando exe para {exe_dst}...')
    shutil.copy2(exe_src, exe_dst)

    print(f'Escrevendo version.txt ({version})...')
    with open(ver_dst, 'w', encoding='utf-8') as f:
        f.write(version)

    print(f'Deploy concluido em {deploy_path}')
    return True


def _do_build():
    print('Gerando icone...')
    from create_icon import save_icon
    save_icon(ICON)

    # DLLs criticas do VC runtime — incluir explicitamente para evitar
    # "Failed to load Python DLL" em maquinas com caminhos 8.3
    vcrt_dlls = ['vcruntime140.dll', 'vcruntime140_1.dll', 'python3.dll']
    add_bins = []
    for dll in vcrt_dlls:
        dll_path = os.path.join(PYTHON_DIR, dll)
        if os.path.isfile(dll_path):
            add_bins.append(f'--add-binary={dll_path};.')

    cmd = [
        sys.executable, '-m', 'PyInstaller',
        '--noconfirm',
        '--onefile',
        '--windowed',
        '--noupx',                  # UPX corrompe DLLs do VC runtime
        f'--icon={ICON}',
        f'--add-data={ICON};assets',
        *add_bins,                  # vcruntime140, vcruntime140_1, python3
        '--paths=.',
        '--hidden-import=messenger',
        '--hidden-import=network',
        '--hidden-import=database',
        '--hidden-import=updater',
        '--hidden-import=version',
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
    result = subprocess.run(cmd, cwd=HERE)

    if result.returncode != 0:
        print(f'\nErro no build (codigo {result.returncode})')
        return False

    exe = os.path.join(HERE, 'dist', 'MBChat.exe')
    print(f'\nBuild concluido! -> {exe}')
    return True


def _interactive():
    current = _read_version()
    print(f'\n=== MB Chat Build ===')
    print(f'Versao atual: {current}')
    print(f'Deploy padrao: {DEFAULT_DEPLOY}')
    print()
    print('Opcoes:')
    print('  1) Build normal (sem mudar versao, sem deploy)')
    print('  2) Build com nova versao + deploy para o share')
    print('  3) Somente deploy (sem buildar, envia exe existente)')
    print('  4) Sair')
    print()

    choice = input('Escolha [1-4]: ').strip()

    if choice == '1':
        print(f'\nBuildando versao {current}...')
        if _do_build():
            print(f'\nVersao: {current}')
    elif choice == '2':
        new_ver = input(f'Nova versao (atual: {current}): ').strip()
        if not new_ver:
            print('Versao nao informada, cancelado.')
            return
        _set_version(new_ver)
        deploy_path = input(f'Pasta de deploy [{DEFAULT_DEPLOY}]: ').strip()
        if not deploy_path:
            deploy_path = DEFAULT_DEPLOY
        print(f'\nBuildando versao {new_ver}...')
        if _do_build():
            print(f'\nVersao: {new_ver}')
            _deploy(deploy_path, new_ver)
    elif choice == '3':
        version = _read_version()
        exe = os.path.join(HERE, 'dist', 'MBChat.exe')
        if not os.path.isfile(exe):
            print(f'Erro: {exe} nao existe. Faca um build primeiro.')
            return
        deploy_path = input(f'Pasta de deploy [{DEFAULT_DEPLOY}]: ').strip()
        if not deploy_path:
            deploy_path = DEFAULT_DEPLOY
        _deploy(deploy_path, version)
    elif choice == '4':
        print('Saindo.')
    else:
        print('Opcao invalida.')


def build():
    parser = argparse.ArgumentParser(description='Build MBChat.exe')
    parser.add_argument('--version', type=str, default=None,
                        help='Define a versao (ex: 1.2.0)')
    parser.add_argument('--deploy', type=str, default=None,
                        help='Caminho para copiar exe + version.txt')
    args = parser.parse_args()

    # Se nenhum argumento, modo interativo
    if args.version is None and args.deploy is None:
        _interactive()
        return

    # Modo CLI direto
    if args.version:
        _set_version(args.version)

    version = _read_version()
    print(f'Build versao: {version}')

    if _do_build():
        print(f'Versao: {version}')
        if args.deploy:
            _deploy(args.deploy, version)


if __name__ == '__main__':
    build()
