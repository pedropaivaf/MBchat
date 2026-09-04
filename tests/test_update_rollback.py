# test_update_rollback.py
# Testa o script PowerShell gerado por updater.apply_update() num sandbox real
# (pasta de install falsa + staging falso), rodando o PS de verdade.
#
# O que garante:
#   - caminho feliz continua funcionando (exe e _internal trocados, backups
#     descartados, staging/pending limpos);
#   - QUALQUER falha depois do backup restaura a versao anterior INTEIRA, em
#     vez de deixar a pasta sem _internal ou com _internal novo + exe velho —
#     o estado que produz "Failed to load Python DLL" em toda abertura
#     seguinte, mesmo sem estar atualizando;
#   - o contador de tentativas corta o loop de "app fecha sozinho e nao abre".
#
# O bloco de auto-elevacao UAC e o relancamento final sao removidos do script
# antes de rodar: o primeiro abriria prompt de UAC no meio do teste, e o
# segundo esta fora do escopo desta mudanca (logica intocada).
#
# Rodar: python tests/test_update_rollback.py

import os
import shutil
import subprocess
import sys
import tempfile

here = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(here) if os.path.basename(here) == 'tests' else here
sys.path.insert(0, root_dir)

PASS, FAIL = [], []


def ok(msg):
    PASS.append(msg)
    print(f'  PASS  {msg}')


def fail(msg, detail=''):
    FAIL.append(msg)
    print(f'  FAIL  {msg}' + (f': {detail}' if detail else ''))


OLD_EXE = b'EXE-VERSAO-ANTIGA'
NEW_EXE = b'EXE-VERSAO-NOVA-MAIOR'          # tamanho diferente de proposito
OLD_DLL = b'python314.dll VERSAO ANTIGA'
NEW_DLL = b'python314.dll VERSAO NOVA'


def build_sandbox(base, internal_files=60):
    # Pasta "instalada"
    inst = os.path.join(base, 'install')
    os.makedirs(os.path.join(inst, '_internal'), exist_ok=True)
    with open(os.path.join(inst, 'MBChat.exe'), 'wb') as f:
        f.write(OLD_EXE)
    with open(os.path.join(inst, '_internal', 'python314.dll'), 'wb') as f:
        f.write(OLD_DLL)
    for i in range(internal_files):
        with open(os.path.join(inst, '_internal', f'lib{i}.pyd'), 'wb') as f:
            f.write(b'antigo')

    # Staging com a "versao nova"
    stg = os.path.join(base, 'staging')
    os.makedirs(os.path.join(stg, '_internal'), exist_ok=True)
    with open(os.path.join(stg, 'MBChat.exe'), 'wb') as f:
        f.write(NEW_EXE)
    with open(os.path.join(stg, '_internal', 'python314.dll'), 'wb') as f:
        f.write(NEW_DLL)
    for i in range(internal_files):
        with open(os.path.join(stg, '_internal', f'lib{i}.pyd'), 'wb') as f:
            f.write(b'novo')
    return inst, stg


# O apply_update passa TODO caminho por updater._get_long_path() antes de
# escrever no script PS - e o fix documentado pro caso 8.3 (conta
# "nome.sobrenome" vira "PEDRO~1.PAI"). Entao o caminho que sai no PS pode nao
# ser, string a string, o que entrou.
#
# Estes testes comparavam a string crua do tempfile.mkdtemp() com o conteudo do
# PS. Na maquina do dev os dois batem (o temp nao e 8.3) e o teste passava; no
# runner do CI o temp fica sob C:\Users\RUNNER~1\..., a comparacao falhava e o
# teste virava falso-negativo - justamente na maquina que REPRODUZ a condicao
# 8.3 pra qual o fix existe. Normalize sempre pelo mesmo helper do codigo.
def _long(p):
    import updater
    return updater._get_long_path(p)


def gen_script(base, inst, stg):
    # Gera o update.ps1 real, sem lancar o PowerShell.
    import updater
    updater._UPDATE_DIR = base
    real_exe, real_popen = updater.sys.executable, updater.subprocess.Popen
    updater.sys.executable = os.path.join(inst, 'MBChat.exe')
    updater.subprocess.Popen = lambda *a, **kw: None
    try:
        updater.apply_update(stg)
    finally:
        updater.sys.executable = real_exe
        updater.subprocess.Popen = real_popen

    ps_path = os.path.join(base, 'update.ps1')
    with open(ps_path, encoding='utf-8') as f:
        content = f.read()
    # tira a auto-elevacao (abriria UAC) e o relancamento (fora do escopo)
    content = '$isAdmin = $true\n' + content[content.index('$LogFile ='):]
    content = content[:content.index('# Lanca o app via CreateProcess')]
    content = content.replace('Start-Sleep -Seconds 5', 'Start-Sleep -Milliseconds 50')
    content = content.replace('Start-Sleep -Seconds 2', 'Start-Sleep -Milliseconds 50')
    with open(ps_path, 'w', encoding='utf-8') as f:
        f.write(content)
    return ps_path


