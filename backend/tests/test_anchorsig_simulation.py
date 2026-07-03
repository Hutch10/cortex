import pytest
import sqlite3
import copy
from fastapi import FastAPI
from fastapi.testclient import TestClient
from api.core_api import router as core_router
from core.ledger import CortexLedger

app = FastAPI()
app.include_router(core_router, prefix="/api/v1/core")
client = TestClient(app)

class AnchorSigProjection:
    def __init__(self, ledger):
        self.ledger = ledger
        self.snapshots = {} # thread_id -> latest snapshot event id
    
    def take_snapshot(self, thread_id, event_id):
        self.snapshots[thread_id] = event_id

    def reconstruct_thread(self, thread_id: str):
        events = self.ledger.get_events(limit=10000)
        
        # If snapshot exists, we would skip iterating prior events.
        # For simulation, we just find the state.
        
        state = {
            "last_snapshot": None,
            "interrupted": False,
            "recovered": False,
            "context": None,
            "missing_links": False
        }
        
        # Simulate applying events
        for e in events:
            if "domain" in e.payload and e.payload["domain"] == "anchorsig" and e.payload.get("thread_id") == thread_id:
                if e.payload.get("context_type") == "snapshot":
                    state["last_snapshot"] = e.id
                    state["context"] = e.payload.get("context")
                    state["interrupted"] = False
                    state["recovered"] = False
                elif e.payload.get("context_type") == "interruption":
                    # Check if parent is the snapshot
                    if not e.parent_ids or state["last_snapshot"] not in e.parent_ids:
                        state["missing_links"] = True
                    state["interrupted"] = True
                elif e.payload.get("context_type") == "recovery":
                    state["recovered"] = True
                    state["interrupted"] = False
                    
        return state

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
            "actor_id": "anchorsig_user",
            "payload": payload_copy,
            "parent_ids": parent_ids,
            "signature": "SIG"
        })
        return local_uuid

    def pop(self):
        return self.queue.pop(0)

@pytest.fixture(scope="module")
def setup_test_db(tmp_path_factory):
    db_file = tmp_path_factory.mktemp("data") / "test_anchorsig.sqlite"
    test_ledger = CortexLedger(str(db_file))
    
    import api.core_api
    app.dependency_overrides[api.core_api.get_ledger] = lambda: test_ledger
    
    yield test_ledger
    
    app.dependency_overrides.clear()

def test_scenario_1_interrupted_task_recovery(setup_test_db):
    # 1. Interrupted Task Recovery
    # User captures context
    resp1 = client.post("/api/v1/core/append/observation", json={
        "actor_id": "user",
        "payload": {"domain": "anchorsig", "thread_id": "T1", "context_type": "snapshot", "context": "Editing test.py"},
        "parent_ids": [],
        "signature": "SIG"
    })
    snap_id = resp1.json()["id"]
    
    # Interruption (24 hours disappear simulated by next event)
    client.post("/api/v1/core/append/evidence", json={
        "actor_id": "user",
        "payload": {"domain": "anchorsig", "thread_id": "T1", "context_type": "interruption"},
        "parent_ids": [snap_id],
        "signature": "SIG"
    })
    
    # Replay reconstructs where they stopped
    proj = AnchorSigProjection(setup_test_db)
    state = proj.reconstruct_thread("T1")
    
    assert state["interrupted"] is True
    assert state["context"] == "Editing test.py"
    assert state["missing_links"] is False

def test_scenario_2_context_loss_recovery(setup_test_db):
    # 2. Context Loss Recovery (Fragmented observations)
    client.post("/api/v1/core/append/observation", json={
        "actor_id": "user",
        "payload": {"domain": "anchorsig", "thread_id": "T2", "context_type": "snapshot", "context": "Fragment A"},
        "parent_ids": [],
        "signature": "SIG"
    })
    resp = client.post("/api/v1/core/append/observation", json={
        "actor_id": "user",
        "payload": {"domain": "anchorsig", "thread_id": "T2", "context_type": "snapshot", "context": "Fragment B"},
        "parent_ids": [],
        "signature": "SIG"
    })
    
    proj = AnchorSigProjection(setup_test_db)
    state = proj.reconstruct_thread("T2")
    
    # Reconstructs meaningful continuity (latest fragment)
    assert state["context"] == "Fragment B"
    assert state["interrupted"] is False

