# Gate de verificacao do MB Chat — o portao unico entre o codigo e os 30 PCs.
#
# POR QUE ISSO EXISTE
# A v1.8.37 saiu com uma regressao que ninguem viu: o fix multi-monitor trocou a
# referencia de centralizacao de janela e TODA janela secundaria passou a abrir
# colada na principal em vez de no centro da tela. O codigo importava, os testes
# de entao passavam, o build gerou, a release subiu — e o problema so apareceu
# quando ja estava instalado em todo mundo.
#
# A licao nao e "testar mais", e "ter UM lugar por onde tudo passa". Este script
# e esse lugar: roda identico na sua maquina (chamado pelo build.py antes de
# publicar) e no GitHub Actions (a cada push). Se ele fecha, nada sai.
#
# Uso:
#   python tools/prerelease_check.py             -> gate de desenvolvimento
#   python tools/prerelease_check.py --release   -> + exigencias de publicacao
#                                                   (sem -dev, versoes casadas,
#                                                    arvore git limpa)
#
# Sai com 0 se tudo passou, 1 se qualquer verificacao falhou.

import argparse
import ast
import io
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

PASS = []
FAIL = []
SKIP = []

# Modulos do app (nao inclui build.py/tools, que nao vao no executavel)
APP_MODULES = ['gui.py', 'messenger.py', 'network.py', 'database.py',
               'updater.py', 'version.py', 'audio_recorder.py']
IMPORTABLE = ['gui', 'messenger', 'network', 'database', 'updater', 'version',
              'audio_recorder']


def ok(msg):
    PASS.append(msg)
    print(f'  PASS  {msg}')


def fail(msg, detail=''):
    FAIL.append(msg)
    print(f'  FAIL  {msg}' + (f'\n        {detail}' if detail else ''))


def skip(msg, detail=''):
    SKIP.append(msg)
    print(f'  SKIP  {msg}' + (f' ({detail})' if detail else ''))


def head(title):
    print(f'\n{title}')
    print('-' * len(title))


def read(rel):
    # utf-8-sig e nao utf-8: alguns arquivos do repo tem BOM (test_modern_pb.py).
    # O Python roda esses arquivos numa boa, mas ast.parse recusa o U+FEFF —
    # ler com utf-8 aqui acusava "erro de sintaxe" em arquivo perfeitamente valido.
    with io.open(os.path.join(ROOT, rel), encoding='utf-8-sig') as f:
        return f.read()


# ─────────────────────────────────────────────────────────────
# 1) Sintaxe — ast.parse em tudo que e Python
# ─────────────────────────────────────────────────────────────
def check_syntax():
    head('[1] Sintaxe (ast.parse)')
    targets = []
    for name in sorted(os.listdir(ROOT)):
        if name.endswith('.py'):
            targets.append(name)
    for name in sorted(os.listdir(HERE)):
        if name.endswith('.py'):
            targets.append(os.path.join('tools', name))
    tests_dir = os.path.join(ROOT, 'tests')
    if os.path.isdir(tests_dir):
        for name in sorted(os.listdir(tests_dir)):
            if name.endswith('.py'):
                targets.append(os.path.join('tests', name))

    bad = []
    for rel in targets:
        try:
            ast.parse(read(rel))
        except SyntaxError as e:
            bad.append(f'{rel}:{e.lineno} {e.msg}')
    if bad:
        fail(f'{len(bad)} arquivo(s) com erro de sintaxe', '\n        '.join(bad))
    else:
        ok(f'{len(targets)} arquivos Python parseiam sem erro')


# ─────────────────────────────────────────────────────────────
# 2) Imports — o app carrega de verdade
# ─────────────────────────────────────────────────────────────
def check_imports():
    head('[2] Imports dos modulos do app')
    code = 'import ' + ', '.join(IMPORTABLE) + '; print(version.APP_VERSION)'
    r = subprocess.run([sys.executable, '-c', code], cwd=ROOT,
                       capture_output=True, text=True)
    if r.returncode == 0:
        ok(f'import de {", ".join(IMPORTABLE)} OK (versao {r.stdout.strip()})')
    else:
        fail('falha ao importar modulos do app',
             (r.stderr or r.stdout).strip()[-600:])


