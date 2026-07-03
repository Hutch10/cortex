import time
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import Dict, Any, List

from core.primitives import EventEnvelope, PrimitiveType
from core.ledger import CortexLedger
from core.replay import ReplayEngine

router = APIRouter()

# In a real app this would be injected via FastAPI Depends, but for the kernel we'll instantiate it here.
# Assuming tests / main point this to cortex.sqlite
def get_ledger():
    return CortexLedger("cortex.sqlite")

class AppendPayload(BaseModel):
    actor_id: str
    payload: Dict[str, Any]
    parent_ids: List[str] = []
    signature: str

def _append_commitment(req: AppendPayload, p_type: PrimitiveType, ledger: CortexLedger) -> EventEnvelope:
    import hashlib
    import json
    
    timestamp = int(time.time())
    previous_hash = ledger.get_latest_hash()
    
    basis = {
        "timestamp": timestamp,
        "actor_id": req.actor_id,
        "type": p_type.value,
        "payload": req.payload,
        "parent_ids": req.parent_ids,
        "previous_hash": previous_hash
    }
    basis_json = json.dumps(basis, sort_keys=True, separators=(',', ':'))
    event_id = hashlib.sha256(basis_json.encode('utf-8')).hexdigest()
    
    event = EventEnvelope(
        id=event_id,
        timestamp=timestamp,
        actor_id=req.actor_id,
        type=p_type,
        payload=req.payload,
        parent_ids=req.parent_ids,
        signature=req.signature,
        previous_hash=previous_hash
    )
    
    try:
        ledger.append_event(event)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
        
    return event

@router.post("/actor/resolve")
def resolve_actor(actor_id: str):
    # Stub for actor creation/resolution
    # Future: Verify DID or public key existence
    return {"status": "resolved", "actor_id": actor_id}

@router.post("/append/observation")
def append_observation(req: AppendPayload, ledger: CortexLedger = Depends(get_ledger)):
    return _append_commitment(req, PrimitiveType.OBSERVATION, ledger)

@router.post("/append/evidence")
def append_evidence(req: AppendPayload, ledger: CortexLedger = Depends(get_ledger)):
    return _append_commitment(req, PrimitiveType.EVIDENCE, ledger)

@router.post("/append/claim")
def append_claim(req: AppendPayload, ledger: CortexLedger = Depends(get_ledger)):
    return _append_commitment(req, PrimitiveType.CLAIM, ledger)

@router.post("/append/decision")
def append_decision(req: AppendPayload, ledger: CortexLedger = Depends(get_ledger)):
    return _append_commitment(req, PrimitiveType.DECISION, ledger)

@router.get("/replay")
def replay_timeline(ledger: CortexLedger = Depends(get_ledger)):
    engine = ReplayEngine(ledger)
    state = engine.reconstruct_state()
    
    # Return raw timeline events for UI rendering
    events = ledger.get_events(limit=10000)
    timeline = [
        {
            "id": e.id,
            "timestamp": e.timestamp,
            "actor_id": e.actor_id,
            "type": e.type.value,
            "payload": e.payload,
            "parent_ids": e.parent_ids
        } for e in events
    ]
    
    return {"status": "success", "state": state, "timeline": timeline}

@router.get("/integrity")
def verify_integrity(ledger: CortexLedger = Depends(get_ledger)):
    events = ledger.get_events(limit=10000) # In production, this would stream or chunk
    if not events:
        return {"valid": True, "chain_length": 0, "latest_hash": "GENESIS"}
        
    current_hash = "GENESIS"
    for event in events:
        if event.previous_hash != current_hash:
            raise HTTPException(status_code=500, detail=f"Broken hash chain at event {event.id}")
        current_hash = event.id
        
    return {
        "valid": True,
        "chain_length": len(events),
        "latest_hash": current_hash
    }

class CreateSnapshotRequest(BaseModel):
    projection_name: str
    module_name: str
    last_commitment_id: str
    projection_payload: Dict[str, Any]

@router.post("/snapshots")
def create_snapshot(req: CreateSnapshotRequest, ledger: CortexLedger = Depends(get_ledger)):
    import json
    import hashlib
    
    # 1. Snapshot create succeeds only against a valid last commitment hash
    event = ledger.get_event(req.last_commitment_id)
    if not event:
        raise HTTPException(status_code=400, detail="last_commitment_id not found in ledger")
        
    payload_json = json.dumps(req.projection_payload, sort_keys=True, separators=(',', ':'))
    payload_hash = hashlib.sha256(payload_json.encode('utf-8')).hexdigest()
    
    snapshot_id = hashlib.sha256(f"{req.last_commitment_id}:{payload_hash}".encode('utf-8')).hexdigest()
    
    from core.primitives import SnapshotEnvelope
    snapshot = SnapshotEnvelope(
        id=snapshot_id,
        projection_name=req.projection_name,
        module_name=req.module_name,
        last_commitment_id=req.last_commitment_id,
        last_commitment_hash=event.id, # The hash is the id
        created_at=int(time.time()),
        projection_payload=req.projection_payload,
        projection_hash=payload_hash
    )
    
    ledger.save_snapshot(snapshot)
    return {"status": "success", "snapshot_id": snapshot.id}

@router.get("/snapshots/{module_name}/{projection_name}/latest")
def get_latest_snapshot(module_name: str, projection_name: str, ledger: CortexLedger = Depends(get_ledger)):
    snapshot = ledger.get_latest_snapshot(module_name, projection_name)
    if not snapshot:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    return snapshot

@router.get("/replay/snapshot")
def replay_from_snapshot(module_name: str, projection_name: str, ledger: CortexLedger = Depends(get_ledger)):
    snapshot = ledger.get_latest_snapshot(module_name, projection_name)
    if not snapshot:
        # Gracefully degrade to full replay
        engine = ReplayEngine(ledger)
        return {"status": "success", "state": engine.reconstruct_state(), "snapshot_used": False}
        
    # Verify snapshot payload hasn't been tampered with
    import json
    import hashlib
    payload_json = json.dumps(snapshot.projection_payload, sort_keys=True, separators=(',', ':'))
    payload_hash = hashlib.sha256(payload_json.encode('utf-8')).hexdigest()
    if snapshot.projection_hash != payload_hash:
        raise HTTPException(status_code=500, detail="Snapshot payload hash mismatch")
        
    # Verify ledger integrity up to this snapshot's last_commitment_id
    # We do a mini integrity check
    events = ledger.get_events(limit=10000)
    current_hash = "GENESIS"
    event_found = False
    for event in events:
        if event.previous_hash != current_hash:
            # Ledger is broken. Do not use snapshot. Degrade to full replay? Or fail?
            # Instructions: "Broken ledger integrity invalidates snapshot use."
            # Actually, if ledger is broken, full replay will also eventually fail or we should just fail closed.
            # But the prompt specifically says "Broken ledger integrity invalidates snapshot use" -> wait, does it mean we reject the snapshot?
            # Let's just raise an error because the ledger is fundamentally corrupted.
            pass
        if event.previous_hash != current_hash:
            raise HTTPException(status_code=500, detail="Broken hash chain in ledger")
            
        current_hash = event.id
        if event.id == snapshot.last_commitment_id:
            event_found = True
            break
            
    if not event_found:
        raise HTTPException(status_code=400, detail="Snapshot last_commitment_id not in valid ledger chain")
        
    engine = ReplayEngine(ledger)
    state = engine.reconstruct_state(snapshot_state=snapshot.projection_payload, start_event_id=snapshot.last_commitment_id)
    return {"status": "success", "state": state, "snapshot_used": True}
