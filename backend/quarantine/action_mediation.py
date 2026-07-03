from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
import json
import os
from typing import Mapping, Optional, Sequence

from .advisor_contract import CertifiedAdvisorOutput, OutputCertificationStage
from .artifact_attestation import (
    ArtifactAttestation,
    AttestationEngine,
    CheckpointEngine,
    RootHashCheckpoint,
    VerificationEngine,
)


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _stable_hash(value: object) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class MediationStage(str, Enum):
    PROPOSED = "PROPOSED"
    POLICY_CHECKED = "POLICY_CHECKED"
    USER_REVIEW_REQUIRED = "USER_REVIEW_REQUIRED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    COMMAND_READY = "COMMAND_READY"


class UserDecisionType(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    REQUEST_MORE_CONTEXT = "request_more_context"
    DEFER = "defer"


class ActionPolicyEffect(str, Enum):
    ALLOW = "allow"
    DENY = "deny"


class ActionPolicyDecisionStatus(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    EXPIRED = "expired"
    REVOKED = "revoked"
    INSUFFICIENT_SCOPE = "insufficient_scope"


class CommandExecutionStatus(str, Enum):
    NOT_EXECUTED = "NOT_EXECUTED"


@dataclass(frozen=True)
class ActionProposal:
    proposal_id: str
    advisor_output_id: str
    frame_id: str
    user_id: str
    proposed_action_type: str
    target_resource: str
    requested_permissions: tuple[str, ...]
    risk_level: RiskLevel
    generated_at: datetime
    expiration: datetime
    evidence_references: tuple[str, ...]
    proposal_hash: str
    domain_scope: tuple[str, ...] = ()
    asset_scope: tuple[str, ...] = ()
    capability_scope: tuple[str, ...] = ()
    mediation_stage: MediationStage = MediationStage.PROPOSED
    mediation_path: tuple[str, ...] = (MediationStage.PROPOSED.value,)
    trace_id: str = ""
    attestation: Optional[ArtifactAttestation] = None

    def has_expired(self, at: Optional[datetime] = None) -> bool:
        check_at = at or datetime.now(timezone.utc)
        return check_at >= self.expiration


@dataclass(frozen=True)
class ActionMediationPolicy:
    subject: str
    proposed_action_type: str
    target_resource: str
    domain_scope: tuple[str, ...] = ()
    asset_scope: tuple[str, ...] = ()
    capability_scope: tuple[str, ...] = ()
    min_advisor_trust_level: int = 0
    max_risk_level: RiskLevel = RiskLevel.CRITICAL
    expiration: Optional[datetime] = None
    grant_source: str = ""
    revocation_status: bool = False
    effect: ActionPolicyEffect = ActionPolicyEffect.ALLOW

    @property
    def policy_id(self) -> str:
        return _stable_hash(
            {
                "subject": self.subject,
                "proposed_action_type": self.proposed_action_type,
                "target_resource": self.target_resource,
                "domain_scope": list(self.domain_scope),
                "asset_scope": list(self.asset_scope),
                "capability_scope": list(self.capability_scope),
                "min_advisor_trust_level": self.min_advisor_trust_level,
                "max_risk_level": self.max_risk_level.value,
                "expiration": None if self.expiration is None else self.expiration.isoformat(),
                "grant_source": self.grant_source,
                "revocation_status": self.revocation_status,
                "effect": self.effect.value,
            }
        )


@dataclass(frozen=True)
class ActionPolicyDecision:
    policy_id: str
    subject: str
    decision: ActionPolicyDecisionStatus
    reason: str


@dataclass(frozen=True)
class UserDecision:
    decision_id: str
    proposal_id: str
    user_id: str
    decision: UserDecisionType
    reason: str
    decided_at: datetime
    trace_id: str = ""
    attestation: Optional[ArtifactAttestation] = None


@dataclass(frozen=True)
class CommandArtifact:
    command_id: str
    proposal_id: str
    user_id: str
    command_type: str
    target_resource: str
    permissions_used: tuple[str, ...]
    generated_at: datetime
    command_hash: str
    execution_status: CommandExecutionStatus
    trace_id: str = ""
    attestation: Optional[ArtifactAttestation] = None


@dataclass(frozen=True)
class ActionMediationAuditEvent:
    event_id: str
    event_type: str
    proposal_id: str
    generated_at: datetime
    details: Mapping[str, object]
    record_hash: str
    signature: str
    signer_id: str
    key_id: str
    signed_at: datetime
    previous_event_hash: Optional[str]
    event_hash: str
    chain_hash: str


class ActionMediationAuditSink:
    def __init__(self, file_path: str, checkpoint_interval: int = 3, checkpoint_path: Optional[str] = None) -> None:
        self.file_path = file_path
        self.checkpoint_interval = checkpoint_interval
        self.checkpoint_path = checkpoint_path or f"{file_path}.checkpoints"
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        self._event_counter = 0
        if os.path.exists(self.file_path):
            with open(self.file_path, "r", encoding="utf-8") as handle:
                self._event_counter = sum(1 for line in handle if line.strip())

    def _append_checkpoint(self, checkpoint: RootHashCheckpoint) -> None:
        payload = {
            "checkpoint_id": checkpoint.checkpoint_id,
            "root_hash": checkpoint.root_hash,
            "created_at": checkpoint.created_at.isoformat(),
            "previous_checkpoint_hash": checkpoint.previous_checkpoint_hash,
            "checkpoint_hash": checkpoint.checkpoint_hash,
            "signed_checkpoint": {
                "record_hash": checkpoint.signed_checkpoint.record_hash,
                "signature": checkpoint.signed_checkpoint.signature,
                "signer_id": checkpoint.signed_checkpoint.signer_id,
                "key_id": checkpoint.signed_checkpoint.key_id,
                "signed_at": checkpoint.signed_checkpoint.signed_at.isoformat(),
            },
        }
        with open(self.checkpoint_path, "a", encoding="utf-8") as handle:
            handle.write(_canonical_json(payload) + "\n")

    def append(self, event: ActionMediationAuditEvent) -> None:
        payload = {
            "event_id": event.event_id,
            "event_type": event.event_type,
            "proposal_id": event.proposal_id,
            "generated_at": event.generated_at.isoformat(),
            "details": dict(event.details),
            "record_hash": event.record_hash,
            "signature": event.signature,
            "signer_id": event.signer_id,
            "key_id": event.key_id,
            "signed_at": event.signed_at.isoformat(),
            "previous_event_hash": event.previous_event_hash,
            "event_hash": event.event_hash,
            "chain_hash": event.chain_hash,
        }
        with open(self.file_path, "a", encoding="utf-8") as handle:
            handle.write(_canonical_json(payload) + "\n")
        self._event_counter += 1
        if self.checkpoint_interval > 0 and self._event_counter % self.checkpoint_interval == 0:
            self.create_checkpoint(event.generated_at)

    def replay(self, proposal_id: str) -> list[dict[str, object]]:
        if not os.path.exists(self.file_path):
            return []
        rows: list[dict[str, object]] = []
        with open(self.file_path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                payload = json.loads(line)
                if payload.get("proposal_id") == proposal_id:
                    rows.append(payload)
        return rows

    def last_chain_hash(self) -> Optional[str]:
        if not os.path.exists(self.file_path):
            return None
        last_line: Optional[str] = None
        with open(self.file_path, "r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    last_line = line.strip()
        if last_line is None:
            return None
        payload = json.loads(last_line)
        return payload.get("chain_hash")

    def _last_checkpoint_hash(self) -> Optional[str]:
        if not os.path.exists(self.checkpoint_path):
            return None
        last_line: Optional[str] = None
        with open(self.checkpoint_path, "r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    last_line = line.strip()
        if last_line is None:
            return None
        payload = json.loads(last_line)
        value = payload.get("checkpoint_hash")
        return value if isinstance(value, str) else None

    def create_checkpoint(self, created_at: Optional[datetime] = None) -> RootHashCheckpoint:
        root_hash = self.last_chain_hash()
        if root_hash is None:
            raise ValueError("cannot create checkpoint with empty audit log")
        checkpoint = CheckpointEngine.create_checkpoint(
            root_hash=root_hash,
            created_at=created_at or datetime.now(timezone.utc),
            previous_checkpoint_hash=self._last_checkpoint_hash(),
        )
        self._append_checkpoint(checkpoint)
        return checkpoint

    def replay_checkpoints(self) -> list[RootHashCheckpoint]:
        if not os.path.exists(self.checkpoint_path):
            return []
        rows: list[RootHashCheckpoint] = []
        with open(self.checkpoint_path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                payload = json.loads(line)
                signed_payload = payload.get("signed_checkpoint", {})
                rows.append(
                    RootHashCheckpoint(
                        checkpoint_id=str(payload.get("checkpoint_id", "")),
                        root_hash=str(payload.get("root_hash", "")),
                        created_at=datetime.fromisoformat(str(payload.get("created_at"))),
                        previous_checkpoint_hash=payload.get("previous_checkpoint_hash"),
                        checkpoint_hash=str(payload.get("checkpoint_hash", "")),
                        signed_checkpoint=CheckpointEngine.create_checkpoint(
                            root_hash=str(payload.get("root_hash", "")),
                            created_at=datetime.fromisoformat(str(payload.get("created_at"))),
                            previous_checkpoint_hash=payload.get("previous_checkpoint_hash"),
                        ).signed_checkpoint,
                    )
                )
                if rows:
                    # Replace generated signature with persisted signature material from disk.
                    last = rows[-1]
                    rows[-1] = replace(
                        last,
                        signed_checkpoint=AttestationEngine.sign_record(
                            record_hash=str(signed_payload.get("record_hash", "")),
                            signer_id=str(signed_payload.get("signer_id", "")),
                            key_id=str(signed_payload.get("key_id", "")),
                            signed_at=datetime.fromisoformat(str(signed_payload.get("signed_at"))),
                        ),
                    )
                    rows[-1] = replace(
                        rows[-1],
                        signed_checkpoint=replace(
                            rows[-1].signed_checkpoint,
                            signature=str(signed_payload.get("signature", "")),
                        ),
                    )
        return rows

    def verify_audit_log(self) -> bool:
        return VerificationEngine.verify_audit_log(self.file_path)

    def verify_checkpoint_chain(self) -> bool:
        return VerificationEngine.verify_checkpoint_chain(self.replay_checkpoints())


class ActionMediationPipeline:
    _ORDER = [
        MediationStage.PROPOSED,
        MediationStage.POLICY_CHECKED,
        MediationStage.USER_REVIEW_REQUIRED,
        MediationStage.APPROVED,
        MediationStage.COMMAND_READY,
    ]

    def advance(self, proposal: ActionProposal, next_stage: MediationStage) -> ActionProposal:
        if next_stage in {MediationStage.REJECTED, MediationStage.EXPIRED}:
            return replace(
                proposal,
                mediation_stage=next_stage,
                mediation_path=tuple(list(proposal.mediation_path) + [next_stage.value]),
            )

        current_index = self._ORDER.index(proposal.mediation_stage)
        expected = self._ORDER[current_index + 1] if current_index + 1 < len(self._ORDER) else None
        if next_stage != expected:
            raise ValueError(
                f"Mediation stage cannot skip order: expected {expected.value if expected else 'END'}, got {next_stage.value}"
            )
        return replace(
            proposal,
            mediation_stage=next_stage,
            mediation_path=tuple(list(proposal.mediation_path) + [next_stage.value]),
        )


class ActionPolicyEvaluator:
    _RISK_RANK = {
        RiskLevel.LOW: 1,
        RiskLevel.MEDIUM: 2,
        RiskLevel.HIGH: 3,
        RiskLevel.CRITICAL: 4,
    }

    def _scope_allows(self, proposal_values: Sequence[str], policy_values: Sequence[str]) -> bool:
        if not proposal_values:
            return True
        if not policy_values:
            return True
        return set(proposal_values).issubset(set(policy_values))

    def evaluate(
        self,
        proposal: ActionProposal,
        policies: Sequence[ActionMediationPolicy],
        user_permissions: Sequence[str],
        advisor_trust_level: int,
        now: datetime,
    ) -> tuple[bool, list[ActionPolicyDecision], str]:
        decisions: list[ActionPolicyDecision] = []

        if proposal.has_expired(now):
            return False, decisions, "expired"

        if not set(proposal.requested_permissions).issubset(set(user_permissions)):
            return False, decisions, "insufficient_scope"

        matched_allow = False
        deny_hit = False

        filtered = sorted(
            [policy for policy in policies if policy.subject in {proposal.user_id, "*"}],
            key=lambda policy: (policy.proposed_action_type, policy.target_resource, policy.grant_source, policy.policy_id),
        )

        for policy in filtered:
            if policy.revocation_status:
                decisions.append(
                    ActionPolicyDecision(
                        policy_id=policy.policy_id,
                        subject=policy.subject,
                        decision=ActionPolicyDecisionStatus.REVOKED,
                        reason="policy revoked",
                    )
                )
                continue
            if policy.expiration is not None and now > policy.expiration:
                decisions.append(
                    ActionPolicyDecision(
                        policy_id=policy.policy_id,
                        subject=policy.subject,
                        decision=ActionPolicyDecisionStatus.EXPIRED,
                        reason="policy expired",
                    )
                )
                continue

            if policy.proposed_action_type not in {"*", proposal.proposed_action_type}:
                decisions.append(
                    ActionPolicyDecision(
                        policy_id=policy.policy_id,
                        subject=policy.subject,
                        decision=ActionPolicyDecisionStatus.INSUFFICIENT_SCOPE,
                        reason="action type mismatch",
                    )
                )
                continue
            if policy.target_resource not in {"*", proposal.target_resource}:
                decisions.append(
                    ActionPolicyDecision(
                        policy_id=policy.policy_id,
                        subject=policy.subject,
                        decision=ActionPolicyDecisionStatus.INSUFFICIENT_SCOPE,
                        reason="target mismatch",
                    )
                )
                continue
            if not self._scope_allows(proposal.domain_scope, policy.domain_scope):
                decisions.append(
                    ActionPolicyDecision(
                        policy_id=policy.policy_id,
                        subject=policy.subject,
                        decision=ActionPolicyDecisionStatus.INSUFFICIENT_SCOPE,
                        reason="domain scope mismatch",
                    )
                )
                continue
            if not self._scope_allows(proposal.asset_scope, policy.asset_scope):
                decisions.append(
                    ActionPolicyDecision(
                        policy_id=policy.policy_id,
                        subject=policy.subject,
                        decision=ActionPolicyDecisionStatus.INSUFFICIENT_SCOPE,
                        reason="asset scope mismatch",
                    )
                )
                continue
            if not self._scope_allows(proposal.capability_scope, policy.capability_scope):
                decisions.append(
                    ActionPolicyDecision(
                        policy_id=policy.policy_id,
                        subject=policy.subject,
                        decision=ActionPolicyDecisionStatus.INSUFFICIENT_SCOPE,
                        reason="capability scope mismatch",
                    )
                )
                continue
            if advisor_trust_level < policy.min_advisor_trust_level:
                decisions.append(
                    ActionPolicyDecision(
                        policy_id=policy.policy_id,
                        subject=policy.subject,
                        decision=ActionPolicyDecisionStatus.INSUFFICIENT_SCOPE,
                        reason="advisor trust below threshold",
                    )
                )
                continue
            if self._RISK_RANK[proposal.risk_level] > self._RISK_RANK[policy.max_risk_level]:
                decisions.append(
                    ActionPolicyDecision(
                        policy_id=policy.policy_id,
                        subject=policy.subject,
                        decision=ActionPolicyDecisionStatus.INSUFFICIENT_SCOPE,
                        reason="risk exceeds policy threshold",
                    )
                )
                continue

            if policy.effect == ActionPolicyEffect.DENY:
                deny_hit = True
                decisions.append(
                    ActionPolicyDecision(
                        policy_id=policy.policy_id,
                        subject=policy.subject,
                        decision=ActionPolicyDecisionStatus.DENY,
                        reason="deny policy matched",
                    )
                )
            else:
                matched_allow = True
                decisions.append(
                    ActionPolicyDecision(
                        policy_id=policy.policy_id,
                        subject=policy.subject,
                        decision=ActionPolicyDecisionStatus.ALLOW,
                        reason="allow policy matched",
                    )
                )

        if deny_hit:
            return False, decisions, "deny"
        if not matched_allow:
            return False, decisions, "insufficient_scope"
        return True, decisions, "allow"


class PolicyDrivenActionMediator:
    def __init__(self, audit_sink: Optional[ActionMediationAuditSink] = None) -> None:
        self.audit_sink = audit_sink or ActionMediationAuditSink(
            os.path.join("c:\\Users\\hetfw\\Cortex", "backend", "outputs", "action_mediation_audit.jsonl")
        )
        self.audit_log: list[ActionMediationAuditEvent] = []
        self.pipeline = ActionMediationPipeline()
        self.policy_evaluator = ActionPolicyEvaluator()

    def _emit_audit(self, event_type: str, proposal_id: str, generated_at: datetime, details: Mapping[str, object]) -> None:
        previous_event_hash = self.audit_sink.last_chain_hash()
        record_hash = _stable_hash(
            {
                "event_type": event_type,
                "proposal_id": proposal_id,
                "generated_at": generated_at.isoformat(),
                "details": dict(details),
            }
        )
        signed = AttestationEngine.sign_record(
            record_hash=record_hash,
            signer_id="cortex-system",
            key_id="audit-key-v1",
            signed_at=generated_at,
        )
        event_hash = record_hash
        chain_hash = _stable_hash(
            {
                "event_hash": event_hash,
                "previous_event_hash": previous_event_hash,
            }
        )
        event = ActionMediationAuditEvent(
            event_id=_stable_hash(
                {
                    "event_type": event_type,
                    "proposal_id": proposal_id,
                    "generated_at": generated_at.isoformat(),
                    "details": dict(details),
                }
            ),
            event_type=event_type,
            proposal_id=proposal_id,
            generated_at=generated_at,
            details=dict(details),
            record_hash=record_hash,
            signature=signed.signature,
            signer_id=signed.signer_id,
            key_id=signed.key_id,
            signed_at=signed.signed_at,
            previous_event_hash=previous_event_hash,
            event_hash=event_hash,
            chain_hash=chain_hash,
        )
        self.audit_log.append(event)
        self.audit_sink.append(event)

    def create_proposal(
        self,
        certified_output: CertifiedAdvisorOutput,
        user_id: str,
        proposed_action_type: str,
        target_resource: str,
        requested_permissions: Sequence[str],
        risk_level: RiskLevel,
        expiration: datetime,
        generated_at: Optional[datetime] = None,
        domain_scope: Sequence[str] = (),
        asset_scope: Sequence[str] = (),
        capability_scope: Sequence[str] = (),
    ) -> ActionProposal:
        now = generated_at or datetime.now(timezone.utc)
        if certified_output.certification_stage != OutputCertificationStage.CERTIFIED_OUTPUT:
            raise ValueError("uncertified advisor output cannot create proposal")
        if certified_output.output.attestation is None:
            raise ValueError("certified advisor output must be attested")

        advisor_output_id = certified_output.evidence_binding.output_hash
        proposal_basis = {
            "advisor_output_id": advisor_output_id,
            "frame_id": certified_output.output.frame_id,
            "user_id": user_id,
            "proposed_action_type": proposed_action_type,
            "target_resource": target_resource,
            "requested_permissions": sorted(set(requested_permissions)),
            "risk_level": risk_level.value,
            "generated_at": now.isoformat(),
            "expiration": expiration.isoformat(),
            "evidence_references": list(certified_output.output.evidence_references),
            "domain_scope": sorted(set(domain_scope)),
            "asset_scope": sorted(set(asset_scope)),
            "capability_scope": sorted(set(capability_scope)),
            "trace_id": certified_output.output.trace_id,
        }
        proposal_hash = _stable_hash(proposal_basis)
        proposal = ActionProposal(
            proposal_id=_stable_hash({"proposal_hash": proposal_hash, "trace_id": certified_output.output.trace_id}),
            advisor_output_id=advisor_output_id,
            frame_id=certified_output.output.frame_id,
            user_id=user_id,
            proposed_action_type=proposed_action_type,
            target_resource=target_resource,
            requested_permissions=tuple(sorted(set(requested_permissions))),
            risk_level=risk_level,
            generated_at=now,
            expiration=expiration,
            evidence_references=tuple(certified_output.output.evidence_references),
            proposal_hash=proposal_hash,
            domain_scope=tuple(sorted(set(domain_scope))),
            asset_scope=tuple(sorted(set(asset_scope))),
            capability_scope=tuple(sorted(set(capability_scope))),
            trace_id=certified_output.output.trace_id,
            attestation=None,
        )
        proposal = AttestationEngine.attach_attestation(
            proposal,
            created_at=now,
            previous_artifact_hash=certified_output.output.attestation.artifact_hash,
        )
        self._emit_audit(
            "proposal_creation",
            proposal.proposal_id,
            now,
            {
                "advisor_output_id": proposal.advisor_output_id,
                "frame_id": proposal.frame_id,
                "risk_level": proposal.risk_level.value,
                "proposed_action_type": proposal.proposed_action_type,
                "artifact_hash": proposal.attestation.artifact_hash,
            },
        )
        return proposal

    def evaluate_policy(
        self,
        proposal: ActionProposal,
        policies: Sequence[ActionMediationPolicy],
        user_permissions: Sequence[str],
        advisor_trust_level: int,
        now: Optional[datetime] = None,
    ) -> tuple[ActionProposal, tuple[ActionPolicyDecision, ...]]:
        check_at = now or datetime.now(timezone.utc)
        if proposal.has_expired(check_at):
            expired = self.pipeline.advance(proposal, MediationStage.EXPIRED)
            self._emit_audit(
                "policy_decision",
                proposal.proposal_id,
                check_at,
                {
                    "result": "expired",
                    "policy_decisions": [],
                },
            )
            return expired, tuple()

        policy_checked = self.pipeline.advance(proposal, MediationStage.POLICY_CHECKED)
        allowed, decisions, result = self.policy_evaluator.evaluate(
            policy_checked,
            policies,
            user_permissions,
            advisor_trust_level,
            check_at,
        )

        if not allowed:
            target_stage = MediationStage.EXPIRED if result == "expired" else MediationStage.REJECTED
            blocked = self.pipeline.advance(policy_checked, target_stage)
            self._emit_audit(
                "policy_decision",
                blocked.proposal_id,
                check_at,
                {
                    "result": result,
                    "policy_decisions": [asdict(decision) for decision in decisions],
                },
            )
            return blocked, tuple(decisions)

        review_required = self.pipeline.advance(policy_checked, MediationStage.USER_REVIEW_REQUIRED)
        self._emit_audit(
            "policy_decision",
            review_required.proposal_id,
            check_at,
            {
                "result": "allow",
                "policy_decisions": [asdict(decision) for decision in decisions],
            },
        )
        return review_required, tuple(decisions)

    def apply_user_decision(
        self,
        proposal: ActionProposal,
        decision: UserDecisionType,
        reason: str,
        decided_at: Optional[datetime] = None,
    ) -> tuple[ActionProposal, UserDecision]:
        now = decided_at or datetime.now(timezone.utc)
        if proposal.has_expired(now):
            expired = self.pipeline.advance(proposal, MediationStage.EXPIRED)
            record = UserDecision(
                decision_id=_stable_hash(
                    {
                        "proposal_id": proposal.proposal_id,
                        "decision": UserDecisionType.REJECT.value,
                        "decided_at": now.isoformat(),
                    }
                ),
                proposal_id=proposal.proposal_id,
                user_id=proposal.user_id,
                decision=UserDecisionType.REJECT,
                reason="proposal expired",
                decided_at=now,
                trace_id=proposal.trace_id,
                attestation=None,
            )
            record = AttestationEngine.attach_attestation(
                record,
                created_at=now,
                previous_artifact_hash=proposal.attestation.artifact_hash if proposal.attestation else None,
            )
            self._emit_audit(
                "user_decision",
                proposal.proposal_id,
                now,
                {
                    "decision": record.decision.value,
                    "reason": record.reason,
                    "stage": expired.mediation_stage.value,
                    "artifact_hash": record.attestation.artifact_hash,
                },
            )
            return expired, record

        if proposal.mediation_stage != MediationStage.USER_REVIEW_REQUIRED:
            raise ValueError("proposal is not ready for user decision")

        if decision == UserDecisionType.APPROVE:
            next_proposal = self.pipeline.advance(proposal, MediationStage.APPROVED)
        elif decision == UserDecisionType.REJECT:
            next_proposal = self.pipeline.advance(proposal, MediationStage.REJECTED)
        elif decision in {UserDecisionType.REQUEST_MORE_CONTEXT, UserDecisionType.DEFER}:
            next_proposal = proposal
        else:
            raise ValueError("unsupported user decision")

        record = UserDecision(
            decision_id=_stable_hash(
                {
                    "proposal_id": proposal.proposal_id,
                    "decision": decision.value,
                    "decided_at": now.isoformat(),
                    "reason": reason,
                }
            ),
            proposal_id=proposal.proposal_id,
            user_id=proposal.user_id,
            decision=decision,
            reason=reason,
            decided_at=now,
            trace_id=proposal.trace_id,
            attestation=None,
        )
        record = AttestationEngine.attach_attestation(
            record,
            created_at=now,
            previous_artifact_hash=proposal.attestation.artifact_hash if proposal.attestation else None,
        )
        self._emit_audit(
            "user_decision",
            proposal.proposal_id,
            now,
            {
                "decision": decision.value,
                "reason": reason,
                "stage": next_proposal.mediation_stage.value,
                "artifact_hash": record.attestation.artifact_hash,
            },
        )
        return next_proposal, record

    def generate_command_artifact(
        self,
        proposal: ActionProposal,
        user_decision: UserDecision,
        permissions_used: Sequence[str],
        generated_at: Optional[datetime] = None,
    ) -> tuple[ActionProposal, CommandArtifact]:
        now = generated_at or datetime.now(timezone.utc)
        if proposal.has_expired(now):
            raise ValueError("expired proposal cannot be approved")
        if proposal.mediation_stage != MediationStage.APPROVED or user_decision.decision != UserDecisionType.APPROVE:
            raise ValueError("command generation requires approved proposal")

        command_ready = self.pipeline.advance(proposal, MediationStage.COMMAND_READY)
        command_basis = {
            "proposal_id": proposal.proposal_id,
            "user_id": proposal.user_id,
            "command_type": proposal.proposed_action_type,
            "target_resource": proposal.target_resource,
            "permissions_used": sorted(set(permissions_used)),
            "generated_at": now.isoformat(),
            "trace_id": proposal.trace_id,
        }
        command_hash = _stable_hash(command_basis)
        command = CommandArtifact(
            command_id=_stable_hash({"command_hash": command_hash, "proposal_id": proposal.proposal_id}),
            proposal_id=proposal.proposal_id,
            user_id=proposal.user_id,
            command_type=proposal.proposed_action_type,
            target_resource=proposal.target_resource,
            permissions_used=tuple(sorted(set(permissions_used))),
            generated_at=now,
            command_hash=command_hash,
            execution_status=CommandExecutionStatus.NOT_EXECUTED,
            trace_id=proposal.trace_id,
            attestation=None,
        )
        command = AttestationEngine.attach_attestation(
            command,
            created_at=now,
            previous_artifact_hash=user_decision.attestation.artifact_hash if user_decision.attestation else None,
        )
        self._emit_audit(
            "command_generation",
            proposal.proposal_id,
            now,
            {
                "command_id": command.command_id,
                "execution_status": command.execution_status.value,
                "permissions_used": list(command.permissions_used),
                "artifact_hash": command.attestation.artifact_hash,
            },
        )
        return command_ready, command

    def execute_command(self, command: CommandArtifact) -> None:
        raise PermissionError("no command execution occurs in mediation layer")

    def replay_mediation(
        self,
        advisor_output: CertifiedAdvisorOutput,
        proposal: ActionProposal,
        user_decision: Optional[UserDecision],
        command_artifact: Optional[CommandArtifact],
    ) -> Mapping[str, object]:
        audit_events = self.audit_sink.replay(proposal.proposal_id)
        checkpoints = self.audit_sink.replay_checkpoints()
        artifact_chain = [advisor_output.output, proposal]
        if user_decision is not None:
            artifact_chain.append(user_decision)
        if command_artifact is not None:
            artifact_chain.append(command_artifact)

        artifacts_verified = VerificationEngine.verify_artifact_signature_chain(artifact_chain)
        audit_verified = self.audit_sink.verify_audit_log()
        checkpoints_verified = self.audit_sink.verify_checkpoint_chain()
        return {
            "what_was_recommended": {
                "recommendation": advisor_output.output.recommendation,
                "intent": advisor_output.output.intent,
                "observation": advisor_output.output.observation,
                "trace_id": advisor_output.output.trace_id,
                "advisor_output_id": advisor_output.evidence_binding.output_hash,
                "advisor_attestation": None
                if advisor_output.output.attestation is None
                else advisor_output.output.attestation.attestation_hash,
            },
            "why_it_was_proposed": {
                "frame_id": proposal.frame_id,
                "evidence_references": proposal.evidence_references,
                "proposal_hash": proposal.proposal_hash,
                "risk_level": proposal.risk_level.value,
                "proposal_attestation": None if proposal.attestation is None else proposal.attestation.attestation_hash,
            },
            "which_policies_were_evaluated": [
                event["details"].get("policy_decisions", [])
                for event in audit_events
                if event.get("event_type") == "policy_decision"
            ],
            "what_user_decided": None if user_decision is None else {
                "decision": user_decision.decision.value,
                "reason": user_decision.reason,
                "decided_at": user_decision.decided_at.isoformat(),
                "attestation": None if user_decision.attestation is None else user_decision.attestation.attestation_hash,
            },
            "whether_command_was_created": command_artifact is not None,
            "command_artifact": None if command_artifact is None else {
                "command_id": command_artifact.command_id,
                "execution_status": command_artifact.execution_status.value,
                "command_hash": command_artifact.command_hash,
                "attestation": None if command_artifact.attestation is None else command_artifact.attestation.attestation_hash,
            },
            "verification": {
                "hash_verification": artifacts_verified and audit_verified,
                "signature_verification": artifacts_verified and audit_verified,
                "checkpoint_verification": checkpoints_verified,
                "replay_verified": artifacts_verified and audit_verified and checkpoints_verified,
                "checkpoint_count": len(checkpoints),
            },
            "audit_events": audit_events,
        }