# ─────────────────────────────────────────────────────────────
# 3) Suites de teste — todas, exit 0 obrigatorio
# ─────────────────────────────────────────────────────────────
def check_tests():
    head('[3] Suites de teste')
    tests_dir = os.path.join(ROOT, 'tests')
    if not os.path.isdir(tests_dir):
        fail('pasta tests/ nao encontrada')
        return
    todas = sorted(n for n in os.listdir(tests_dir)
                   if n.startswith('test_') and n.endswith('.py'))
    if not todas:
        fail('nenhuma suite test_*.py encontrada')
        return

    # Testes VISUAIS ficam de fora: chamam root.mainloop() e esperam clique
    # humano, entao travariam o gate pra sempre (e abrem janela na tela de quem
    # so queria verificar codigo). Marcados no proprio arquivo com
    # MANUAL_TEST = True, nao por lista aqui — assim um teste manual novo ja
    # nasce fora do gate sem ninguem lembrar de editar este script.
    suites, manuais = [], []
    for name in todas:
        with io.open(os.path.join(tests_dir, name), encoding='utf-8-sig') as f:
            cabecalho = f.read(4000)
        (manuais if re.search(r'^MANUAL_TEST\s*=\s*True', cabecalho, re.M)
         else suites).append(name)

    for name in manuais:
        skip(name, 'teste visual — rodar a mao')

    for name in suites:
        try:
            r = subprocess.run([sys.executable, os.path.join('tests', name)],
                               cwd=ROOT, capture_output=True, text=True,
                               timeout=180)
        except subprocess.TimeoutExpired:
            fail(f'{name} travou (timeout 180s)',
                 'suite interativa sem MANUAL_TEST = True? ou deadlock real')
            continue
        out = (r.stdout or '') + (r.stderr or '')
        m = re.search(r'(\d+)\s+passou\s+(\d+)\s+falhou(?:\s+(\d+)\s+pulou)?', out)
        resumo = ''
        if m:
            resumo = f'{m.group(1)} passou, {m.group(2)} falhou'
            if m.group(3):
                resumo += f', {m.group(3)} pulou'
        if r.returncode == 0:
            ok(f'{name}' + (f' ({resumo})' if resumo else ''))
        else:
            linhas = [l for l in out.splitlines() if 'FAIL' in l or 'Error' in l]
            fail(f'{name} falhou (exit {r.returncode})',
                 '\n        '.join(linhas[:8]) or out.strip()[-500:])


# ─────────────────────────────────────────────────────────────
# 4) Invariantes de JANELA — a regressao da v1.8.37
# ─────────────────────────────────────────────────────────────
# _center_window centraliza na WORK AREA DO MONITOR. O pai serve so pra
# descobrir QUAL monitor (via _get_monitor_bounds), nunca como origem de X/Y.
# Na v1.8.37 ele passou a somar parent.winfo_rootx/rooty e, como a root vive
# grudada na direita da tela (_position_right), toda janela nasceu colada nela.
# winfo_screenwidth/height sao a outra armadilha: no Windows so enxergam o
# monitor primario, entao janela no monitor secundario era puxada de volta.
def check_window_invariants():
    head('[4] Invariantes de posicionamento de janela (regressao v1.8.37)')
    src = read('gui.py')

    m = re.search(r'^def _center_window\(.*?(?=^def |\Z)', src, re.M | re.S)
    if not m:
        fail('_center_window nao encontrada em gui.py')
        return
    body = m.group(0)

    proibidos = {
        'winfo_rootx': 'usa a POSICAO do pai como origem — janela cola na root '
                       '(exatamente a regressao da v1.8.37)',
        'winfo_rooty': 'usa a POSICAO do pai como origem — janela cola na root '
                       '(exatamente a regressao da v1.8.37)',
        'winfo_screenwidth': 'no Windows so enxerga o monitor primario — janela '
                             'no secundario e puxada de volta',
        'winfo_screenheight': 'no Windows so enxerga o monitor primario — janela '
                              'no secundario e puxada de volta',
    }
    achados = [f'{k}: {v}' for k, v in proibidos.items() if k in body]
    if achados:
        fail('_center_window usa referencia de posicao proibida',
             '\n        '.join(achados))
    else:
        ok('_center_window nao usa winfo_rootx/rooty nem winfo_screenwidth/height')

    if '_get_monitor_bounds' in body:
        ok('_center_window resolve o monitor via _get_monitor_bounds')
    else:
        fail('_center_window nao chama _get_monitor_bounds — perde multi-monitor')

    if re.search(r'^def _get_monitor_bounds\(', src, re.M):
        ok('_get_monitor_bounds definida em gui.py')
    else:
        fail('_get_monitor_bounds ausente em gui.py')

    # A janela precisa nascer invisivel e so aparecer montada, mas com alpha e
    # NAO withdraw: 8 dialogos chamam grab_set() depois do _center_window, e
    # grab_set em janela nao-viewable levanta TclError.
    if "attributes('-alpha'" in body or 'attributes("-alpha"' in body:
        ok('_center_window esconde por alpha (preserva grab_set dos modais)')
    else:
        fail('_center_window nao usa alpha — modais podem quebrar com TclError')

    if re.search(r"state\(\)\s*!=\s*'withdrawn'", body):
        ok('_center_window respeita janela ja escondida pelo caller (start_hidden)')
    else:
        fail('_center_window nao checa state()==withdrawn — quebra surfacing via tray')


