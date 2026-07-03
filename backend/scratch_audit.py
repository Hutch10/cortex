import sqlite3
import json

db_path = "c:/Users/hetfw/Cortex/backend/outputs/cortex_ledger.sqlite"
try:
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [row[0] for row in c.fetchall()]
    print("TABLES:", tables)
    for t in tables:
        c.execute(f"PRAGMA table_info({t});")
        print(f"SCHEMA for {t}:", c.fetchall())
        c.execute(f"SELECT * FROM {t} LIMIT 3;")
        print(f"DATA for {t}:", c.fetchall())
except Exception as e:
    print(f"Error: {e}")
