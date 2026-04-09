# Gera file_version_info.txt para PyInstaller (VERSIONINFO resource)
# Reduz falsos positivos de antivirus ao embedar metadados no EXE
import os
import sys

def generate_version_info(output_path=None):
    here = os.path.dirname(os.path.abspath(__file__))
    if output_path is None:
        output_path = os.path.join(here, 'file_version_info.txt')

    # Le versao de version.py
    ver_file = os.path.join(here, 'version.py')
    version = '0.0.0'
    with open(ver_file, 'r', encoding='utf-8') as f:
        for line in f:
            if line.startswith('APP_VERSION'):
                version = line.split('=')[1].strip().strip('"').strip("'")
                break

    # Pad para 4 partes
    parts = version.split('.')
    while len(parts) < 4:
        parts.append('0')
    major, minor, patch, build = [int(p) for p in parts[:4]]
    ver_str = f'{major}.{minor}.{patch}.{build}'

    content = f'''# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({major}, {minor}, {patch}, {build}),
    prodvers=({major}, {minor}, {patch}, {build}),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
        StringTable(
          u'041604B0',
          [
            StringStruct(u'CompanyName', u'MB Contabilidade'),
            StringStruct(u'FileDescription', u'MB Chat - Mensageiro de Rede Local'),
            StringStruct(u'FileVersion', u'{ver_str}'),
            StringStruct(u'InternalName', u'MBChat'),
            StringStruct(u'LegalCopyright', u'\\u00a9 2025-2026 MB Contabilidade'),
            StringStruct(u'OriginalFilename', u'MBChat.exe'),
            StringStruct(u'ProductName', u'MB Chat'),
            StringStruct(u'ProductVersion', u'{ver_str}'),
          ]
        )
      ]
    ),
    VarFileInfo([VarStruct(u'Translation', [0x0416, 1200])])
  ]
)
'''

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(content)
    return output_path


if __name__ == '__main__':
    path = generate_version_info()
    print(f'Version info gerado: {path}')
