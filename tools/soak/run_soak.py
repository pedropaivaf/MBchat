# tools/soak/run_soak.py -- "dia de trabalho acelerado" para medir a RAM do MB Chat.
# Roda o app REAL (codigo do repositorio, ou de outra pasta com --repo) contra 30
# colegas falsos em loopback e imprime a memoria a cada 15s. Resultado em
# %TEMP%\mbchat_soak\soak_<tag>.json.
#
#   python tools/soak/run_soak.py 480                     # codigo atual, 8 min
#   python tools/soak/run_soak.py 480 --repo C:\v1838     # outra versao (git archive)
#   python tools/soak/run_soak.py 260 --close-at 200      # fecha os chats aos 200s
#
# FECHE O MB CHAT ANTES: com ele aberto os 30 colegas falsos iriam para o app de
# verdade. Por isso o script se recusa a rodar se UDP 50100 ou TCP 50101 estao em uso.
# Referencia (Xvfb, 8 min, ~1.170 mensagens, ~29 mil anuncios): 1.8.38 +506 MB;
# codigo com a correcao da RAM +39 MB, que e o conteudo das 30 janelas de chat e
# volta ao fechar as janelas (widgets e objetos abaixo do valor da abertura).
import os
import socket
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))


def _porta_livre(tipo, porta):
    s = socket.socket(socket.AF_INET, tipo)
    try:
        s.bind(('0.0.0.0', porta))
        return True
    except OSError:
        return False
    finally:
        s.close()


def main():
    args = sys.argv[1:]
    repo, close_at = ROOT, None
    if '--repo' in args:
        i = args.index('--repo')
        repo = os.path.abspath(args[i + 1])
        del args[i:i + 2]
    if '--close-at' in args:
        i = args.index('--close-at')
        close_at = args[i + 1]
        del args[i:i + 2]
    dur = args[0] if args else '480'
    if not (_porta_livre(socket.SOCK_DGRAM, 50100) and _porta_livre(socket.SOCK_STREAM, 50101)):
        print('Recusado: UDP 50100 ou TCP 50101 em uso -- feche o MB Chat antes de medir.')
        sys.exit(2)
    work = os.path.join(tempfile.gettempdir(), 'mbchat_soak')
    os.makedirs(work, exist_ok=True)
    info = os.path.join(work, 'soak_info.json')
    if os.path.exists(info):
        os.remove(info)
    tag = os.path.basename(repo.rstrip('\\/')) or 'app'
    gen = subprocess.Popen([sys.executable, os.path.join(HERE, 'soak_gen.py'), dur])
    cmd = [sys.executable, os.path.join(HERE, 'soak_app.py'), repo, tag, str(float(dur) + 20)]
    if close_at:
        cmd.append(close_at)
    t0 = time.time()
    rc = subprocess.call(cmd)
    gen.wait(timeout=120)
    print(f'fim ({round(time.time() - t0)}s, rc={rc}); resultado em {os.path.join(work, "soak_" + tag + ".json")}')
    sys.exit(rc)


if __name__ == '__main__':
    main()
