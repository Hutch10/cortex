from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Iterable, Optional
from uuid import uuid4


@dataclass(frozen=True)
class BaseEvent:
    aggregate_id: str
    sequence: int
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    event_id: str = field(default_factory=lambda: str(uuid4()))

    @property
    def event_type(self) -> str:
        return self.__class__.__name__


@dataclass(frozen=True)
class DomainCreated(BaseEvent):
    domain_name: str = ""
    owner_id: str = ""


@dataclass(frozen=True)
class AssetCreated(BaseEvent):
    asset_id: str = ""
    domain_name: str = ""
    owner_id: str = ""


@dataclass(frozen=True)
class AssetRegistered(BaseEvent):
    asset_id: str = ""
    asset_type: str = ""
    continuity_id: str = ""
    lifecycle_state: str = "ACTIVE"
    ownership_status: str = ""
    acquisition_date: Optional[datetime] = None
    retirement_date: Optional[datetime] = None
    owner_id: str = ""
    domain_id: str = ""
    capabilities: Dict[str, Dict[str, object]] = field(default_factory=dict)
    metadata: Dict[str, object] = field(default_factory=dict)
    extension_payload: Dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class AssetUpdated(BaseEvent):
    asset_id: str = ""
    ownership_status: Optional[str] = None
    capabilities_patch: Dict[str, Dict[str, object]] = field(default_factory=dict)
    metadata_patch: Dict[str, object] = field(default_factory=dict)
    extension_payload: Dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class AssetTransferred(BaseEvent):
    asset_id: str = ""
    new_owner_id: str = ""
    new_domain_name: Optional[str] = None
    ownership_status: str = ""
    extension_payload: Dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class AssetRetired(BaseEvent):
    asset_id: str = ""
    reason: str = ""
    retirement_date: Optional[datetime] = None
    extension_payload: Dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class GoalCreated(BaseEvent):
    goal_id: str = ""
    title: str = ""
    metric_name: str = ""
    target_value: float = 0.0


@dataclass(frozen=True)
class GoalCompleted(BaseEvent):
    goal_id: str = ""


@dataclass(frozen=True)
class PersonaActivated(BaseEvent):
    persona_id: str = ""
    activation_mode: str = "manual"
    activation_reason: str = ""
    conflict_resolution_path: tuple[str, ...] = ()


@dataclass(frozen=True)
class PersonaDeactivated(BaseEvent):
    persona_id: str = ""
    deactivation_reason: str = ""


# Backward-compatible vehicle event types retained for legacy event ingestion paths.
@dataclass(frozen=True)
class VehicleRegistered(BaseEvent):
    vehicle_id: str = ""
    make: str = ""
    model: str = ""
    year: int = 0
    ownership_status: str = ""
    lifecycle_state: str = "ACTIVE"
    acquisition_date: Optional[datetime] = None
    retirement_date: Optional[datetime] = None
    continuity_id: str = ""
    owner_id: str = ""
    domain_name: str = ""
    odometer: float = 0.0
    fuel_battery_state: str = ""


@dataclass(frozen=True)
class VehicleUpdated(BaseEvent):
    vehicle_id: str = ""
    odometer: Optional[float] = None
    fuel_battery_state: Optional[str] = None
    ownership_status: Optional[str] = None


@dataclass(frozen=True)
class VehicleServiced(BaseEvent):
    vehicle_id: str = ""
    service_note: str = ""
    service_at_odometer: float = 0.0


@dataclass(frozen=True)
class VehicleTransferred(BaseEvent):
    vehicle_id: str = ""
    new_owner_id: str = ""
    ownership_status: str = ""


@dataclass(frozen=True)
class VehicleRetired(BaseEvent):
    vehicle_id: str = ""
    retired_reason: str = ""
    retirement_date: Optional[datetime] = None


Event = (
    DomainCreated
    | AssetCreated
    | AssetRegistered
    | AssetUpdated
    | AssetRetired
    | AssetTransferred
    | GoalCreated
    | GoalCompleted
    | PersonaActivated
    | PersonaDeactivated
    | VehicleRegistered
    | VehicleUpdated
    | VehicleServiced
    | VehicleTransferred
    | VehicleRetired
)


def ensure_deterministic_order(events: Iterable[Event]) -> list[Event]:
    ordered = sorted(events, key=lambda e: (e.sequence, e.occurred_at.isoformat(), e.event_id))
    seen = set()
    for event in ordered:
        if event.sequence in seen:
            raise ValueError(f"Duplicate event sequence detected: {event.sequence}")
        seen.add(event.sequence)
    return ordered


def event_to_dict(event: Event) -> Dict[str, object]:
    payload = {
        "event_type": event.event_type,
        "event_id": event.event_id,
        "aggregate_id": event.aggregate_id,
        "sequence": event.sequence,
        "occurred_at": event.occurred_at.isoformat(),
    }
    for key, value in event.__dict__.items():
        if key in payload:
            continue
        if isinstance(value, datetime):
            payload[key] = value.isoformat()
        else:
            payload[key] = value
    return payload
