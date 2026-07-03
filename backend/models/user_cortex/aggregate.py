from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from hashlib import sha256
import json
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .events import (
    AssetCreated,
    AssetRegistered,
    AssetRetired,
    AssetTransferred,
    AssetUpdated,
    DomainCreated,
    Event,
    GoalCompleted,
    GoalCreated,
    PersonaActivated,
    PersonaDeactivated,
    VehicleRegistered,
    VehicleRetired,
    VehicleServiced,
    VehicleTransferred,
    VehicleUpdated,
    ensure_deterministic_order,
)


class AssetState(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    RETIRED = "RETIRED"
    TRANSFERRED = "TRANSFERRED"
    ARCHIVED = "ARCHIVED"


class LifeDomainName(str, Enum):
    PERSONAL = "Personal"
    FAMILY = "Family"
    HEALTH = "Health"
    BUSINESS = "Business"
    TRAVEL = "Travel"
    VEHICLES = "Vehicles"
    PROPERTY = "Property"
    AVIATION = "Aviation"
    MARINE = "Marine"
    RESEARCH = "Research"
    FINANCE = "Finance"
    EDUCATION = "Education"


class PersonaType(str, Enum):
    PERSONAL = "Personal"
    BUSINESS = "Business"
    PILOT = "Pilot"
    RESEARCHER = "Researcher"
    TRAVELER = "Traveler"


class PersonaActivationMode(str, Enum):
    MANUAL = "manual"
    CONTEXT = "context"
    SCHEDULED = "scheduled"
    DEACTIVATED = "deactivated"


class ProjectionType(str, Enum):
    GOAL_PROJECTION = "GoalProjection"
    ASSET_PROJECTION = "AssetProjection"
    SCHEDULE_PROJECTION = "ScheduleProjection"
    MAINTENANCE_PROJECTION = "MaintenanceProjection"
    TRAVEL_PROJECTION = "TravelProjection"


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _stable_hash(value: object) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


class ContinuityRelationType(str, Enum):
    REPLACEMENT = "replacement"
    SUCCESSION = "succession"
    TRANSFER = "transfer"
    MERGE = "merge"
    MERGER = "merge"
    SPLIT = "split"


@dataclass
class RootIdentity:
    continuity_id: str
    legal_name: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class LifeDomain:
    name: LifeDomainName
    owner_id: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def isolation_key(self) -> str:
        return f"{self.owner_id}:{self.name.value.lower()}"


@dataclass
class AssetStateRecord:
    state: AssetState
    changed_at: datetime
    owner_id: str
    domain_name: LifeDomainName
    note: str = ""


@dataclass
class Asset:
    asset_id: str
    continuity_id: str
    owner_id: str
    domain_name: LifeDomainName
    state: AssetState = AssetState.ACTIVE
    history: List[AssetStateRecord] = field(default_factory=list)

    def record(
        self,
        state: AssetState,
        owner_id: str,
        domain_name: LifeDomainName,
        note: str = "",
        changed_at: Optional[datetime] = None,
    ) -> None:
        self.state = state
        self.owner_id = owner_id
        self.domain_name = domain_name
        self.history.append(
            AssetStateRecord(
                state=state,
                changed_at=changed_at or datetime.now(timezone.utc),
                owner_id=owner_id,
                domain_name=domain_name,
                note=note,
            )
        )

    def state_at(self, history_index: int) -> AssetStateRecord:
        return self.history[history_index]


@dataclass
class MobilityCapability:
    make: str = ""
    model: str = ""
    year: int = 0
    odometer: float = 0.0
    fuel_battery_state: str = ""

    def to_dict(self) -> Dict[str, object]:
        return {
            "make": self.make,
            "model": self.model,
            "year": self.year,
            "odometer": self.odometer,
            "fuel_battery_state": self.fuel_battery_state,
        }


@dataclass
class MaintenanceCapability:
    maintenance_records: List[str] = field(default_factory=list)
    service_history: List[Dict[str, object]] = field(default_factory=list)
    inspection_history: List[Dict[str, object]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        return {
            "maintenance_records": list(self.maintenance_records),
            "service_history": list(self.service_history),
            "inspection_history": list(self.inspection_history),
        }


@dataclass
class TelemetryCapability:
    metrics: Dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, object]:
        return {"metrics": dict(self.metrics)}


@dataclass
class PropertyCapability:
    details: Dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, object]:
        return {"details": dict(self.details)}


@dataclass
class DeviceCapability:
    details: Dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, object]:
        return {"details": dict(self.details)}


@dataclass
class AssetOwnershipRecord:
    owner_id: str
    status: str
    changed_at: datetime


@dataclass
class AssetNode:
    asset_id: str
    asset_type: str
    continuity_id: str
    lifecycle_state: AssetState
    ownership_status: str
    acquisition_date: datetime
    retirement_date: Optional[datetime]
    domain_id: str
    owner_id: str
    capabilities: Dict[str, Dict[str, object]] = field(default_factory=dict)
    metadata: Dict[str, object] = field(default_factory=dict)
    ownership_history: List[AssetOwnershipRecord] = field(default_factory=list)


@dataclass
class ContinuityEdge:
    source_asset_id: str
    target_asset_id: str
    relation: ContinuityRelationType
    occurred_at: datetime
    metadata: Dict[str, object] = field(default_factory=dict)


@dataclass
class Goal:
    goal_id: str
    title: str
    metric_name: str
    target_value: float
    current_value: float = 0.0
    completed: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None


@dataclass
class Relationship:
    relationship_id: str
    subject_id: str
    relation_type: str
    target_id: str


@dataclass
class Module:
    module_id: str
    active: bool = True


@dataclass
class Permission:
    principal_id: str
    capabilities: set[str] = field(default_factory=set)


@dataclass
class Persona:
    persona_id: str
    persona_name: str
    persona_type: PersonaType = PersonaType.PERSONAL
    priority: int = 0
    activation_rules: Dict[str, object] = field(default_factory=dict)
    visibility_rules: Dict[str, object] = field(default_factory=dict)
    domain_scope: tuple[str, ...] = ()
    goal_scope: tuple[str, ...] = ()
    asset_scope: tuple[str, ...] = ()
    active: bool = False
    activated_at: Optional[datetime] = None

    @property
    def label(self) -> str:
        return self.persona_name


@dataclass
class PersonaAuditArtifact:
    artifact_id: str
    event_type: str
    persona_id: str
    activation_mode: str
    reason: str
    conflict_resolution_path: tuple[str, ...]
    visible_context: Dict[str, object]
    generated_at: datetime
    artifact_hash: str


@dataclass
class ProjectedState:
    projection_id: str
    projection_type: ProjectionType
    source_state_hash: str
    confidence_score: float
    generated_at: datetime
    expires_at: datetime
    trace_id: str
    projection_inputs: Dict[str, object] = field(default_factory=dict)
    projection_payload: Dict[str, object] = field(default_factory=dict)
    confidence_calculation: Dict[str, object] = field(default_factory=dict)
    source_truth_snapshot: Dict[str, object] = field(default_factory=dict)

    def is_expired(self, at: Optional[datetime] = None) -> bool:
        check_at = at or datetime.now(timezone.utc)
        return check_at >= self.expires_at


