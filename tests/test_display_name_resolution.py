# test_display_name_resolution.py
# Garante que mensagens de grupo mostram o NOME da pessoa (ex.: "Pedro"),
# nunca o UID cru derivado de hostname/maquina (ex.: "047f0e441f62_DESKTOP").
# Cobre o helper central (messenger.py) e a cadeia de fallback do historico
# na GUI (gui.py GroupChatWindow._load_history).
# Rodar: python tests/test_display_name_resolution.py

import sys
import os
from types import SimpleNamespace

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass  # stdout sem suporte a reconfigure (raro); segue com o encoding padrao

here = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(here) if os.path.basename(here) == 'tests' else here
sys.path.insert(0, root_dir)

PASS = []
FAIL = []


def ok(msg):
    PASS.append(msg)
    print(f'  PASS  {msg}')


def fail(msg, detail=''):
    FAIL.append(msg)
    print(f'  FAIL  {msg}' + (f': {detail}' if detail else ''))


# ─────────────────────────────────────────────
# 1 — messenger._resolve_group_sender_name: cadeia completa de fallback
# ─────────────────────────────────────────────
def test_resolve_group_sender_name():
    print('\n[1] Messenger._resolve_group_sender_name')
    import messenger

    def make_self(contact=None, peer=None):
        db = SimpleNamespace(get_contact=lambda uid: contact)
        disc = SimpleNamespace(peers={'the_uid': peer} if peer else {})
        return SimpleNamespace(db=db, discovery=disc)

    # Pacote ja traz nome bom -> usa direto, nem olha DB/discovery
    fake = make_self()
    got = messenger.Messenger._resolve_group_sender_name(fake, 'the_uid', 'Pedro')
    if got == 'Pedro':
        ok('pacote com nome bom -> usa direto')
    else:
        fail(f'pacote com nome bom -> {got}, esperado Pedro')

    # Pacote sem nome (vazio) ou auto-referente (== uid) -> tenta contato salvo
    fake = make_self(contact={'display_name': 'Pedro (contato salvo)'})
    for bad_packet_name in ('', 'the_uid'):
        got = messenger.Messenger._resolve_group_sender_name(fake, 'the_uid', bad_packet_name)
        if got == 'Pedro (contato salvo)':
            ok(f'pacote invalido ({bad_packet_name!r}) -> cai pro contato salvo')
        else:
            fail(f'pacote invalido ({bad_packet_name!r}) -> {got}, esperado o contato salvo')

    # Sem pacote, sem contato salvo, MAS visto no discovery ao vivo -> usa isso
    # (exatamente o caso "047f0e441f62_DESKTOP" -- peer so visto via grupo,
    # nunca teve chat individual salvo como contato)
    fake = make_self(contact=None, peer={'display_name': 'Pedro'})
    got = messenger.Messenger._resolve_group_sender_name(fake, 'the_uid', '')
    if got == 'Pedro':
        ok('sem contato salvo, com discovery ao vivo -> usa nome do discovery')
    else:
        fail(f'sem contato, com discovery -> {got}, esperado Pedro (NAO deveria mostrar UID)')

    # Ultimo recurso: nada em lugar nenhum -> UID cru (nao ha nome pra mostrar)
    fake = make_self(contact=None, peer=None)
    got = messenger.Messenger._resolve_group_sender_name(fake, 'the_uid', '')
    if got == 'the_uid':
        ok('sem nenhuma fonte de nome -> UID cru como ultimo recurso (esperado)')
    else:
        fail(f'sem fonte de nome -> {got}, esperado o UID cru')


# ─────────────────────────────────────────────
# 1b — Isolamento entre pessoas: resolver uid A NUNCA pode devolver o nome
# de uid B, mesmo com varios registros presentes ao mesmo tempo no DB e no
# discovery. Ao contrario de test_resolve_group_sender_name (que usa um
# mock "burro" que devolve sempre o mesmo contato/peer, sem checar QUAL uid
# foi pedido), aqui o mock so devolve o registro se o uid bater exatamente
# -- pega justamente o tipo de bug em que a variavel errada e usada na busca.
# ─────────────────────────────────────────────
def test_no_cross_contamination_between_people():
    print('\n[1b] Isolamento entre pessoas diferentes (sem vazar nome errado)')
    import messenger

    contacts_db = {
        'uid_pedro': {'display_name': 'Pedro'},
        'uid_eduardo': {'display_name': 'Eduardo'},
        # uid_maria propositalmente SEM contato salvo -- so no discovery
    }
    peers_live = {
        'uid_pedro': {'display_name': 'Pedro (via discovery)'},
        'uid_maria': {'display_name': 'Maria'},
        'uid_bot': {'display_name': '🤖 Bot de Teste'},
    }

    def get_contact(uid):
        return contacts_db.get(uid)  # None se o uid nao tiver contato salvo

    fake = SimpleNamespace(
        db=SimpleNamespace(get_contact=get_contact),
        discovery=SimpleNamespace(peers=peers_live),
    )

    cases = [
        ('uid_pedro', 'Pedro'),      # tem contato salvo -> usa o dele
        ('uid_eduardo', 'Eduardo'),  # tem contato salvo -> usa o dele
        ('uid_maria', 'Maria'),      # sem contato, so discovery -> usa o dela
        ('uid_bot', '🤖 Bot de Teste'),
        ('uid_desconhecido', 'uid_desconhecido'),  # ninguem conhece -> UID cru dele mesmo
    ]
    for uid, expected in cases:
        got = messenger.Messenger._resolve_group_sender_name(fake, uid, '')
        if got == expected:
            ok(f'{uid} -> {got!r} (o nome certo, nao vazou de outra pessoa)')
        else:
            fail(f'{uid} -> {got!r}, esperado {expected!r} -- '
                 f'POSSIVEL VAZAMENTO DE NOME ERRADO')

    # Garantia extra: resolver todos e checar que os 4 nomes resultantes sao
    # todos DIFERENTES entre si (nenhuma colisao/repeticao indevida).
    resolved = [messenger.Messenger._resolve_group_sender_name(fake, uid, '')
                for uid, _ in cases[:4]]
    if len(set(resolved)) == len(resolved):
        ok(f'4 pessoas distintas -> 4 nomes distintos, sem colisao ({resolved})')
    else:
        fail(f'Nomes duplicados entre pessoas diferentes: {resolved}')


# ─────────────────────────────────────────────
# 2 — GroupChatWindow._load_history: cadeia de fallback tambem robusta
# ─────────────────────────────────────────────
def test_load_history_fallback_chain():
    print('\n[2] GroupChatWindow._load_history (analise de codigo)')
    with open(os.path.join(root_dir, 'gui.py'), encoding='utf-8') as f:
        src = f.read()

    checks = [
        ("elif not sender or sender == from_user:",
         'checa nome vazio OU auto-referente (nao so vazio)'),
        ("_disc = getattr(self.app.messenger, 'discovery', None)",
         'consulta o discovery ao vivo como fallback adicional'),
        ("_peer = _disc.peers.get(from_user, {}) if _disc else {}",
         'busca o peer especifico no cache de discovery'),
    ]
    for needle, label in checks:
        if needle in src:
            ok(label)
        else:
            fail(f'{label} -- padrao nao encontrado em _load_history')


if __name__ == '__main__':
    test_resolve_group_sender_name()
    test_no_cross_contamination_between_people()
    test_load_history_fallback_chain()

    print(f'\n{"="*50}')
    print(f'  {len(PASS)} passou   {len(FAIL)} falhou')
    print('='*50)
    sys.exit(0 if not FAIL else 1)
