# Build script - Gera o executavel do MB Chat via PyInstaller + instalador Inno Setup.
#
# Modos de uso:
#   python build.py              -> menu interativo
#   python build.py --version X.Y.Z --deploy PATH  -> direto via CLI
#   python build.py --version X.Y.Z --release       -> build + instalador + GitHub release
import subprocess
import sys
import os
import shutil
import argparse
import re
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ICON = os.path.join(HERE, 'assets', 'mbchat.ico')
MAIN = os.path.join(HERE, 'gui.py')
VERSION_FILE = os.path.join(HERE, 'version.py')
ISS_FILE = os.path.join(HERE, 'installer.iss')
DEFAULT_DEPLOY = r'\\192.168.0.9\Works2026\Publico\mbchat-update'
PYTHON_DIR = sys.base_prefix

# Caminhos comuns do Inno Setup no Windows
ISCC_PATHS = [
    os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Programs', 'Inno Setup 6', 'ISCC.exe'),
    os.path.join(os.environ.get('PROGRAMFILES(X86)', ''), 'Inno Setup 6', 'ISCC.exe'),
    os.path.join(os.environ.get('PROGRAMFILES', ''), 'Inno Setup 6', 'ISCC.exe'),
]


def _find_iscc():
    for p in ISCC_PATHS:
        if os.path.isfile(p):
            return p
    try:
        result = subprocess.run(['where', 'iscc'], capture_output=True, text=True)
        if result.returncode == 0:
            return result.stdout.strip().split('\n')[0]
    except Exception:
        pass
    return None


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
    _update_iss_version(version)
    _update_landing_version(version)
    print(f'Versao definida: {version}')


def _update_iss_version(version):
    if not os.path.isfile(ISS_FILE):
        return
    with open(ISS_FILE, 'r', encoding='utf-8') as f:
        content = f.read()
    content = re.sub(r'AppVersion=[\d.]+', f'AppVersion={version}', content)
    content = re.sub(r'AppVerName=MB Chat v[\d.]+', f'AppVerName=MB Chat v{version}', content)
    with open(ISS_FILE, 'w', encoding='utf-8') as f:
        f.write(content)


def _update_landing_version(version):
    landing = os.path.join(HERE, 'docs', 'index.html')
    if not os.path.isfile(landing):
        return
    with open(landing, 'r', encoding='utf-8') as f:
        content = f.read()
    content = re.sub(
        r'v[\d.]+(\s*&middot;\s*Windows)',
        f'v{version}\\1',
        content)
    with open(landing, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f'Landing page atualizada para v{version}')


def _deploy(deploy_path, version):
    src_dir = os.path.join(HERE, 'dist', 'MBChat')
    if not os.path.isdir(src_dir):
        print(f'Erro: {src_dir} nao encontrado.')
        return False

    os.makedirs(deploy_path, exist_ok=True)

    # Copia a pasta inteira para o share
    dst_dir = os.path.join(deploy_path, 'MBChat')
    print(f'Copiando para {dst_dir}...')
    if os.path.isdir(dst_dir):
        shutil.rmtree(dst_dir, ignore_errors=True)
    shutil.copytree(src_dir, dst_dir)

    ver_dst = os.path.join(deploy_path, 'version.txt')
    print(f'Escrevendo version.txt ({version})...')
    with open(ver_dst, 'w', encoding='utf-8') as f:
        f.write(version)

    # Copia tambem o zip para o share (fallback de update)
    zip_src = os.path.join(HERE, 'dist', 'MBChat_update.zip')
    if os.path.isfile(zip_src):
        shutil.copy2(zip_src, os.path.join(deploy_path, 'MBChat_update.zip'))

    print(f'Deploy concluido em {deploy_path}')
    return True


