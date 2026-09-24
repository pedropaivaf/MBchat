# test_build_release.py
# Travas do build.py que protegem o auto-update e o instalador web.
#   1. Release que JA existe (rodar --release de novo para a mesma versao):
#      o zip reenviado e outro build, com outro hash. O corpo da release
#      precisa ganhar o SHA256 NOVO (preservando as notas do sino) -- senao o
#      updater das maquinas recusa o zip e ninguem atualiza.
#   2. Setup do build anterior nunca pode ser publicado como se fosse o novo:
#      _do_installer apaga o dist/MBChat_Setup.exe velho antes de compilar, e
#      o --release aborta se o Inno Setup falhar. O instalador web baixa sempre
#      releases/latest/download/MBChat_Setup.exe -- um setup velho ali faria
#      TODO mundo que usa o instalador web instalar a versao errada.
#   3. Release sem MBChat_Setup.exe ou sem MBChat_update.zip nao e criada.
# O gh e o git sao simulados: nada e publicado.
# Rodar: python tests/test_build_release.py

import os
import sys
import types
import hashlib
import tempfile

here = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(here) if os.path.basename(here) == 'tests' else here
sys.path.insert(0, root_dir)

try:
    sys.stdout.reconfigure(errors='backslashreplace')
except Exception:
    pass

import build

PASS, FAIL = [], []


def ok(msg):
    PASS.append(msg)
    print(f'  PASS  {msg}')


def fail(msg, detail=''):
    FAIL.append(msg)
    print(f'  FAIL  {msg}' + (f': {detail}' if detail else ''))


def check(cond, msg, detail=''):
    ok(msg) if cond else fail(msg, detail)


OLD_BODY = ('Busca do historico acha palavras com acento\n'
            'Emoji da mao italiana aparece no Windows 10\n'
            '\n'
            'SHA256: ' + 'a' * 64)


class FakeRun:
    # Simula gh/git/ISCC. release_exists decide o "gh release view TAG".
    def __init__(self, release_exists=False, body=OLD_BODY, iscc_rc=0, make_setup=True):
        self.calls = []
        self.release_exists = release_exists
        self.body = body
        self.iscc_rc = iscc_rc
        self.make_setup = make_setup

    def __call__(self, cmd, *a, **k):
        self.calls.append(list(cmd))
        r = types.SimpleNamespace(returncode=0, stdout='', stderr='')
        if cmd[:2] == ['gh', 'release'] and cmd[2] == 'view':
            if '--json' in cmd:
                r.stdout = self.body + '\n'
            else:
                r.returncode = 0 if self.release_exists else 1
        elif cmd[:2] == ['git', 'rev-parse']:
            r.stdout = 'abc123\n'
        elif cmd and cmd[0] == 'ISCC.exe':
            r.returncode = self.iscc_rc
            if self.iscc_rc == 0 and self.make_setup:
                with open(os.path.join(build.HERE, 'dist', 'MBChat_Setup.exe'), 'wb') as f:
                    f.write(b'setup novo')
        return r

    def gh(self, verb):
        return [c for c in self.calls if c[:3] == ['gh', 'release', verb]]


def fresh_dist(setup=True, zip_=True, web=True):
    d = tempfile.mkdtemp(prefix='mbchat_build_')
    os.makedirs(os.path.join(d, 'dist'))
    build.HERE = d
    if zip_:
        with open(os.path.join(d, 'dist', 'MBChat_update.zip'), 'wb') as f:
            f.write(b'zip novo do build ' + os.urandom(8))
    if setup:
        with open(os.path.join(d, 'dist', 'MBChat_Setup.exe'), 'wb') as f:
            f.write(b'setup')
    if web:
        with open(os.path.join(d, 'dist', 'MBChat_WebInstaller.exe'), 'wb') as f:
            f.write(b'stub')
    return d