def run_ps(ps_path):
    r = subprocess.run(
        ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
         '-File', ps_path],
        capture_output=True, text=True, encoding='utf-8', errors='replace')
    return r.returncode, (r.stdout or '') + (r.stderr or '')


def state(inst):
    ex = os.path.join(inst, 'MBChat.exe')
    dll = os.path.join(inst, '_internal', 'python314.dll')
    return {
        'exe': open(ex, 'rb').read() if os.path.isfile(ex) else None,
        'dll': open(dll, 'rb').read() if os.path.isfile(dll) else None,
        'internal': os.path.isdir(os.path.join(inst, '_internal')),
        'bak_internal': os.path.isdir(os.path.join(inst, '_internal.bak')),
        'bak_exe': os.path.isfile(os.path.join(inst, 'MBChat.exe.bak')),
    }


def coerente(s):
    # Exe e _internal precisam ser SEMPRE do mesmo par. A mistura e o que
    # produz "Failed to load Python DLL".
    return ((s['exe'] == OLD_EXE and s['dll'] == OLD_DLL) or
            (s['exe'] == NEW_EXE and s['dll'] == NEW_DLL))


# ---------------------------------------------------------------------
def caso_sucesso():
    print('\n[1] Caminho feliz: update aplicado por completo')
    base = tempfile.mkdtemp(prefix='mbup_ok_')
    try:
        inst, stg = build_sandbox(base)
        open(os.path.join(base, 'update_pending.txt'), 'w').write(stg)
        open(os.path.join(base, 'update_attempts.txt'), 'w').write('1')
        rc, _ = run_ps(gen_script(base, inst, stg))
        s = state(inst)
        if rc == 0 and s['exe'] == NEW_EXE and s['dll'] == NEW_DLL:
            ok('exe e _internal atualizados')
        else:
            fail(f'update nao aplicou (rc={rc})', str(s)[:120])
        if not s['bak_internal'] and not s['bak_exe']:
            ok('backups descartados apos sucesso')
        else:
            fail('backups ficaram para tras')
        if not os.path.exists(os.path.join(base, 'update_pending.txt')):
            ok('update_pending.txt removido')
        else:
            fail('update_pending.txt sobrou (causaria reaplicacao no proximo boot)')
        if not os.path.exists(os.path.join(base, 'update_attempts.txt')):
            ok('update_attempts.txt removido')
        else:
            fail('contador de tentativas sobrou')
        if not os.path.isdir(stg):
            ok('staging limpo')
        else:
            fail('staging sobrou')
    finally:
        shutil.rmtree(base, ignore_errors=True)


def caso_copia_falha():
    print('\n[2] Copia falha no meio -> rollback (era o estado quebrado permanente)')
    base = tempfile.mkdtemp(prefix='mbup_cp_')
    try:
        inst, stg = build_sandbox(base)
        ps = gen_script(base, inst, stg)
        # Some com o staging depois do script gerado: o Copy-Item falha.
        shutil.rmtree(stg)
        rc, _ = run_ps(ps)
        s = state(inst)
        if rc != 0:
            ok(f'script abortou com erro (rc={rc})')
        else:
            fail('script retornou 0 mesmo com a copia falhando')
        if s['internal'] and s['dll'] == OLD_DLL and s['exe'] == OLD_EXE:
            ok('versao anterior restaurada INTEIRA (exe + _internal)')
        else:
            fail('nao restaurou', str(s)[:140])
        if coerente(s):
            ok('exe e _internal do mesmo par (nao quebra o load da DLL)')
        else:
            fail('exe e _internal de versoes diferentes -> Failed to load Python DLL')
        if not s['bak_internal'] and not s['bak_exe']:
            ok('backups limpos apos o rollback')
        else:
            fail('backups ficaram para tras')
    finally:
        shutil.rmtree(base, ignore_errors=True)


def caso_internal_incompleto():
    print('\n[3] _internal incompleto (antivirus/copia parcial) -> rollback')
    base = tempfile.mkdtemp(prefix='mbup_few_')
    try:
        inst, stg = build_sandbox(base, internal_files=60)
        # staging com poucos arquivos: reprova o sanity de _internal
        shutil.rmtree(os.path.join(stg, '_internal'))
        os.makedirs(os.path.join(stg, '_internal'))
        with open(os.path.join(stg, '_internal', 'python314.dll'), 'wb') as f:
            f.write(NEW_DLL)
        rc, _ = run_ps(gen_script(base, inst, stg))
        s = state(inst)
        if rc != 0:
            ok(f'sanity de _internal reprovou (rc={rc})')
        else:
            fail('aceitou _internal incompleto')
        if s['dll'] == OLD_DLL and s['exe'] == OLD_EXE and coerente(s):
            ok('versao anterior restaurada e coerente')
        else:
            fail('nao restaurou', str(s)[:140])
    finally:
        shutil.rmtree(base, ignore_errors=True)


