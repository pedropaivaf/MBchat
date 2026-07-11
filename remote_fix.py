import sqlite3
import os
import uuid

def remote_fix():
    print("=== Corretor Remoto de Identidade (MB Chat) ===")
    print("Este script acessa o banco de dados de outro computador pela rede (via C$).")
    print("OBS: O MB Chat DEVE estar fechado no computador de destino no momento da correção.\n")
    
    ip = input("Digite o IP da maquina (ex: 192.168.0.29): ").strip()
    user = input("Digite o nome de usuario do Windows lá (ex: aux2.depcontabil): ").strip()
    
    # Caminho UNC padrão do Windows para acessar o C$ de outra máquina
    unc_path = rf"\\{ip}\c$\Users\{user}\AppData\Roaming\.mbchat\mbchat.db"
    
    print(f"\nTentando acessar: {unc_path}")
    
    if not os.path.exists(unc_path):
        print(f"ERRO: Nao foi possivel acessar o arquivo.")
        print("Motivos comuns:")
        print("1. O IP ou usuario estao incorretos.")
        print("2. Voce nao tem permissao de Administrador na rede para acessar o C$ dessa maquina.")
        print("3. A maquina destino esta desligada.")
        return
        
    try:
        conn = sqlite3.connect(unc_path)
        conn.row_factory = sqlite3.Row
        
        row = conn.execute("SELECT user_id FROM local_user WHERE id=1").fetchone()
        if not row:
            print("ERRO: Usuario local nao encontrado no banco de dados.")
            return
            
        old_uid = row['user_id']
        # Gera um ID totalmente novo e seguro
        new_uid = uuid.uuid4().hex
        
        print(f"\n[OK] Banco de dados acessado com sucesso!")
        print(f"ID Clonado atual : {old_uid}")
        print(f"Novo ID gerado   : {new_uid}")
        print("Aplicando correcao...")
        
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
        print("\n[SUCESSO] O banco de dados remoto foi corrigido definitivamente!")
        print("A partir de agora, essa maquina tera uma identidade propria.")
    except Exception as e:
        print(f"\nERRO ao modificar banco de dados: {e}")
        if "database is locked" in str(e).lower():
            print("-> O MB Chat ainda esta aberto no computador de destino! Peca para fechar.")
    finally:
        try:
            conn.close()
        except:
            pass

if __name__ == "__main__":
    remote_fix()
    input("\nPressione ENTER para sair...")