# ─────────────────────────────────────────────────────────────
# 5) Invariantes do AUTO-UPDATE — o que deixa PC morto se quebrar
# ─────────────────────────────────────────────────────────────
def check_updater_invariants():
    head('[5] Invariantes do auto-update')
    up = read('updater.py')

    # Backup por rename (reversivel) e nao delete. A v<=1.8.37 apagava _internal
    # antes de copiar: qualquer falha no meio deixava a pasta sem _internal e o
    # app nunca mais abria ("Failed to load Python DLL").
    if re.search(r'Rename-Item.*_internal\.bak', up, re.S):
        ok('backup de _internal por Rename-Item (reversivel)')
    else:
        fail('backup de _internal nao usa Rename-Item — falha deixa PC sem _internal')

    if 'function Restore-Backup' in up:
        ok('funcao Restore-Backup presente')
    else:
        fail('Restore-Backup ausente — sem rollback, falha quebra o app')

    # Todo "exit 1" precisa OU restaurar o backup, OU declarar que nao mexeu em
    # nada ainda. A unica saida legitima sem rollback e a do backup que falhou:
    # ali _internal continua no lugar, nao ha o que restaurar. Qualquer outra
    # e um caminho que larga a pasta pela metade — o "Failed to load Python DLL".
    linhas = up.splitlines()
    orfas = []
    for i, linha in enumerate(linhas):
        if linha.strip() != 'exit 1':
            continue
        antes = '\n'.join(linhas[max(0, i - 6):i])
        if 'Restore-Backup' in antes or 'Nada foi alterado' in antes:
            continue
        orfas.append(i + 1)
    if orfas:
        fail(f'{len(orfas)} caminho(s) de "exit 1" sem Restore-Backup nem '
             f'"Nada foi alterado"', 'updater.py linhas: '
             + ', '.join(str(n) for n in orfas))
    else:
        ok('todo "exit 1" ou faz rollback ou declara que nada foi alterado')

    if 'Sanity exe OK' in up and 'nao foi substituido' in up:
        ok('sanity check do MBChat.exe (tamanho staging x destino)')
    else:
        fail('sanity do exe ausente — _internal novo + exe velho passa batido')

    # CreateProcess herda env LONGO do pai; Start-Process usa ShellExecute e
    # quebra em contas com caminho 8.3 (nome.sobrenome -> PEDRO~1.PAI).
    if 'UseShellExecute = $false' in up:
        ok('relancamento via CreateProcess (UseShellExecute=$false)')
    else:
        fail('CreateProcess ausente — quebra em conta com caminho 8.3')

    if 'Start-Process -FilePath' in up:
        ok('Start-Process mantido como fallback')
    else:
        fail('fallback Start-Process ausente')

    if '"--show"' in up:
        ok('flag --show repassada no relancamento')
    else:
        fail('--show ausente — app reabre escondido na bandeja')

    for fn in ('bump_update_attempt', 'reset_update_attempts'):
        if re.search(r'^def ' + fn + r'\(', up, re.M):
            ok(f'{fn}() presente (corta loop de boot que nunca abre)')
        else:
            fail(f'{fn}() ausente')

    # No boot, os._exit(0) so pode acontecer se apply_update REALMENTE lancou o
    # script. Fora do if, um update quebrado fecha o app pra sempre.
    gui = read('gui.py')
    m = re.search(r'if updater\.apply_update\(pending_update_dir\):\s*\n(\s*)os\._exit\(0\)',
                  gui)
    if m:
        ok('os._exit(0) do boot esta dentro do if apply_update(...)')
    else:
        fail('os._exit(0) do boot fora do if apply_update — update quebrado fecha o app')

    # O download silencioso so pode marcar "pronto pra instalar" se funcionou.
    if re.search(r'if success:\s*\n\s*self\.root\.after\(0, _on_ready\)', gui):
        ok('botao "Reiniciar para Atualizar" so aparece se o download deu certo')
    else:
        fail('_on_ready pode ser chamado sem sucesso no download')