def test_scenario_3_offline_capture(setup_test_db):
    # 3. Offline Capture
    queue = EdgeCommitQueue()
    loc_id1 = queue.enqueue("observation", {"domain": "anchorsig", "thread_id": "T3", "context_type": "snapshot", "context": "Offline Context"}, [])
    loc_id2 = queue.enqueue("evidence", {"domain": "anchorsig", "thread_id": "T3", "context_type": "interruption"}, [loc_id1])
    
    # Sync
    id_map = {}
    while queue.queue:
        item = queue.pop()
        resolved_parents = [id_map.get(p, p) for p in item["parent_ids"]]
        resp = client.post(f"/api/v1/core/append/{item['type']}", json={
            "actor_id": item["actor_id"],
            "payload": item["payload"],
            "parent_ids": resolved_parents,
            "signature": item["signature"]
        })
        id_map[item["payload"]["_local_uuid"]] = resp.json()["id"]
        
    proj = AnchorSigProjection(setup_test_db)
    state = proj.reconstruct_thread("T3")
    assert state["context"] == "Offline Context"
    assert state["interrupted"] is True

def test_scenario_4_high_volume_capture(setup_test_db):
    # 4. High-Volume Capture
    # Simulate high volume by directly appending to db to avoid slow http calls in test
    import sqlite3
    db_path = setup_test_db.db_path
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        for i in range(100): # Mocking volume
            cursor.execute('''INSERT INTO events (id, timestamp, actor_id, type, payload, parent_ids, signature, previous_hash)
                              VALUES (?, ?, ?, ?, ?, ?, ?, ?)''', 
                           (f"VOL_{i}", "2026", "user", "Observation", f'{{"domain":"anchorsig","thread_id":"T4","context_type":"snapshot","context":"V_{i}"}}', "[]", "SIG", f"VOL_{i-1}"))
        conn.commit()
    
    proj = AnchorSigProjection(setup_test_db)
    # The snapshot strategy would take over here. We test if replay handles it deterministically.
    state = proj.reconstruct_thread("T4")
    assert state["context"] == "V_99"

def test_scenario_5_corrupted_context(setup_test_db):
    # 5. Corrupted Context
    # Missing parent link (e.g. interruption event without context snapshot parent)
    resp = client.post("/api/v1/core/append/evidence", json={
        "actor_id": "user",
        "payload": {"domain": "anchorsig", "thread_id": "T5", "context_type": "interruption"},
        "parent_ids": [], # Missing
        "signature": "SIG"
    })
    # Cortex invariant (Evidence must link) blocks it
    assert resp.status_code == 400

def test_scenario_6_competing_threads(setup_test_db):
    # 6. Competing Context Threads
    # Multiple active tasks
    client.post("/api/v1/core/append/observation", json={
        "actor_id": "user",
        "payload": {"domain": "anchorsig", "thread_id": "A", "context_type": "snapshot", "context": "Task A"},
        "parent_ids": [],
        "signature": "SIG"
    })
    client.post("/api/v1/core/append/observation", json={
        "actor_id": "user",
        "payload": {"domain": "anchorsig", "thread_id": "B", "context_type": "snapshot", "context": "Task B"},
        "parent_ids": [],
        "signature": "SIG"
    })
    
    proj = AnchorSigProjection(setup_test_db)
    assert proj.reconstruct_thread("A")["context"] == "Task A"
    assert proj.reconstruct_thread("B")["context"] == "Task B"

def test_scenario_7_edge_queue_failure(setup_test_db):
    # 7. Edge Queue Failure (Partial Sync)
    queue = EdgeCommitQueue()
    loc_1 = queue.enqueue("observation", {"domain": "anchorsig", "thread_id": "T7", "context_type": "snapshot", "context": "Partial Context"}, [])
    loc_2 = queue.enqueue("evidence", {"domain": "anchorsig", "thread_id": "T7", "context_type": "interruption"}, [loc_1])
    
    # Sync ONLY the first item
    item = queue.pop()
    client.post(f"/api/v1/core/append/{item['type']}", json={
        "actor_id": item["actor_id"],
        "payload": item["payload"],
        "parent_ids": item["parent_ids"],
        "signature": item["signature"]
    })
    
    # Second item fails or network drops
    proj = AnchorSigProjection(setup_test_db)
    state = proj.reconstruct_thread("T7")
    
    # Deterministic recovery: Context exists, but it's not marked interrupted because evidence didn't sync
    assert state["context"] == "Partial Context"
    assert state["interrupted"] is False