def caso_exe_nao_trocado():
    print('\n[4] _internal novo + exe velho -> detectado e revertido')
    print('    (o check antigo so contava arquivos de _internal e deixava passar)')
    base = tempfile.mkdtemp(prefix='mbup_exe_')
    try:
        inst, stg = build_sandbox(base)
        ps = gen_script(base, inst, stg)
        # Simula o exe travado: o Copy-Item copia _internal (vem antes) mas
        # nao substitui o exe.
        with open(ps, encoding='utf-8') as f:
            c = f.read()
        stg_ps = _long(stg)   # o PS carrega o caminho LONGO, nao o do mkdtemp
        alvo = 'Copy-Item -Path "%s\\*"' % stg_ps
        assert alvo in c, ('padrao do Copy-Item nao encontrado no PS gerado - '
                           'o teste nao estaria simulando nada')
        c = c.replace(alvo, 'Copy-Item -Path "%s\\_internal"' % stg_ps)
        with open(ps, 'w', encoding='utf-8') as f:
            f.write(c)
        rc, _ = run_ps(ps)
        s = state(inst)
        if rc != 0:
            ok(f'exe nao substituido foi detectado (rc={rc})')
        else:
            fail('passou batido: exe velho com _internal novo')
        if coerente(s):
            ok(f'estado final coerente (exe={s["exe"]!r})')
        else:
            fail('estado misto -> Failed to load Python DLL', str(s)[:140])
    finally:
        shutil.rmtree(base, ignore_errors=True)


def caso_bak_orfao():
    print('\n[5] .bak orfao de uma tentativa anterior nao atrapalha')
    base = tempfile.mkdtemp(prefix='mbup_bak_')
    try:
        inst, stg = build_sandbox(base)
        os.makedirs(os.path.join(inst, '_internal.bak'), exist_ok=True)
        with open(os.path.join(inst, '_internal.bak', 'lixo.txt'), 'w') as f:
            f.write('sobra de execucao anterior')
        with open(os.path.join(inst, 'MBChat.exe.bak'), 'wb') as f:
            f.write(b'exe orfao')
        rc, _ = run_ps(gen_script(base, inst, stg))
        s = state(inst)
        if rc == 0 and s['exe'] == NEW_EXE and s['dll'] == NEW_DLL:
            ok('update aplicou normalmente mesmo com .bak orfao')
        else:
            fail(f'orfao atrapalhou (rc={rc})', str(s)[:140])
        if not s['bak_internal'] and not s['bak_exe']:
            ok('orfaos removidos')
        else:
            fail('orfaos sobraram')
    finally:
        shutil.rmtree(base, ignore_errors=True)


def caso_contador():
    print('\n[6] Contador de tentativas corta o loop de boot')
    import updater
    base = tempfile.mkdtemp(prefix='mbup_cnt_')
    try:
        updater._UPDATE_DIR = base
        updater.reset_update_attempts()
        seq = [updater.bump_update_attempt() for _ in range(4)]
        if seq == [1, 2, 3, 4]:
            ok(f'contador incrementa e persiste: {seq}')
        else:
            fail(f'sequencia inesperada: {seq}')

        # mark_update_ready zera o contador: um download novo nao pode herdar
        # o contador de um update velho que falhou.
        updater.mark_update_ready(os.path.join(base, 'staging'))
        n = updater.bump_update_attempt()
        if n == 1:
            ok('mark_update_ready zera o contador (update novo nao herda falhas)')
        else:
            fail(f'contador nao zerou: {n}')

        # Formato do update_pending.txt intocado — is_update_pending() devolve
        # o conteudo inteiro como caminho.
        pend = updater.is_update_pending()
        if pend == os.path.join(base, 'staging'):
            ok('update_pending.txt continua contendo so o caminho')
        else:
            fail(f'formato do pending mudou: {pend!r}')

        updater.reset_update_attempts()
        if updater.bump_update_attempt() == 1:
            ok('reset_update_attempts zera')
        else:
            fail('reset nao funcionou')
    finally:
        shutil.rmtree(base, ignore_errors=True)


if __name__ == '__main__':
    if sys.platform != 'win32':
        print('  SKIP  teste especifico de Windows/PowerShell')
        sys.exit(0)
    caso_sucesso()
    caso_copia_falha()
    caso_internal_incompleto()
    caso_exe_nao_trocado()
    caso_bak_orfao()
    caso_contador()
    print(f'\n{"=" * 56}')
    print(f'  {len(PASS)} passou   {len(FAIL)} falhou')
    print('=' * 56)
    sys.exit(0 if not FAIL else 1)