# ─────────────────────────────────────────────────────────────
# 6) Consistencia de versao
# ─────────────────────────────────────────────────────────────
def check_version(release_mode):
    head('[6] Consistencia de versao')
    ver = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', read('version.py'))
    if not ver:
        fail('APP_VERSION nao encontrada em version.py')
        return
    v = ver.group(1)

    iss = read('installer.iss')
    iss_ver = re.search(r'AppVersion=([\d.]+)', iss)
    iss_name = re.search(r'AppVerName=MB Chat v([\d.]+)', iss)

    base = v.split('-')[0]
    if iss_ver and iss_ver.group(1) == base:
        ok(f'installer.iss AppVersion casa com version.py ({base})')
    else:
        fail(f'installer.iss AppVersion={iss_ver.group(1) if iss_ver else "?"} '
             f'!= version.py {base}')

    if iss_name and iss_name.group(1) == base:
        ok(f'installer.iss AppVerName casa com version.py ({base})')
    else:
        fail(f'installer.iss AppVerName={iss_name.group(1) if iss_name else "?"} '
             f'!= version.py {base}')

    if release_mode:
        if v.endswith('-dev'):
            fail(f'version.py ainda tem sufixo -dev ({v}) — nao publicar assim')
        else:
            ok(f'version.py sem sufixo -dev ({v})')
    else:
        ok(f'version.py = {v}')


# ─────────────────────────────────────────────────────────────
# 7) Arvore git limpa (so no modo release)
# ─────────────────────────────────────────────────────────────
def check_git_clean(release_mode, allow_version_bump=False):
    head('[7] Estado do repositorio')
    if not release_mode:
        skip('arvore git limpa', 'so exigido com --release')
        return
    r = subprocess.run(['git', 'status', '--porcelain'], cwd=ROOT,
                       capture_output=True, text=True)
    if r.returncode != 0:
        skip('git status indisponivel')
        return
    sujo = [l for l in r.stdout.splitlines() if l.strip()]

    # O build.py chama este gate DEPOIS de _set_version(), que reescreve
    # version.py e installer.iss. Essas duas alteracoes sao o proprio bump da
    # release, feito pelo build segundos atras — nao sao "codigo nao commitado".
    # Qualquer OUTRO arquivo sujo continua barrando: e o caso perigoso, o de
    # publicar binario gerado de codigo que nao esta no GitHub.
    if allow_version_bump:
        permitido = ('version.py', 'installer.iss')
        restante = [l for l in sujo if l[3:].strip().strip('"') not in permitido]
        if len(restante) < len(sujo):
            ok('version.py/installer.iss modificados pelo bump da release (esperado)')
        sujo = restante

    if sujo:
        fail(f'{len(sujo)} arquivo(s) nao commitado(s) — release sairia de codigo '
             'que nao esta no GitHub', '\n        '.join(sujo[:10]))
    else:
        ok('arvore git limpa — o que sai na release e o que esta commitado')


def main():
    ap = argparse.ArgumentParser(
        description='Gate de verificacao do MB Chat (dev e release)')
    ap.add_argument('--release', action='store_true',
                    help='exige tambem: sem -dev, versoes casadas, git limpo')
    ap.add_argument('--allow-version-bump', action='store_true',
                    help='aceita version.py/installer.iss sujos (uso do build.py, '
                         'que acabou de escrever os dois no bump)')
    args = ap.parse_args()

    print('=' * 62)
    print(f'  MB Chat — gate de verificacao'
          f'{"  [MODO RELEASE]" if args.release else ""}')
    print('=' * 62)

    check_syntax()
    check_imports()
    check_tests()
    check_window_invariants()
    check_updater_invariants()
    check_version(args.release)
    check_git_clean(args.release, args.allow_version_bump)

    print('\n' + '=' * 62)
    extra = f'   {len(SKIP)} pulou' if SKIP else ''
    print(f'  {len(PASS)} passou   {len(FAIL)} falhou{extra}')
    print('=' * 62)
    if FAIL:
        print('\nGATE FECHADO — nao publicar. Falhas:')
        for f in FAIL:
            print(f'  - {f}')
        return 1
    print('\nGATE ABERTO — pode publicar.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
