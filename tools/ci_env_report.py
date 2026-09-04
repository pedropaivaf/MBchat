# Relatorio do ambiente onde o gate esta rodando.
#
# Existe porque ja aconteceu tres vezes de um teste falhar por causa da MAQUINA
# e nao do codigo: bind em UDP 50100 impossivel por reserva do SO, IP local numa
# faixa que o network.py trata como "sou cliente VPN", e resolucao/monitor
# diferentes do esperado. Quando o CI reprova e a maquina do dev passa (ou o
# contrario), a resposta costuma estar nestes numeros.
#
# Nunca falha: qualquer erro vira uma linha de aviso. Isto e diagnostico, nao gate.

import os
import platform
import socket
import sys


def linha(rotulo, valor):
    print(f'  {rotulo:<26} {valor}')


def seguro(rotulo, fn):
    try:
        linha(rotulo, fn())
    except Exception as e:
        linha(rotulo, f'(indisponivel: {e.__class__.__name__}: {e})')


def main():
    print('=' * 62)
    print('  Ambiente do runner')
    print('=' * 62)

    linha('Python', sys.version.split()[0])
    linha('Plataforma', platform.platform())
    seguro('Hostname', socket.gethostname)

    # O IP local decide o caminho de is_vpn_subnet() em network.py: 10.x, 100.x e
    # 172.16-31.x sao tratados como "esta maquina e cliente VPN". Runner de CI
    # costuma cair em 10.x — por isso testes de rede tem que fixar get_local_ip.
    def ip_local():
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(('8.8.8.8', 80))
            return s.getsockname()[0]
        finally:
            s.close()
    seguro('IP local', ip_local)

    def porta_50100():
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(('127.0.0.1', 50100))
            return 'livre'
        except OSError as e:
            return f'INDISPONIVEL ({e.errno})'
        finally:
            s.close()
    seguro('UDP 50100', porta_50100)

    # Tkinter e as APIs Win32 de monitor: e daqui que vem quase toda diferenca
    # entre "passa na minha maquina" e "falha no CI" nos testes de janela.
    def tk_info():
        import tkinter as tk
        r = tk.Tk()
        try:
            r.withdraw()
            r.update_idletasks()
            return (f'ok — tela primaria {r.winfo_screenwidth()}x'
                    f'{r.winfo_screenheight()}, Tcl {r.tk.call("info", "patchlevel")}')
        finally:
            r.destroy()
    seguro('Tkinter', tk_info)

    def monitores():
        import ctypes
        u = ctypes.windll.user32
        return f'{u.GetSystemMetrics(80)} monitor(es) reportado(s) pelo SO'
    seguro('Monitores', monitores)

    def dwm():
        import ctypes
        enabled = ctypes.c_int(0)
        hr = ctypes.windll.dwmapi.DwmIsCompositionEnabled(ctypes.byref(enabled))
        return f'composicao={"ativa" if enabled.value else "INATIVA"} (HRESULT={hr})'
    seguro('DWM', dwm)

    def deps():
        achadas = []
        for nome in ('PIL', 'pystray', 'winotify', 'windnd', 'win32api',
                     'sounddevice'):
            try:
                __import__(nome)
                achadas.append(nome)
            except Exception:
                achadas.append(f'{nome}(ausente)')
        return ', '.join(achadas)
    seguro('Dependencias opcionais', deps)

    linha('CI', os.environ.get('GITHUB_ACTIONS', 'nao (execucao local)'))
    print()


if __name__ == '__main__':
    try:
        main()
    except Exception as e:  # diagnostico nunca derruba o pipeline
        print(f'  (relatorio de ambiente falhou: {e})')
