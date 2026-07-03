from .primitives import EventEnvelope, PrimitiveType

class PolicyInvariants:
    @staticmethod
    def check_invariants(event: EventEnvelope) -> None:
        """
        Ensures foundational rules are obeyed before an event can be appended.
        """
        # 1. Claims MUST cite evidence or observations.
        if event.type == PrimitiveType.CLAIM:
            if not event.parent_ids:
                raise ValueError("Invariant Failed: Claims must cite evidence or observations.")
                
        # 2. Decisions MUST cite claims or observations.
        if event.type == PrimitiveType.DECISION:
            if not event.parent_ids:
                raise ValueError("Invariant Failed: Decisions must cite claims or observations.")
                
        # 3. Evidence MUST link.
        if event.type == PrimitiveType.EVIDENCE:
            if len(event.parent_ids) < 1:
                raise ValueError("Invariant Failed: Evidence must link to an observation or claim.")