def zip_sha(d):
    with open(os.path.join(d, 'dist', 'MBChat_update.zip'), 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


def test_existing_release_gets_new_sha():
    print('\n[1] --release de novo numa release que ja existe')
    d = fresh_dist()
    fake = FakeRun(release_exists=True)
    build.subprocess.run = fake
    res = build._do_release('1.8.39')
    check(res is True, 'publicacao concluida')
    check(len(fake.gh('upload')) == 1 and '--clobber' in fake.gh('upload')[0],
          'assets reenviados com --clobber')
    edits = fake.gh('edit')
    check(len(edits) == 1, 'corpo da release atualizado (gh release edit)', repr(edits))
    if edits:
        body = edits[0][edits[0].index('--notes') + 1]
        check(f'SHA256: {zip_sha(d)}' in body, 'corpo tem o SHA256 do zip NOVO')
        check('a' * 64 not in body, 'SHA256 antigo removido (o updater usaria o primeiro)')
        check(body.startswith('Busca do historico acha palavras com acento\n'
                              'Emoji da mao italiana aparece no Windows 10'),
              'notas do sino preservadas', repr(body[:80]))
        check(body.count('SHA256:') == 1, 'uma unica linha SHA256')
        # o updater das maquinas extrai exatamente assim
        import updater
        check(updater._extract_sha256(body) == zip_sha(d),
              'updater._extract_sha256 le o hash novo do corpo')
    check(not fake.gh('create'), 'nao tenta criar release duplicada')


def test_existing_release_with_notes_flag():
    print('\n[2] --release de novo com --notes')
    d = fresh_dist()
    fake = FakeRun(release_exists=True)
    build.subprocess.run = fake
    build._do_release('1.8.39', notes='Nota nova 1\nNota nova 2')
    edits = fake.gh('edit')
    body = edits[0][edits[0].index('--notes') + 1] if edits else ''
    check(body == f'Nota nova 1\nNota nova 2\n\nSHA256: {zip_sha(d)}',
          'corpo = notas novas + SHA256 novo (mesmo formato da criacao)', repr(body))


def test_existing_release_without_sha_line():
    print('\n[3] release antiga sem linha SHA256')
    d = fresh_dist()
    fake = FakeRun(release_exists=True, body='MB Chat v1.8.39')
    build.subprocess.run = fake
    build._do_release('1.8.39')
    edits = fake.gh('edit')
    body = edits[0][edits[0].index('--notes') + 1] if edits else ''
    check(body == f'MB Chat v1.8.39\n\nSHA256: {zip_sha(d)}', 'SHA256 acrescentado', repr(body))


def test_new_release_unchanged():
    print('\n[4] release nova (caminho normal) continua igual')
    d = fresh_dist()
    fake = FakeRun(release_exists=False)
    build.subprocess.run = fake
    res = build._do_release('1.8.39', notes='Linha 1\nLinha 2')
    creates = fake.gh('create')
    check(res is True and len(creates) == 1, 'gh release create chamado 1 vez')
    if creates:
        c = creates[0]
        check(c[3] == 'v1.8.39', 'tag v1.8.39')
        check(c[c.index('--notes') + 1] == f'Linha 1\nLinha 2\n\nSHA256: {zip_sha(d)}',
              'corpo = notas + SHA256')
        names = sorted(os.path.basename(x) for x in c if x.endswith(('.zip', '.exe')))
        check(names == ['MBChat_Setup.exe', 'MBChat_WebInstaller.exe', 'MBChat_update.zip'],
              'os 3 assets com os nomes que o updater e o instalador web procuram', repr(names))
    check(not fake.gh('edit'), 'sem edit extra na criacao')


def test_missing_required_assets():
    print('\n[5] sem setup ou sem zip nao ha release')
    for kw, label in (({'setup': False}, 'sem MBChat_Setup.exe'),
                      ({'zip_': False}, 'sem MBChat_update.zip')):
        fresh_dist(**kw)
        fake = FakeRun(release_exists=False)
        build.subprocess.run = fake
        res = build._do_release('1.8.39')
        check(res is False and not fake.gh('create') and not fake.gh('upload'),
              f'{label}: release NAO criada')


def test_stale_setup_never_published():
    print('\n[6] setup do build anterior nunca e publicado')
    d = fresh_dist()
    setup = os.path.join(d, 'dist', 'MBChat_Setup.exe')
    build._find_iscc = lambda: 'ISCC.exe'
    build.subprocess.run = FakeRun(iscc_rc=2)
    res = build._do_installer()
    check(res is False and not os.path.exists(setup),
          'Inno falhou: setup velho apagado e _do_installer devolve False')
    fresh_dist()
    build.subprocess.run = FakeRun(iscc_rc=0, make_setup=False)
    check(build._do_installer() is False, 'Inno "ok" mas sem gerar arquivo: falha')
    d = fresh_dist()
    build.subprocess.run = FakeRun(iscc_rc=0)
    check(build._do_installer() is True and
          open(os.path.join(d, 'dist', 'MBChat_Setup.exe'), 'rb').read() == b'setup novo',
          'Inno ok: setup novo no lugar')

    # build() --release com o Inno falhando: aborta antes de publicar
    fresh_dist()
    called = []
    orig = (build._set_version, build._run_gate, build._do_build, build._do_installer,
            build._do_web_installer, build._do_release)
    build._set_version = lambda v: None
    build._run_gate = lambda r: True
    build._do_build = lambda: True
    build._do_installer = lambda: False
    build._do_web_installer = lambda: called.append('web') or True
    build._do_release = lambda *a, **k: called.append('release') or True
    argv = sys.argv
    sys.argv = ['build.py', '--version', '1.8.39', '--release']
    code = None
    try:
        build.build()
    except SystemExit as e:
        code = e.code
    finally:
        sys.argv = argv
        (build._set_version, build._run_gate, build._do_build, build._do_installer,
         build._do_web_installer, build._do_release) = orig
    check(code == 1 and 'release' not in called,
          '--release aborta (exit 1) sem publicar quando o instalador nao foi gerado',
          f'code={code} called={called}')


def test_web_installer_url_contract():
    print('\n[7] contrato do instalador web (nao muda entre versoes)')
    with open(os.path.join(root_dir, 'tools', 'installer_stub.py'), encoding='utf-8') as f:
        src = f.read()
    check("releases/latest/download/MBChat_Setup.exe" in src,
          'instalador web baixa sempre releases/latest/download/MBChat_Setup.exe')
    with open(os.path.join(root_dir, 'installer.iss'), encoding='utf-8') as f:
        iss = f.read()
    check('OutputBaseFilename=MBChat_Setup' in iss,
          'installer.iss gera exatamente MBChat_Setup.exe (nome que o instalador web procura)')
    with open(os.path.join(root_dir, 'build.py'), encoding='utf-8') as f:
        bsrc = f.read()
    check("'--prerelease'" not in bsrc and "'--draft'" not in bsrc,
          'release nunca sai como pre-release/rascunho (o /latest/ ignoraria)')


if __name__ == '__main__':
    real_run = build.subprocess.run
    try:
        test_existing_release_gets_new_sha()
        test_existing_release_with_notes_flag()
        test_existing_release_without_sha_line()
        test_new_release_unchanged()
        test_missing_required_assets()
        test_stale_setup_never_published()
        test_web_installer_url_contract()
    finally:
        build.subprocess.run = real_run
    print(f'\n{len(PASS)} PASS, {len(FAIL)} FAIL')
    print(f'{len(PASS)} passou {len(FAIL)} falhou')  # resumo lido pelo gate
    sys.exit(0 if not FAIL else 1)
