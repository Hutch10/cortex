import pytest
from fastapi.testclient import TestClient
from main import app
from core.ledger import CortexLedger
import os

client = TestClient(app)

# We will patch the dependency in the router to use a test database
@pytest.fixture(autouse=True)
def setup_test_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_api.sqlite"
    test_ledger = CortexLedger(str(db_file))
    
    # Patch the get_ledger function in core_api
    import api.core_api
    monkeypatch.setattr(api.core_api, "get_ledger", lambda: test_ledger)
    
    return test_ledger

def test_resolve_actor():
    response = client.post("/api/v1/core/actor/resolve?actor_id=test_actor")
    assert response.status_code == 200
    assert response.json()["actor_id"] == "test_actor"

def test_valid_observation_append():
    response = client.post("/api/v1/core/append/observation", json={
        "actor_id": "actor_1",
        "payload": {"data": "test"},
        "parent_ids": [],
        "signature": "TRUSTED_ACTOR_SIG"
    })
    assert response.status_code == 200
    assert response.json()["type"] == "Observation"
    return response.json()["id"]

def test_valid_evidence_append():
    obs_id = test_valid_observation_append()
    response = client.post("/api/v1/core/append/evidence", json={
        "actor_id": "actor_1",
        "payload": {"data": "test evidence"},
        "parent_ids": [obs_id],
        "signature": "TRUSTED_ACTOR_SIG"
    })
    assert response.status_code == 200
    assert response.json()["type"] == "Evidence"
    return response.json()["id"]

def test_valid_claim_with_evidence():
    ev_id = test_valid_evidence_append()
    response = client.post("/api/v1/core/append/claim", json={
        "actor_id": "actor_1",
        "payload": {"data": "test claim"},
        "parent_ids": [ev_id],
        "signature": "TRUSTED_ACTOR_SIG"
    })
    assert response.status_code == 200
    assert response.json()["type"] == "Claim"

def test_invalid_claim_fails_closed():
    response = client.post("/api/v1/core/append/claim", json={
        "actor_id": "actor_1",
        "payload": {"data": "baseless claim"},
        "parent_ids": [],
        "signature": "TRUSTED_ACTOR_SIG"
    })
    assert response.status_code == 400
    assert "must cite evidence or observations" in response.json()["detail"]

def test_valid_decision():
    obs_id = test_valid_observation_append()
    response = client.post("/api/v1/core/append/decision", json={
        "actor_id": "actor_1",
        "payload": {"action": "do it"},
        "parent_ids": [obs_id],
        "signature": "TRUSTED_ACTOR_SIG"
    })
    assert response.status_code == 200

def test_invalid_decision_fails_closed():
    response = client.post("/api/v1/core/append/decision", json={
        "actor_id": "actor_1",
        "payload": {"action": "do it randomly"},
        "parent_ids": [],
        "signature": "TRUSTED_ACTOR_SIG"
    })
    assert response.status_code == 400

def test_replay_deterministic_ordering():
    test_valid_observation_append()
    test_valid_evidence_append()
    
    response = client.get("/api/v1/core/replay")
    assert response.status_code == 200
    state = response.json()["state"]
    assert len(state["observations"]) > 0

def test_hash_chain_validation():
    test_valid_observation_append()
    response = client.get("/api/v1/core/integrity")
    assert response.status_code == 200
    assert response.json()["valid"] is True
    assert response.json()["chain_length"] > 0
