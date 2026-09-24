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
import hashlib
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
    # Versao removida do hero badge da landing page (so aparece em Ajuda > Sobre)
    pass


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
    from tools.create_icon import save_icon
    save_icon(ICON)

    # Gera VERSIONINFO para reduzir falsos positivos de antivirus
    from tools.make_version_info import generate_version_info
    version_info_path = os.path.join(HERE, 'file_version_info.txt')
    generate_version_info(version_info_path)
    manifest_path = os.path.join(HERE, 'MBChat.exe.manifest')

    cmd = [
        sys.executable, '-m', 'PyInstaller',
        '--noconfirm',
        '--onedir',
        '--windowed',
        '--noupx',
        f'--icon={ICON}',
        f'--version-file={version_info_path}',
        f'--manifest={manifest_path}',
        f'--add-data={os.path.join(HERE, "assets")};assets',
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
        '--hidden-import=windnd',
        '--hidden-import=win32com.client',
        '--hidden-import=win32com.propsys',
        '--hidden-import=win32com.shell',
        '--hidden-import=pythoncom',
        '--name=MBChat',
        '--clean',
        MAIN,
    ]

    # Inclui pasta sounds/ se existir (arquivos WAV/MP3 estilo MSN).
    # Inserido antes do --name para manter ordem de --add-data agrupada.
    sounds_dir = os.path.join(HERE, 'sounds')
    if os.path.isdir(sounds_dir):
        assets_flag = f'--add-data={os.path.join(HERE, "assets")};assets'
        cmd.insert(cmd.index(assets_flag) + 1,
                   f'--add-data={sounds_dir};sounds')

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

    # Apaga o setup do build anterior ANTES de compilar: se o Inno falhar, nao
    # pode sobrar um MBChat_Setup.exe velho em dist/ para o --release publicar
    # como se fosse o novo (o instalador web baixa sempre o da ultima release).
    setup = os.path.join(HERE, 'dist', 'MBChat_Setup.exe')
    if os.path.isfile(setup):
        os.remove(setup)

    print('Compilando instalador (Inno Setup)...')
    result = subprocess.run([iscc, ISS_FILE], cwd=HERE, capture_output=True, text=True)

    if result.returncode != 0:
        print(f'Erro no Inno Setup (codigo {result.returncode})')
        if result.stderr:
            print(result.stderr)
        if result.stdout:
            print(result.stdout[-500:])
        return False

    if not os.path.isfile(setup):
        print('Erro: Inno Setup terminou sem gerar dist/MBChat_Setup.exe')
        return False
    print(f'Instalador gerado! -> {setup}')
    return True


# Stub de instalador que baixa a versao mais recente do MBChat_Setup.exe
# do GitHub Releases e executa. Uso: usuario baixa uma vez e sempre que
# executar pega a versao atual, sem precisar atualizar depois no app.
def _do_web_installer():
    stub_src = os.path.join(HERE, 'tools', 'installer_stub.py')
    if not os.path.isfile(stub_src):
        print('AVISO: installer_stub.py nao encontrado, pulando web installer.')
        return False

    print('Gerando MBChat_WebInstaller (stub que baixa versao mais recente)...')
    out = os.path.join(HERE, 'dist', 'MBChat_WebInstaller.exe')
    if os.path.isfile(out):
        os.remove(out)
    cmd = [
        sys.executable, '-m', 'PyInstaller',
        '--noconfirm', '--onefile', '--console',
        f'--icon={ICON}',
        '--distpath', os.path.join(HERE, 'dist'),
        '--workpath', os.path.join(HERE, 'build', 'web_installer'),
        '--specpath', os.path.join(HERE, 'build'),
        '--name=MBChat_WebInstaller',
        '--clean',
        stub_src,
    ]
    result = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True)
    if result.returncode != 0:
        print(f'Erro no build do web installer (codigo {result.returncode})')
        if result.stderr:
            print(result.stderr[-500:])
        return False
    if os.path.isfile(out):
        print(f'Web installer gerado! -> {out}')
        return True
    return False


