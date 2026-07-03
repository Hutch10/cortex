from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass, replace
from datetime import datetime
from hashlib import sha256
import json
import os
from typing import Any, Iterable, Optional


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _stable_hash(value: object) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _to_plain(value: Any) -> Any:
    if is_dataclass(value):
        return {k: _to_plain(v) for k, v in asdict(value).items()}
    if isinstance(value, dict):
        return {str(k): _to_plain(v) for k, v in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (list, tuple)):
        return [_to_plain(v) for v in value]
    if isinstance(value, datetime):
        return value.isoformat()
    return value


@dataclass(frozen=True)
class SignatureRecord:
    record_hash: str
    signature: str
    signer_id: str
    key_id: str
    signed_at: datetime


@dataclass(frozen=True)
class ArtifactAttestation:
    artifact_hash: str
    previous_artifact_hash: Optional[str]
    attestation_hash: str
    created_at: datetime
    signature: str
    signer_id: str
    key_id: str
    signed_at: datetime


@dataclass(frozen=True)
class LedgerEnvelope:
    artifact_type: str
    artifact_hash: str
    trace_id: str
    certification_state: str
    attestation_chain: tuple[str, ...]


@dataclass(frozen=True)
class RootHashCheckpoint:
    checkpoint_id: str
    root_hash: str
    created_at: datetime
    previous_checkpoint_hash: Optional[str]
    checkpoint_hash: str
    signed_checkpoint: SignatureRecord


class SigningKeyRegistry:
    _KEYS: dict[tuple[str, str], str] = {
        ("cortex-system", "artifact-key-v1"): "cortex_artifact_secret_v1",
        ("cortex-system", "audit-key-v1"): "cortex_audit_secret_v1",
        ("cortex-system", "checkpoint-key-v1"): "cortex_checkpoint_secret_v1",
    }

    @classmethod
    def has_key(cls, signer_id: str, key_id: str) -> bool:
        return (signer_id, key_id) in cls._KEYS

    @classmethod
    def get_secret(cls, signer_id: str, key_id: str) -> Optional[str]:
        return cls._KEYS.get((signer_id, key_id))

    @classmethod
    def register_key(cls, signer_id: str, key_id: str, secret: str) -> None:
        cls._KEYS[(signer_id, key_id)] = secret


class AttestationEngine:
    @staticmethod
    def compute_signature(record_hash: str, signer_id: str, key_id: str, signed_at: datetime) -> str:
        secret = SigningKeyRegistry.get_secret(signer_id, key_id)
        if secret is None:
            raise ValueError("unknown signer_id/key_id")
        return _stable_hash(
            {
                "record_hash": record_hash,
                "signer_id": signer_id,
                "key_id": key_id,
                "signed_at": signed_at.isoformat(),
                "secret": secret,
            }
        )

    @staticmethod
    def sign_record(
        record_hash: str,
        signer_id: str,
        key_id: str,
        signed_at: datetime,
    ) -> SignatureRecord:
        return SignatureRecord(
            record_hash=record_hash,
            signature=AttestationEngine.compute_signature(record_hash, signer_id, key_id, signed_at),
            signer_id=signer_id,
            key_id=key_id,
            signed_at=signed_at,
        )

    @staticmethod
    def compute_artifact_hash(artifact: Any) -> str:
        payload = _to_plain(artifact)
        if isinstance(payload, dict) and "attestation" in payload:
            payload["attestation"] = None
        return _stable_hash(payload)

    @staticmethod
    def create_attestation(
        artifact: Any,
        created_at: datetime,
        previous_artifact_hash: Optional[str] = None,
        signer_id: str = "cortex-system",
        key_id: str = "artifact-key-v1",
        signed_at: Optional[datetime] = None,
    ) -> ArtifactAttestation:
        artifact_hash = AttestationEngine.compute_artifact_hash(artifact)
        resolved_signed_at = signed_at or created_at
        signature = AttestationEngine.compute_signature(
            artifact_hash,
            signer_id,
            key_id,
            resolved_signed_at,
        )
        attestation_hash = _stable_hash(
            {
                "artifact_hash": artifact_hash,
                "previous_artifact_hash": previous_artifact_hash,
                "created_at": created_at.isoformat(),
                "signature": signature,
                "signer_id": signer_id,
                "key_id": key_id,
                "signed_at": resolved_signed_at.isoformat(),
            }
        )
        return ArtifactAttestation(
            artifact_hash=artifact_hash,
            previous_artifact_hash=previous_artifact_hash,
            attestation_hash=attestation_hash,
            created_at=created_at,
            signature=signature,
            signer_id=signer_id,
            key_id=key_id,
            signed_at=resolved_signed_at,
        )

    @staticmethod
    def attach_attestation(
        artifact: Any,
        created_at: datetime,
        previous_artifact_hash: Optional[str] = None,
        signer_id: str = "cortex-system",
        key_id: str = "artifact-key-v1",
        signed_at: Optional[datetime] = None,
    ) -> Any:
        if not hasattr(artifact, "attestation"):
            raise TypeError("artifact must expose an attestation field")
        unsigned = replace(artifact, attestation=None)
        attestation = AttestationEngine.create_attestation(
            unsigned,
            created_at=created_at,
            previous_artifact_hash=previous_artifact_hash,
            signer_id=signer_id,
            key_id=key_id,
            signed_at=signed_at,
        )
        return replace(unsigned, attestation=attestation)


