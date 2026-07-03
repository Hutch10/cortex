import pytest
import os
import hashlib
import json
import copy
from fastapi import FastAPI
from fastapi.testclient import TestClient
from api.core_api import router as core_router, AppendPayload
from core.ledger import CortexLedger

app = FastAPI()
app.include_router(core_router, prefix="/api/v1/core")
client = TestClient(app)

class EdgeCommitQueue:
    def __init__(self):
        self.queue = []
    
    def enqueue(self, item_type: str, payload: dict, parent_ids: list):
        import uuid
        local_uuid = str(uuid.uuid4())
        payload_copy = copy.deepcopy(payload)
        payload_copy["_local_uuid"] = local_uuid
        
        self.queue.append({
            "type": item_type,
            "actor_id": "myco_user_1",
            "payload": payload_copy,
            "parent_ids": parent_ids,
            "signature": "MYCO_SIG_1"
        })
        return local_uuid
    
    def persist(self):
        # Simulate saving to IndexedDB
        return json.dumps(self.queue)
        
    def restore(self, data: str):
        # Simulate loading from IndexedDB
        self.queue = json.loads(data)

    def pop(self):
        return self.queue.pop(0)

@pytest.fixture(scope="module")
def setup_test_db(tmp_path_factory):
    # Use a persistent db for the whole module so state accumulates
    db_file = tmp_path_factory.mktemp("data") / "test_myco.sqlite"
    test_ledger = CortexLedger(str(db_file))
    
    import api.core_api
    app.dependency_overrides[api.core_api.get_ledger] = lambda: test_ledger
    
    # We must append a genesis event or handle it, but appending is done in test 4.
    
    yield test_ledger
    
    # Teardown
    app.dependency_overrides.clear()

@pytest.fixture(scope="module")
def edge_queue():
    return EdgeCommitQueue()

def test_scenario_1_offline_observation(edge_queue):
    # Scenario 1: Offline Observation Capture
    payload = {"domain": "myco_os", "type": "field_encounter", "gps": "[45.0, -90.0]", "habitat": "coniferous forest"}
    edge_queue.enqueue("observation", payload, [])
    assert len(edge_queue.queue) == 1
    # Succeeds: It is stored offline

def test_scenario_2_offline_media_evidence(edge_queue):
    # Scenario 2: Offline Media Evidence Capture
    # Simulate External Hash Strategy
    fake_photo_data = b"mushroom_photo_binary"
    photo_hash = hashlib.sha256(fake_photo_data).hexdigest()
    photo_uri = f"s3://myco-photos/{photo_hash}.jpg"
    
    payload = {
        "domain": "myco_os", 
        "type": "specimen_media", 
        "uri": photo_uri, 
        "file_hash": photo_hash
    }
    
    parent_uuid = edge_queue.queue[0]["payload"]["_local_uuid"]
    
    edge_queue.enqueue("evidence", payload, [parent_uuid])
    assert len(edge_queue.queue) == 2
    # Succeeds: Evidence is stored offline with URI/Hash, no BLOB.

def test_scenario_3_offline_queue_persistence(edge_queue):
    # Scenario 3: Offline Queue Persistence
    persisted_data = edge_queue.persist()
    assert persisted_data is not None
    
    # Simulate application restart
    new_queue = EdgeCommitQueue()
    new_queue.restore(persisted_data)
    
    assert len(new_queue.queue) == 2
    assert new_queue.queue[1]["payload"]["uri"].startswith("s3://")
    
    # We replace the fixture's queue with the restored one
    edge_queue.queue = new_queue.queue

def test_scenario_4_sync_after_reconnection(setup_test_db, edge_queue):
    # Scenario 4: Sync After Reconnection
    id_map = {}
    
    synced_count = 0
    while edge_queue.queue:
        item = edge_queue.queue[0]
        local_uuid = item["payload"]["_local_uuid"]
        
        # Resolve local parent_ids to Cortex IDs
        resolved_parents = []
        for p in item["parent_ids"]:
            if p in id_map:
                resolved_parents.append(id_map[p])
            else:
                resolved_parents.append(p)
                
        req_json = {
            "actor_id": item["actor_id"],
            "payload": item["payload"],
            "parent_ids": resolved_parents,
            "signature": item["signature"]
        }
        
        endpoint = f"/api/v1/core/append/{item['type']}"
        response = client.post(endpoint, json=req_json)
        
        assert response.status_code == 200, f"Sync failed: {response.text}"
        
        cortex_id = response.json()["id"]
        id_map[local_uuid] = cortex_id
        
        edge_queue.pop()
        synced_count += 1
        
    assert synced_count == 2
    assert len(edge_queue.queue) == 0

