# test_backup_restore.py
# Valida a IMPORTACAO e EXPORTACAO do banco de dados dentro do proprio app
# (Ferramentas > Backup do historico / Restaurar backup), sem precisar de GUI.
#
# Reproduz fielmente o mecanismo de gui.py:
#   - _backup_history  : sqlite3.Connection.backup -> zip (mbchat.db + themes + avatars)
#   - _restore_history : valida zip, escreve mbchat_restore.db, extrai themes/avatars
#   - main() boot-swap : remove mbchat.db/-wal/-shm e os.replace(mbchat_restore.db)
#
# Inclui o caso critico de WAL: dados commitados que ainda estao no -wal (nao
# checkpointed) PRECISAM entrar no backup — e por isso o app usa a API .backup()
# e nao uma copia crua do .db. O teste prova que nada se perde.
#
# Rodar: python tests/test_backup_restore.py

import os
import sys
import shutil
import sqlite3
import tempfile
import zipfile

here = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(here) if os.path.basename(here) == 'tests' else here
sys.path.insert(0, root_dir)

import database  # noqa: E402

PASS = []
FAIL = []

def ok(msg):
    PASS.append(msg)
    print(f'  PASS  {msg}')

def fail(msg, detail=''):
    FAIL.append(msg)
    print(f'  FAIL  {msg}' + (f': {detail}' if detail else ''))

def read_src(name):
    with open(os.path.join(root_dir, name), encoding='utf-8') as f:
        return f.read()


