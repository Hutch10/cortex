import sqlite3
import json
from pathlib import Path
from datetime import datetime

class PulseAuditService:
    def __init__(self, db_path: str = "outputs/cortex_ledger.sqlite"):
        self.db_path = Path(db_path)
        self._initialize_db()

    def _initialize_db(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pulse_ledger (
                id TEXT PRIMARY KEY,
                timestamp TEXT,
                payload TEXT,
                kp_index REAL,
                seismic_count INTEGER,
                hrv REAL,
                mood INTEGER,
                sleep REAL,
                hash TEXT,
                signature TEXT,
                cortex_id TEXT
            )
        """)
        conn.commit()
        conn.close()

    def log_entry(self, entry: dict):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO pulse_ledger (id, timestamp, payload, kp_index, seismic_count, hrv, mood, sleep, hash, signature, cortex_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            entry["_id"],
            entry["_id"], # Using ISO timestamp as ID
            entry["notes"],
            entry["kp_index"],
            entry["seismic_count"],
            entry.get("hrv"),
            entry.get("mood"),
            entry.get("sleep"),
            entry["fingerprint"],
            entry["integrity_seal"],
            entry["cortex_id"]
        ))
        conn.commit()
        conn.close()

    def get_all_entries(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM pulse_ledger ORDER BY timestamp DESC")
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

pulse_audit = PulseAuditService()
