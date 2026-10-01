# tools/release_parity.py -- compara o pacote novo (MBChat_update.zip) com o da
# release que esta nas maquinas, ANTES de publicar.
#
#   python tools/release_parity.py dist/MBChat_update.zip base_update.zip 1.8.39
#
# Reprova (exit 1) se o pacote novo nao tiver o mesmo Python (python3XX.dll) e o
# mesmo Tcl/Tk da base, se o MBChat.exe nao for da versao esperada, ou se faltar
# qualquer pasta de _internal que a base tinha. Lista todos os arquivos que entraram
# ou sairam -- o que muda de verdade entre as duas versoes e so o codigo do app.
# Precisa do pefile (pip install pefile), so para ler a versao das DLLs.
import os
import sys
import zipfile

import pefile


def _versao(z, nome):
    try:
        pe = pefile.PE(data=z.read(nome))
    except KeyError:
        return None
    for fi in getattr(pe, 'FileInfo', None) or []:
        for e in fi:
            if getattr(e, 'Key', b'') == b'StringFileInfo':
                for st in e.StringTable:
                    v = st.entries.get(b'FileVersion')
                    if v:
                        return v.decode(errors='replace').strip()
    return None


def _dlls(nomes, prefixo):
    return sorted(n for n in nomes if n.lower().startswith('_internal/' + prefixo)
                  and n.lower().endswith('.dll') and n.count('/') == 1)


# Sem diferenciar maiusculas: no Windows "Pythonwin" e "pythonwin" sao a mesma pasta
# (o pywin32 novo passou a usar minusculas)
def _pastas(nomes):
    return {n.split('/')[1].lower() for n in nomes if n.startswith('_internal/') and n.count('/') >= 2}


def main():
    novo_p, base_p, versao = sys.argv[1], sys.argv[2], sys.argv[3]
    novo, base = zipfile.ZipFile(novo_p), zipfile.ZipFile(base_p)
    nn = [n for n in novo.namelist() if not n.endswith('/')]
    bn = [n for n in base.namelist() if not n.endswith('/')]
    falhas = []
    print(f'arquivos: novo {len(nn)} | base {len(bn)}')

    for prefixo in ('python3', 'tcl', 'tk', 'vcruntime'):
        dn, db = _dlls(nn, prefixo), _dlls(bn, prefixo)
        vn = {os.path.basename(d): _versao(novo, d) for d in dn}
        vb = {os.path.basename(d): _versao(base, d) for d in db}
        print(f'{prefixo}: novo {vn} | base {vb}')
        if prefixo != 'vcruntime' and vn != vb:
            falhas.append(f'{prefixo} diferente da base: {vn} x {vb}')
        if not dn:
            falhas.append(f'{prefixo}*.dll ausente no pacote novo')

    exe = _versao(novo, 'MBChat.exe')
    print(f'MBChat.exe: {exe}')
    if exe != f'{versao}.0':
        falhas.append(f'MBChat.exe com versao {exe}, esperado {versao}.0')

    sem = sorted(_pastas(bn) - _pastas(nn))
    print('pastas de _internal que a base tinha e o novo NAO tem:', sem or 'nenhuma')
    if sem:
        falhas.append(f'pastas sumiram de _internal: {sem}')
    print('pastas novas em _internal:', sorted(_pastas(nn) - _pastas(bn)) or 'nenhuma')

    sn, sb = set(nn), set(bn)
    saiu, entrou = sorted(sb - sn), sorted(sn - sb)
    print(f'\narquivos so na base ({len(saiu)}):')
    for n in saiu:
        print('  -', n)
    print(f'arquivos so no novo ({len(entrou)}):')
    for n in entrou:
        print('  +', n)

    if falhas:
        print('\nPARIDADE REPROVADA:')
        for f in falhas:
            print('  -', f)
        sys.exit(1)
    print('\nPARIDADE OK: mesmo Python e Tcl/Tk da base, MBChat.exe na versao certa, nenhuma pasta a menos')


if __name__ == '__main__':
    main()