def test_scenario_5_duplicate_sync_attempt(setup_test_db):
    # Scenario 5: Duplicate Sync Attempt
    response = client.get("/api/v1/core/replay")
    timeline = response.json()["timeline"]
    
    # Find our myco observation
    myco_events = [t for t in timeline if "domain" in t["payload"] and t["payload"]["domain"] == "myco_os"]
    local_uuid = myco_events[0]["payload"]["_local_uuid"]
    
    duplicate_item = {
        "type": "observation",
        "actor_id": "myco_user_1",
        "payload": {"domain": "myco_os", "_local_uuid": local_uuid},
        "parent_ids": [],
        "signature": "MYCO_SIG_1"
    }
    
    # Sync logic pre-check
    is_duplicate = any(t["payload"].get("_local_uuid") == duplicate_item["payload"]["_local_uuid"] for t in timeline)
    assert is_duplicate is True

def test_scenario_6_missing_media_hash(setup_test_db):
    # Scenario 6: Missing Media Hash
    payload = {
        "domain": "myco_os", 
        "type": "specimen_media", 
        "uri": "s3://missing_hash.jpg"
    }
    
    def validate_myco_schema(item_type, payload):
        if item_type == "evidence" and "uri" in payload:
            if "file_hash" not in payload:
                raise ValueError("Missing file_hash for media evidence")
    
    with pytest.raises(ValueError, match="Missing file_hash"):
        validate_myco_schema("evidence", payload)

def test_scenario_7_invalid_parent_reference(setup_test_db):
    # Scenario 7: Invalid Parent Reference
    response = client.post("/api/v1/core/append/evidence", json={
        "actor_id": "myco_user_1",
        "payload": {"data": "orphan evidence"},
        "parent_ids": [],
        "signature": "MYCO_SIG"
    })
    assert response.status_code == 400
    assert "Evidence must link" in response.json()["detail"]

def test_scenario_8_claim_without_evidence(setup_test_db):
    # Scenario 8: Claim Without Supporting Evidence
    response = client.post("/api/v1/core/append/claim", json={
        "actor_id": "myco_user_1",
        "payload": {"species": "Amanita virosa"},
        "parent_ids": [],
        "signature": "MYCO_SIG"
    })
    assert response.status_code == 400
    assert "Claims must cite" in response.json()["detail"]

def test_scenario_9_decision_without_claim(setup_test_db):
    # Scenario 9: Decision Without Supporting Claim or Observation
    response = client.post("/api/v1/core/append/decision", json={
        "actor_id": "myco_user_1",
        "payload": {"action": "harvest"},
        "parent_ids": [],
        "signature": "MYCO_SIG"
    })
    assert response.status_code == 400
    assert "Decisions must cite" in response.json()["detail"]

def test_scenario_10_replay_reconstruction(setup_test_db):
    # Scenario 10: Replay Reconstruction
    response = client.get("/api/v1/core/replay")
    assert response.status_code == 200
    timeline = response.json()["timeline"]
    
    types = [t["type"] for t in timeline]
    assert "Observation" in types
    assert "Evidence" in types
    assert len(timeline) >= 2

def test_scenario_11_integrity_validation(setup_test_db):
    # Scenario 11: Integrity Validation
    response = client.get("/api/v1/core/integrity")
    assert response.status_code == 200
    assert response.json()["valid"] is True

def test_scenario_12_corrupted_commitment(setup_test_db):
    # Scenario 12: Corrupted Commitment
    import sqlite3
    db_path = setup_test_db.db_path
    
    events = setup_test_db.get_events(limit=2)
    event_id = events[0].id
    
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE events SET id = 'TAMPERED_ID' WHERE id = ?", (event_id,))
        conn.commit()
    
    response = client.get("/api/v1/core/integrity")
    assert response.status_code == 500
    assert "Broken hash chain" in response.json()["detail"]
