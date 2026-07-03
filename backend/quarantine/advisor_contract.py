from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
import json
from typing import Any, Callable, Mapping, Optional

from .artifact_attestation import ArtifactAttestation, AttestationEngine


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _stable_hash(value: object) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


class AdvisorOutputType(str, Enum):
    RECOMMENDATION = "Recommendation"
    INTENT = "Intent"
    OBSERVATION = "Observation"


class OutputCertificationStage(str, Enum):
    UNCERTIFIED = "UNCERTIFIED"
    STRUCTURALLY_VALID = "STRUCTURALLY_VALID"
    EVIDENCE_LINKED = "EVIDENCE_LINKED"
    TRACEABLE = "TRACEABLE"
    CERTIFIED_OUTPUT = "CERTIFIED_OUTPUT"


@dataclass(frozen=True)
class AdvisorOutput:
    advisor_id: str
    advisor_version: str
    frame_id: str
    output_type: AdvisorOutputType
    confidence: float
    evidence_references: tuple[str, ...]
    generated_at: datetime
    expiration: datetime
    trace_id: str
    recommendation: str
    intent: str
    observation: str
    attestation: Optional[ArtifactAttestation] = None

    def has_expired(self, at: Optional[datetime] = None) -> bool:
        check_at = at or datetime.now(timezone.utc)
        return check_at >= self.expiration


@dataclass(frozen=True)
class AdvisorEvidenceBinding:
    output_hash: str
    frame_id: str
    source_hashes: Mapping[str, str]
    supporting_evidence: Mapping[str, object]


@dataclass(frozen=True)
class CertifiedAdvisorOutput:
    output: AdvisorOutput
    certification_stage: OutputCertificationStage
    certification_path: tuple[str, ...]
    evidence_binding: AdvisorEvidenceBinding


@dataclass(frozen=True)
class AdvisorActionProposal:
    proposal_id: str
    output_trace_id: str
    action: str
    payload: Mapping[str, object]


class OutputCertificationPipeline:
    _ORDER = [
        OutputCertificationStage.UNCERTIFIED,
        OutputCertificationStage.STRUCTURALLY_VALID,
        OutputCertificationStage.EVIDENCE_LINKED,
        OutputCertificationStage.TRACEABLE,
        OutputCertificationStage.CERTIFIED_OUTPUT,
    ]

    def __init__(self) -> None:
        self.current_stage = OutputCertificationStage.UNCERTIFIED
        self.path: list[str] = [OutputCertificationStage.UNCERTIFIED.value]

    def advance(self, next_stage: OutputCertificationStage, passed: bool) -> None:
        if not passed:
            raise ValueError(f"Output certification stage failed: {next_stage.value}")
        current_index = self._ORDER.index(self.current_stage)
        expected = self._ORDER[current_index + 1] if current_index + 1 < len(self._ORDER) else None
        if next_stage != expected:
            raise ValueError(
                f"Output certification cannot skip order: expected {expected.value if expected else 'END'}, got {next_stage.value}"
            )
        self.current_stage = next_stage
        self.path.append(next_stage.value)


class AdvisorOutputGovernor:
    def certify(
        self,
        output: AdvisorOutput,
        frame: Any,
        supporting_evidence: Mapping[str, object],
        signer_id: str = "cortex-system",
        key_id: str = "artifact-key-v1",
    ) -> CertifiedAdvisorOutput:
        pipeline = OutputCertificationPipeline()

        structure_ok = (
            bool(output.advisor_id)
            and bool(output.advisor_version)
            and bool(output.frame_id)
            and bool(output.trace_id)
            and 0.0 <= output.confidence <= 1.0
            and output.expiration > output.generated_at
        )
        pipeline.advance(OutputCertificationStage.STRUCTURALLY_VALID, passed=structure_ok)

        if getattr(frame, "frame_id", None) != output.frame_id:
            raise ValueError("AdvisorOutput frame_id mismatch")
        if output.output_type == AdvisorOutputType.RECOMMENDATION and not output.evidence_references:
            raise ValueError("Recommendation outputs require evidence references")

        source_hashes = getattr(frame, "source_hashes", None)
        if not source_hashes:
            raise ValueError("ContextFrame source hashes are required for evidence binding")

        binding = AdvisorEvidenceBinding(
            output_hash=_stable_hash(
                {
                    "advisor_id": output.advisor_id,
                    "advisor_version": output.advisor_version,
                    "frame_id": output.frame_id,
                    "output_type": output.output_type.value,
                    "confidence": output.confidence,
                    "evidence_references": list(output.evidence_references),
                    "generated_at": output.generated_at.isoformat(),
                    "expiration": output.expiration.isoformat(),
                    "trace_id": output.trace_id,
                    "recommendation": output.recommendation,
                    "intent": output.intent,
                    "observation": output.observation,
                }
            ),
            frame_id=output.frame_id,
            source_hashes=source_hashes,
            supporting_evidence=dict(supporting_evidence),
        )
        pipeline.advance(OutputCertificationStage.EVIDENCE_LINKED, passed=True)

        traceable = bool(output.trace_id) and bool(binding.output_hash)
        pipeline.advance(OutputCertificationStage.TRACEABLE, passed=traceable)
        pipeline.advance(OutputCertificationStage.CERTIFIED_OUTPUT, passed=True)

        output_attested = AttestationEngine.attach_attestation(
            replace(output, attestation=None),
            created_at=output.generated_at,
            previous_artifact_hash=None,
            signer_id=signer_id,
            key_id=key_id,
        )

        return CertifiedAdvisorOutput(
            output=output_attested,
            certification_stage=pipeline.current_stage,
            certification_path=tuple(pipeline.path),
            evidence_binding=binding,
        )


class AdvisorReplayEngine:
    def replay(self, frame: Any, certified_output: CertifiedAdvisorOutput) -> Mapping[str, object]:
        return {
            "frame_id": getattr(frame, "frame_id", ""),
            "what_advisor_saw": {
                "source_hashes": getattr(frame, "source_hashes", {}),
                "context_payload": getattr(frame, "context_payload", {}),
            },
            "what_advisor_concluded": {
                "recommendation": certified_output.output.recommendation,
                "intent": certified_output.output.intent,
                "observation": certified_output.output.observation,
                "confidence": certified_output.output.confidence,
                "output_type": certified_output.output.output_type.value,
            },
            "why": {
                "evidence_references": certified_output.output.evidence_references,
                "supporting_evidence": certified_output.evidence_binding.supporting_evidence,
                "source_hashes": certified_output.evidence_binding.source_hashes,
                "certification_path": certified_output.certification_path,
                "trace_id": certified_output.output.trace_id,
            },
        }


class AdvisorMutationBoundary:
    def propose_action(
        self,
        certified_output: CertifiedAdvisorOutput,
        action: str,
        payload: Mapping[str, object],
    ) -> AdvisorActionProposal:
        proposal_id = _stable_hash(
            {
                "trace_id": certified_output.output.trace_id,
                "action": action,
                "payload": dict(payload),
            }
        )
        return AdvisorActionProposal(
            proposal_id=proposal_id,
            output_trace_id=certified_output.output.trace_id,
            action=action,
            payload=dict(payload),
        )

    def execute_mutation(self, proposal: AdvisorActionProposal, mutator: Callable[[], object], explicit_user_action: bool) -> object:
        if not explicit_user_action:
            raise PermissionError("Advisor outputs cannot mutate Cortex state without explicit user action")
        return mutator()
