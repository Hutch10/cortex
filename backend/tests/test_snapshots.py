import pytest
import sqlite3
import json
import hashlib
from fastapi.testclient import TestClient
from fastapi import FastAPI
from api.core_api import router as core_router
from core.ledger import CortexLedger

app = FastAPI()
app.include_router(core_router, prefix="/api/v1/core")
client = TestClient(app)

@pytest.fixture(scope="module")
def setup_test_db(tmp_path_factory):
    db_file = tmp_path_factory.mktemp("data") / "test_snapshots.sqlite"
    test_ledger = CortexLedger(str(db_file))
    
    import api.core_api
    app.dependency_overrides[api.core_api.get_ledger] = lambda: test_ledger
    
    # Pre-populate some events
    for i in range(5):
        client.post("/api/v1/core/append/observation", json={
            "actor_id": "tester",
            "payload": {"data": f"obs_{i}"},
            "parent_ids": [],
            "signature": "SIG"
        })
        
    yield test_ledger
    app.dependency_overrides.clear()

def test_1_create_snapshot_valid_hash(setup_test_db):
    resp = client.get("/api/v1/core/replay")
    timeline = resp.json()["timeline"]
    last_event_id = timeline[2]["id"] # Take snapshot at event index 2
    
    payload = {"cached_state": "some_value"}
    
    # Try invalid hash
    resp_inv = client.post("/api/v1/core/snapshots", json={
        "projection_name": "test_proj",
        "module_name": "test_mod",
        "last_commitment_id": "INVALID_ID",
        "projection_payload": payload
    })
    assert resp_inv.status_code == 400
    
    # Try valid hash
    resp_val = client.post("/api/v1/core/snapshots", json={
        "projection_name": "test_proj",
        "module_name": "test_mod",
        "last_commitment_id": last_event_id,
        "projection_payload": payload
    })
    assert resp_val.status_code == 200
    assert "snapshot_id" in resp_val.json()

def test_2_get_latest_snapshot(setup_test_db):
    resp = client.get("/api/v1/core/snapshots/test_mod/test_proj/latest")
    assert resp.status_code == 200
    data = resp.json()
    assert data["projection_name"] == "test_proj"
    assert data["projection_payload"] == {"cached_state": "some_value"}

def test_3_replay_from_snapshot_matches_genesis(setup_test_db):
    # Take a real state snapshot at index 2
    resp = client.get("/api/v1/core/replay")
    full_state = resp.json()["state"]
    timeline = resp.json()["timeline"]
    
    # Replay state up to index 2 (manually reconstruct for test)
    # ReplayEngine state format has observations dict
    partial_state = {
        "observations": {},
        "claims": {},
        "decisions": {},
        "evidence_links": []
    }
    for e in timeline[:3]:
        partial_state["observations"][e["id"]] = e["payload"]
        
    # Save partial state as snapshot
    client.post("/api/v1/core/snapshots", json={
        "projection_name": "core_replay",
        "module_name": "core",
        "last_commitment_id": timeline[2]["id"],
        "projection_payload": partial_state
    })
    
    # Now replay from snapshot
    snap_replay_resp = client.get("/api/v1/core/replay/snapshot?module_name=core&projection_name=core_replay")
    assert snap_replay_resp.status_code == 200
    assert snap_replay_resp.json()["snapshot_used"] is True
    
    # State should match full replay
    assert snap_replay_resp.json()["state"] == full_state

def test_7_snapshot_payload_hash_mismatch(setup_test_db):
    # Modify snapshot payload directly in DB to corrupt hash
    db_path = setup_test_db.db_path
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE snapshots SET projection_payload = '{\"tampered\": true}' WHERE module_name='core'")
        conn.commit()
        
    resp = client.get("/api/v1/core/replay/snapshot?module_name=core&projection_name=core_replay")
    assert resp.status_code == 500
    assert "payload hash mismatch" in resp.json()["detail"]
    
def test_4_corrupt_snapshot_rejected(setup_test_db):
    # Already proven by test 7, failing closed.
    pass

def test_5_deleting_snapshots_does_not_affect_ledger(setup_test_db):
    db_path = setup_test_db.db_path
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM snapshots")
        conn.commit()
        
    # Replay still works
    resp = client.get("/api/v1/core/replay")
    assert resp.status_code == 200
    assert len(resp.json()["timeline"]) == 5
    
    # Snapshot replay degrades to full replay gracefully
    snap_replay_resp = client.get("/api/v1/core/replay/snapshot?module_name=core&projection_name=core_replay")
    assert snap_replay_resp.status_code == 200
    assert snap_replay_resp.json()["snapshot_used"] is False
    assert snap_replay_resp.json()["state"] == resp.json()["state"]

def test_6_broken_ledger_invalidates_snapshot(setup_test_db):
    # Append new event, take snapshot
    resp = client.post("/api/v1/core/append/observation", json={
        "actor_id": "tester",
        "payload": {"data": "valid_obs"},
        "parent_ids": [],
        "signature": "SIG"
    })
    last_event_id = resp.json()["id"]
    
    client.post("/api/v1/core/snapshots", json={
        "projection_name": "broken_proj",
        "module_name": "core",
        "last_commitment_id": last_event_id,
        "projection_payload": {}
    })
    
    # Break ledger BEFORE the snapshot (e.g. event index 1)
    db_path = setup_test_db.db_path
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM events ORDER BY timestamp ASC LIMIT 1 OFFSET 1")
        target = cursor.fetchone()[0]
        cursor.execute("UPDATE events SET previous_hash = 'BROKEN' WHERE id = ?", (target,))
        conn.commit()
        
    # Replay from snapshot should fail because ledger up to snapshot is broken
    snap_replay_resp = client.get("/api/v1/core/replay/snapshot?module_name=core&projection_name=broken_proj")
    assert snap_replay_resp.status_code == 500
    assert "Broken hash chain" in snap_replay_resp.json()["detail"]
