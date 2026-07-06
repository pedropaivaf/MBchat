import sqlite3
import os
import uuid
import platform
import getpass

def generate_user_id():
    try:
        user = getpass.getuser()
        host = platform.node()
        mac = uuid.getnode()
        random_suffix = uuid.uuid4().hex[:6]
        return f"{mac}_{host}_{user}_{random_suffix}"
    except Exception:
        return uuid.uuid4().hex

def fix_database():
    appdata = os.environ.get('APPDATA') or os.path.expanduser('~')
    db_path = os.path.join(appdata, '.mbchat', 'mbchat.db')
    
    if not os.path.exists(db_path):
        print(f"Erro: Banco de dados nao encontrado em {db_path}")
        print("Certifique-se de que o backup ja foi restaurado pelo aplicativo antes de rodar este script.")
        return

    # Conecta ao banco de dados
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    try:
        row = conn.execute("SELECT user_id FROM local_user WHERE id=1").fetchone()
        if not row:
            print("Erro: Usuario local nao encontrado no banco de dados.")
            return
            
        old_uid = row['user_id']
        new_uid = generate_user_id()
        
        print(f"Encontrado ID clonado : {old_uid}")
        print(f"Gerando ID exclusivo  : {new_uid}")
        print("Modificando registros de historico...")
        
        # 1. Update local_user (nova identidade)
        conn.execute("UPDATE local_user SET user_id=? WHERE user_id=?", (new_uid, old_uid))
        
        # 2. Update contacts
        row_new = conn.execute("SELECT 1 FROM contacts WHERE user_id=?", (new_uid,)).fetchone()
        if row_new:
            conn.execute("DELETE FROM contacts WHERE user_id=?", (old_uid,))
        else:
            conn.execute("UPDATE contacts SET user_id=? WHERE user_id=?", (new_uid, old_uid))
            
        # 3. Update messages (todas as msgs enviadas/recebidas por ela)
        conn.execute("UPDATE messages SET from_user=? WHERE from_user=?", (new_uid, old_uid))
        conn.execute("UPDATE messages SET to_user=? WHERE to_user=?", (new_uid, old_uid))
        
        # 4. Update group_members e groups
        conn.execute("UPDATE group_members SET user_id=? WHERE user_id=?", (new_uid, old_uid))
        conn.execute("UPDATE groups SET creator_uid=? WHERE creator_uid=?", (new_uid, old_uid))
        
        conn.commit()
        print("\nSUCESSO! O banco de dados foi corrigido.")
        print("O historico inteiro foi preservado, mas associado a uma identidade de rede nova.")
        
    except Exception as e:
        print(f"Erro ao modificar banco de dados: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    print("=== Corretor de Backup MB Chat ===")
    fix_database()
    input("\nPressione ENTER para fechar...")
