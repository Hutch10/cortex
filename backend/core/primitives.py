from enum import Enum
from pydantic import BaseModel, Field
from typing import Dict, Any, List

class PrimitiveType(str, Enum):
    OBSERVATION = "Observation"
    EVIDENCE = "Evidence"
    CLAIM = "Claim"
    DECISION = "Decision"

class EventEnvelope(BaseModel):
    """The universal cryptographic wrapper for all primitives."""
    id: str = Field(..., description="SHA-256 hash of the event contents")
    timestamp: int = Field(..., description="Unix epoch time of the event")
    actor_id: str = Field(..., description="Public key or DID of the actor")
    type: PrimitiveType = Field(..., description="The fundamental primitive type")
    payload: Dict[str, Any] = Field(..., description="Module-specific data payload")
    parent_ids: List[str] = Field(default_factory=list, description="IDs of precursor events")
    signature: str = Field(..., description="Cryptographic signature by the actor")
    previous_hash: str = Field(..., description="Hash of the preceding ledger entry to form a chain")

class SnapshotEnvelope(BaseModel):
    """A disposable cached projection derived from the ledger up to a specific commitment hash."""
    id: str = Field(..., description="Unique ID for the snapshot")
    projection_name: str = Field(..., description="Name of the projection")
    module_name: str = Field(..., description="Name of the module")
    last_commitment_id: str = Field(..., description="Event ID of the last processed commitment")
    last_commitment_hash: str = Field(..., description="Hash of the last processed commitment")
    created_at: int = Field(..., description="Unix epoch time of snapshot creation")
    projection_payload: Dict[str, Any] = Field(..., description="The cached projection state")
    projection_hash: str = Field(..., description="Hash of the projection payload to detect corruption")
