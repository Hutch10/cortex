from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json

from backend.models.user_cortex import (
    ActionMediationAuditSink,
    ActionMediationPolicy,
    ActionPolicyEffect,
    AdvisorOutput,
    AdvisorOutputGovernor,
    AdvisorOutputType,
    AttestationEngine,
    ContextFrameAssembler,
    ContextFrameRequest,
    LedgerEnvelopeBuilder,
    LifeDomainName,
    PolicyAction,
    PolicyDrivenActionMediator,
    RiskLevel,
    RootIdentity,
    TypedPermissionPolicy,
    UserCortexAggregate,
    UserDecisionType,
    VerificationEngine,
)


def _make_certified_output(now: datetime):
    aggregate = UserCortexAggregate(root_identity=RootIdentity(continuity_id="user-att-1"))
    aggregate.create_domain(LifeDomainName.VEHICLES, owner_id="owner-alpha")
    aggregate.register_vehicle(
        vehicle_id="vehicle-1",
        make="Cadillac",
        model="Escalade IQ",
        year=2026,
        ownership_status="OWNED",
        owner_id="owner-alpha",
        continuity_id="chain-a",
        odometer=1500,
        fuel_battery_state="Battery 89%",
    )

    frame_policies = (
        TypedPermissionPolicy(
            subject="advisor-alpha",
            action=PolicyAction.READ_CONTEXT,
            resource="*",
            grant_source="test",
        ),
        TypedPermissionPolicy(
            subject="advisor-alpha",
            action=PolicyAction.READ_DOMAIN,
            resource=LifeDomainName.VEHICLES.value,
            domain_scope=(LifeDomainName.VEHICLES.value,),
            grant_source="test",
        ),
        TypedPermissionPolicy(
            subject="advisor-alpha",
            action=PolicyAction.READ_ASSET,
            resource="vehicle-1",
            asset_scope=("vehicle-1",),
            grant_source="test",
        ),
        TypedPermissionPolicy(
            subject="advisor-alpha",
            action=PolicyAction.READ_CAPABILITY,
            resource="mobility",
            capability_scope=("mobility", "maintenance"),
            grant_source="test",
        ),
    )
    frame = ContextFrameAssembler().generate(
        aggregate,
        ContextFrameRequest(
            user_id="user-att-1",
            requesting_interface="advisor-alpha",
            domain_scope=(LifeDomainName.VEHICLES.value,),
            asset_scope=("vehicle-1",),
            policies=frame_policies,
        ),
        generated_at=now,
    )

    output = AdvisorOutput(
        advisor_id="advisor-att",
        advisor_version="2.0.0",
        frame_id=frame.frame_id,
        output_type=AdvisorOutputType.RECOMMENDATION,
        confidence=0.88,
        evidence_references=("ev:trend",),
        generated_at=now,
        expiration=now + timedelta(hours=4),
        trace_id="trace-att-1",
        recommendation="Shift usage profile to reduce maintenance risk.",
        intent="risk_reduction",
        observation="Telemetry trend indicates elevated wear pattern.",
    )
    certified = AdvisorOutputGovernor().certify(
        output,
        frame,
        supporting_evidence={"metric": "wear_score", "value": 0.71},
    )
    return certified


def _make_mediation_policy(now: datetime):
    return (
        ActionMediationPolicy(
            subject="user-att-1",
            proposed_action_type="update_asset_state",
            target_resource="vehicle-1",
            domain_scope=(LifeDomainName.VEHICLES.value,),
            asset_scope=("vehicle-1",),
            capability_scope=("mobility",),
            min_advisor_trust_level=2,
            max_risk_level=RiskLevel.HIGH,
            expiration=now + timedelta(hours=1),
            grant_source="test",
            effect=ActionPolicyEffect.ALLOW,
        ),
    )


def _approved_chain(now: datetime, tmp_path):
    certified = _make_certified_output(now)
    sink = ActionMediationAuditSink(str(tmp_path / "mediation_audit.jsonl"))
    mediator = PolicyDrivenActionMediator(audit_sink=sink)

    proposal = mediator.create_proposal(
        certified,
        user_id="user-att-1",
        proposed_action_type="update_asset_state",
        target_resource="vehicle-1",
        requested_permissions=("perm:update_asset",),
        risk_level=RiskLevel.MEDIUM,
        expiration=now + timedelta(minutes=30),
        domain_scope=(LifeDomainName.VEHICLES.value,),
        asset_scope=("vehicle-1",),
        capability_scope=("mobility",),
        generated_at=now,
    )
    review_required, _ = mediator.evaluate_policy(
        proposal,
        _make_mediation_policy(now),
        user_permissions=("perm:update_asset",),
        advisor_trust_level=5,
        now=now,
    )
    approved, decision = mediator.apply_user_decision(
        review_required,
        decision=UserDecisionType.APPROVE,
        reason="approved",
        decided_at=now + timedelta(minutes=1),
    )
    _, command = mediator.generate_command_artifact(
        approved,
        decision,
        permissions_used=("perm:update_asset",),
        generated_at=now + timedelta(minutes=2),
    )
    return certified, mediator, sink, proposal, approved, decision, command