def _do_release(version, notes=''):
    try:
        subprocess.run(['gh', '--version'], capture_output=True, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        print('AVISO: GitHub CLI (gh) nao encontrado. Release nao criada.')
        return False

    update_zip = os.path.join(HERE, 'dist', 'MBChat_update.zip')
    setup = os.path.join(HERE, 'dist', 'MBChat_Setup.exe')
    web_inst = os.path.join(HERE, 'dist', 'MBChat_WebInstaller.exe')
    tag = f'v{version}'

    # zip e setup sao obrigatorios: sem o zip o auto-update nao acha o que
    # baixar; sem o MBChat_Setup.exe o instalador web (que sempre baixa
    # releases/latest/download/MBChat_Setup.exe) quebra com 404 para todos.
    faltando = [os.path.basename(p) for p in (update_zip, setup) if not os.path.isfile(p)]
    if faltando:
        print(f'ERRO: faltam artefatos obrigatorios em dist/: {", ".join(faltando)}')
        print('Release NAO criada.')
        return False
    assets = [update_zip, setup]
    if os.path.isfile(web_inst):
        assets.append(web_inst)

    sha256_line = ''
    if os.path.isfile(update_zip):
        h = hashlib.sha256()
        with open(update_zip, 'rb') as f:
            for chunk in iter(lambda: f.read(65536), b''):
                h.update(chunk)
        sha256_line = f'\n\nSHA256: {h.hexdigest()}'

    if notes:
        release_notes = f'{notes}{sha256_line}'
    else:
        release_notes = f'MB Chat {tag}{sha256_line}'

    # O `gh release create` cria a tag no HEAD DO REMOTO. Se o bump de versao
    # ainda nao foi commitado e enviado, a tag nasce apontando pra um commit
    # onde version.py tem a versao ANTERIOR — foi o que aconteceu na v1.8.38 e
    # so apareceu conferindo `git show v1.8.38:version.py` depois.
    # Quem clonar a tag pega codigo que se identifica com a versao errada.
    sujo = subprocess.run(['git', 'status', '--porcelain', 'version.py',
                           'installer.iss'],
                          capture_output=True, text=True, cwd=HERE)
    if sujo.returncode == 0 and sujo.stdout.strip():
        print('\nERRO: version.py/installer.iss ainda nao estao commitados.')
        print('A tag sairia apontando pra um commit com a versao ANTERIOR.')
        print('\nFaca antes:')
        print(f'  git add -A && git commit -m "release: v{version}" && git push')
        print('\nDepois rode de novo com --release (o build ja esta pronto em dist/).')
        return False

    local = subprocess.run(['git', 'rev-parse', 'HEAD'],
                           capture_output=True, text=True, cwd=HERE)
    remoto = subprocess.run(['git', 'rev-parse', '@{u}'],
                            capture_output=True, text=True, cwd=HERE)
    if (local.returncode == 0 and remoto.returncode == 0
            and local.stdout.strip() != remoto.stdout.strip()):
        print('\nERRO: HEAD local difere do remoto — falta `git push`.')
        print('A tag sairia no commit antigo do GitHub, sem as mudancas desta versao.')
        return False

    check = subprocess.run(['gh', 'release', 'view', tag], capture_output=True, cwd=HERE)
    if check.returncode == 0:
        print(f'Release {tag} ja existe, atualizando assets...')
        cmd = ['gh', 'release', 'upload', tag, '--clobber'] + assets
    else:
        print(f'Criando release {tag}...')
        cmd = ['gh', 'release', 'create', tag,
               '--title', f'MB Chat {tag}',
               '--notes', release_notes] + assets

    result = subprocess.run(cmd, cwd=HERE)
    if result.returncode != 0:
        print(f'Erro ao criar/atualizar release (codigo {result.returncode})')
        return False

    # Release que ja existia: o zip reenviado e outro build, com OUTRO hash.
    # O corpo continuaria com o SHA256 antigo e o updater das maquinas
    # recusaria o zip ("update corrompido") -- ninguem atualizaria. Troca so a
    # linha SHA256 do corpo, preservando as notas que aparecem no sino.
    if check.returncode == 0 and sha256_line:
        if not _update_release_sha(tag, sha256_line.strip(), notes):
            print('ERRO: assets reenviados mas o SHA256 do corpo da release NAO foi '
                  'atualizado.')
            print(f'As maquinas vao recusar o zip. Corrija com: gh release edit {tag} '
                  '--notes "..."')
            return False

    print(f'Release {tag} publicada no GitHub!')
    return True


# Troca a linha "SHA256: ..." do corpo de uma release existente (ou acrescenta,
# se nao houver). Com --notes, o corpo vira notes + SHA256, igual a criacao.
def _update_release_sha(tag, sha_line, notes=''):
    if notes:
        body = f'{notes}\n\n{sha_line}'
    else:
        cur = subprocess.run(['gh', 'release', 'view', tag, '--json', 'body',
                              '-q', '.body'], capture_output=True, text=True, cwd=HERE)
        if cur.returncode != 0:
            return False
        body = _replace_sha_line(cur.stdout.rstrip('\n'), sha_line)
    edit = subprocess.run(['gh', 'release', 'edit', tag, '--notes', body], cwd=HERE)
    return edit.returncode == 0


def _replace_sha_line(body, sha_line):
    if re.search(r'^\s*SHA256:.*$', body, re.IGNORECASE | re.MULTILINE):
        return re.sub(r'^\s*SHA256:.*$', sha_line, body, count=1,
                      flags=re.IGNORECASE | re.MULTILINE)
    return f'{body}\n\n{sha_line}' if body.strip() else sha_line


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
            _do_web_installer()
            _do_release(new_ver)
            print(f'\nVersao: {new_ver}')
    elif choice == '5':
        print('Saindo.')
    else:
        print('Opcao invalida.')


# Roda tools/prerelease_check.py. Devolve True se o gate abriu.
#
# POR QUE ISSO BLOQUEIA O BUILD
# A v1.8.37 saiu com uma regressao de janela que passou por tudo: o codigo
# importava, o build gerou, a release subiu — e so apareceu depois de instalada
# nas 30 maquinas. Nao havia nenhum ponto no caminho obrigado a dizer "nao".
# Agora ha: sem gate aberto, nao existe release.
def _run_gate(release_mode):
    script = os.path.join(HERE, 'tools', 'prerelease_check.py')
    if not os.path.isfile(script):
        print('AVISO: tools/prerelease_check.py nao encontrado — gate PULADO.')
        return True
    cmd = [sys.executable, script]
    if release_mode:
        cmd += ['--release', '--allow-version-bump']
    print('\n' + '=' * 62)
    print('  Rodando gate de verificacao antes de gerar artefatos...')
    print('=' * 62)
    return subprocess.run(cmd, cwd=HERE).returncode == 0


def build():
    parser = argparse.ArgumentParser(description='Build MBChat.exe')
    parser.add_argument('--version', type=str, default=None,
                        help='Define a versao (ex: 1.2.0)')
    parser.add_argument('--deploy', type=str, default=None,
                        help='Caminho para copiar exe + version.txt')
    parser.add_argument('--release', action='store_true',
                        help='Cria GitHub release com zip + instalador')
    parser.add_argument('--notes', type=str, default='',
                        help='Texto das release notes (substitui o padrao)')
    parser.add_argument('--skip-checks', action='store_true',
                        help='NAO USE para publicar: pula o gate de verificacao. '
                             'Existe so para build local de teste.')
    args = parser.parse_args()

    if args.version is None and args.deploy is None and not args.release:
        _interactive()
        return

    if args.version:
        _set_version(args.version)

    version = _read_version()
    print(f'Build versao: {version}')

    # Gate ANTES de gerar qualquer artefato: se algo esta quebrado, nem chega a
    # existir exe/instalador/zip pra alguem publicar por engano.
    if args.skip_checks:
        print('\n*** ATENCAO: --skip-checks ativo. Gate de verificacao PULADO. ***')
        if args.release:
            print('*** Publicar sem o gate e exatamente como a v1.8.37 quebrou. ***')
    elif not _run_gate(args.release):
        print('\nBuild ABORTADO: o gate de verificacao reprovou (veja as falhas acima).')
        print('Corrija e rode de novo. Para build local de teste: --skip-checks')
        sys.exit(1)

    if not _do_build():
        sys.exit(1)
    installer_ok = _do_installer()
    if args.release and not installer_ok:
        # Sem setup novo nao ha release: o instalador web baixaria o setup da
        # ultima release, e ele precisa ser DESTA versao.
        print('\nRelease ABORTADA: o instalador (Inno Setup) nao foi gerado.')
        sys.exit(1)
    if args.release:
        _do_web_installer()
    print(f'Versao: {version}')
    if args.deploy:
        _deploy(args.deploy, version)
    if args.release:
        if not _do_release(version, notes=getattr(args, 'notes', '')):
            sys.exit(1)


if __name__ == '__main__':
    build()
