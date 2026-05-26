import sqlite3
import os

db_path = os.path.join(os.environ['APPDATA'], '.mbchat', 'mbchat.db')
print("Lendo banco de dados em:", db_path)

conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

cursor = conn.cursor()
cursor.execute("SELECT user_id, display_name, ip_address, status, last_seen FROM contacts WHERE user_id LIKE '%aline%' OR display_name LIKE '%aline%'")
rows = cursor.fetchall()

print("\nContatos encontrados:")
for row in rows:
    print(dict(row))

conn.close()
