from typing import Dict, Any, List
from .primitives import EventEnvelope, PrimitiveType
from .ledger import CortexLedger

class ReplayEngine:
    def __init__(self, ledger: CortexLedger):
        self.ledger = ledger

    def reconstruct_state(self, snapshot_state: Dict[str, Any] = None, start_event_id: str = None) -> Dict[str, Any]:
        """
        Replays the append-only ledger chronologically to reconstruct reality.
        If a snapshot state and start_event_id are provided, it resumes replay from that point.
        """
        if snapshot_state and start_event_id:
            events = self.ledger.get_events_after(start_event_id, limit=10000)
            state = snapshot_state
        else:
            events = self.ledger.get_events(limit=10000)
            state = {
                "observations": {},
                "claims": {},
                "decisions": {},
                "evidence_links": []
            }
            
        for event in events:
            if event.type == PrimitiveType.OBSERVATION:
                state["observations"][event.id] = event.payload
            elif event.type == PrimitiveType.CLAIM:
                state["claims"][event.id] = {
                    "payload": event.payload,
                    "evidence_refs": event.parent_ids
                }
            elif event.type == PrimitiveType.DECISION:
                state["decisions"][event.id] = {
                    "payload": event.payload,
                    "based_on": event.parent_ids
                }
            elif event.type == PrimitiveType.EVIDENCE:
                state["evidence_links"].append({
                    "id": event.id,
                    "payload": event.payload,
                    "targets": event.parent_ids
                })
                
        return state
