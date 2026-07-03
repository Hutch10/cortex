import sqlite3
import hashlib
import json
from datetime import datetime
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from core.ledger import CortexLedger
from core.primitives import EventEnvelope, PrimitiveType
from core.replay import ReplayEngine

LEGACY_DB = os.path.join(os.path.dirname(__file__), "outputs/cortex_ledger.sqlite")
DRY_RUN_DB = os.path.join(os.path.dirname(__file__), "dry_run_cortex.sqlite")

def main():
    if os.path.exists(DRY_RUN_DB):
        os.remove(DRY_RUN_DB)
        
    print("=== Phase 4B: Dry-Run Legacy Migration ===")
    
    # 1. Init new dry run ledger
    ledger = CortexLedger(DRY_RUN_DB)
    
    # 2. Connect to legacy
    try:
        conn = sqlite3.connect(LEGACY_DB)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM pulse_ledger ORDER BY timestamp ASC")
        legacy_records = c.fetchall()
    except Exception as e:
        print(f"Error reading legacy ledger: {e}")
        return

    total_records = len(legacy_records)
    migrated = 0
    unmappable = 0
    duplicates = 0
    
    print(f"Discovered {total_records} legacy records.")
    
    imported_legacy_ids = set()

    for row in legacy_records:
        r = dict(row)
        
        # Check duplicates (idempotency via legacy id)
        legacy_id = r.get("id")
        if legacy_id in imported_legacy_ids:
            duplicates += 1
            continue
            
        try:
            # Parse timestamp to unix
            dt = datetime.fromisoformat(r['timestamp'].replace("Z", "+00:00"))
            ts = int(dt.timestamp())
        except Exception:
            ts = int(datetime.utcnow().timestamp())
            
        # Payload shape
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
            print(f"Failed to append record {legacy_id}: {e}")
            unmappable += 1

    print("\n--- Integrity Check ---")
    events = ledger.get_events()
    valid = True
    current_hash = "GENESIS"
    for e in events:
        if e.previous_hash != current_hash:
            print(f"Broken hash chain at {e.id}")
            valid = False
            break
        current_hash = e.id
        
    print(f"Hash Chain Integrity: {'PASS' if valid else 'FAIL'}")
    
    print("\n--- Replay Check ---")
    engine = ReplayEngine(ledger)
    state = engine.reconstruct_state()
    obs_count = len(state['observations'])
    print(f"Reconstructed Observations: {obs_count}")
    
    print("\n=== Dry-Run Report ===")
    print(f"Total Legacy: {total_records}")
    print(f"Successfully Migrated: {migrated}")
    print(f"Duplicates Skipped: {duplicates}")
    print(f"Unmappable/Failed: {unmappable}")
    print(f"Replay Match: {'PASS' if obs_count == migrated else 'FAIL'}")
    print("--------------------------------------")
    if valid and obs_count == migrated and unmappable == 0:
        print("RECOMMENDATION: GO for real migration.")
    else:
        print("RECOMMENDATION: NO-GO. Address issues above.")

if __name__ == "__main__":
    main()