def test_artifact_signature_tampering_detected(tmp_path) -> None:
    now = datetime(2026, 5, 29, 18, 0, 0, tzinfo=timezone.utc)
    certified = _make_certified_output(now)

    assert VerificationEngine.verify_signature(
        record_hash=certified.output.attestation.artifact_hash,
        signature=certified.output.attestation.signature,
        signer_id=certified.output.attestation.signer_id,
        key_id=certified.output.attestation.key_id,
        signed_at=certified.output.attestation.signed_at,
    )

    tampered_attestation = replace(certified.output.attestation, signature="forged-signature")
    tampered = replace(certified.output, attestation=tampered_attestation)
    assert not VerificationEngine.verify_artifact_signature_chain([tampered])


def test_audit_signature_tampering_detected(tmp_path) -> None:
    now = datetime(2026, 5, 29, 18, 10, 0, tzinfo=timezone.utc)
    _, _, sink, _, _, _, _ = _approved_chain(now, tmp_path)

    assert sink.verify_audit_log()

    audit_path = tmp_path / "mediation_audit.jsonl"
    lines = audit_path.read_text(encoding="utf-8").splitlines()
    payload = json.loads(lines[0])
    payload["signature"] = "forged-audit-signature"
    lines[0] = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    audit_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    assert not sink.verify_audit_log()


def test_forged_signer_rejected(tmp_path) -> None:
    now = datetime(2026, 5, 29, 18, 20, 0, tzinfo=timezone.utc)
    certified = _make_certified_output(now)

    forged = replace(
        certified.output,
        attestation=replace(
            certified.output.attestation,
            signer_id="forged-signer",
            key_id="forged-key",
        ),
    )
    assert not VerificationEngine.verify_artifact(forged)


def test_checkpoint_tampering_detected(tmp_path) -> None:
    now = datetime(2026, 5, 29, 18, 30, 0, tzinfo=timezone.utc)
    _, _, sink, _, _, _, _ = _approved_chain(now, tmp_path)

    checkpoint_path = tmp_path / "mediation_audit.jsonl.checkpoints"
    assert checkpoint_path.exists()
    assert sink.verify_checkpoint_chain()

    lines = checkpoint_path.read_text(encoding="utf-8").splitlines()
    payload = json.loads(lines[0])
    payload["root_hash"] = "tampered-root"
    lines[0] = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    checkpoint_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    assert not sink.verify_checkpoint_chain()


def test_replay_verification_succeeds(tmp_path) -> None:
    now = datetime(2026, 5, 29, 18, 40, 0, tzinfo=timezone.utc)
    certified, mediator, sink, proposal, approved, decision, command = _approved_chain(now, tmp_path)

    replay = mediator.replay_mediation(certified, proposal, decision, command)

    assert replay["whether_command_was_created"] is True
    assert replay["verification"]["hash_verification"] is True
    assert replay["verification"]["signature_verification"] is True
    assert replay["verification"]["checkpoint_verification"] is True
    assert replay["verification"]["replay_verified"] is True
    assert VerificationEngine.verify_replay(
        [certified.output, proposal, decision, command],
        str(tmp_path / "mediation_audit.jsonl"),
        sink.replay_checkpoints(),
    )


def test_deterministic_signatures_preserved(tmp_path) -> None:
    now = datetime(2026, 5, 29, 18, 50, 0, tzinfo=timezone.utc)
    certified = _make_certified_output(now)

    unsigned_one = replace(certified.output, attestation=None)
    unsigned_two = replace(certified.output, attestation=None)

    attestation_one = AttestationEngine.create_attestation(
        unsigned_one,
        created_at=now,
        previous_artifact_hash=None,
        signer_id="cortex-system",
        key_id="artifact-key-v1",
        signed_at=now,
    )
    attestation_two = AttestationEngine.create_attestation(
        unsigned_two,
        created_at=now,
        previous_artifact_hash=None,
        signer_id="cortex-system",
        key_id="artifact-key-v1",
        signed_at=now,
    )

    assert attestation_one.signature == attestation_two.signature
    assert attestation_one.attestation_hash == attestation_two.attestation_hash


def test_ledger_envelope_remains_deterministic(tmp_path) -> None:
    now = datetime(2026, 5, 29, 19, 0, 0, tzinfo=timezone.utc)
    certified, _, _, proposal, approved, decision, command = _approved_chain(now, tmp_path)

    envelope_a = LedgerEnvelopeBuilder.build(
        artifact_type="CommandArtifact",
        artifact=command,
        trace_id=command.trace_id,
        certification_state=approved.mediation_stage.value,
        chain=[certified.output, proposal, decision, command],
    )
    envelope_b = LedgerEnvelopeBuilder.build(
        artifact_type="CommandArtifact",
        artifact=command,
        trace_id=command.trace_id,
        certification_state=approved.mediation_stage.value,
        chain=[certified.output, proposal, decision, command],
    )

    assert envelope_a == envelope_b
