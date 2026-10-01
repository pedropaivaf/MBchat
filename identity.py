# identity.py - Identidade do usuario no MB Chat (funcoes puras, sem rede/banco)
#
# O user_id tem o formato  <mac 12 hex>_<hostname>_<login do Windows>
# (network.generate_user_id). Ele e criado na PRIMEIRA execucao e fica gravado
# no banco do perfil (%APPDATA%\.mbchat) -- acompanha a PASTA, nao o PC.
# O login no final diz de QUEM e o ID: e ele que decide se um banco copiado
# de outro perfil esta se passando por outra pessoa, e se dois IDs diferentes
# sao a mesma pessoa em PCs diferentes.

import os
import re

_MAC_PREFIX = re.compile(r'^[0-9a-f]{12}_', re.IGNORECASE)


# True se o user_id foi criado para esse login do Windows (sem diferenciar
# maiusculas: o Windows trata "Pedro.Paiva" e "pedro.paiva" como o mesmo login)
def uid_belongs_to(uid, login):
    login = (login or '').strip().lower()
    return bool(uid and login) and uid.lower().endswith('_' + login)


# Hostname gravado dentro do user_id (o PC onde ele nasceu).
# '' se o user_id nao e desse login ou nao esta no formato mac_host_login.
def uid_hostname(uid, login):
    login = (login or '').strip()
    if not uid_belongs_to(uid, login) or not _MAC_PREFIX.match(uid):
        return ''
    return uid[13:len(uid) - len(login) - 1]


# Login do Windows gravado no user_id, sem saber o login de antemao.
# Hostname do Windows nao tem '_', entao o login e tudo depois do primeiro '_'
# que segue o hostname. '' se o user_id nao tem login (formato antigo mac_host).
def uid_login(uid):
    if not uid or not _MAC_PREFIX.match(uid):
        return ''
    rest = uid[13:]
    if '_' not in rest:
        return ''
    return rest.split('_', 1)[1]


# Tipo da conta do Windows logada:
#   'domain' -> conta de dominio: o mesmo login e a mesma pessoa em qualquer PC
#   'local'  -> conta local do PC (USERDOMAIN == nome do PC): o mesmo login em
#               outro PC pode ser outra pessoa ("Usuario", "Admin"...)
#   ''       -> desconhecido (fora do Windows)
def login_scope(environ=None):
    env = os.environ if environ is None else environ
    dom = (env.get('USERDOMAIN') or '').strip()
    comp = (env.get('COMPUTERNAME') or '').strip()
    if not dom:
        return ''
    if comp and dom.upper() == comp.upper():
        return 'local'
    return 'domain'
