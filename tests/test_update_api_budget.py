# test_update_api_budget.py
# Os PCs do escritorio saem pelo MESMO IP e a API do GitHub aceita 60
# chamadas/hora por IP sem login. Duas travas:
#   1. O download silencioso reaproveita a resposta da API que ACABOU de achar
#      o update (1 chamada por update em vez de 2). Com a API esgotada, a 2a
#      chamada falhava e o download nao acontecia.
#   2. Se o download silencioso falhar, o app libera o aviso para a checagem
#      periodica tentar de novo. Antes o sino ficava em "Baixando
#      atualizacao..." ate o app ser reaberto (proximo boot).
# Nada de rede de verdade: urlopen e simulado.
# Rodar: python tests/test_update_api_budget.py

import io
import os
import sys
import json
import time
import types
import hashlib
import zipfile
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

import updater

PASS, FAIL = [], []


def ok(msg):
    PASS.append(msg)
    print(f'  PASS  {msg}')


def fail(msg, detail=''):
    FAIL.append(msg)
    print(f'  FAIL  {msg}' + (f': {detail}' if detail else ''))


def check(cond, msg, detail=''):
    ok(msg) if cond else fail(msg, detail)


def make_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr('MBChat.exe', b'exe novo')
        zf.writestr('_internal/python314.dll', b'dll')
    return buf.getvalue()


ZIP = make_zip()
ZIP_SHA = hashlib.sha256(ZIP).hexdigest()
ZIP_URL = 'https://github.com/x/releases/download/v9.9.9/MBChat_update.zip'


class FakeNet:
    def __init__(self, api_ok=True):
        self.api_calls = 0
        self.zip_calls = 0
        self.api_ok = api_ok

    def __call__(self, req, timeout=10):
        url = req.full_url if hasattr(req, 'full_url') else str(req)
        if 'api.github.com' in url:
            self.api_calls += 1
            if not self.api_ok:
                raise OSError('HTTP Error 403: rate limit exceeded')
            data = json.dumps({'tag_name': 'v9.9.9', 'body': f'Nota 1\n\nSHA256: {ZIP_SHA}',
                               'assets': [{'name': 'MBChat_update.zip',
                                           'browser_download_url': ZIP_URL}]}).encode()
            return _Resp(data)
        if url == ZIP_URL:
            self.zip_calls += 1
            return _Resp(ZIP)
        raise OSError(f'url inesperada {url}')


