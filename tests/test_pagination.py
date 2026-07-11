import os
import sys
import uuid
import time
import tkinter as tk

# Adiciona o diretorio pai ao sys.path para importar database e messenger
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from database import Database

def run_test():
    print("Iniciando teste de paginação de histórico...")
    db_path = "test_pagination.db"
    if os.path.exists(db_path):
        os.remove(db_path)
        
    db = Database(db_path)
    my_id = "user1"
    peer_id = "user2"
    
    print("Inserindo 250 mensagens no banco...")
    for i in range(250):
        db.save_message(
            msg_id=str(uuid.uuid4()),
            from_user=peer_id if i % 2 == 0 else my_id,
            to_user=my_id if i % 2 == 0 else peer_id,
            content=f"Mensagem de teste {i}",
            msg_type="text"
        )
        time.sleep(0.001)  # Para garantir ordem do timestamp

    # Verifica o metodo do DB
    print("Testando database.py get_chat_history com limit=100...")
    history = db.get_chat_history(my_id, peer_id, limit=100)
    assert len(history) == 100, f"Deveria ter retornado 100 mensagens, retornou {len(history)}"
    
    print("Testando database.py get_chat_history com limit=200...")
    history_200 = db.get_chat_history(my_id, peer_id, limit=200)
    assert len(history_200) == 200, f"Deveria ter retornado 200 mensagens, retornou {len(history_200)}"
    
    print("Sucesso! O banco de dados suporta e aplica o limite de paginação corretamente.")
    
    # Fecha conexoes do BD antes de excluir
    if hasattr(db, 'conn') and db.conn:
        db.conn.close()
        
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except Exception:
            pass

if __name__ == "__main__":
    run_test()
