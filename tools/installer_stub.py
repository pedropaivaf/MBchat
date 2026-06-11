import os
import sys
import ctypes
import tempfile
import subprocess
import urllib.request
import urllib.error

LATEST_URL = 'https://github.com/pedropaivaf/MBchat/releases/latest/download/MBChat_Setup.exe'
MB_OK = 0x00000000
MB_ICONERROR = 0x00000010
MB_ICONINFO = 0x00000040


def _msgbox(text, title='MB Chat', flags=MB_OK):
    try:
        ctypes.windll.user32.MessageBoxW(0, text, title, flags)
    except Exception:
        pass


def _show_progress_console():
    try:
        ctypes.windll.kernel32.AllocConsole()
        sys.stdout = open('CONOUT$', 'w')
        sys.stderr = sys.stdout
    except Exception:
        pass


class _Reporter:
    def __init__(self):
        self.last_pct = -1

    def __call__(self, block_num, block_size, total_size):
        if total_size <= 0:
            return
        done = block_num * block_size
        pct = int(done * 100 / total_size)
        if pct != self.last_pct and pct % 5 == 0:
            self.last_pct = pct
            sys.stdout.write(f'\rBaixando... {pct}% ({done // 1024} KB / {total_size // 1024} KB)')
            sys.stdout.flush()


def main():
    _show_progress_console()
    print('MB Chat - Instalador Web')
    print('Buscando a versao mais recente...')
    tmp_path = os.path.join(tempfile.gettempdir(), 'MBChat_Setup.exe')
    try:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
        urllib.request.urlretrieve(LATEST_URL, tmp_path, _Reporter())
        print('\nDownload concluido.')
    except urllib.error.URLError as e:
        _msgbox(f'Nao foi possivel baixar o instalador.\n\n'
                f'Verifique sua conexao e tente novamente.\n\n'
                f'Detalhe: {e}', flags=MB_ICONERROR)
        sys.exit(1)
    except Exception as e:
        _msgbox(f'Falha inesperada no download.\n\nDetalhe: {e}',
                flags=MB_ICONERROR)
        sys.exit(1)

    print('Iniciando instalacao...')
    try:
        subprocess.Popen([tmp_path])
    except Exception as e:
        _msgbox(f'Nao foi possivel executar o instalador.\n\n'
                f'Arquivo baixado em: {tmp_path}\n\nDetalhe: {e}',
                flags=MB_ICONERROR)
        sys.exit(1)


if __name__ == '__main__':
    main()