@dataclass
class ProjectionAuditArtifact:
    audit_id: str
    projection_id: str
    source_state_hash: str
    projection_inputs: Dict[str, object]
    confidence_calculation: Dict[str, object]
    generated_at: datetime
    expires_at: datetime
    trace_id: str
    audit_hash: str


@dataclass
class WorkingMemory:
    values: Dict[str, object] = field(default_factory=dict)

    def put(self, key: str, value: object) -> None:
        self.values[key] = value

    def get(self, key: str, default: object = None) -> object:
        return self.values.get(key, default)


@dataclass
class EpisodicMemoryItem:
    timestamp: datetime
    summary: str
    tags: List[str] = field(default_factory=list)


@dataclass
class EpisodicMemory:
    episodes: List[EpisodicMemoryItem] = field(default_factory=list)

    def add(self, summary: str, tags: Optional[List[str]] = None) -> None:
        self.episodes.append(
            EpisodicMemoryItem(
                timestamp=datetime.now(timezone.utc),
                summary=summary,
                tags=tags or [],
            )
        )


@dataclass
class CoreMemory:
    facts: Dict[str, object] = field(default_factory=dict)

    def set_if_absent(self, key: str, value: object) -> None:
        if key not in self.facts:
            self.facts[key] = value


@dataclass
class MemoryFoundation:
    working: WorkingMemory = field(default_factory=WorkingMemory)
    episodic: EpisodicMemory = field(default_factory=EpisodicMemory)
    core: CoreMemory = field(default_factory=CoreMemory)


@dataclass
class TwinSnapshot:
    timestamp: datetime
    event_type: str
    state: Dict[str, object]


@dataclass
class DigitalTwin:
    current_state: Dict[str, object] = field(default_factory=dict)
    historical_state: List[TwinSnapshot] = field(default_factory=list)
    projected_state: Optional[Dict[str, object]] = None
    projections: Dict[str, ProjectedState] = field(default_factory=dict)
    projection_audit: List[ProjectionAuditArtifact] = field(default_factory=list)

    def update_from_event(self, event: Event, aggregate: "UserCortexAggregate") -> None:
        active_asset_nodes = {
            asset_id: aggregate.project_asset_node(node)
            for asset_id, node in sorted(aggregate.asset_nodes.items(), key=lambda item: item[0])
            if node.lifecycle_state not in {AssetState.RETIRED, AssetState.ARCHIVED}
        }
        self.current_state = {
            "identity": aggregate.root_identity.continuity_id,
            "domains": sorted([d.value for d in aggregate.life_domains.keys()]),
            "asset_nodes": active_asset_nodes,
            "assets": {
                asset_id: {
                    "state": asset.state.value,
                    "owner_id": asset.owner_id,
                    "domain": asset.domain_name.value,
                    "continuity_id": asset.continuity_id,
                }
                for asset_id, asset in aggregate.assets.items()
            },
            "active_persona": aggregate.active_persona_id,
            "completed_goals": sorted([goal_id for goal_id, goal in aggregate.goals.items() if goal.completed]),
        }
        self.historical_state.append(
            TwinSnapshot(
                timestamp=event.occurred_at,
                event_type=event.event_type,
                state=deepcopy(self.current_state),
            )
        )

    def build_projection_stub(self) -> Dict[str, object]:
        self.projected_state = {
            "status": "stub",
            "basis": deepcopy(self.current_state),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        return self.projected_state

    def _build_projection_payload(
        self,
        projection_type: ProjectionType,
        projection_inputs: Mapping[str, object],
    ) -> Dict[str, object]:
        normalized_inputs = {str(k): deepcopy(v) for k, v in sorted(projection_inputs.items(), key=lambda item: str(item[0]))}
        if projection_type == ProjectionType.GOAL_PROJECTION:
            return {"target_trajectory": normalized_inputs, "category": projection_type.value}
        if projection_type == ProjectionType.ASSET_PROJECTION:
            return {"asset_trajectory": normalized_inputs, "category": projection_type.value}
        if projection_type == ProjectionType.SCHEDULE_PROJECTION:
            return {"schedule_trajectory": normalized_inputs, "category": projection_type.value}
        if projection_type == ProjectionType.MAINTENANCE_PROJECTION:
            return {"maintenance_trajectory": normalized_inputs, "category": projection_type.value}
        return {"travel_trajectory": normalized_inputs, "category": projection_type.value}

    def _deterministic_confidence(
        self,
        projection_type: ProjectionType,
        source_state_hash: str,
        projection_inputs: Mapping[str, object],
        trace_id: str,
    ) -> tuple[float, Dict[str, object]]:
        basis = {
            "projection_type": projection_type.value,
            "source_state_hash": source_state_hash,
            "projection_inputs": {str(k): deepcopy(v) for k, v in sorted(projection_inputs.items(), key=lambda item: str(item[0]))},
            "trace_id": trace_id,
        }
        confidence_hash = _stable_hash(basis)
        confidence_bucket = int(confidence_hash[:8], 16) % 4001
        confidence_score = round(0.6 + (confidence_bucket / 10000.0), 4)
        confidence_score = min(confidence_score, 0.99)
        return confidence_score, {
            "algorithm": "deterministic_hash_bucket_v1",
            "confidence_hash": confidence_hash,
            "confidence_bucket": confidence_bucket,
            "confidence_formula": "0.6 + bucket/10000",
            "confidence_score": confidence_score,
            "basis": basis,
        }

    def create_projection(
        self,
        projection_type: ProjectionType,
        projection_inputs: Mapping[str, object],
        ttl_seconds: int,
        trace_id: str,
        generated_at: Optional[datetime] = None,
    ) -> ProjectedState:
        if ttl_seconds <= 0:
            raise ValueError("projection ttl must be positive")

        now = generated_at or datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=ttl_seconds)
        source_truth_snapshot = deepcopy(self.current_state)
        source_state_hash = _stable_hash(source_truth_snapshot)
        normalized_inputs = {str(k): deepcopy(v) for k, v in sorted(projection_inputs.items(), key=lambda item: str(item[0]))}
        confidence_score, confidence_calculation = self._deterministic_confidence(
            projection_type=projection_type,
            source_state_hash=source_state_hash,
            projection_inputs=normalized_inputs,
            trace_id=trace_id,
        )
        projection_id = _stable_hash(
            {
                "projection_type": projection_type.value,
                "source_state_hash": source_state_hash,
                "projection_inputs": normalized_inputs,
                "generated_at": now.isoformat(),
                "expires_at": expires_at.isoformat(),
                "trace_id": trace_id,
            }
        )
        projection = ProjectedState(
            projection_id=projection_id,
            projection_type=projection_type,
            source_state_hash=source_state_hash,
            confidence_score=confidence_score,
            generated_at=now,
            expires_at=expires_at,
            trace_id=trace_id,
            projection_inputs=normalized_inputs,
            projection_payload=self._build_projection_payload(projection_type, normalized_inputs),
            confidence_calculation=confidence_calculation,
            source_truth_snapshot=source_truth_snapshot,
        )
        self.projections[projection_id] = projection

        audit_basis = {
            "projection_id": projection_id,
            "source_state_hash": source_state_hash,
            "projection_inputs": normalized_inputs,
            "confidence_calculation": confidence_calculation,
            "generated_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
            "trace_id": trace_id,
        }
        audit_hash = _stable_hash(audit_basis)
        audit_id = _stable_hash({"projection_id": projection_id, "audit_hash": audit_hash})
        self.projection_audit.append(
            ProjectionAuditArtifact(
                audit_id=audit_id,
                projection_id=projection_id,
                source_state_hash=source_state_hash,
                projection_inputs=normalized_inputs,
                confidence_calculation=confidence_calculation,
                generated_at=now,
                expires_at=expires_at,
                trace_id=trace_id,
                audit_hash=audit_hash,
            )
        )
        return projection

    def is_projection_active(self, projection_id: str, at: Optional[datetime] = None) -> bool:
        projection = self.projections.get(projection_id)
        if projection is None:
            return False
        return not projection.is_expired(at)

    def active_projections(self, at: Optional[datetime] = None) -> List[ProjectedState]:
        check_at = at or datetime.now(timezone.utc)
        return [
            projection
            for _, projection in sorted(self.projections.items(), key=lambda item: item[0])
            if not projection.is_expired(check_at)
        ]

    def replay_projection(self, projection_id: str, at: Optional[datetime] = None) -> Dict[str, object]:
        if projection_id not in self.projections:
            raise KeyError(f"Unknown projection: {projection_id}")
        projection = self.projections[projection_id]
        check_at = at or datetime.now(timezone.utc)
        source_truth_hash_recomputed = _stable_hash(projection.source_truth_snapshot)
        return {
            "projection_id": projection.projection_id,
            "source_truth": {
                "source_state_hash": projection.source_state_hash,
                "source_state_hash_recomputed": source_truth_hash_recomputed,
                "source_truth_snapshot": deepcopy(projection.source_truth_snapshot),
            },
            "projection_inputs": deepcopy(projection.projection_inputs),
            "confidence_calculations": deepcopy(projection.confidence_calculation),
            "expiration_state": {
                "generated_at": projection.generated_at.isoformat(),
                "expires_at": projection.expires_at.isoformat(),
                "is_expired": projection.is_expired(check_at),
            },
            "audit_artifacts": [
                {
                    "audit_id": audit.audit_id,
                    "projection_id": audit.projection_id,
                    "audit_hash": audit.audit_hash,
                    "trace_id": audit.trace_id,
                }
                for audit in self.projection_audit
                if audit.projection_id == projection_id
            ],
        }