def _do_build():
    cache_dir = os.path.join(HERE, '__pycache__')
    if os.path.isdir(cache_dir):
        shutil.rmtree(cache_dir)

    print('Gerando icone...')
    from create_icon import save_icon
    save_icon(ICON)

    cmd = [
        sys.executable, '-m', 'PyInstaller',
        '--noconfirm',
        '--onedir',
        '--windowed',
        '--noupx',
        f'--icon={ICON}',
        f'--add-data={ICON};assets',
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

    out_dir = os.path.join(HERE, 'dist', 'MBChat')
    print(f'\nBuild concluido! -> {out_dir}')

    # Gera zip para auto-update
    _create_update_zip(out_dir)

    return True


def _create_update_zip(src_dir):
    zip_path = os.path.join(HERE, 'dist', 'MBChat_update.zip')
    print(f'Criando {zip_path}...')
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(src_dir):
            for f in files:
                full = os.path.join(root, f)
                arcname = os.path.relpath(full, src_dir)
                zf.write(full, arcname)
    size_mb = os.path.getsize(zip_path) / (1024 * 1024)
    print(f'Zip criado ({size_mb:.1f} MB)')


def _do_installer():
    iscc = _find_iscc()
    if not iscc:
        print('AVISO: Inno Setup nao encontrado. Instalador nao gerado.')
        print('       Instale com: winget install JRSoftware.InnoSetup')
        return False

    print('Compilando instalador (Inno Setup)...')
    result = subprocess.run([iscc, ISS_FILE], cwd=HERE, capture_output=True, text=True)

    if result.returncode != 0:
        print(f'Erro no Inno Setup (codigo {result.returncode})')
        if result.stderr:
            print(result.stderr)
        if result.stdout:
            print(result.stdout[-500:])
        return False

    setup = os.path.join(HERE, 'dist', 'MBChat_Setup.exe')
    print(f'Instalador gerado! -> {setup}')
    return True


def _do_release(version):
    try:
        subprocess.run(['gh', '--version'], capture_output=True, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        print('AVISO: GitHub CLI (gh) nao encontrado. Release nao criada.')
        return False

    update_zip = os.path.join(HERE, 'dist', 'MBChat_update.zip')
    setup = os.path.join(HERE, 'dist', 'MBChat_Setup.exe')
    tag = f'v{version}'

    assets = []
    if os.path.isfile(update_zip):
        assets.append(update_zip)
    if os.path.isfile(setup):
        assets.append(setup)

    if not assets:
        print('AVISO: nenhum asset encontrado para upload.')
        return False

    check = subprocess.run(['gh', 'release', 'view', tag], capture_output=True, cwd=HERE)
    if check.returncode == 0:
        print(f'Release {tag} ja existe, atualizando assets...')
        cmd = ['gh', 'release', 'upload', tag, '--clobber'] + assets
    else:
        print(f'Criando release {tag}...')
        cmd = ['gh', 'release', 'create', tag,
               '--title', f'MB Chat {tag}',
               '--notes', f'MB Chat {tag}'] + assets

    result = subprocess.run(cmd, cwd=HERE)
    if result.returncode != 0:
        print(f'Erro ao criar/atualizar release (codigo {result.returncode})')
        return False

    print(f'Release {tag} publicada no GitHub!')
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
    print('  4) Build com nova versao + GitHub release')
    print('  5) Sair')
    print()

    choice = input('Escolha [1-5]: ').strip()

    if choice == '1':
        print(f'\nBuildando versao {current}...')
        if _do_build():
            _do_installer()
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
            _do_installer()
            print(f'\nVersao: {new_ver}')
            _deploy(deploy_path, new_ver)
    elif choice == '3':
        version = _read_version()
        src_dir = os.path.join(HERE, 'dist', 'MBChat')
        if not os.path.isdir(src_dir):
            print(f'Erro: {src_dir} nao existe. Faca um build primeiro.')
            return
        deploy_path = input(f'Pasta de deploy [{DEFAULT_DEPLOY}]: ').strip()
        if not deploy_path:
            deploy_path = DEFAULT_DEPLOY
        _deploy(deploy_path, version)
    elif choice == '4':
        new_ver = input(f'Nova versao (atual: {current}): ').strip()
        if not new_ver:
            print('Versao nao informada, cancelado.')
            return
        _set_version(new_ver)
        print(f'\nBuildando versao {new_ver}...')
        if _do_build():
            _do_installer()
            _do_release(new_ver)
            print(f'\nVersao: {new_ver}')
    elif choice == '5':
        print('Saindo.')
    else:
        print('Opcao invalida.')


def build():
    parser = argparse.ArgumentParser(description='Build MBChat.exe')
    parser.add_argument('--version', type=str, default=None,
                        help='Define a versao (ex: 1.2.0)')
    parser.add_argument('--deploy', type=str, default=None,
                        help='Caminho para copiar exe + version.txt')
    parser.add_argument('--release', action='store_true',
                        help='Cria GitHub release com zip + instalador')
    args = parser.parse_args()

    if args.version is None and args.deploy is None and not args.release:
        _interactive()
        return

    if args.version:
        _set_version(args.version)

    version = _read_version()
    print(f'Build versao: {version}')

    if _do_build():
        _do_installer()
        print(f'Versao: {version}')
        if args.deploy:
            _deploy(args.deploy, version)
        if args.release:
            _do_release(version)


if __name__ == '__main__':
    build()