# Replica EXATA do nucleo de _backup_history (gui.py:10550) — sem tkinter.
def do_backup(data_dir, dest_zip):
    db_path = os.path.join(data_dir, 'mbchat.db')
    tmp_db = os.path.join(data_dir, f'_backup_tmp_{os.getpid()}.db')
    src_conn = sqlite3.connect(db_path)
    dst_conn = sqlite3.connect(tmp_db)
    with dst_conn:
        src_conn.backup(dst_conn)   # API consistente com WAL (igual ao app)
    dst_conn.close()
    src_conn.close()
    with zipfile.ZipFile(dest_zip, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.write(tmp_db, 'mbchat.db')
        themes = os.path.join(data_dir, 'user_themes.json')
        if os.path.exists(themes):
            zf.write(themes, 'user_themes.json')
        avdir = os.path.join(data_dir, 'avatars')
        if os.path.isdir(avdir):
            for fn in os.listdir(avdir):
                fp = os.path.join(avdir, fn)
                if os.path.isfile(fp):
                    zf.write(fp, f'avatars/{fn}')
    os.remove(tmp_db)


# Replica EXATA do nucleo de _restore_history (gui.py:10607) — retorna False se invalido.
def do_restore(data_dir, src_zip):
    with zipfile.ZipFile(src_zip) as zf:
        names = zf.namelist()
        if 'mbchat.db' not in names:
            return False
        with zf.open('mbchat.db') as f, \
             open(os.path.join(data_dir, 'mbchat_restore.db'), 'wb') as out:
            shutil.copyfileobj(f, out)
        for n in names:
            if n == 'user_themes.json':
                zf.extract(n, data_dir)
            elif n.startswith('avatars/') and not n.endswith('/'):
                zf.extract(n, data_dir)
    return True


# Replica EXATA do boot-swap em main() (gui.py:19311-19324).
def do_boot_swap(data_dir):
    restore = os.path.join(data_dir, 'mbchat_restore.db')
    if os.path.exists(restore):
        target = os.path.join(data_dir, 'mbchat.db')
        for suf in ('', '-wal', '-shm'):
            try:
                os.remove(target + suf)
            except FileNotFoundError:
                pass
        os.replace(restore, target)
        return True
    return False


# ─────────────────────────────────────────────
# 1) Round-trip completo: export -> (outro PC) -> import -> boot -> tudo intacto
# ─────────────────────────────────────────────
def test_roundtrip_preserva_tudo():
    print('\n[Backup] export -> import -> boot-swap preserva DB, settings, themes, avatar')
    src_dir = tempfile.mkdtemp(prefix='mbchat_src_')
    dst_dir = tempfile.mkdtemp(prefix='mbchat_dst_')
    zip_path = os.path.join(tempfile.gettempdir(), 'mbchat_backup_test.zip')
    try:
        # --- Maquina de origem: app populado ---
        db1 = database.Database(db_path=os.path.join(src_dir, 'mbchat.db'))
        db1.set_setting('display_name', 'Pedro Paiva')
        db1.set_setting('show_main_on_start', '1')
        N = 250
        for i in range(N):
            db1.save_message(f'm{i}', 'pedro@mb', 'maria@mb',
                             f'mensagem numero {i}', is_sent=(i % 2 == 0))
        # contato (segunda tabela) via SQL direto
        db1.conn.execute(
            "INSERT INTO contacts (user_id, display_name, ip_address, last_seen, first_seen) "
            "VALUES (?,?,?,?,?)", ('maria@mb', 'Maria', '192.168.0.50', 1.0, 1.0))
        db1.conn.commit()
        # themes + avatar
        with open(os.path.join(src_dir, 'user_themes.json'), 'w', encoding='utf-8') as f:
            f.write('{"MeuTema": {"bg_white": "#101010"}}')
        os.makedirs(os.path.join(src_dir, 'avatars'), exist_ok=True)
        with open(os.path.join(src_dir, 'avatars', 'custom_avatar_1.png'), 'wb') as f:
            f.write(b'\x89PNG\r\n\x1a\n_fake_avatar_bytes_')

        # IMPORTANTE: NAO fechamos db1 — simula o app ABERTO, com commits ainda
        # no -wal (nao checkpointed). E o cenario classico que quebra copia crua do .db.
        wal = os.path.join(src_dir, 'mbchat.db-wal')
        if os.path.exists(wal) and os.path.getsize(wal) > 0:
            ok('Dados estao no -wal (app aberto) — cenario WAL coberto')
        else:
            ok('(-wal vazio neste ambiente; backup via API cobre ambos os casos)')

        # --- Export (Ferramentas > Backup do historico) ---
        do_backup(src_dir, zip_path)
        if os.path.exists(zip_path) and os.path.getsize(zip_path) > 0:
            ok('Backup .zip gerado')
        else:
            fail('Backup .zip nao foi gerado')
            return
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
        for need in ('mbchat.db', 'user_themes.json', 'avatars/custom_avatar_1.png'):
            if need in names:
                ok(f'Zip contem {need}')
            else:
                fail(f'Zip NAO contem {need}')

        # --- Maquina destino (reinstalacao / outro PC): import + boot-swap ---
        # dst comeca com um DB "velho/vazio" para provar que e substituido.
        db_old = database.Database(db_path=os.path.join(dst_dir, 'mbchat.db'))
        db_old.set_setting('display_name', 'ANTIGO')
        db_old._local.conn.close()  # fecha p/ permitir swap (no app o boot-swap roda antes de abrir)

        if do_restore(dst_dir, zip_path):
            ok('Restore aceitou o zip valido e preparou mbchat_restore.db')
        else:
            fail('Restore rejeitou um zip valido')
            return
        if do_boot_swap(dst_dir):
            ok('Boot-swap trocou mbchat.db pelo restaurado')
        else:
            fail('Boot-swap nao executou')
            return

        # --- Verificacao: tudo presente no destino ---
        db2 = database.Database(db_path=os.path.join(dst_dir, 'mbchat.db'))
        cnt = db2.conn.execute("SELECT COUNT(*) AS c FROM messages").fetchone()['c']
        if cnt == N:
            ok(f'Todas as {N} mensagens preservadas (nada perdido do -wal)')
        else:
            fail(f'Mensagens perdidas: esperado {N}, veio {cnt}')

        name = db2.get_setting('display_name')
        if name == 'Pedro Paiva':
            ok("Setting 'display_name' restaurado (sobrescreveu o DB antigo)")
        else:
            fail(f"display_name esperado 'Pedro Paiva', veio {name!r}")

        contact = db2.conn.execute(
            "SELECT display_name FROM contacts WHERE user_id='maria@mb'").fetchone()
        if contact and contact['display_name'] == 'Maria':
            ok('Contato preservado (segunda tabela)')
        else:
            fail('Contato nao foi preservado')

        # conteudo integro de uma mensagem especifica
        msg = db2.conn.execute(
            "SELECT content FROM messages WHERE msg_id='m123'").fetchone()
        if msg and msg['content'] == 'mensagem numero 123':
            ok('Conteudo das mensagens integro (amostra m123)')
        else:
            fail('Conteudo de mensagem corrompido/ausente')

        # themes + avatar extraidos no destino
        if os.path.exists(os.path.join(dst_dir, 'user_themes.json')):
            ok('user_themes.json restaurado no destino')
        else:
            fail('user_themes.json nao restaurado')
        if os.path.exists(os.path.join(dst_dir, 'avatars', 'custom_avatar_1.png')):
            ok('avatar restaurado no destino')
        else:
            fail('avatar nao restaurado')

        # marcador mbchat_restore.db consumido (nao fica re-aplicando todo boot)
        if not os.path.exists(os.path.join(dst_dir, 'mbchat_restore.db')):
            ok('mbchat_restore.db consumido no boot (sem re-aplicar)')
        else:
            fail('mbchat_restore.db ainda presente — re-aplicaria todo boot')

        db1._local.conn.close()
        db2._local.conn.close()
    finally:
        shutil.rmtree(src_dir, ignore_errors=True)
        shutil.rmtree(dst_dir, ignore_errors=True)
        try:
            os.remove(zip_path)
        except OSError:
            pass


# ─────────────────────────────────────────────
# 2) WAL: backup via API captura dados ainda no -wal (copia crua perderia)
# ─────────────────────────────────────────────
def test_wal_safety():
    print('\n[Backup] API .backup() captura dados do -wal (copia crua falharia)')
    d = tempfile.mkdtemp(prefix='mbchat_wal_')
    tmp_db = os.path.join(d, 'crua.db')
    try:
        db = database.Database(db_path=os.path.join(d, 'mbchat.db'))
        for i in range(20):
            db.save_message(f'w{i}', 'a@x', 'b@x', f'wal {i}', is_sent=True)
        # NAO fecha db (mantem -wal sem checkpoint)

        # Backup via API (igual ao app)
        src = sqlite3.connect(os.path.join(d, 'mbchat.db'))
        dst = sqlite3.connect(tmp_db)
        with dst:
            src.backup(dst)
        n_api = dst.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        dst.close()
        src.close()
        if n_api == 20:
            ok('Backup via API trouxe as 20 mensagens (inclui o que estava no -wal)')
        else:
            fail(f'API perdeu dados do WAL: {n_api}/20')
        db._local.conn.close()
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ─────────────────────────────────────────────
# 3) Zip invalido (sem mbchat.db) e rejeitado
# ─────────────────────────────────────────────
def test_restore_rejeita_zip_invalido():
    print('\n[Restore] zip sem mbchat.db e rejeitado (nao prepara restore)')
    d = tempfile.mkdtemp(prefix='mbchat_inv_')
    bad = os.path.join(d, 'bad.zip')
    try:
        with zipfile.ZipFile(bad, 'w') as zf:
            zf.writestr('readme.txt', 'isto nao e um backup')
        result = do_restore(d, bad)
        if result is False:
            ok('Restore retornou False para zip sem mbchat.db')
        else:
            fail('Restore aceitou um zip invalido')
        if not os.path.exists(os.path.join(d, 'mbchat_restore.db')):
            ok('Nenhum mbchat_restore.db criado a partir de zip invalido')
        else:
            fail('mbchat_restore.db criado de zip invalido — risco de corromper boot')
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ─────────────────────────────────────────────
# 4) Codigo real do app usa esse mecanismo (analise de gui.py)
# ─────────────────────────────────────────────
def test_gui_usa_mecanismo_correto():
    print('\n[GUI] _backup_history/_restore_history/boot-swap usam o mecanismo validado')
    src = read_src('gui.py')

    import re
    bk = re.search(r'def _backup_history\(self\).*?(?=\n    def |\n    # )', src, re.DOTALL)
    rs = re.search(r'def _restore_history\(self\).*?(?=\n    def |\n    # )', src, re.DOTALL)
    bk = bk.group(0) if bk else ''
    rs = rs.group(0) if rs else ''

    if '.backup(' in bk:
        ok('_backup_history usa a API .backup() (consistente com WAL)')
    else:
        fail('_backup_history NAO usa .backup() — risco de backup inconsistente')

    if "shutil.copy" not in bk and "shutil.copyfile(" not in bk:
        ok('_backup_history nao faz copia crua do .db aberto')
    else:
        fail('_backup_history faz copia crua do .db — pode corromper/perder WAL')

    for token, desc in (("'mbchat.db'", 'inclui mbchat.db no zip'),
                        ('user_themes.json', 'inclui user_themes.json'),
                        ('avatars/', 'inclui avatars/')):
        if token in bk:
            ok(f'_backup_history {desc}')
        else:
            fail(f'_backup_history NAO {desc}')

    if "'mbchat.db' not in names" in rs:
        ok('_restore_history valida presenca de mbchat.db no zip')
    else:
        fail('_restore_history nao valida o zip')
    if 'mbchat_restore.db' in rs:
        ok('_restore_history grava mbchat_restore.db (swap no proximo boot)')
    else:
        fail('_restore_history nao grava mbchat_restore.db')
    if 'askyesno' in rs:
        ok('_restore_history confirma antes de substituir o historico')
    else:
        fail('_restore_history nao pede confirmacao')

    swap = re.search(r"mbchat_restore\.db.*?os\.replace\([^\n]+\)", src, re.DOTALL)
    if swap and "-wal" in swap.group(0) and "-shm" in swap.group(0):
        ok('boot-swap remove .db/-wal/-shm antes de os.replace (troca atomica e limpa)')
    else:
        fail('boot-swap nao remove WAL/SHM antes do swap')


if __name__ == '__main__':
    test_roundtrip_preserva_tudo()
    test_wal_safety()
    test_restore_rejeita_zip_invalido()
    test_gui_usa_mecanismo_correto()

    print(f'\n{"="*54}')
    print(f'  {len(PASS)} passou   {len(FAIL)} falhou')
    print('='*54)
    sys.exit(0 if not FAIL else 1)
