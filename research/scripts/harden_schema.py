import sqlite3
db_path = 'cortex.sqlite'
try:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    # 1. Add flight_hours column
    try:
        cursor.execute("ALTER TABLE asset_health ADD COLUMN flight_hours REAL DEFAULT 0.0")
        print("[OK] Schema Hardened: Added flight_hours.")
    except sqlite3.OperationalError:
        print("[SKIP] flight_hours already exists.")

    # 2. Update NorthStar data: 25ppm @ 1000h -> 55ppm @ 1025h
    cursor.execute("UPDATE asset_health SET flight_hours = 1000.0 WHERE tenant_id = 'tenant-ebfcdd10' AND iron_ppm = 25.0")
    cursor.execute("UPDATE asset_health SET flight_hours = 1025.0 WHERE tenant_id = 'tenant-ebfcdd10' AND iron_ppm = 55.0")
    
    conn.commit()
    print("[SUCCESS] Data points normalized for rate-of-change analysis.")
except Exception as e:
    print(f"Database Error: {e}")
finally:
    conn.close()
