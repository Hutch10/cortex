import sqlite3
import json
import hashlib
from typing import List, Optional
from .primitives import EventEnvelope, SnapshotEnvelope
from .policy import PolicyInvariants

class CortexLedger:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY,
                    timestamp INTEGER NOT NULL,
                    actor_id TEXT NOT NULL,
                    type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    parent_ids TEXT NOT NULL,
                    signature TEXT NOT NULL,
                    previous_hash TEXT NOT NULL
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_actor ON events(actor_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_time ON events(timestamp)')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS snapshots (
                    id TEXT PRIMARY KEY,
                    projection_name TEXT NOT NULL,
                    module_name TEXT NOT NULL,
                    last_commitment_id TEXT NOT NULL,
                    last_commitment_hash TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    projection_payload TEXT NOT NULL,
                    projection_hash TEXT NOT NULL
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_snapshot_module_proj ON snapshots(module_name, projection_name)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_snapshot_created ON snapshots(created_at)')
            conn.commit()

    def _calculate_hash(self, event: EventEnvelope) -> str:
        basis = {
            "timestamp": event.timestamp,
            "actor_id": event.actor_id,
            "type": event.type.value,
            "payload": event.payload,
            "parent_ids": event.parent_ids,
            "previous_hash": event.previous_hash
        }
        basis_json = json.dumps(basis, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(basis_json.encode('utf-8')).hexdigest()

    def get_latest_hash(self) -> str:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT id FROM events ORDER BY timestamp DESC, rowid DESC LIMIT 1')
            row = cursor.fetchone()
            return row[0] if row else "GENESIS"

    def append_event(self, event: EventEnvelope) -> None:
        # Enforce epistemological rules
        PolicyInvariants.check_invariants(event)
        
        expected_hash = self._calculate_hash(event)
        if event.id != expected_hash:
            raise ValueError(f"Invalid event hash. Expected {expected_hash}, got {event.id}")
        
        latest_hash = self.get_latest_hash()
        if event.previous_hash != latest_hash and latest_hash != "GENESIS":
            raise ValueError(f"Invalid chain: previous_hash must be {latest_hash}")
            
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO events (id, timestamp, actor_id, type, payload, parent_ids, signature, previous_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                event.id,
                event.timestamp,
                event.actor_id,
                event.type.value,
                json.dumps(event.payload),
                json.dumps(event.parent_ids),
                event.signature,
                event.previous_hash
            ))
            conn.commit()

    def get_events(self, limit: int = 100) -> List[EventEnvelope]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT id, timestamp, actor_id, type, payload, parent_ids, signature, previous_hash FROM events ORDER BY timestamp ASC LIMIT ?', (limit,))
            rows = cursor.fetchall()
            return [
                EventEnvelope(
                    id=row[0],
                    timestamp=row[1],
                    actor_id=row[2],
                    type=row[3],
                    payload=json.loads(row[4]),
                    parent_ids=json.loads(row[5]),
                    signature=row[6],
                    previous_hash=row[7]
                )
                for row in rows
            ]

    def get_event(self, event_id: str) -> Optional[EventEnvelope]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT id, timestamp, actor_id, type, payload, parent_ids, signature, previous_hash FROM events WHERE id = ?', (event_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return EventEnvelope(
                id=row[0],
                timestamp=row[1],
                actor_id=row[2],
                type=row[3],
                payload=json.loads(row[4]),
                parent_ids=json.loads(row[5]),
                signature=row[6],
                previous_hash=row[7]
            )

    def save_snapshot(self, snapshot: SnapshotEnvelope) -> None:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO snapshots (id, projection_name, module_name, last_commitment_id, last_commitment_hash, created_at, projection_payload, projection_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                snapshot.id,
                snapshot.projection_name,
                snapshot.module_name,
                snapshot.last_commitment_id,
                snapshot.last_commitment_hash,
                snapshot.created_at,
                json.dumps(snapshot.projection_payload),
                snapshot.projection_hash
            ))
            conn.commit()

    def get_latest_snapshot(self, module_name: str, projection_name: str) -> Optional[SnapshotEnvelope]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, projection_name, module_name, last_commitment_id, last_commitment_hash, created_at, projection_payload, projection_hash
                FROM snapshots 
                WHERE module_name = ? AND projection_name = ?
                ORDER BY created_at DESC LIMIT 1
            ''', (module_name, projection_name))
            row = cursor.fetchone()
            if not row:
                return None
            return SnapshotEnvelope(
                id=row[0],
                projection_name=row[1],
                module_name=row[2],
                last_commitment_id=row[3],
                last_commitment_hash=row[4],
                created_at=row[5],
                projection_payload=json.loads(row[6]),
                projection_hash=row[7]
            )

    def get_events_after(self, event_id: str, limit: int = 10000) -> List[EventEnvelope]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT rowid FROM events WHERE id = ?', (event_id,))
            row = cursor.fetchone()
            if not row:
                return []
            target_rowid = row[0]
            
            cursor.execute('''
                SELECT id, timestamp, actor_id, type, payload, parent_ids, signature, previous_hash 
                FROM events 
                WHERE rowid > ?
                ORDER BY rowid ASC LIMIT ?
            ''', (target_rowid, limit))
            rows = cursor.fetchall()
            return [
                EventEnvelope(
                    id=row[0],
                    timestamp=row[1],
                    actor_id=row[2],
                    type=row[3],
                    payload=json.loads(row[4]),
                    parent_ids=json.loads(row[5]),
                    signature=row[6],
                    previous_hash=row[7]
                )
                for row in rows
            ]
