import sqlite3
import hashlib
import json
from datetime import datetime
import os
import sys
import shutil

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from core.ledger import CortexLedger
from core.primitives import EventEnvelope, PrimitiveType
from core.replay import ReplayEngine

LEGACY_DB = os.path.join(os.path.dirname(__file__), "outputs/cortex_ledger.sqlite")
LIVE_DB = os.path.join(os.path.dirname(__file__), "cortex.sqlite")

def get_legacy_count():
    if not os.path.exists(LEGACY_DB):
        return 0
    try:
        conn = sqlite3.connect(LEGACY_DB)
        c = conn.cursor()
        c.execute("SELECT count(*) FROM pulse_ledger")
        return c.fetchone()[0]
    except Exception:
        return 0

def get_live_count():
    if not os.path.exists(LIVE_DB):
        return 0
    try:
        conn = sqlite3.connect(LIVE_DB)
        c = conn.cursor()
        c.execute("SELECT count(*) FROM events")
        return c.fetchone()[0]
    except Exception:
        return 0

def backup_databases():
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    backup_dir = os.path.join(os.path.dirname(__file__), "backups")
    os.makedirs(backup_dir, exist_ok=True)
    
    legacy_backup = os.path.join(backup_dir, f"cortex_ledger_{timestamp}.sqlite.bak")
    live_backup = os.path.join(backup_dir, f"cortex_{timestamp}.sqlite.bak")
    
    if os.path.exists(LEGACY_DB):
        shutil.copy2(LEGACY_DB, legacy_backup)
    if os.path.exists(LIVE_DB):
        shutil.copy2(LIVE_DB, live_backup)
        
    return legacy_backup, live_backup

def migrate(ledger, is_idempotency_run=False):
    try:
        conn = sqlite3.connect(LEGACY_DB)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM pulse_ledger ORDER BY timestamp ASC")
        legacy_records = c.fetchall()
    except Exception as e:
        print(f"Error reading legacy ledger: {e}")
        return 0, 0, 0
    
    # Load already imported IDs
    events = ledger.get_events()
    imported_legacy_ids = set()
    for e in events:
        if e.payload and "legacy_metadata" in e.payload:
            imported_legacy_ids.add(e.payload["legacy_metadata"]["original_id"])

    migrated = 0
    unmappable = 0
    duplicates = 0

    for row in legacy_records:
        r = dict(row)
        legacy_id = r.get("id")
        
        if legacy_id in imported_legacy_ids:
            duplicates += 1
            continue
            
        try:
            dt = datetime.fromisoformat(r['timestamp'].replace("Z", "+00:00"))
            ts = int(dt.timestamp())
        except Exception:
            ts = int(datetime.utcnow().timestamp())
            
        payload = {
            "text": r['payload'],
            "metrics": {
                "kp_index": r.get('kp_index'),
                "seismic_count": r.get('seismic_count'),
                "hrv": r.get('hrv'),
                "mood": r.get('mood'),
                "sleep": r.get('sleep')
            },
            "legacy_metadata": {
                "original_id": legacy_id,
                "original_hash": r.get('hash'),
                "original_signature": r.get('signature')
            }
        }
        
        actor_id = r.get('cortex_id') or "unknown_legacy_actor"
        previous_hash = ledger.get_latest_hash()
        
        basis = {
            "timestamp": ts,
            "actor_id": actor_id,
            "type": PrimitiveType.OBSERVATION.value,
            "payload": payload,
            "parent_ids": [],
            "previous_hash": previous_hash
        }
        basis_json = json.dumps(basis, sort_keys=True, separators=(',', ':'))
        event_id = hashlib.sha256(basis_json.encode('utf-8')).hexdigest()
        
        event = EventEnvelope(
            id=event_id,
            timestamp=ts,
            actor_id=actor_id,
            type=PrimitiveType.OBSERVATION,
            payload=payload,
            parent_ids=[],
            signature="LEGACY_MIGRATED_SIG",
            previous_hash=previous_hash
        )
        
        try:
            ledger.append_event(event)
            imported_legacy_ids.add(legacy_id)
            migrated += 1
        except ValueError as e:
            unmappable += 1
            
    return migrated, duplicates, unmappable

def main():
    print("=== Phase 4C: Live Migration ===")
    
    # 1. Backups
    leg_bak, liv_bak = backup_databases()
    print(f"Legacy backup created: {leg_bak}")
    print(f"Live backup created: {liv_bak}")
    
    # 2. Before counts
    src_count = get_legacy_count()
    dst_before = get_live_count()
    print(f"Source records count: {src_count}")
    print(f"Destination before count: {dst_before}")
    
    # 3. Migrate
    ledger = CortexLedger(LIVE_DB)
    migrated, duplicates, unmappable = migrate(ledger)
    
    # 4. After counts
    dst_after = get_live_count()
    print(f"Destination after count: {dst_after}")
    
    # 5. Idempotency test (run again)
    migrated_idempotent, duplicates_idempotent, unmappable_idempotent = migrate(ledger, True)
    
    # 6. Verify Integrity
    events = ledger.get_events()
    valid = True
    current_hash = "GENESIS"
    for e in events:
        if e.previous_hash != current_hash:
            valid = False
            break
        current_hash = e.id
        
    # 7. Replay
    engine = ReplayEngine(ledger)
    state = engine.reconstruct_state()
    obs_count = len(state['observations'])
    
    # Check if payload metadata exists
    metadata_verified = False
    for e in events:
        if e.payload and "legacy_metadata" in e.payload:
            metadata_verified = True
            break
            
    print("\n=== Certification Report ===")
    print(f"Migration Timestamp: {datetime.utcnow().isoformat()}Z")
    print(f"Source Record Count: {src_count}")
    print(f"Migrated Record Count: {migrated}")
    print(f"Skipped/Unmappable: {unmappable}")
    print(f"Duplicates Detection (Idempotency Run): Found {duplicates_idempotent} duplicates (Expected {src_count}).")
    print(f"Integrity Validation: {'PASS' if valid else 'FAIL'}")
    print(f"Replay Validation: {'PASS' if obs_count >= migrated else 'FAIL'} ({obs_count} total observations)")
    print(f"Metadata Preservation: {'PASS' if metadata_verified else 'FAIL'}")
    print(f"Backup Legacy: {leg_bak}")
    print(f"Backup Live: {liv_bak}")
    
    is_success = valid and metadata_verified and (migrated == src_count) and (duplicates_idempotent == src_count)
    print(f"Final Status: {'GO (CERTIFIED)' if is_success else 'FAIL'}")

if __name__ == "__main__":
    main()
