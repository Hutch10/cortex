from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Dict, Mapping, Optional, Protocol, Sequence

from .action_mediation import ActionProposal, CommandArtifact, UserDecision
from .advisor_contract import (
    AdvisorOutput,
    AdvisorOutputGovernor,
    AdvisorOutputType,
    CertifiedAdvisorOutput,
)
from .artifact_attestation import (
    ArtifactAttestation,
    AttestationEngine,
    CheckpointEngine,
    RootHashCheckpoint,
    SigningKeyRegistry,
    VerificationEngine,
)
from .context_frame import ContextFrame


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _stable_hash(value: object) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _freeze(value: object) -> object:
    if isinstance(value, dict):
        return MappingProxyType({str(k): _freeze(v) for k, v in sorted(value.items(), key=lambda item: str(item[0]))})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze(item) for item in value)
    return value


class SidecarType(str, Enum):
    RESEARCH = "ResearchSidecar"
    TRAVEL = "TravelSidecar"
    MAINTENANCE = "MaintenanceSidecar"
    HEALTH = "HealthSidecar"
    BUSINESS = "BusinessSidecar"


class SidecarStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
    DEPRECATED = "DEPRECATED"


@dataclass(frozen=True)
class SidecarModel:
    sidecar_id: str
    sidecar_name: str
    sidecar_type: SidecarType
    sidecar_version: str
    trust_level: int
    supported_personas: tuple[str, ...]
    supported_domains: tuple[str, ...]
    status: SidecarStatus


@dataclass(frozen=True)
class SidecarContextView:
    frame_id: str
    user_id: str
    certification_level: str
    generated_at: datetime
    expires_at: datetime
    domain_scope: tuple[str, ...]
    persona_scope: tuple[str, ...]
    goal_scope: tuple[str, ...]
    asset_scope: tuple[str, ...]
    source_hashes: Mapping[str, str]
    context_payload: Mapping[str, object]


@dataclass(frozen=True)
class SidecarOutputDraft:
    output_type: AdvisorOutputType
    recommendation: str
    intent: str
    observation: str
    confidence: float
    evidence_references: tuple[str, ...]


@dataclass(frozen=True)
class SidecarInvocation:
    invocation_id: str
    frame_id: str
    sidecar_id: str
    trace_ids: tuple[str, ...]
    output_ids: tuple[str, ...]
    generated_at: datetime
    record_hash: str
    signer_id: str
    key_id: str
    signature: str
    signed_at: datetime
    previous_invocation_hash: Optional[str]
    invocation_hash: str


@dataclass(frozen=True)
class SidecarInvocationAuditArtifact:
    invocation_id: str
    frame_id: str
    sidecar_id: str
    generated_at: datetime
    output_ids: tuple[str, ...]
    audit_hash: str
    signer_id: str
    key_id: str
    signature: str
    signed_at: datetime


@dataclass(frozen=True)
class SidecarTraceRecord:
    trace_id: str
    frame_id: str
    sidecar_invocation_id: str
    advisor_output_id: str
    action_proposal: Optional[ActionProposal] = None
    user_decision: Optional[UserDecision] = None
    command_artifact: Optional[CommandArtifact] = None


class SidecarImplementation(Protocol):
    def invoke(self, context: SidecarContextView, generated_at: datetime) -> Sequence[SidecarOutputDraft]:
        ...


class DeterministicMockSidecar:
    def __init__(self, sidecar_id: str, sidecar_name: str) -> None:
        self.sidecar_id = sidecar_id
        self.sidecar_name = sidecar_name

    def _seed(self, context: SidecarContextView, generated_at: datetime) -> str:
        return _stable_hash(
            {
                "sidecar_id": self.sidecar_id,
                "frame_id": context.frame_id,
                "generated_at": generated_at.isoformat(),
                "source_hashes": dict(context.source_hashes),
            }
        )


class ResearchMockSidecar(DeterministicMockSidecar):
    def invoke(self, context: SidecarContextView, generated_at: datetime) -> Sequence[SidecarOutputDraft]:
        seed = self._seed(context, generated_at)
        return (
            SidecarOutputDraft(
                output_type=AdvisorOutputType.RECOMMENDATION,
                recommendation=f"Research trend action {seed[:8]}",
                intent=f"research_intent_{seed[8:14]}",
                observation=f"Research observation {seed[14:22]}",
                confidence=0.82,
                evidence_references=(f"research:{context.frame_id}",),
            ),
        )