class CheckpointEngine:
    @staticmethod
    def create_checkpoint(
        root_hash: str,
        created_at: datetime,
        previous_checkpoint_hash: Optional[str] = None,
        signer_id: str = "cortex-system",
        key_id: str = "checkpoint-key-v1",
    ) -> RootHashCheckpoint:
        checkpoint_hash = _stable_hash(
            {
                "root_hash": root_hash,
                "created_at": created_at.isoformat(),
                "previous_checkpoint_hash": previous_checkpoint_hash,
            }
        )
        signed_checkpoint = AttestationEngine.sign_record(
            record_hash=checkpoint_hash,
            signer_id=signer_id,
            key_id=key_id,
            signed_at=created_at,
        )
        checkpoint_id = _stable_hash(
            {
                "checkpoint_hash": checkpoint_hash,
                "signature": signed_checkpoint.signature,
            }
        )
        return RootHashCheckpoint(
            checkpoint_id=checkpoint_id,
            root_hash=root_hash,
            created_at=created_at,
            previous_checkpoint_hash=previous_checkpoint_hash,
            checkpoint_hash=checkpoint_hash,
            signed_checkpoint=signed_checkpoint,
        )


class VerificationEngine:
    @staticmethod
    def verify_signature(record_hash: str, signature: str, signer_id: str, key_id: str, signed_at: datetime) -> bool:
        if not SigningKeyRegistry.has_key(signer_id, key_id):
            return False
        expected = AttestationEngine.compute_signature(record_hash, signer_id, key_id, signed_at)
        return expected == signature

    @staticmethod
    def verify_artifact(artifact: Any) -> bool:
        attestation = getattr(artifact, "attestation", None)
        if attestation is None:
            return False
        unsigned = replace(artifact, attestation=None)
        computed_artifact_hash = AttestationEngine.compute_artifact_hash(unsigned)
        if computed_artifact_hash != attestation.artifact_hash:
            return False
        expected_attestation_hash = _stable_hash(
            {
                "artifact_hash": attestation.artifact_hash,
                "previous_artifact_hash": attestation.previous_artifact_hash,
                "created_at": attestation.created_at.isoformat(),
                "signature": attestation.signature,
                "signer_id": attestation.signer_id,
                "key_id": attestation.key_id,
                "signed_at": attestation.signed_at.isoformat(),
            }
        )
        if expected_attestation_hash != attestation.attestation_hash:
            return False
        return VerificationEngine.verify_signature(
            record_hash=attestation.artifact_hash,
            signature=attestation.signature,
            signer_id=attestation.signer_id,
            key_id=attestation.key_id,
            signed_at=attestation.signed_at,
        )

    @staticmethod
    def verify_chain(artifacts: Iterable[Any]) -> bool:
        previous_hash: Optional[str] = None
        for artifact in artifacts:
            if not VerificationEngine.verify_artifact(artifact):
                return False
            current = artifact.attestation
            if current.previous_artifact_hash != previous_hash:
                return False
            previous_hash = current.artifact_hash
        return True

    @staticmethod
    def verify_artifact_signature_chain(artifacts: Iterable[Any]) -> bool:
        return VerificationEngine.verify_chain(artifacts)

    @staticmethod
    def verify_audit_log(file_path: str) -> bool:
        if not os.path.exists(file_path):
            return False

        previous_chain_hash: Optional[str] = None
        with open(file_path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                payload = json.loads(line)
                record_hash_expected = _stable_hash(
                    {
                        "event_type": payload.get("event_type"),
                        "proposal_id": payload.get("proposal_id"),
                        "generated_at": payload.get("generated_at"),
                        "details": payload.get("details", {}),
                    }
                )
                if payload.get("record_hash") != record_hash_expected:
                    return False

                signed_at_raw = payload.get("signed_at")
                if not isinstance(signed_at_raw, str):
                    return False
                signed_at = datetime.fromisoformat(signed_at_raw)
                if not VerificationEngine.verify_signature(
                    record_hash=payload.get("record_hash", ""),
                    signature=payload.get("signature", ""),
                    signer_id=payload.get("signer_id", ""),
                    key_id=payload.get("key_id", ""),
                    signed_at=signed_at,
                ):
                    return False

                if payload.get("event_hash") != payload.get("record_hash"):
                    return False
                if payload.get("previous_event_hash") != previous_chain_hash:
                    return False
                chain_hash_expected = _stable_hash(
                    {
                        "event_hash": payload.get("event_hash"),
                        "previous_event_hash": payload.get("previous_event_hash"),
                    }
                )
                if payload.get("chain_hash") != chain_hash_expected:
                    return False
                previous_chain_hash = payload.get("chain_hash")
        return True

    @staticmethod
    def verify_checkpoint_chain(checkpoints: Iterable[RootHashCheckpoint]) -> bool:
        previous_checkpoint_hash: Optional[str] = None
        for checkpoint in checkpoints:
            expected_checkpoint_hash = _stable_hash(
                {
                    "root_hash": checkpoint.root_hash,
                    "created_at": checkpoint.created_at.isoformat(),
                    "previous_checkpoint_hash": checkpoint.previous_checkpoint_hash,
                }
            )
            if expected_checkpoint_hash != checkpoint.checkpoint_hash:
                return False
            if checkpoint.previous_checkpoint_hash != previous_checkpoint_hash:
                return False
            signed = checkpoint.signed_checkpoint
            if signed.record_hash != checkpoint.checkpoint_hash:
                return False
            if not VerificationEngine.verify_signature(
                record_hash=signed.record_hash,
                signature=signed.signature,
                signer_id=signed.signer_id,
                key_id=signed.key_id,
                signed_at=signed.signed_at,
            ):
                return False
            previous_checkpoint_hash = checkpoint.checkpoint_hash
        return True

    @staticmethod
    def verify_replay(
        artifacts: Iterable[Any],
        audit_log_path: str,
        checkpoints: Iterable[RootHashCheckpoint],
    ) -> bool:
        return (
            VerificationEngine.verify_artifact_signature_chain(artifacts)
            and VerificationEngine.verify_audit_log(audit_log_path)
            and VerificationEngine.verify_checkpoint_chain(checkpoints)
        )


class LedgerEnvelopeBuilder:
    @staticmethod
    def build(
        artifact_type: str,
        artifact: Any,
        trace_id: str,
        certification_state: str,
        chain: Iterable[Any],
    ) -> LedgerEnvelope:
        artifact_attestation = getattr(artifact, "attestation", None)
        if artifact_attestation is None:
            raise ValueError("artifact must be attested")
        chain_hashes = []
        for item in chain:
            item_attestation = getattr(item, "attestation", None)
            if item_attestation is None:
                raise ValueError("all chain artifacts must be attested")
            chain_hashes.append(item_attestation.attestation_hash)
        return LedgerEnvelope(
            artifact_type=artifact_type,
            artifact_hash=artifact_attestation.artifact_hash,
            trace_id=trace_id,
            certification_state=certification_state,
            attestation_chain=tuple(chain_hashes),
        )