class _Resp(io.BytesIO):
    def __init__(self, data):
        super().__init__(data)
        self.headers = {'Content-Length': str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def reset(net):
    updater._UPDATE_DIR = tempfile.mkdtemp(prefix='mbchat_upd_')
    updater._urlopen_with_fallback = net
    updater._LAST_FOUND['at'] = 0.0
    updater._LAST_FOUND['result'] = None


def test_one_api_call_per_update():
    print('\n[1] checagem + download = 1 chamada a API')
    net = FakeNet()
    reset(net)
    has, ver, url, notes, sha = updater.check_update_github()
    check(has and ver == '9.9.9' and url == ZIP_URL and sha == ZIP_SHA, 'checagem acha o update')
    staging = updater.download_update()
    check(staging and os.path.isfile(os.path.join(staging, 'MBChat.exe')),
          'download + SHA256 + extracao ok')
    check(net.api_calls == 1, 'API consultada 1 vez so (antes: 2)', str(net.api_calls))
    check(net.zip_calls == 1, 'zip baixado 1 vez', str(net.zip_calls))


def test_download_survives_exhausted_api():
    print('\n[2] API esgota entre a checagem e o download')
    net = FakeNet()
    reset(net)
    updater.check_update_github()
    net.api_ok = False  # limite de 60/h estourou logo depois
    staging = updater.download_update()
    check(bool(staging), 'download acontece mesmo com a API respondendo 403 (usa a resposta anterior)')


def test_p2p_path_calls_api_once():
    print('\n[3] aviso veio da rede (P2P), sem checagem previa')
    net = FakeNet()
    reset(net)
    staging = updater.download_update()
    check(bool(staging) and net.api_calls == 1, 'consulta a API 1 vez e baixa', str(net.api_calls))


def test_cache_expires():
    print('\n[4] resposta guardada vence em 15 min')
    net = FakeNet()
    reset(net)
    updater.check_update_github()
    updater._LAST_FOUND['at'] = time.monotonic() - updater._LAST_FOUND_TTL - 1
    updater.download_update()
    check(net.api_calls == 2, 'depois de 15 min consulta a API de novo', str(net.api_calls))


def test_no_update_not_cached():
    print('\n[5] sem update nao guarda nada')
    net = FakeNet()
    reset(net)
    real = updater.APP_VERSION
    updater.APP_VERSION = '9.9.9'
    try:
        has = updater.check_update_github()[0]
    finally:
        updater.APP_VERSION = real
    check(not has and updater._LAST_FOUND['result'] is None, 'versao igual: nada guardado')
    net.api_ok = False
    check(updater.check_update_github()[0] is False, 'API com erro: sem update, sem excecao')
    check(updater._LAST_FOUND['result'] is None, 'erro da API nao guarda nada')


def test_bad_sha_still_rejected():
    print('\n[6] SHA256 errado continua recusado com a resposta guardada')
    net = FakeNet()
    reset(net)
    updater.check_update_github()
    r = list(updater._LAST_FOUND['result'])
    r[4] = '0' * 64
    updater._LAST_FOUND['result'] = tuple(r)
    check(updater.download_update() is None, 'zip com hash diferente do publicado: abortado')


def _fake_app():
    import gui
    app = types.SimpleNamespace()
    app._pending_update = None
    app._update_ready_to_install = False
    app._is_downloading_update = False
    app.badge = []
    app._refresh_bell_badge = lambda: app.badge.append(app._pending_update)
    app.root = types.SimpleNamespace(after=lambda ms, fn: fn())
    app.messenger = types.SimpleNamespace(db=types.SimpleNamespace(get_setting=lambda k, d='': d))
    app.show = lambda v, n='': gui.LanMessengerApp._show_update_bar(app, v, n)
    return app


def _wait(pred, t=5):
    end = time.time() + t
    while time.time() < end and not pred():
        time.sleep(0.02)
    return pred()


def test_gui_retries_after_failed_download():
    print('\n[7] sino: download que falha libera nova tentativa')
    orig = (updater.is_update_pending, updater.download_update, updater.mark_update_ready)
    try:
        updater.is_update_pending = lambda: None
        updater.download_update = lambda *a, **k: None  # falhou
        app = _fake_app()
        app.show('9.9.9', 'Nota')
        check(app._pending_update is not None or app.badge, 'sino marcou o update ao receber o aviso')
        done = _wait(lambda: not app._is_downloading_update)
        check(done and app._pending_update is None,
              'falhou: aviso liberado para a checagem periodica tentar de novo',
              repr(app._pending_update))
        check(app.badge and app.badge[-1] is None, 'sino atualizado (sem "Baixando..." preso)')
        check(not app._update_ready_to_install, 'nao oferece "Reiniciar para Atualizar"')

        updater.download_update = lambda *a, **k: '/tmp/staging'
        updater.mark_update_ready = lambda s: True
        app.show('9.9.9', 'Nota')  # proxima checagem periodica
        done = _wait(lambda: app._update_ready_to_install)
        check(done and app._pending_update == {'version': '9.9.9', 'notes': 'Nota'},
              'nova tentativa baixa e oferece "Reiniciar para Atualizar"')
    finally:
        updater.is_update_pending, updater.download_update, updater.mark_update_ready = orig


if __name__ == '__main__':
    real_open = updater._urlopen_with_fallback
    try:
        test_one_api_call_per_update()
        test_download_survives_exhausted_api()
        test_p2p_path_calls_api_once()
        test_cache_expires()
        test_no_update_not_cached()
        test_bad_sha_still_rejected()
        test_gui_retries_after_failed_download()
    finally:
        updater._urlopen_with_fallback = real_open
    print(f'\n{len(PASS)} PASS, {len(FAIL)} FAIL')
    print(f'{len(PASS)} passou {len(FAIL)} falhou')  # resumo lido pelo gate
    sys.exit(0 if not FAIL else 1)