class TravelMockSidecar(DeterministicMockSidecar):
    def invoke(self, context: SidecarContextView, generated_at: datetime) -> Sequence[SidecarOutputDraft]:
        seed = self._seed(context, generated_at)
        return (
            SidecarOutputDraft(
                output_type=AdvisorOutputType.INTENT,
                recommendation=f"Travel optimization {seed[:8]}",
                intent=f"travel_intent_{seed[8:14]}",
                observation=f"Travel observation {seed[14:22]}",
                confidence=0.79,
                evidence_references=(f"travel:{context.frame_id}",),
            ),
        )


class MaintenanceMockSidecar(DeterministicMockSidecar):
    def invoke(self, context: SidecarContextView, generated_at: datetime) -> Sequence[SidecarOutputDraft]:
        seed = self._seed(context, generated_at)
        return (
            SidecarOutputDraft(
                output_type=AdvisorOutputType.OBSERVATION,
                recommendation=f"Maintenance planning {seed[:8]}",
                intent=f"maintenance_intent_{seed[8:14]}",
                observation=f"Maintenance observation {seed[14:22]}",
                confidence=0.84,
                evidence_references=(f"maintenance:{context.frame_id}",),
            ),
        )


class AISidecarFrameworkV0:
    def __init__(self, checkpoint_interval: int = 3) -> None:
        self._sidecars: Dict[str, SidecarModel] = {}
        self._implementations: Dict[str, SidecarImplementation] = {}
        self._invocation_outputs: Dict[str, tuple[CertifiedAdvisorOutput, ...]] = {}
        self._invocations: Dict[str, SidecarInvocation] = {}
        self._frames: Dict[str, ContextFrame] = {}
        self._trace_registry: Dict[str, SidecarTraceRecord] = {}
        self._last_invocation_hash: Optional[str] = None
        self._checkpoint_interval = checkpoint_interval
        self._sidecar_checkpoints: list[RootHashCheckpoint] = []
        self.audit_log: list[SidecarInvocationAuditArtifact] = []
        self.output_governor = AdvisorOutputGovernor()

        if not SigningKeyRegistry.has_key("sidecar-forensics", "sidecar-audit-key-v1"):
            SigningKeyRegistry.register_key("sidecar-forensics", "sidecar-audit-key-v1", "sidecar_forensics_audit_secret_v1")
        if not SigningKeyRegistry.has_key("sidecar-forensics", "sidecar-checkpoint-key-v1"):
            SigningKeyRegistry.register_key(
                "sidecar-forensics",
                "sidecar-checkpoint-key-v1",
                "sidecar_forensics_checkpoint_secret_v1",
            )

    @property
    def sidecar_checkpoints(self) -> tuple[RootHashCheckpoint, ...]:
        return tuple(self._sidecar_checkpoints)

    def register_sidecar(self, model: SidecarModel, implementation: SidecarImplementation) -> None:
        self._sidecars[model.sidecar_id] = model
        self._implementations[model.sidecar_id] = implementation
        key_id = "sidecar-signing-key-v1"
        if not SigningKeyRegistry.has_key(model.sidecar_id, key_id):
            SigningKeyRegistry.register_key(
                model.sidecar_id,
                key_id,
                _stable_hash({"sidecar_id": model.sidecar_id, "key_id": key_id, "version": model.sidecar_version}),
            )

    def register_default_mock_sidecars(self) -> None:
        self.register_sidecar(
            SidecarModel(
                sidecar_id="research-v0",
                sidecar_name="Research Sidecar",
                sidecar_type=SidecarType.RESEARCH,
                sidecar_version="0.1.0",
                trust_level=2,
                supported_personas=("researcher",),
                supported_domains=("Research", "Business"),
                status=SidecarStatus.ACTIVE,
            ),
            ResearchMockSidecar("research-v0", "Research Sidecar"),
        )
        self.register_sidecar(
            SidecarModel(
                sidecar_id="travel-v0",
                sidecar_name="Travel Sidecar",
                sidecar_type=SidecarType.TRAVEL,
                sidecar_version="0.1.0",
                trust_level=2,
                supported_personas=("traveler", "pilot"),
                supported_domains=("Travel",),
                status=SidecarStatus.ACTIVE,
            ),
            TravelMockSidecar("travel-v0", "Travel Sidecar"),
        )
        self.register_sidecar(
            SidecarModel(
                sidecar_id="maintenance-v0",
                sidecar_name="Maintenance Sidecar",
                sidecar_type=SidecarType.MAINTENANCE,
                sidecar_version="0.1.0",
                trust_level=2,
                supported_personas=("personal", "business"),
                supported_domains=("Vehicles", "Property"),
                status=SidecarStatus.ACTIVE,
            ),
            MaintenanceMockSidecar("maintenance-v0", "Maintenance Sidecar"),
        )

    def _context_view(self, frame: ContextFrame) -> SidecarContextView:
        return SidecarContextView(
            frame_id=frame.frame_id,
            user_id=frame.user_id,
            certification_level=frame.certification_level,
            generated_at=frame.generated_at,
            expires_at=frame.expires_at,
            domain_scope=tuple(frame.domain_scope),
            persona_scope=tuple(frame.persona_scope),
            goal_scope=tuple(frame.goal_scope),
            asset_scope=tuple(frame.asset_scope),
            source_hashes=MappingProxyType(dict(frame.source_hashes)),
            context_payload=MappingProxyType(dict(_freeze(dict(frame.context_payload)))),
        )

    def _create_checkpoint_if_due(self, generated_at: datetime) -> None:
        if self._checkpoint_interval <= 0:
            return
        if len(self._invocations) % self._checkpoint_interval != 0:
            return
        if self._last_invocation_hash is None:
            return
        previous_hash = self._sidecar_checkpoints[-1].checkpoint_hash if self._sidecar_checkpoints else None
        checkpoint = CheckpointEngine.create_checkpoint(
            root_hash=self._last_invocation_hash,
            created_at=generated_at,
            previous_checkpoint_hash=previous_hash,
            signer_id="sidecar-forensics",
            key_id="sidecar-checkpoint-key-v1",
        )
        self._sidecar_checkpoints.append(checkpoint)

    def _verify_invocation_signature(self, invocation: SidecarInvocation) -> bool:
        expected_record_hash = _stable_hash(
            {
                "invocation_id": invocation.invocation_id,
                "frame_id": invocation.frame_id,
                "sidecar_id": invocation.sidecar_id,
                "trace_ids": list(invocation.trace_ids),
                "output_ids": list(invocation.output_ids),
                "generated_at": invocation.generated_at.isoformat(),
            }
        )
        if expected_record_hash != invocation.record_hash:
            return False
        expected_invocation_hash = _stable_hash(
            {
                "record_hash": invocation.record_hash,
                "previous_invocation_hash": invocation.previous_invocation_hash,
                "signature": invocation.signature,
                "signed_at": invocation.signed_at.isoformat(),
            }
        )
        if expected_invocation_hash != invocation.invocation_hash:
            return False
        return VerificationEngine.verify_signature(
            record_hash=invocation.record_hash,
            signature=invocation.signature,
            signer_id=invocation.signer_id,
            key_id=invocation.key_id,
            signed_at=invocation.signed_at,
        )

    def _verify_audit_signature(self, audit: SidecarInvocationAuditArtifact) -> bool:
        expected_audit_hash = _stable_hash(
            {
                "invocation_id": audit.invocation_id,
                "frame_id": audit.frame_id,
                "sidecar_id": audit.sidecar_id,
                "generated_at": audit.generated_at.isoformat(),
                "output_ids": list(audit.output_ids),
            }
        )
        if expected_audit_hash != audit.audit_hash:
            return False
        return VerificationEngine.verify_signature(
            record_hash=audit.audit_hash,
            signature=audit.signature,
            signer_id=audit.signer_id,
            key_id=audit.key_id,
            signed_at=audit.signed_at,
        )

    def invoke_sidecar(
        self,
        sidecar_id: str,
        frame: ContextFrame,
        generated_at: Optional[datetime] = None,
    ) -> tuple[CertifiedAdvisorOutput, ...]:
        if sidecar_id not in self._sidecars:
            raise KeyError(f"Unknown sidecar: {sidecar_id}")
        model = self._sidecars[sidecar_id]
        if model.status != SidecarStatus.ACTIVE:
            raise PermissionError("sidecar not active")
        if frame.certification_level != "VERIFIED_CONTEXT":
            raise PermissionError("sidecars may consume only VERIFIED_CONTEXT")

        now = generated_at or datetime.now(timezone.utc)
        sidecar_context = self._context_view(frame)
        drafts = tuple(self._implementations[sidecar_id].invoke(sidecar_context, now))

        certified_outputs: list[CertifiedAdvisorOutput] = []
        for index, draft in enumerate(drafts):
            if draft.output_type not in {
                AdvisorOutputType.RECOMMENDATION,
                AdvisorOutputType.INTENT,
                AdvisorOutputType.OBSERVATION,
            }:
                raise ValueError("invalid sidecar output type")
            trace_id = _stable_hash(
                {
                    "sidecar_id": model.sidecar_id,
                    "frame_id": frame.frame_id,
                    "index": index,
                    "generated_at": now.isoformat(),
                }
            )
            output = AdvisorOutput(
                advisor_id=model.sidecar_id,
                advisor_version=model.sidecar_version,
                frame_id=frame.frame_id,
                output_type=draft.output_type,
                confidence=draft.confidence,
                evidence_references=tuple(sorted(set(draft.evidence_references))),
                generated_at=now,
                expiration=now + timedelta(minutes=30),
                trace_id=trace_id,
                recommendation=draft.recommendation,
                intent=draft.intent,
                observation=draft.observation,
            )
            certified = self.output_governor.certify(
                output,
                frame,
                supporting_evidence={
                    "sidecar_id": model.sidecar_id,
                    "sidecar_type": model.sidecar_type.value,
                    "trust_level": model.trust_level,
                    "invocation_frame_id": frame.frame_id,
                },
                signer_id=model.sidecar_id,
                key_id="sidecar-signing-key-v1",
            )
            certified_outputs.append(certified)

        output_ids = tuple(certified.evidence_binding.output_hash for certified in certified_outputs)
        trace_ids = tuple(certified.output.trace_id for certified in certified_outputs)
        invocation_id = _stable_hash(
            {
                "frame_id": frame.frame_id,
                "sidecar_id": sidecar_id,
                "generated_at": now.isoformat(),
                "output_ids": list(output_ids),
            }
        )
        record_hash = _stable_hash(
            {
                "invocation_id": invocation_id,
                "frame_id": frame.frame_id,
                "sidecar_id": sidecar_id,
                "trace_ids": list(trace_ids),
                "output_ids": list(output_ids),
                "generated_at": now.isoformat(),
            }
        )
        signature_record = AttestationEngine.sign_record(
            record_hash=record_hash,
            signer_id=model.sidecar_id,
            key_id="sidecar-signing-key-v1",
            signed_at=now,
        )
        invocation_hash = _stable_hash(
            {
                "record_hash": record_hash,
                "previous_invocation_hash": self._last_invocation_hash,
                "signature": signature_record.signature,
                "signed_at": signature_record.signed_at.isoformat(),
            }
        )
        invocation = SidecarInvocation(
            invocation_id=invocation_id,
            frame_id=frame.frame_id,
            sidecar_id=sidecar_id,
            trace_ids=trace_ids,
            output_ids=output_ids,
            generated_at=now,
            record_hash=record_hash,
            signer_id=signature_record.signer_id,
            key_id=signature_record.key_id,
            signature=signature_record.signature,
            signed_at=signature_record.signed_at,
            previous_invocation_hash=self._last_invocation_hash,
            invocation_hash=invocation_hash,
        )

        audit_hash = _stable_hash(
            {
                "invocation_id": invocation_id,
                "frame_id": frame.frame_id,
                "sidecar_id": sidecar_id,
                "generated_at": now.isoformat(),
                "output_ids": list(output_ids),
            }
        )
        audit_signature = AttestationEngine.sign_record(
            record_hash=audit_hash,
            signer_id="sidecar-forensics",
            key_id="sidecar-audit-key-v1",
            signed_at=now,
        )
        audit = SidecarInvocationAuditArtifact(
            invocation_id=invocation_id,
            frame_id=frame.frame_id,
            sidecar_id=sidecar_id,
            generated_at=now,
            output_ids=output_ids,
            audit_hash=audit_hash,
            signer_id=audit_signature.signer_id,
            key_id=audit_signature.key_id,
            signature=audit_signature.signature,
            signed_at=audit_signature.signed_at,
        )

        self._frames[frame.frame_id] = frame
        self._invocation_outputs[invocation_id] = tuple(certified_outputs)
        self._invocations[invocation_id] = invocation
        self.audit_log.append(audit)
        self._last_invocation_hash = invocation.invocation_hash
        self._create_checkpoint_if_due(now)

        for index, trace_id in enumerate(trace_ids):
            self._trace_registry[trace_id] = SidecarTraceRecord(
                trace_id=trace_id,
                frame_id=frame.frame_id,
                sidecar_invocation_id=invocation_id,
                advisor_output_id=output_ids[index],
            )
        return tuple(certified_outputs)

    def register_mediation_trace(
        self,
        trace_id: str,
        action_proposal: ActionProposal,
        user_decision: UserDecision,
        command_artifact: CommandArtifact,
    ) -> None:
        if trace_id not in self._trace_registry:
            raise KeyError(f"Unknown trace_id: {trace_id}")
        record = self._trace_registry[trace_id]
        self._trace_registry[trace_id] = replace(
            record,
            action_proposal=action_proposal,
            user_decision=user_decision,
            command_artifact=command_artifact,
        )

    def verify_sidecar_integrity(self) -> bool:
        expected_previous_hash: Optional[str] = None
        for invocation_id in sorted(self._invocations.keys()):
            invocation = self._invocations[invocation_id]
            if invocation.previous_invocation_hash != expected_previous_hash:
                return False
            if not self._verify_invocation_signature(invocation):
                return False
            expected_previous_hash = invocation.invocation_hash

        for audit in self.audit_log:
            if not self._verify_audit_signature(audit):
                return False

        for outputs in self._invocation_outputs.values():
            for item in outputs:
                if not VerificationEngine.verify_artifact(item.output):
                    return False
        return VerificationEngine.verify_checkpoint_chain(self._sidecar_checkpoints)

    def replay_invocation(self, invocation_id: str) -> Mapping[str, object]:
        if invocation_id not in self._invocations:
            raise KeyError(f"Unknown invocation_id: {invocation_id}")
        invocation = self._invocations[invocation_id]
        model = self._sidecars[invocation.sidecar_id]
        outputs = self._invocation_outputs.get(invocation_id, tuple())
        return {
            "invocation_id": invocation.invocation_id,
            "which_sidecar_was_invoked": {
                "sidecar_id": model.sidecar_id,
                "sidecar_name": model.sidecar_name,
                "sidecar_type": model.sidecar_type.value,
                "sidecar_version": model.sidecar_version,
            },
            "which_contextframe_was_consumed": invocation.frame_id,
            "which_outputs_were_generated": [
                {
                    "output_id": item.evidence_binding.output_hash,
                    "output_type": item.output.output_type.value,
                    "trace_id": item.output.trace_id,
                }
                for item in outputs
            ],
            "signature_verification": self._verify_invocation_signature(invocation),
            "audit_hash": next((item.audit_hash for item in self.audit_log if item.invocation_id == invocation_id), ""),
        }

    def replay_trace(self, trace_id: str) -> Mapping[str, object]:
        if trace_id not in self._trace_registry:
            raise KeyError(f"Unknown trace_id: {trace_id}")
        trace = self._trace_registry[trace_id]
        invocation = self._invocations[trace.sidecar_invocation_id]
        frame = self._frames[trace.frame_id]
        output = next(
            (
                item
                for item in self._invocation_outputs[trace.sidecar_invocation_id]
                if item.evidence_binding.output_hash == trace.advisor_output_id
            ),
            None,
        )
        if output is None:
            raise KeyError(f"Missing advisor output for trace_id: {trace_id}")

        chain_items: list[object] = [output.output]
        if trace.action_proposal is not None:
            chain_items.append(trace.action_proposal)
        if trace.user_decision is not None:
            chain_items.append(trace.user_decision)
        if trace.command_artifact is not None:
            chain_items.append(trace.command_artifact)

        trace_continuity_ok = all(
            item.trace_id == trace_id
            for item in [trace.action_proposal, trace.user_decision, trace.command_artifact]
            if item is not None
        )

        return {
            "trace_id": trace_id,
            "context_frame": {
                "frame_id": frame.frame_id,
                "certification_level": frame.certification_level,
            },
            "sidecar_invocation": {
                "invocation_id": invocation.invocation_id,
                "sidecar_id": invocation.sidecar_id,
                "signature_valid": self._verify_invocation_signature(invocation),
            },
            "advisor_output": {
                "output_id": trace.advisor_output_id,
                "trace_id": output.output.trace_id,
                "attestation_valid": VerificationEngine.verify_artifact(output.output),
            },
            "action_proposal": None if trace.action_proposal is None else {
                "proposal_id": trace.action_proposal.proposal_id,
                "trace_id": trace.action_proposal.trace_id,
            },
            "user_decision": None if trace.user_decision is None else {
                "decision_id": trace.user_decision.decision_id,
                "trace_id": trace.user_decision.trace_id,
            },
            "command_artifact": None if trace.command_artifact is None else {
                "command_id": trace.command_artifact.command_id,
                "trace_id": trace.command_artifact.trace_id,
            },
            "verification": {
                "trace_continuity": trace_continuity_ok,
                "artifact_chain": VerificationEngine.verify_artifact_signature_chain(chain_items),
                "checkpoint_chain": VerificationEngine.verify_checkpoint_chain(self._sidecar_checkpoints),
            },
        }

    def execute_command(self) -> None:
        raise PermissionError("sidecars may not execute commands")
