import pytest
import os
import json
from core.primitives import EventEnvelope, PrimitiveType
from core.ledger import CortexLedger
from core.identity import IdentityResolver
from core.replay import ReplayEngine
from core.policy import PolicyInvariants

@pytest.fixture
def temp_ledger(tmp_path):
    db_file = tmp_path / "test_cortex.sqlite"
    return CortexLedger(str(db_file))

def create_valid_event(type: PrimitiveType, payload: dict, parent_ids: list, prev_hash: str) -> EventEnvelope:
    event = EventEnvelope(
        id="temp",
        timestamp=1000000,
        actor_id="actor_1",
        type=type,
        payload=payload,
        parent_ids=parent_ids,
        signature="TRUSTED_ACTOR_SIG",
        previous_hash=prev_hash
    )
    
    basis = {
        "timestamp": event.timestamp,
        "actor_id": event.actor_id,
        "type": event.type.value,
        "payload": event.payload,
        "parent_ids": event.parent_ids,
        "previous_hash": event.previous_hash
    }
    import hashlib
    basis_json = json.dumps(basis, sort_keys=True, separators=(',', ':'))
    event.id = hashlib.sha256(basis_json.encode('utf-8')).hexdigest()
    return event

def test_append_observation(temp_ledger):
    obs = create_valid_event(PrimitiveType.OBSERVATION, {"data": "test"}, [], "GENESIS")
    temp_ledger.append_event(obs)
    
    events = temp_ledger.get_events()
    assert len(events) == 1
    assert events[0].id == obs.id

def test_hash_chaining_fails_on_invalid_hash(temp_ledger):
    obs = create_valid_event(PrimitiveType.OBSERVATION, {"data": "test"}, [], "GENESIS")
    obs.id = "BAD_HASH"
    with pytest.raises(ValueError, match="Invalid event hash"):
        temp_ledger.append_event(obs)

def test_hash_chaining_fails_on_invalid_prev_hash(temp_ledger):
    obs = create_valid_event(PrimitiveType.OBSERVATION, {"data": "test"}, [], "GENESIS")
    temp_ledger.append_event(obs)
    
    obs2 = create_valid_event(PrimitiveType.OBSERVATION, {"data": "test2"}, [], "WRONG_CHAIN")
    with pytest.raises(ValueError, match="Invalid chain"):
        temp_ledger.append_event(obs2)

def test_policy_invariants_fail_closed(temp_ledger):
    # Claim without parent (no evidence)
    claim = create_valid_event(PrimitiveType.CLAIM, {"belief": "true"}, [], "GENESIS")
    with pytest.raises(ValueError, match="Claims must cite evidence or observations"):
        temp_ledger.append_event(claim)

def test_replay_reconstruction(temp_ledger):
    obs = create_valid_event(PrimitiveType.OBSERVATION, {"hrv": 50}, [], "GENESIS")
    temp_ledger.append_event(obs)
    
    ev = create_valid_event(PrimitiveType.EVIDENCE, {"source": "garmin"}, [obs.id], obs.id)
    temp_ledger.append_event(ev)
    
    claim = create_valid_event(PrimitiveType.CLAIM, {"stressed": True}, [ev.id], ev.id)
    temp_ledger.append_event(claim)
    
    replay = ReplayEngine(temp_ledger)
    state = replay.reconstruct_state()
    
    assert obs.id in state["observations"]
    assert claim.id in state["claims"]
    assert len(state["evidence_links"]) == 1
    assert state["evidence_links"][0]["targets"][0] == obs.id