@dataclass
class UserCortexAggregate:
    root_identity: RootIdentity
    preferences: Dict[str, object] = field(default_factory=dict)
    goals: Dict[str, Goal] = field(default_factory=dict)
    relationships: Dict[str, Relationship] = field(default_factory=dict)
    life_domains: Dict[LifeDomainName, LifeDomain] = field(default_factory=dict)
    assets: Dict[str, Asset] = field(default_factory=dict)
    asset_nodes: Dict[str, AssetNode] = field(default_factory=dict)
    continuity_index: Dict[str, List[str]] = field(default_factory=dict)
    continuity_graph: Dict[str, List[ContinuityEdge]] = field(default_factory=dict)
    modules: Dict[str, Module] = field(default_factory=dict)
    permissions: Dict[str, Permission] = field(default_factory=dict)
    personas: Dict[str, Persona] = field(default_factory=dict)
    persona_audit: List[PersonaAuditArtifact] = field(default_factory=list)
    goal_asset_state_attachments: Dict[str, List[Dict[str, object]]] = field(default_factory=dict)
    digital_twin: DigitalTwin = field(default_factory=DigitalTwin)
    memory: MemoryFoundation = field(default_factory=MemoryFoundation)
    _uncommitted_events: List[Event] = field(default_factory=list)
    _sequence: int = 1

    @property
    def vehicles(self) -> Dict[str, AssetNode]:
        return {asset_id: node for asset_id, node in self.asset_nodes.items() if node.asset_type == "vehicle"}

    @property
    def active_persona_id(self) -> Optional[str]:
        for persona_id, persona in self.personas.items():
            if persona.active:
                return persona_id
        return None

    @property
    def uncommitted_events(self) -> List[Event]:
        return list(self._uncommitted_events)

    def clear_uncommitted_events(self) -> None:
        self._uncommitted_events.clear()

    def _next_sequence(self) -> int:
        sequence = self._sequence
        self._sequence += 1
        return sequence

    def _record(self, event: Event) -> None:
        self._apply(event)
        self._uncommitted_events.append(event)

    def _record_persona_audit(
        self,
        event_type: str,
        persona_id: str,
        activation_mode: str,
        reason: str,
        conflict_resolution_path: Sequence[str],
        occurred_at: datetime,
    ) -> None:
        visible_context = self.resolve_visible_context_for_persona(persona_id)
        basis = {
            "event_type": event_type,
            "persona_id": persona_id,
            "activation_mode": activation_mode,
            "reason": reason,
            "conflict_resolution_path": list(conflict_resolution_path),
            "visible_context": visible_context,
            "occurred_at": occurred_at.isoformat(),
        }
        artifact_hash_value = _stable_hash(basis)
        artifact_id = _stable_hash(
            {
                "persona_id": persona_id,
                "event_type": event_type,
                "generated_at": occurred_at.isoformat(),
                "artifact_hash": artifact_hash_value,
            }
        )
        self.persona_audit.append(
            PersonaAuditArtifact(
                artifact_id=artifact_id,
                event_type=event_type,
                persona_id=persona_id,
                activation_mode=activation_mode,
                reason=reason,
                conflict_resolution_path=tuple(conflict_resolution_path),
                visible_context=visible_context,
                generated_at=occurred_at,
                artifact_hash=artifact_hash_value,
            )
        )

    def _persona_matches_context(
        self,
        persona: Persona,
        domain_scope: Sequence[str],
        goal_scope: Sequence[str],
        asset_scope: Sequence[str],
    ) -> bool:
        domain_match = not persona.domain_scope or bool(set(persona.domain_scope) & set(domain_scope))
        goal_match = not persona.goal_scope or bool(set(persona.goal_scope) & set(goal_scope))
        asset_match = not persona.asset_scope or bool(set(persona.asset_scope) & set(asset_scope))
        return domain_match and goal_match and asset_match

    def _persona_is_scheduled_active(self, persona: Persona, at: datetime) -> bool:
        windows = persona.activation_rules.get("schedule_windows", [])
        if not windows:
            return False
        weekday = at.weekday()
        hour = at.hour
        for window in windows:
            start_hour = int(window.get("start_hour", 0))
            end_hour = int(window.get("end_hour", 24))
            days = window.get("days", [0, 1, 2, 3, 4, 5, 6])
            if weekday in days and start_hour <= hour < end_hour:
                return True
        return False

    def _resolve_persona_priority(self, candidate_ids: Sequence[str]) -> tuple[Optional[str], tuple[str, ...]]:
        if not candidate_ids:
            return None, ("no_candidates",)
        ranked = sorted(
            [self.personas[persona_id] for persona_id in candidate_ids if persona_id in self.personas],
            key=lambda persona: (-persona.priority, persona.persona_id),
        )
        if not ranked:
            return None, ("no_registered_candidates",)
        selected = ranked[0]
        path = [f"candidates={','.join(sorted(candidate_ids))}"]
        path.append(f"selected={selected.persona_id}")
        path.append("rule=priority_desc_then_persona_id")
        return selected.persona_id, tuple(path)

    def resolve_visible_context_for_persona(self, persona_id: Optional[str]) -> Dict[str, object]:
        if persona_id is None or persona_id not in self.personas:
            return {
                "active_persona": None,
                "domain_scope": tuple(sorted([domain.value for domain in self.life_domains.keys()])),
                "goal_scope": tuple(sorted(self.goals.keys())),
                "asset_scope": tuple(sorted(self.asset_nodes.keys())),
            }
        persona = self.personas[persona_id]
        domain_scope = persona.domain_scope or tuple(sorted([domain.value for domain in self.life_domains.keys()]))
        goal_scope = persona.goal_scope or tuple(sorted(self.goals.keys()))
        asset_scope = persona.asset_scope or tuple(sorted(self.asset_nodes.keys()))
        return {
            "active_persona": persona_id,
            "domain_scope": tuple(sorted(domain_scope)),
            "goal_scope": tuple(sorted(goal_scope)),
            "asset_scope": tuple(sorted(asset_scope)),
        }

    def replay_persona_audit(self) -> Dict[str, object]:
        active = self.active_persona_id
        latest = self.persona_audit[-1] if self.persona_audit else None
        return {
            "active_persona": active,
            "activation_reason": None if latest is None else latest.reason,
            "conflict_resolution_path": tuple() if latest is None else latest.conflict_resolution_path,
            "visible_context": self.resolve_visible_context_for_persona(active),
            "audit_artifacts": [
                {
                    "artifact_id": item.artifact_id,
                    "event_type": item.event_type,
                    "persona_id": item.persona_id,
                    "activation_mode": item.activation_mode,
                    "reason": item.reason,
                    "conflict_resolution_path": item.conflict_resolution_path,
                    "artifact_hash": item.artifact_hash,
                }
                for item in self.persona_audit
            ],
        }

    def _merge_capabilities(
        self,
        current: Dict[str, Dict[str, object]],
        patch: Dict[str, Dict[str, object]],
    ) -> Dict[str, Dict[str, object]]:
        merged = deepcopy(current)
        for capability_name, capability_values in patch.items():
            target = dict(merged.get(capability_name, {}))
            target.update(capability_values)
            merged[capability_name] = target
        return merged

    def _append_ownership_record(self, node: AssetNode, owner_id: str, status: str, changed_at: datetime) -> None:
        node.ownership_history.append(
            AssetOwnershipRecord(
                owner_id=owner_id,
                status=status,
                changed_at=changed_at,
            )
        )

    def _apply(self, event: Event) -> None:
        if isinstance(event, DomainCreated):
            domain_name = LifeDomainName(event.domain_name)
            self.life_domains[domain_name] = LifeDomain(name=domain_name, owner_id=event.owner_id)
        elif isinstance(event, AssetCreated):
            domain_name = LifeDomainName(event.domain_name)
            asset = Asset(
                asset_id=event.asset_id,
                continuity_id=event.asset_id,
                owner_id=event.owner_id,
                domain_name=domain_name,
            )
            asset.record(
                AssetState.ACTIVE,
                owner_id=event.owner_id,
                domain_name=domain_name,
                note="registered",
                changed_at=event.occurred_at,
            )
            self.assets[event.asset_id] = asset
        elif isinstance(event, AssetRegistered):
            acquisition_date = event.acquisition_date or event.occurred_at
            node = AssetNode(
                asset_id=event.asset_id,
                asset_type=event.asset_type,
                continuity_id=event.continuity_id,
                lifecycle_state=AssetState(event.lifecycle_state),
                ownership_status=event.ownership_status,
                acquisition_date=acquisition_date,
                retirement_date=event.retirement_date,
                domain_id=event.domain_id,
                owner_id=event.owner_id,
                capabilities=deepcopy(event.capabilities),
                metadata=deepcopy(event.metadata),
            )
            self._append_ownership_record(node, owner_id=event.owner_id, status=event.ownership_status, changed_at=event.occurred_at)
            self.asset_nodes[event.asset_id] = node
            chain = self.continuity_index.setdefault(event.continuity_id, [])
            if chain:
                previous_asset_id = chain[-1]
                previous_node = self.asset_nodes.get(previous_asset_id)
                relation = ContinuityRelationType.SUCCESSION
                if previous_node is not None and previous_node.lifecycle_state == AssetState.RETIRED:
                    relation = ContinuityRelationType.REPLACEMENT
                self.link_continuity(previous_asset_id, event.asset_id, relation, occurred_at=event.occurred_at)
            chain.append(event.asset_id)
        elif isinstance(event, AssetUpdated):
            node = self.asset_nodes[event.asset_id]
            node.capabilities = self._merge_capabilities(node.capabilities, event.capabilities_patch)
            node.metadata.update(event.metadata_patch)
            if event.ownership_status is not None:
                node.ownership_status = event.ownership_status
                self._append_ownership_record(
                    node,
                    owner_id=node.owner_id,
                    status=event.ownership_status,
                    changed_at=event.occurred_at,
                )
        elif isinstance(event, AssetTransferred):
            if event.asset_id in self.assets:
                asset = self.assets[event.asset_id]
                next_domain = asset.domain_name if event.new_domain_name is None else LifeDomainName(event.new_domain_name)
                asset.record(
                    AssetState.TRANSFERRED,
                    owner_id=event.new_owner_id,
                    domain_name=next_domain,
                    note="transfer",
                    changed_at=event.occurred_at,
                )
            if event.asset_id in self.asset_nodes:
                node = self.asset_nodes[event.asset_id]
                node.owner_id = event.new_owner_id
                node.lifecycle_state = AssetState.TRANSFERRED
                if event.new_domain_name is not None:
                    node.domain_id = event.new_domain_name
                if event.ownership_status:
                    node.ownership_status = event.ownership_status
                self._append_ownership_record(
                    node,
                    owner_id=event.new_owner_id,
                    status=node.ownership_status,
                    changed_at=event.occurred_at,
                )
        elif isinstance(event, AssetRetired):
            if event.asset_id in self.assets:
                asset = self.assets[event.asset_id]
                asset.record(
                    AssetState.RETIRED,
                    owner_id=asset.owner_id,
                    domain_name=asset.domain_name,
                    note=event.reason,
                    changed_at=event.occurred_at,
                )
            if event.asset_id in self.asset_nodes:
                node = self.asset_nodes[event.asset_id]
                node.lifecycle_state = AssetState.RETIRED
                node.retirement_date = event.retirement_date or event.occurred_at
        elif isinstance(event, GoalCreated):
            self.goals[event.goal_id] = Goal(
                goal_id=event.goal_id,
                title=event.title,
                metric_name=event.metric_name,
                target_value=event.target_value,
            )
        elif isinstance(event, GoalCompleted):
            goal = self.goals[event.goal_id]
            goal.completed = True
            goal.completed_at = event.occurred_at
            goal.current_value = goal.target_value
        elif isinstance(event, PersonaActivated):
            for persona in self.personas.values():
                persona.active = False
            if event.persona_id in self.personas:
                self.personas[event.persona_id].active = True
                self.personas[event.persona_id].activated_at = event.occurred_at
                self._record_persona_audit(
                    event_type="persona_activated",
                    persona_id=event.persona_id,
                    activation_mode=event.activation_mode,
                    reason=event.activation_reason,
                    conflict_resolution_path=event.conflict_resolution_path,
                    occurred_at=event.occurred_at,
                )
        elif isinstance(event, PersonaDeactivated):
            for persona in self.personas.values():
                persona.active = False
            self._record_persona_audit(
                event_type="persona_deactivated",
                persona_id=event.persona_id,
                activation_mode=PersonaActivationMode.DEACTIVATED.value,
                reason=event.deactivation_reason,
                conflict_resolution_path=("all_personas_deactivated",),
                occurred_at=event.occurred_at,
            )
        elif isinstance(event, VehicleRegistered):
            self._apply(
                AssetRegistered(
                    aggregate_id=event.aggregate_id,
                    sequence=event.sequence,
                    occurred_at=event.occurred_at,
                    event_id=event.event_id,
                    asset_id=event.vehicle_id,
                    asset_type="vehicle",
                    continuity_id=event.continuity_id,
                    lifecycle_state=event.lifecycle_state,
                    ownership_status=event.ownership_status,
                    acquisition_date=event.acquisition_date,
                    retirement_date=event.retirement_date,
                    owner_id=event.owner_id,
                    domain_id=event.domain_name,
                    capabilities={
                        "mobility": MobilityCapability(
                            make=event.make,
                            model=event.model,
                            year=event.year,
                            odometer=event.odometer,
                            fuel_battery_state=event.fuel_battery_state,
                        ).to_dict(),
                        "maintenance": MaintenanceCapability().to_dict(),
                    },
                    metadata={
                        "make": event.make,
                        "model": event.model,
                        "year": event.year,
                    },
                    extension_payload={"legacy_event": "VehicleRegistered"},
                )
            )
        elif isinstance(event, VehicleUpdated):
            patch: Dict[str, Dict[str, object]] = {}
            mobility_patch: Dict[str, object] = {}
            if event.odometer is not None:
                mobility_patch["odometer"] = event.odometer
            if event.fuel_battery_state is not None:
                mobility_patch["fuel_battery_state"] = event.fuel_battery_state
            if mobility_patch:
                patch["mobility"] = mobility_patch
            self._apply(
                AssetUpdated(
                    aggregate_id=event.aggregate_id,
                    sequence=event.sequence,
                    occurred_at=event.occurred_at,
                    event_id=event.event_id,
                    asset_id=event.vehicle_id,
                    ownership_status=event.ownership_status,
                    capabilities_patch=patch,
                    metadata_patch={},
                    extension_payload={"legacy_event": "VehicleUpdated"},
                )
            )
        elif isinstance(event, VehicleServiced):
            node = self.asset_nodes[event.vehicle_id]
            maintenance = dict(node.capabilities.get("maintenance", {}))
            service_history = list(maintenance.get("service_history", []))
            maintenance_records = list(maintenance.get("maintenance_records", []))
            service_history.append(
                {
                    "serviced_at": event.occurred_at.isoformat(),
                    "note": event.service_note,
                    "odometer": event.service_at_odometer,
                }
            )
            maintenance_records.append(event.service_note)
            mobility = dict(node.capabilities.get("mobility", {}))
            current_odometer = float(mobility.get("odometer", 0.0))
            mobility["odometer"] = max(current_odometer, event.service_at_odometer)
            self._apply(
                AssetUpdated(
                    aggregate_id=event.aggregate_id,
                    sequence=event.sequence,
                    occurred_at=event.occurred_at,
                    event_id=event.event_id,
                    asset_id=event.vehicle_id,
                    capabilities_patch={
                        "maintenance": {
                            "service_history": service_history,
                            "maintenance_records": maintenance_records,
                        },
                        "mobility": mobility,
                    },
                    metadata_patch={},
                    extension_payload={"legacy_event": "VehicleServiced"},
                )
            )
        elif isinstance(event, VehicleTransferred):
            self._apply(
                AssetTransferred(
                    aggregate_id=event.aggregate_id,
                    sequence=event.sequence,
                    occurred_at=event.occurred_at,
                    event_id=event.event_id,
                    asset_id=event.vehicle_id,
                    new_owner_id=event.new_owner_id,
                    ownership_status=event.ownership_status,
                    extension_payload={"legacy_event": "VehicleTransferred"},
                )
            )
        elif isinstance(event, VehicleRetired):
            self._apply(
                AssetRetired(
                    aggregate_id=event.aggregate_id,
                    sequence=event.sequence,
                    occurred_at=event.occurred_at,
                    event_id=event.event_id,
                    asset_id=event.vehicle_id,
                    reason=event.retired_reason,
                    retirement_date=event.retirement_date,
                    extension_payload={"legacy_event": "VehicleRetired"},
                )
            )
        else:
            raise TypeError(f"Unhandled event type: {type(event)!r}")

        self.digital_twin.update_from_event(event, self)

    @classmethod
    def rehydrate(cls, root_identity: RootIdentity, events: List[Event]) -> "UserCortexAggregate":
        aggregate = cls(root_identity=root_identity)
        for event in ensure_deterministic_order(events):
            aggregate._apply(event)
            aggregate._sequence = max(aggregate._sequence, event.sequence + 1)
        aggregate.clear_uncommitted_events()
        return aggregate

    def project_asset_node(self, node: AssetNode) -> Dict[str, object]:
        return {
            "asset_id": node.asset_id,
            "asset_type": node.asset_type,
            "continuity_id": node.continuity_id,
            "lifecycle_state": node.lifecycle_state.value,
            "ownership_status": node.ownership_status,
            "acquisition_date": node.acquisition_date.isoformat(),
            "retirement_date": None if node.retirement_date is None else node.retirement_date.isoformat(),
            "domain_id": node.domain_id,
            "owner_id": node.owner_id,
            "capabilities": deepcopy(node.capabilities),
            "metadata": deepcopy(node.metadata),
        }

    def create_domain(self, domain_name: LifeDomainName, owner_id: str) -> DomainCreated:
        event = DomainCreated(
            aggregate_id=self.root_identity.continuity_id,
            sequence=self._next_sequence(),
            domain_name=domain_name.value,
            owner_id=owner_id,
        )
        self._record(event)
        return event

    def is_domain_owned_by(self, domain_name: LifeDomainName, owner_id: str) -> bool:
        domain = self.life_domains.get(domain_name)
        return domain is not None and domain.owner_id == owner_id

    def query_domains(self, owner_id: Optional[str] = None) -> List[LifeDomain]:
        values = list(self.life_domains.values())
        if owner_id is None:
            return values
        return [domain for domain in values if domain.owner_id == owner_id]

    def register_asset(self, asset_id: str, domain_name: LifeDomainName, owner_id: str) -> AssetCreated:
        if domain_name not in self.life_domains:
            raise ValueError("Asset domain must exist before asset registration")
        if self.life_domains[domain_name].owner_id != owner_id:
            raise ValueError("Owner mismatch for target domain")
        event = AssetCreated(
            aggregate_id=self.root_identity.continuity_id,
            sequence=self._next_sequence(),
            asset_id=asset_id,
            domain_name=domain_name.value,
            owner_id=owner_id,
        )
        self._record(event)
        return event

    def register_asset_node(
        self,
        asset_id: str,
        asset_type: str,
        owner_id: str,
        domain_id: str,
        ownership_status: str,
        continuity_id: Optional[str] = None,
        capabilities: Optional[Dict[str, Dict[str, object]]] = None,
        metadata: Optional[Dict[str, object]] = None,
        acquisition_date: Optional[datetime] = None,
        extension_payload: Optional[Dict[str, object]] = None,
    ) -> AssetRegistered:
        domain_name = LifeDomainName(domain_id)
        if domain_name not in self.life_domains:
            raise ValueError("Asset domain must exist before asset registration")
        if self.life_domains[domain_name].owner_id != owner_id:
            raise ValueError("Owner mismatch for target domain")
        event = AssetRegistered(
            aggregate_id=self.root_identity.continuity_id,
            sequence=self._next_sequence(),
            asset_id=asset_id,
            asset_type=asset_type,
            continuity_id=continuity_id or asset_id,
            lifecycle_state=AssetState.ACTIVE.value,
            ownership_status=ownership_status,
            acquisition_date=acquisition_date,
            owner_id=owner_id,
            domain_id=domain_id,
            capabilities=deepcopy(capabilities or {}),
            metadata=deepcopy(metadata or {}),
            extension_payload=deepcopy(extension_payload or {}),
        )
        self._record(event)
        return event

    def update_asset_node(
        self,
        asset_id: str,
        ownership_status: Optional[str] = None,
        capabilities_patch: Optional[Dict[str, Dict[str, object]]] = None,
        metadata_patch: Optional[Dict[str, object]] = None,
        extension_payload: Optional[Dict[str, object]] = None,
    ) -> AssetUpdated:
        if asset_id not in self.asset_nodes:
            raise KeyError(f"Unknown asset node: {asset_id}")
        event = AssetUpdated(
            aggregate_id=self.root_identity.continuity_id,
            sequence=self._next_sequence(),
            asset_id=asset_id,
            ownership_status=ownership_status,
            capabilities_patch=deepcopy(capabilities_patch or {}),
            metadata_patch=deepcopy(metadata_patch or {}),
            extension_payload=deepcopy(extension_payload or {}),
        )
        self._record(event)
        return event

    def transfer_asset_node(
        self,
        asset_id: str,
        new_owner_id: str,
        ownership_status: str,
        new_domain_id: Optional[str] = None,
        extension_payload: Optional[Dict[str, object]] = None,
    ) -> AssetTransferred:
        if asset_id not in self.asset_nodes:
            raise KeyError(f"Unknown asset node: {asset_id}")
        if new_domain_id is not None:
            domain_name = LifeDomainName(new_domain_id)
            if domain_name not in self.life_domains:
                raise ValueError("Target domain must exist before transfer")
            if self.life_domains[domain_name].owner_id != new_owner_id:
                raise ValueError("Target domain owner must match transfer owner")
        event = AssetTransferred(
            aggregate_id=self.root_identity.continuity_id,
            sequence=self._next_sequence(),
            asset_id=asset_id,
            new_owner_id=new_owner_id,
            new_domain_name=new_domain_id,
            ownership_status=ownership_status,
            extension_payload=deepcopy(extension_payload or {}),
        )
        self._record(event)
        return event

    def retire_asset(self, asset_id: str, reason: str = "") -> AssetRetired:
        if asset_id not in self.assets:
            raise KeyError(f"Unknown asset: {asset_id}")
        event = AssetRetired(
            aggregate_id=self.root_identity.continuity_id,
            sequence=self._next_sequence(),
            asset_id=asset_id,
            reason=reason,
        )
        self._record(event)
        return event

    def retire_asset_node(
        self,
        asset_id: str,
        reason: str,
        retirement_date: Optional[datetime] = None,
        extension_payload: Optional[Dict[str, object]] = None,
    ) -> AssetRetired:
        if asset_id not in self.asset_nodes:
            raise KeyError(f"Unknown asset node: {asset_id}")
        event = AssetRetired(
            aggregate_id=self.root_identity.continuity_id,
            sequence=self._next_sequence(),
            asset_id=asset_id,
            reason=reason,
            retirement_date=retirement_date,
            extension_payload=deepcopy(extension_payload or {}),
        )
        self._record(event)
        return event

    def transfer_asset(
        self,
        asset_id: str,
        new_owner_id: str,
        new_domain_name: Optional[LifeDomainName] = None,
    ) -> AssetTransferred:
        if asset_id not in self.assets:
            raise KeyError(f"Unknown asset: {asset_id}")
        if new_domain_name is not None and new_domain_name not in self.life_domains:
            raise ValueError("Target domain must exist before transfer")
        if new_domain_name is not None:
            domain_owner = self.life_domains[new_domain_name].owner_id
            if domain_owner != new_owner_id:
                raise ValueError("Target domain owner must match transfer owner")

        event = AssetTransferred(
            aggregate_id=self.root_identity.continuity_id,
            sequence=self._next_sequence(),
            asset_id=asset_id,
            new_owner_id=new_owner_id,
            new_domain_name=None if new_domain_name is None else new_domain_name.value,
        )
        self._record(event)
        return event

    def asset_history(self, asset_id: str) -> List[AssetStateRecord]:
        if asset_id not in self.assets:
            raise KeyError(f"Unknown asset: {asset_id}")
        return list(self.assets[asset_id].history)

    def query_assets(self, domain_name: Optional[LifeDomainName] = None, owner_id: Optional[str] = None) -> List[Asset]:
        assets = list(self.assets.values())
        if domain_name is not None:
            assets = [asset for asset in assets if asset.domain_name == domain_name]
        if owner_id is not None:
            assets = [asset for asset in assets if asset.owner_id == owner_id]
        return assets

    def query_asset_nodes(
        self,
        asset_type: Optional[str] = None,
        domain_id: Optional[str] = None,
        owner_id: Optional[str] = None,
    ) -> List[AssetNode]:
        nodes = list(self.asset_nodes.values())
        if asset_type is not None:
            nodes = [node for node in nodes if node.asset_type == asset_type]
        if domain_id is not None:
            nodes = [node for node in nodes if node.domain_id == domain_id]
        if owner_id is not None:
            nodes = [node for node in nodes if node.owner_id == owner_id]
        return nodes

    def register_persona(
        self,
        persona_id: str,
        label: str,
        priority: int = 0,
        persona_type: PersonaType = PersonaType.PERSONAL,
        activation_rules: Optional[Dict[str, object]] = None,
        visibility_rules: Optional[Dict[str, object]] = None,
        domain_scope: Sequence[str] = (),
        goal_scope: Sequence[str] = (),
        asset_scope: Sequence[str] = (),
    ) -> Persona:
        persona = Persona(
            persona_id=persona_id,
            persona_name=label,
            persona_type=persona_type,
            priority=priority,
            activation_rules=deepcopy(activation_rules or {}),
            visibility_rules=deepcopy(visibility_rules or {}),
            domain_scope=tuple(sorted(set(domain_scope))),
            goal_scope=tuple(sorted(set(goal_scope))),
            asset_scope=tuple(sorted(set(asset_scope))),
        )
        self.personas[persona_id] = persona
        return persona

    def activate_persona(self, persona_id: str, reason: str = "manual activation") -> Optional[PersonaActivated]:
        if persona_id not in self.personas:
            raise KeyError(f"Unknown persona: {persona_id}")

        current_id = self.active_persona_id
        conflict_path = [f"candidate={persona_id}"]
        if current_id is not None:
            current = self.personas[current_id]
            challenger = self.personas[persona_id]
            if current.persona_id != challenger.persona_id and current.priority > challenger.priority:
                conflict_path.append(f"blocked_by={current.persona_id}")
                conflict_path.append("rule=incumbent_higher_priority")
                self._record_persona_audit(
                    event_type="persona_conflict_resolution",
                    persona_id=current.persona_id,
                    activation_mode=PersonaActivationMode.MANUAL.value,
                    reason=reason,
                    conflict_resolution_path=tuple(conflict_path),
                    occurred_at=datetime.now(timezone.utc),
                )
                return None
        conflict_path.append("rule=manual_selected")

        event = PersonaActivated(
            aggregate_id=self.root_identity.continuity_id,
            sequence=self._next_sequence(),
            persona_id=persona_id,
            activation_mode=PersonaActivationMode.MANUAL.value,
            activation_reason=reason,
            conflict_resolution_path=tuple(conflict_path),
        )
        self._record(event)
        return event

    def deactivate_persona(self, reason: str = "manual deactivation") -> Optional[PersonaDeactivated]:
        current_id = self.active_persona_id
        if current_id is None:
            return None
        event = PersonaDeactivated(
            aggregate_id=self.root_identity.continuity_id,
            sequence=self._next_sequence(),
            persona_id=current_id,
            deactivation_reason=reason,
        )
        self._record(event)
        return event

    def activate_persona_for_context(
        self,
        domain_scope: Sequence[str],
        goal_scope: Sequence[str],
        asset_scope: Sequence[str],
        reason: str = "context activation",
    ) -> Optional[PersonaActivated]:
        candidates = [
            persona.persona_id
            for persona in self.personas.values()
            if self._persona_matches_context(persona, domain_scope, goal_scope, asset_scope)
        ]
        selected_id, path = self._resolve_persona_priority(candidates)
        if selected_id is None:
            return None
        event = PersonaActivated(
            aggregate_id=self.root_identity.continuity_id,
            sequence=self._next_sequence(),
            persona_id=selected_id,
            activation_mode=PersonaActivationMode.CONTEXT.value,
            activation_reason=reason,
            conflict_resolution_path=path,
        )
        self._record(event)
        return event

    def activate_persona_for_schedule(
        self,
        at: Optional[datetime] = None,
        reason: str = "scheduled activation",
    ) -> Optional[PersonaActivated]:
        check_at = at or datetime.now(timezone.utc)
        candidates = [
            persona.persona_id
            for persona in self.personas.values()
            if self._persona_is_scheduled_active(persona, check_at)
        ]
        selected_id, path = self._resolve_persona_priority(candidates)
        if selected_id is None:
            return None
        event = PersonaActivated(
            aggregate_id=self.root_identity.continuity_id,
            sequence=self._next_sequence(),
            persona_id=selected_id,
            activation_mode=PersonaActivationMode.SCHEDULED.value,
            activation_reason=reason,
            conflict_resolution_path=path,
            occurred_at=check_at,
        )
        self._record(event)
        return event

    def create_goal(self, goal_id: str, title: str, metric_name: str, target_value: float) -> GoalCreated:
        event = GoalCreated(
            aggregate_id=self.root_identity.continuity_id,
            sequence=self._next_sequence(),
            goal_id=goal_id,
            title=title,
            metric_name=metric_name,
            target_value=target_value,
        )
        self._record(event)
        return event

    def track_goal_progress(self, goal_id: str, metric_value: float) -> Optional[GoalCompleted]:
        if goal_id not in self.goals:
            raise KeyError(f"Unknown goal: {goal_id}")

        goal = self.goals[goal_id]
        goal.current_value = metric_value
        if goal.current_value >= goal.target_value and not goal.completed:
            event = GoalCompleted(
                aggregate_id=self.root_identity.continuity_id,
                sequence=self._next_sequence(),
                goal_id=goal_id,
            )
            self._record(event)
            return event
        return None

    def attach_asset_state_to_goal(self, goal_id: str, asset_id: str) -> Dict[str, object]:
        if goal_id not in self.goals:
            raise KeyError(f"Unknown goal: {goal_id}")
        if asset_id not in self.asset_nodes:
            raise KeyError(f"Unknown asset node: {asset_id}")
        node = self.asset_nodes[asset_id]
        snapshot = {
            "goal_id": goal_id,
            "asset_id": node.asset_id,
            "asset_type": node.asset_type,
            "continuity_id": node.continuity_id,
            "owner_id": node.owner_id,
            "lifecycle_state": node.lifecycle_state.value,
            "ownership_status": node.ownership_status,
            "domain_id": node.domain_id,
            "capabilities": deepcopy(node.capabilities),
            "captured_at": datetime.now(timezone.utc).isoformat(),
        }
        self.goal_asset_state_attachments.setdefault(goal_id, []).append(snapshot)
        return snapshot

    def link_continuity(
        self,
        source_asset_id: str,
        target_asset_id: str,
        relation: ContinuityRelationType,
        occurred_at: Optional[datetime] = None,
        metadata: Optional[Dict[str, object]] = None,
    ) -> ContinuityEdge:
        edge = ContinuityEdge(
            source_asset_id=source_asset_id,
            target_asset_id=target_asset_id,
            relation=relation,
            occurred_at=occurred_at or datetime.now(timezone.utc),
            metadata=deepcopy(metadata or {}),
        )
        self.continuity_graph.setdefault(source_asset_id, []).append(edge)
        return edge

    def continuity_chain(self, continuity_id: str) -> List[AssetNode]:
        asset_ids = self.continuity_index.get(continuity_id, [])
        return [self.asset_nodes[asset_id] for asset_id in asset_ids if asset_id in self.asset_nodes]

    def register_vehicle(
        self,
        vehicle_id: str,
        make: str,
        model: str,
        year: int,
        ownership_status: str,
        owner_id: str,
        continuity_id: Optional[str] = None,
        acquisition_date: Optional[datetime] = None,
        odometer: float = 0.0,
        fuel_battery_state: str = "",
    ) -> AssetRegistered:
        capabilities = {
            "mobility": MobilityCapability(
                make=make,
                model=model,
                year=year,
                odometer=odometer,
                fuel_battery_state=fuel_battery_state,
            ).to_dict(),
            "maintenance": MaintenanceCapability().to_dict(),
        }
        return self.register_asset_node(
            asset_id=vehicle_id,
            asset_type="vehicle",
            owner_id=owner_id,
            domain_id=LifeDomainName.VEHICLES.value,
            ownership_status=ownership_status,
            continuity_id=continuity_id,
            acquisition_date=acquisition_date,
            capabilities=capabilities,
            metadata={
                "make": make,
                "model": model,
                "year": year,
            },
            extension_payload={
                "vehicle": {
                    "make": make,
                    "model": model,
                    "year": year,
                }
            },
        )

    def create_projection(
        self,
        projection_type: ProjectionType,
        projection_inputs: Mapping[str, object],
        ttl_seconds: int,
        trace_id: str,
        generated_at: Optional[datetime] = None,
    ) -> ProjectedState:
        return self.digital_twin.create_projection(
            projection_type=projection_type,
            projection_inputs=projection_inputs,
            ttl_seconds=ttl_seconds,
            trace_id=trace_id,
            generated_at=generated_at,
        )

    def active_projections(self, at: Optional[datetime] = None) -> List[ProjectedState]:
        return self.digital_twin.active_projections(at)

    def replay_projection(self, projection_id: str, at: Optional[datetime] = None) -> Dict[str, object]:
        return self.digital_twin.replay_projection(projection_id, at)

    def update_vehicle(
        self,
        vehicle_id: str,
        odometer: Optional[float] = None,
        fuel_battery_state: Optional[str] = None,
        ownership_status: Optional[str] = None,
    ) -> AssetUpdated:
        if vehicle_id not in self.asset_nodes:
            raise KeyError(f"Unknown vehicle: {vehicle_id}")
        mobility_patch: Dict[str, object] = {}
        if odometer is not None:
            mobility_patch["odometer"] = odometer
        if fuel_battery_state is not None:
            mobility_patch["fuel_battery_state"] = fuel_battery_state
        patch = {"mobility": mobility_patch} if mobility_patch else {}
        return self.update_asset_node(
            asset_id=vehicle_id,
            ownership_status=ownership_status,
            capabilities_patch=patch,
            metadata_patch={},
            extension_payload={"domain": "vehicle"},
        )

    def service_vehicle(self, vehicle_id: str, service_note: str, service_at_odometer: float) -> AssetUpdated:
        if vehicle_id not in self.asset_nodes:
            raise KeyError(f"Unknown vehicle: {vehicle_id}")
        node = self.asset_nodes[vehicle_id]
        maintenance = dict(node.capabilities.get("maintenance", {}))
        service_history = list(maintenance.get("service_history", []))
        maintenance_records = list(maintenance.get("maintenance_records", []))
        service_history.append(
            {
                "serviced_at": datetime.now(timezone.utc).isoformat(),
                "note": service_note,
                "odometer": service_at_odometer,
            }
        )
        maintenance_records.append(service_note)

        mobility = dict(node.capabilities.get("mobility", {}))
        current_odometer = float(mobility.get("odometer", 0.0))
        mobility["odometer"] = max(current_odometer, service_at_odometer)

        return self.update_asset_node(
            asset_id=vehicle_id,
            capabilities_patch={
                "maintenance": {
                    "service_history": service_history,
                    "maintenance_records": maintenance_records,
                },
                "mobility": mobility,
            },
            metadata_patch={},
            extension_payload={"domain": "vehicle", "service_note": service_note},
        )

    def add_vehicle_inspection(self, vehicle_id: str, note: str) -> AssetUpdated:
        if vehicle_id not in self.asset_nodes:
            raise KeyError(f"Unknown vehicle: {vehicle_id}")
        node = self.asset_nodes[vehicle_id]
        maintenance = dict(node.capabilities.get("maintenance", {}))
        inspection_history = list(maintenance.get("inspection_history", []))
        inspection_history.append(
            {
                "inspected_at": datetime.now(timezone.utc).isoformat(),
                "note": note,
            }
        )
        return self.update_asset_node(
            asset_id=vehicle_id,
            capabilities_patch={"maintenance": {"inspection_history": inspection_history}},
            metadata_patch={},
            extension_payload={"domain": "vehicle", "inspection_note": note},
        )

    def transfer_vehicle(self, vehicle_id: str, new_owner_id: str, ownership_status: str) -> AssetTransferred:
        if vehicle_id not in self.asset_nodes:
            raise KeyError(f"Unknown vehicle: {vehicle_id}")
        return self.transfer_asset_node(
            asset_id=vehicle_id,
            new_owner_id=new_owner_id,
            ownership_status=ownership_status,
            extension_payload={"domain": "vehicle"},
        )

    def retire_vehicle(
        self,
        vehicle_id: str,
        retired_reason: str,
        retirement_date: Optional[datetime] = None,
    ) -> AssetRetired:
        if vehicle_id not in self.asset_nodes:
            raise KeyError(f"Unknown vehicle: {vehicle_id}")
        return self.retire_asset_node(
            asset_id=vehicle_id,
            reason=retired_reason,
            retirement_date=retirement_date,
            extension_payload={"domain": "vehicle"},
        )
