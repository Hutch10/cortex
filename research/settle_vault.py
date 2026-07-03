import sqlite3
import os

db_path = 'cortex.sqlite'
try:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS billing_events (tenant_id TEXT, event_type TEXT, duration_minutes INTEGER, amount_usd REAL, timestamp TEXT)")
    cursor.execute("INSERT INTO billing_events (tenant_id, event_type, duration_minutes, amount_usd, timestamp) VALUES (?, ?, ?, ?, ?)", 
                   ('internal', 'flight_log', 168, 700.00, '2026-03-18 16:25:00'))
    conn.commit()
    print('--- SETTLEMENT SUCCESSFUL ---')
    print('Result: 2.8h @ $700.00 committed to the ledger.')
except Exception as e:
    print(f'Database Error: {e}')
finally:
    conn.close()
