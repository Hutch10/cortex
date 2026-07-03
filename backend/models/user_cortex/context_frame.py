from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from hashlib import sha256
import json
import os
import re
from types import MappingProxyType
from typing import Callable, Dict, Iterable, Mapping, Optional, Sequence

from .aggregate import AssetNode, AssetState, Persona, UserCortexAggregate
from .advisor_contract import AdvisorOutput


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _stable_hash(value: object) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _freeze(value: object) -> object:
    if isinstance(value, dict):
        frozen = {str(k): _freeze(v) for k, v in sorted(value.items(), key=lambda item: str(item[0]))}
        return MappingProxyType(frozen)
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: object) -> object:
    if isinstance(value, MappingProxyType):
        value = dict(value)
    if isinstance(value, dict):
        return {str(k): _thaw(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [_thaw(v) for v in value]
    if isinstance(value, list):
        return [_thaw(v) for v in value]
    return value


_SANITIZE_PATTERNS = [
    re.compile(r"ignore\\s+previous\\s+instructions", re.IGNORECASE),
    re.compile(r"^\\s*(system|assistant|developer|tool)\\s*:", re.IGNORECASE),
    re.compile(r"```"),
    re.compile(r"<\\/?system>", re.IGNORECASE),
]


class PolicyEffect(str, Enum):
    ALLOW = "allow"
    DENY = "deny"


class PolicyAction(str, Enum):
    READ_CONTEXT = "read_context"
    READ_DOMAIN = "read_domain"
    READ_ASSET = "read_asset"
    READ_CAPABILITY = "read_capability"
    READ_PERSONA = "read_persona"
    READ_GOAL = "read_goal"
    READ_HISTORICAL = "read_historical"


class PolicyDecisionStatus(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    EXPIRED = "expired"
    REVOKED = "revoked"
    INSUFFICIENT_SCOPE = "insufficient_scope"


class CertificationStage(str, Enum):
    UNCERTIFIED = "UNCERTIFIED"
    POLICY_FILTERED = "POLICY_FILTERED"
    REDACTED = "REDACTED"
    HASH_VERIFIED = "HASH_VERIFIED"
    VERIFIED_CONTEXT = "VERIFIED_CONTEXT"


@dataclass(frozen=True)
class TypedPermissionPolicy:
    subject: str
    action: PolicyAction
    resource: str
    domain_scope: tuple[str, ...] = ()
    asset_scope: tuple[str, ...] = ()
    capability_scope: tuple[str, ...] = ()
    persona_scope: tuple[str, ...] = ()
    expiration: Optional[datetime] = None
    grant_source: str = ""
    revocation_status: bool = False
    effect: PolicyEffect = PolicyEffect.ALLOW

    @property
    def policy_id(self) -> str:
        return _stable_hash(
            {
                "subject": self.subject,
                "action": self.action.value,
                "resource": self.resource,
                "domain_scope": list(self.domain_scope),
                "asset_scope": list(self.asset_scope),
                "capability_scope": list(self.capability_scope),
                "persona_scope": list(self.persona_scope),
                "expiration": None if self.expiration is None else self.expiration.isoformat(),
                "grant_source": self.grant_source,
                "revocation_status": self.revocation_status,
                "effect": self.effect.value,
            }
        )


@dataclass(frozen=True)
class PolicyDecision:
    policy_id: str
    subject: str
    action: str
    resource: str
    decision: PolicyDecisionStatus
    reason: str


@dataclass(frozen=True)
class PermissionProfile:
    allowed_domains: tuple[str, ...]
    denied_domains: tuple[str, ...]
    allowed_assets: tuple[str, ...]
    denied_assets: tuple[str, ...]
    allowed_capabilities: tuple[str, ...]
    denied_capabilities: tuple[str, ...]
    allowed_personas: tuple[str, ...]
    allowed_goals: tuple[str, ...]
    include_historical: bool


@dataclass(frozen=True)
class ContextFrame:
    frame_id: str
    user_id: str
    domain_scope: tuple[str, ...]
    persona_scope: tuple[str, ...]
    goal_scope: tuple[str, ...]
    asset_scope: tuple[str, ...]
    generated_at: datetime
    expires_at: datetime
    certification_level: str
    source_hashes: Mapping[str, str]
    context_payload: Mapping[str, object]
    redaction_metadata: Mapping[str, object]


@dataclass(frozen=True)
class ContextFrameRequest:
    user_id: str
    requesting_interface: str
    domain_scope: tuple[str, ...] = ()
    persona_scope: tuple[str, ...] = ()
    goal_scope: tuple[str, ...] = ()
    asset_scope: tuple[str, ...] = ()
    include_historical_assets: bool = False
    certification_level: str = "VERIFIED_CONTEXT"
    ttl_seconds: int = 600
    policies: tuple[TypedPermissionPolicy, ...] = ()


@dataclass(frozen=True)
class ContextFrameAuditEvent:
    frame_id: str
    user_id: str
    requester: str
    policy_decisions: tuple[PolicyDecision, ...]
    permissions_applied: Mapping[str, object]
    redactions_applied: Mapping[str, object]
    source_hashes: Mapping[str, str]
    generated_at: datetime
    certification_level: str
    included_assets: tuple[str, ...]
    excluded_assets: tuple[str, ...]
    certification_path: tuple[str, ...]
    active_persona: Optional[str]
    activation_reason: str
    conflict_resolution_path: tuple[str, ...]
    visible_domains: tuple[str, ...]
    visible_goals: tuple[str, ...]
    visible_assets: tuple[str, ...]
    visible_recommendations: tuple[str, ...]


class CertificationPipeline:
    _ORDER = [
        CertificationStage.UNCERTIFIED,
        CertificationStage.POLICY_FILTERED,
        CertificationStage.REDACTED,
        CertificationStage.HASH_VERIFIED,
        CertificationStage.VERIFIED_CONTEXT,
    ]

    def __init__(self) -> None:
        self.current_stage = CertificationStage.UNCERTIFIED
        self.path: list[str] = [CertificationStage.UNCERTIFIED.value]

    def advance(self, next_stage: CertificationStage, passed: bool) -> None:
        if not passed:
            raise ValueError(f"Certification stage failed: {next_stage.value}")
        current_index = self._ORDER.index(self.current_stage)
        expected = self._ORDER[current_index + 1] if current_index + 1 < len(self._ORDER) else None
        if next_stage != expected:
            raise ValueError(
                f"Certification stage cannot skip order: expected {expected.value if expected else 'END'}, got {next_stage.value}"
            )
        self.current_stage = next_stage
        self.path.append(next_stage.value)


class PolicyEvaluator:
    def _scope_permits(self, request_values: Sequence[str], policy_values: Sequence[str]) -> bool:
        if not request_values:
            return True
        if not policy_values:
            return True
        return set(request_values).issubset(set(policy_values))

    def evaluate(
        self,
        request: ContextFrameRequest,
        now: datetime,
    ) -> tuple[PermissionProfile, list[PolicyDecision]]:
        policies = sorted(
            [policy for policy in request.policies if policy.subject == request.requesting_interface],
            key=lambda p: (p.action.value, p.resource, p.grant_source, p.policy_id),
        )

        decisions: list[PolicyDecision] = []
        allowed_domains: set[str] = set()
        denied_domains: set[str] = set()
        allowed_assets: set[str] = set()
        denied_assets: set[str] = set()
        allowed_capabilities: set[str] = set()
        denied_capabilities: set[str] = set()
        allowed_personas: set[str] = set()
        allowed_goals: set[str] = set()
        include_historical = False

        def add_decision(policy: TypedPermissionPolicy, decision: PolicyDecisionStatus, reason: str) -> None:
            decisions.append(
                PolicyDecision(
                    policy_id=policy.policy_id,
                    subject=policy.subject,
                    action=policy.action.value,
                    resource=policy.resource,
                    decision=decision,
                    reason=reason,
                )
            )

        for policy in policies:
            if policy.revocation_status:
                add_decision(policy, PolicyDecisionStatus.REVOKED, "policy revoked")
                continue
            if policy.expiration is not None and now > policy.expiration:
                add_decision(policy, PolicyDecisionStatus.EXPIRED, "policy expired")
                continue
            if not self._scope_permits(request.domain_scope, policy.domain_scope):
                add_decision(policy, PolicyDecisionStatus.INSUFFICIENT_SCOPE, "domain scope mismatch")
                continue
            if not self._scope_permits(request.asset_scope, policy.asset_scope):
                add_decision(policy, PolicyDecisionStatus.INSUFFICIENT_SCOPE, "asset scope mismatch")
                continue
            if not self._scope_permits(request.persona_scope, policy.persona_scope):
                add_decision(policy, PolicyDecisionStatus.INSUFFICIENT_SCOPE, "persona scope mismatch")
                continue

            decision = PolicyDecisionStatus.DENY if policy.effect == PolicyEffect.DENY else PolicyDecisionStatus.ALLOW
            add_decision(policy, decision, "policy matched")

            target_resource = policy.resource
            targets = {target_resource} if target_resource != "*" else set()

            if policy.action == PolicyAction.READ_DOMAIN:
                apply_targets = targets or set(policy.domain_scope) or set(request.domain_scope)
                if policy.effect == PolicyEffect.DENY:
                    denied_domains.update(apply_targets)
                else:
                    allowed_domains.update(apply_targets)
            elif policy.action == PolicyAction.READ_ASSET:
                apply_targets = targets or set(policy.asset_scope) or set(request.asset_scope)
                if policy.effect == PolicyEffect.DENY:
                    denied_assets.update(apply_targets)
                else:
                    allowed_assets.update(apply_targets)
            elif policy.action == PolicyAction.READ_CAPABILITY:
                apply_targets = targets or set(policy.capability_scope)
                if policy.effect == PolicyEffect.DENY:
                    denied_capabilities.update(apply_targets)
                else:
                    allowed_capabilities.update(apply_targets)
            elif policy.action == PolicyAction.READ_PERSONA and policy.effect == PolicyEffect.ALLOW:
                apply_targets = targets or set(policy.persona_scope) or set(request.persona_scope)
                allowed_personas.update(apply_targets)
            elif policy.action == PolicyAction.READ_GOAL and policy.effect == PolicyEffect.ALLOW:
                apply_targets = targets or set(request.goal_scope)
                allowed_goals.update(apply_targets)
            elif policy.action == PolicyAction.READ_HISTORICAL and policy.effect == PolicyEffect.ALLOW:
                include_historical = True

        active_denies = [d for d in decisions if d.decision == PolicyDecisionStatus.DENY]
        if active_denies:
            raise PermissionError("deny")

        context_allows = [
            d for d in decisions if d.action == PolicyAction.READ_CONTEXT.value and d.decision == PolicyDecisionStatus.ALLOW
        ]
        if not context_allows:
            raise PermissionError("insufficient_scope")

        requested_domains = set(request.domain_scope)
        if requested_domains and (not requested_domains.issubset(allowed_domains) or requested_domains & denied_domains):
            raise PermissionError("insufficient_scope")

        return (
            PermissionProfile(
                allowed_domains=tuple(sorted(allowed_domains)),
                denied_domains=tuple(sorted(denied_domains)),
                allowed_assets=tuple(sorted(allowed_assets)),
                denied_assets=tuple(sorted(denied_assets)),
                allowed_capabilities=tuple(sorted(allowed_capabilities)),
                denied_capabilities=tuple(sorted(denied_capabilities)),
                allowed_personas=tuple(sorted(allowed_personas)),
                allowed_goals=tuple(sorted(allowed_goals)),
                include_historical=include_historical,
            ),
            decisions,
        )


class DurableAuditSink:
    def __init__(self, file_path: str) -> None:
        self.file_path = file_path
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

    def append(self, event: ContextFrameAuditEvent) -> None:
        payload = {
            "frame_id": event.frame_id,
            "user_id": event.user_id,
            "requester": event.requester,
            "policy_decisions": [asdict(decision) for decision in event.policy_decisions],
            "permissions_applied": _thaw(event.permissions_applied),
            "redactions_applied": _thaw(event.redactions_applied),
            "source_hashes": _thaw(event.source_hashes),
            "generated_at": event.generated_at.isoformat(),
            "certification_level": event.certification_level,
            "included_assets": list(event.included_assets),
            "excluded_assets": list(event.excluded_assets),
            "certification_path": list(event.certification_path),
            "active_persona": event.active_persona,
            "activation_reason": event.activation_reason,
            "conflict_resolution_path": list(event.conflict_resolution_path),
            "visible_domains": list(event.visible_domains),
            "visible_goals": list(event.visible_goals),
            "visible_assets": list(event.visible_assets),
            "visible_recommendations": list(event.visible_recommendations),
        }
        with open(self.file_path, "a", encoding="utf-8") as handle:
            handle.write(_canonical_json(payload) + "\n")

    def replay(self, frame_id: str) -> dict[str, object]:
        if not os.path.exists(self.file_path):
            raise KeyError(f"Unknown frame_id: {frame_id}")

        selected: Optional[dict[str, object]] = None
        with open(self.file_path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                payload = json.loads(line)
                if payload.get("frame_id") == frame_id:
                    selected = payload

        if selected is None:
            raise KeyError(f"Unknown frame_id: {frame_id}")

        return {
            "frame_id": selected["frame_id"],
            "who_requested": selected["requester"],
            "permissions_evaluated": selected["policy_decisions"],
            "what_was_included": selected["included_assets"],
            "what_was_excluded": selected["excluded_assets"],
            "what_was_redacted": selected["redactions_applied"],
            "active_persona": selected.get("active_persona"),
            "activation_reason": selected.get("activation_reason", ""),
            "conflict_resolution_path": selected.get("conflict_resolution_path", []),
            "visible_context": {
                "domains": selected.get("visible_domains", []),
                "goals": selected.get("visible_goals", []),
                "assets": selected.get("visible_assets", []),
                "recommendations": selected.get("visible_recommendations", []),
            },
            "why_certified": {
                "certification_level": selected["certification_level"],
                "certification_path": selected["certification_path"],
                "source_hashes": selected["source_hashes"],
            },
        }


def sanitize_untrusted_text(text: str) -> tuple[str, bool]:
    cleaned = text.replace("\r", " ").replace("\n", " ")
    redacted = False
    for pattern in _SANITIZE_PATTERNS:
        next_cleaned = pattern.sub("[redacted]", cleaned)
        if next_cleaned != cleaned:
            redacted = True
        cleaned = next_cleaned
    cleaned = re.sub(r"\\s+", " ", cleaned).strip()
    return cleaned, redacted


class ReadOnlyAdvisorInterface:
    def evaluate(self, frame: ContextFrame, advisor: Callable[[ContextFrame], AdvisorOutput]) -> AdvisorOutput:
        result = advisor(frame)
        if not isinstance(result, AdvisorOutput):
            raise TypeError("Advisor must return AdvisorOutput")
        return result


class ContextFrameAssembler:
    def __init__(self, audit_sink: Optional[DurableAuditSink] = None) -> None:
        self.audit_log: list[ContextFrameAuditEvent] = []
        self.audit_sink = audit_sink or DurableAuditSink(
            os.path.join("c:\\Users\\hetfw\\Cortex", "backend", "outputs", "context_frame_audit.jsonl")
        )
        self.policy_evaluator = PolicyEvaluator()

    def _project_asset(self, node: AssetNode, allowed_capabilities: set[str]) -> dict[str, object]:
        projected_capabilities: dict[str, dict[str, object]] = {}
        for capability_name, values in sorted(node.capabilities.items(), key=lambda item: item[0]):
            if allowed_capabilities and capability_name not in allowed_capabilities:
                continue
            projected_capabilities[capability_name] = dict(values)
        return {
            "asset_id": node.asset_id,
            "asset_type": node.asset_type,
            "continuity_id": node.continuity_id,
            "lifecycle_state": node.lifecycle_state.value,
            "ownership_status": node.ownership_status,
            "acquisition_date": node.acquisition_date.isoformat(),
            "retirement_date": None if node.retirement_date is None else node.retirement_date.isoformat(),
            "domain_id": node.domain_id,
            "metadata": dict(node.metadata),
            "capabilities": projected_capabilities,
        }

    def _select_persona_for_frame(
        self,
        aggregate: UserCortexAggregate,
        request: ContextFrameRequest,
    ) -> tuple[Optional[Persona], str, tuple[str, ...]]:
        if not aggregate.personas:
            return None, "no persona configured", ("no_personas",)

        if aggregate.active_persona_id is not None:
            active = aggregate.personas.get(aggregate.active_persona_id)
            if active is not None and (
                not request.persona_scope or active.persona_id in set(request.persona_scope)
            ):
                return active, "active persona", ("selected_active_persona", active.persona_id)

        candidates = [
            persona
            for persona in aggregate.personas.values()
            if not request.persona_scope or persona.persona_id in set(request.persona_scope)
        ]
        if not candidates:
            return None, "persona scope mismatch", ("no_matching_persona",)

        selected = sorted(candidates, key=lambda persona: (-persona.priority, persona.persona_id))[0]
        return selected, "priority fallback", (
            "selected_by_priority",
            selected.persona_id,
            "rule=priority_desc_then_persona_id",
        )

    def _filter_recommendations_for_persona(
        self,
        aggregate: UserCortexAggregate,
        persona: Optional[Persona],
    ) -> list[dict[str, object]]:
        recommendations = aggregate.memory.working.get("recommendations", [])
        if not isinstance(recommendations, list):
            return []
        projected = [item for item in recommendations if isinstance(item, dict)]
        if persona is None:
            return sorted(projected, key=lambda item: str(item.get("recommendation_id", "")))

        allowed_tags = set(persona.visibility_rules.get("allowed_recommendation_tags", []))
        denied_tags = set(persona.visibility_rules.get("denied_recommendation_tags", []))
        visible: list[dict[str, object]] = []
        for item in projected:
            domain_id = str(item.get("domain_id", ""))
            goal_id = str(item.get("goal_id", ""))
            asset_id = str(item.get("asset_id", ""))
            tags = {str(tag) for tag in item.get("tags", []) if isinstance(tag, str)}
            if persona.domain_scope and domain_id not in set(persona.domain_scope):
                continue
            if persona.goal_scope and goal_id and goal_id not in set(persona.goal_scope):
                continue
            if persona.asset_scope and asset_id and asset_id not in set(persona.asset_scope):
                continue
            if denied_tags and tags & denied_tags:
                continue
            if allowed_tags and not (tags & allowed_tags):
                continue
            visible.append(item)
        return sorted(visible, key=lambda item: str(item.get("recommendation_id", "")))

    def _sanitize_external_text(self, projected_assets: Sequence[dict[str, object]]) -> tuple[dict[str, object], dict[str, object]]:
        redaction_count = 0
        redacted_fields: list[str] = []
        isolated: dict[str, list[str]] = {
            "calendar_events": [],
            "asset_metadata": [],
            "module_outputs": [],
            "external_records": [],
        }

        for asset in projected_assets:
            metadata = asset.get("metadata", {})
            if not isinstance(metadata, dict):
                continue
            for key, bucket in (
                ("calendar_events", "calendar_events"),
                ("module_outputs", "module_outputs"),
                ("external_records", "external_records"),
            ):
                values = metadata.get(key, [])
                if isinstance(values, str):
                    values = [values]
                if not isinstance(values, list):
                    continue
                for index, value in enumerate(values):
                    if not isinstance(value, str):
                        continue
                    sanitized, redacted = sanitize_untrusted_text(value)
                    isolated[bucket].append(sanitized)
                    if redacted:
                        redaction_count += 1
                        redacted_fields.append(f"{asset['asset_id']}.metadata.{key}[{index}]")

            for key, value in sorted(metadata.items(), key=lambda item: item[0]):
                if key in {"calendar_events", "module_outputs", "external_records"}:
                    continue
                if isinstance(value, str):
                    sanitized, redacted = sanitize_untrusted_text(value)
                    isolated["asset_metadata"].append(sanitized)
                    if redacted:
                        redaction_count += 1
                        redacted_fields.append(f"{asset['asset_id']}.metadata.{key}")

        return isolated, {
            "redaction_count": redaction_count,
            "redacted_fields": tuple(sorted(redacted_fields)),
        }

    def _select_assets(
        self,
        aggregate: UserCortexAggregate,
        request: ContextFrameRequest,
        profile: PermissionProfile,
    ) -> tuple[list[AssetNode], list[AssetNode], list[str]]:
        scope_domains = set(request.domain_scope)
        scope_assets = set(request.asset_scope)
        allowed_domains = set(profile.allowed_domains)
        denied_domains = set(profile.denied_domains)
        allowed_assets = set(profile.allowed_assets)
        denied_assets = set(profile.denied_assets)

        included: list[AssetNode] = []
        historical: list[AssetNode] = []
        excluded: list[str] = []

        for asset_id, node in sorted(aggregate.asset_nodes.items(), key=lambda item: item[0]):
            if scope_assets and asset_id not in scope_assets:
                excluded.append(asset_id)
                continue
            if scope_domains and node.domain_id not in scope_domains:
                excluded.append(asset_id)
                continue
            if allowed_domains and node.domain_id not in allowed_domains:
                excluded.append(asset_id)
                continue
            if node.domain_id in denied_domains:
                excluded.append(asset_id)
                continue
            if allowed_assets and asset_id not in allowed_assets:
                excluded.append(asset_id)
                continue
            if asset_id in denied_assets:
                excluded.append(asset_id)
                continue

            if node.lifecycle_state in {AssetState.RETIRED, AssetState.ARCHIVED}:
                if request.include_historical_assets and profile.include_historical:
                    historical.append(node)
                else:
                    excluded.append(asset_id)
                continue
            included.append(node)

        return included, historical, sorted(set(excluded))

    def _build_goals(self, aggregate: UserCortexAggregate, request: ContextFrameRequest, profile: PermissionProfile) -> list[dict[str, object]]:
        scope_goals = set(request.goal_scope)
        allowed_goals = set(profile.allowed_goals)
        if not allowed_goals and scope_goals:
            return []

        projected: list[dict[str, object]] = []
        for goal in sorted(aggregate.goals.values(), key=lambda g: g.goal_id):
            if scope_goals and goal.goal_id not in scope_goals:
                continue
            if allowed_goals and goal.goal_id not in allowed_goals and "*" not in allowed_goals:
                continue
            projected.append(
                {
                    "goal_id": goal.goal_id,
                    "title": goal.title,
                    "metric_name": goal.metric_name,
                    "target_value": goal.target_value,
                    "current_value": goal.current_value,
                    "completed": goal.completed,
                }
            )
        return projected

    def _build_personas(self, aggregate: UserCortexAggregate, request: ContextFrameRequest, profile: PermissionProfile) -> list[dict[str, object]]:
        scope_personas = set(request.persona_scope)
        allowed_personas = set(profile.allowed_personas)

        projected: list[dict[str, object]] = []
        for persona in sorted(aggregate.personas.values(), key=lambda p: p.persona_id):
            if scope_personas and persona.persona_id not in scope_personas:
                continue
            if allowed_personas and persona.persona_id not in allowed_personas and "*" not in allowed_personas:
                continue
            projected.append(
                {
                    "persona_id": persona.persona_id,
                    "persona_name": persona.persona_name,
                    "persona_type": persona.persona_type.value,
                    "priority": persona.priority,
                    "activation_rules": dict(persona.activation_rules),
                    "visibility_rules": dict(persona.visibility_rules),
                    "domain_scope": persona.domain_scope,
                    "goal_scope": persona.goal_scope,
                    "asset_scope": persona.asset_scope,
                    "active": persona.active,
                }
            )
        return projected

    def generate(
        self,
        aggregate: UserCortexAggregate,
        request: ContextFrameRequest,
        generated_at: Optional[datetime] = None,
    ) -> ContextFrame:
        now = generated_at or datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=request.ttl_seconds)
        certification = CertificationPipeline()

        permission_profile, policy_decisions = self.policy_evaluator.evaluate(request, now)
        certification.advance(CertificationStage.POLICY_FILTERED, passed=True)

        persona, activation_reason, conflict_resolution_path = self._select_persona_for_frame(aggregate, request)
        persona_domain_scope = set() if persona is None else set(persona.domain_scope)
        persona_goal_scope = set() if persona is None else set(persona.goal_scope)
        persona_asset_scope = set() if persona is None else set(persona.asset_scope)

        allowed_capabilities = set(permission_profile.allowed_capabilities)
        current_assets, historical_assets, excluded_assets = self._select_assets(aggregate, request, permission_profile)
        projected_current_assets = [self._project_asset(node, allowed_capabilities) for node in current_assets]
        projected_historical_assets = [self._project_asset(node, allowed_capabilities) for node in historical_assets]

        if persona is not None and persona_asset_scope:
            projected_current_assets = [
                asset for asset in projected_current_assets if asset["asset_id"] in persona_asset_scope
            ]
            projected_historical_assets = [
                asset for asset in projected_historical_assets if asset["asset_id"] in persona_asset_scope
            ]
        if persona is not None and persona_domain_scope:
            projected_current_assets = [
                asset for asset in projected_current_assets if asset["domain_id"] in persona_domain_scope
            ]
            projected_historical_assets = [
                asset for asset in projected_historical_assets if asset["domain_id"] in persona_domain_scope
            ]

        projected_goals = self._build_goals(aggregate, request, permission_profile)
        if persona is not None and persona_goal_scope:
            projected_goals = [goal for goal in projected_goals if goal["goal_id"] in persona_goal_scope]

        projected_personas = self._build_personas(aggregate, request, permission_profile)
        visible_recommendations = self._filter_recommendations_for_persona(aggregate, persona)
        active_projections = [
            {
                "projection_id": projection.projection_id,
                "projection_type": projection.projection_type.value,
                "source_state_hash": projection.source_state_hash,
                "confidence_score": projection.confidence_score,
                "generated_at": projection.generated_at.isoformat(),
                "expires_at": projection.expires_at.isoformat(),
                "trace_id": projection.trace_id,
                "projection_payload": dict(projection.projection_payload),
            }
            for projection in aggregate.active_projections(now)
        ]

        isolated_untrusted_text, redaction_info = self._sanitize_external_text(
            projected_current_assets + projected_historical_assets
        )
        certification.advance(CertificationStage.REDACTED, passed=True)

        source_hashes = {
            "digital_twin": _stable_hash(aggregate.digital_twin.current_state),
            "asset_nodes": _stable_hash(
                [
                    self._project_asset(node, allowed_capabilities)
                    for _, node in sorted(aggregate.asset_nodes.items(), key=lambda item: item[0])
                ]
            ),
            "goals": _stable_hash(projected_goals),
            "personas": _stable_hash(projected_personas),
            "projections": _stable_hash(active_projections),
            "policy_decisions": _stable_hash([asdict(decision) for decision in policy_decisions]),
        }
        certification.advance(CertificationStage.HASH_VERIFIED, passed=True)

        trusted_system_context = {
            "identity": aggregate.root_identity.continuity_id,
            "digital_twin_hash": source_hashes["digital_twin"],
            "certification_level": request.certification_level,
            "generated_at": now.isoformat(),
        }
        user_owned_facts = {
            "assets": projected_current_assets,
            "historical_assets": projected_historical_assets,
            "goals": projected_goals,
            "personas": projected_personas,
            "projections": active_projections,
            "active_persona": None if persona is None else {
                "persona_id": persona.persona_id,
                "persona_name": persona.persona_name,
                "persona_type": persona.persona_type.value,
                "priority": persona.priority,
                "activation_reason": activation_reason,
                "conflict_resolution_path": conflict_resolution_path,
                "domain_scope": persona.domain_scope,
                "goal_scope": persona.goal_scope,
                "asset_scope": persona.asset_scope,
            },
            "visible_recommendations": visible_recommendations,
            "permissions": {
                "allowed_domains": permission_profile.allowed_domains,
                "allowed_assets": permission_profile.allowed_assets,
                "allowed_capabilities": permission_profile.allowed_capabilities,
            },
        }
        context_payload = {
            "trusted_system_context": trusted_system_context,
            "user_owned_facts": user_owned_facts,
            "untrusted_external_text": isolated_untrusted_text,
        }

        frame_basis = {
            "user_id": request.user_id,
            "domain_scope": list(request.domain_scope),
            "persona_scope": list(request.persona_scope),
            "goal_scope": list(request.goal_scope),
            "asset_scope": list(request.asset_scope),
            "generated_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
            "source_hashes": source_hashes,
            "context_payload": context_payload,
            "redaction_metadata": redaction_info,
            "requesting_interface": request.requesting_interface,
            "certification_level": request.certification_level,
        }
        frame_id = _stable_hash(frame_basis)
        certification.advance(CertificationStage.VERIFIED_CONTEXT, passed=True)

        frame = ContextFrame(
            frame_id=frame_id,
            user_id=request.user_id,
            domain_scope=tuple(request.domain_scope),
            persona_scope=tuple(request.persona_scope),
            goal_scope=tuple(request.goal_scope),
            asset_scope=tuple(request.asset_scope),
            generated_at=now,
            expires_at=expires_at,
            certification_level=certification.current_stage.value,
            source_hashes=_freeze(source_hashes),
            context_payload=_freeze(context_payload),
            redaction_metadata=_freeze(redaction_info),
        )

        permissions_applied = {
            "allowed_domains": permission_profile.allowed_domains,
            "denied_domains": permission_profile.denied_domains,
            "allowed_assets": permission_profile.allowed_assets,
            "denied_assets": permission_profile.denied_assets,
            "allowed_capabilities": permission_profile.allowed_capabilities,
            "denied_capabilities": permission_profile.denied_capabilities,
            "allowed_personas": permission_profile.allowed_personas,
            "allowed_goals": permission_profile.allowed_goals,
            "include_historical": permission_profile.include_historical,
        }

        audit_event = ContextFrameAuditEvent(
            frame_id=frame.frame_id,
            user_id=request.user_id,
            requester=request.requesting_interface,
            policy_decisions=tuple(policy_decisions),
            permissions_applied=_freeze(permissions_applied),
            redactions_applied=frame.redaction_metadata,
            source_hashes=frame.source_hashes,
            generated_at=now,
            certification_level=frame.certification_level,
            included_assets=tuple(asset["asset_id"] for asset in projected_current_assets + projected_historical_assets),
            excluded_assets=tuple(excluded_assets),
            certification_path=tuple(certification.path),
            active_persona=None if persona is None else persona.persona_id,
            activation_reason=activation_reason,
            conflict_resolution_path=tuple(conflict_resolution_path),
            visible_domains=tuple(sorted(persona_domain_scope or set(request.domain_scope))),
            visible_goals=tuple(sorted(goal["goal_id"] for goal in projected_goals)),
            visible_assets=tuple(sorted(asset["asset_id"] for asset in projected_current_assets + projected_historical_assets)),
            visible_recommendations=tuple(
                sorted(str(item.get("recommendation_id", "")) for item in visible_recommendations)
            ),
        )
        self.audit_log.append(audit_event)
        self.audit_sink.append(audit_event)
        return frame

    def replay_audit(self, frame_id: str) -> dict[str, object]:
        return self.audit_sink.replay(frame_id)
