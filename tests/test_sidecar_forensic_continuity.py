from dataclasses import replace
from datetime import datetime, timedelta, timezone

from backend.models.user_cortex import (
    AISidecarFrameworkV0,
    ActionMediationAuditSink,
    ActionMediationPolicy,
    ActionPolicyEffect,
    ContextFrameAssembler,
    ContextFrameRequest,
    LifeDomainName,
    PolicyAction,
    PolicyDrivenActionMediator,
    RiskLevel,
    RootIdentity,
    TypedPermissionPolicy,
    UserCortexAggregate,
    UserDecisionType,
)


def _make_aggregate() -> UserCortexAggregate:
    aggregate = UserCortexAggregate(root_identity=RootIdentity(continuity_id="user-sfc-1"))
    aggregate.create_domain(LifeDomainName.VEHICLES, owner_id="owner-a")
    aggregate.register_vehicle(
        vehicle_id="vehicle-sfc-1",
        make="Cadillac",
        model="Escalade IQ",
        year=2026,
        ownership_status="OWNED",
        owner_id="owner-a",
        continuity_id="sfc-chain-1",
        odometer=1000,
        fuel_battery_state="Battery 90%",
    )
    aggregate.create_goal("goal-sfc", "Stability", "score", 99)
    return aggregate


def _build_frame(aggregate: UserCortexAggregate, now: datetime):
    policies = (
        TypedPermissionPolicy(
            subject="advisor-sfc",
            action=PolicyAction.READ_CONTEXT,
            resource="*",
            grant_source="test",
        ),
        TypedPermissionPolicy(
            subject="advisor-sfc",
            action=PolicyAction.READ_DOMAIN,
            resource=LifeDomainName.VEHICLES.value,
            domain_scope=(LifeDomainName.VEHICLES.value,),
            grant_source="test",
        ),
        TypedPermissionPolicy(
            subject="advisor-sfc",
            action=PolicyAction.READ_ASSET,
            resource="vehicle-sfc-1",
            asset_scope=("vehicle-sfc-1",),
            grant_source="test",
        ),
        TypedPermissionPolicy(
            subject="advisor-sfc",
            action=PolicyAction.READ_CAPABILITY,
            resource="mobility",
            capability_scope=("mobility", "maintenance"),
            grant_source="test",
        ),
    )
    return ContextFrameAssembler().generate(
        aggregate,
        ContextFrameRequest(
            user_id="user-sfc-1",
            requesting_interface="advisor-sfc",
            domain_scope=(LifeDomainName.VEHICLES.value,),
            goal_scope=("goal-sfc",),
            asset_scope=("vehicle-sfc-1",),
            policies=policies,
        ),
        generated_at=now,
    )


def _build_mediation_policy(now: datetime):
    return (
        ActionMediationPolicy(
            subject="user-sfc-1",
            proposed_action_type="update_asset_state",
            target_resource="vehicle-sfc-1",
            domain_scope=(LifeDomainName.VEHICLES.value,),
            asset_scope=("vehicle-sfc-1",),
            capability_scope=("mobility",),
            min_advisor_trust_level=1,
            max_risk_level=RiskLevel.HIGH,
            expiration=now + timedelta(hours=1),
            grant_source="test",
            effect=ActionPolicyEffect.ALLOW,
        ),
    )


def _build_trace_bundle(now: datetime, tmp_path):
    aggregate = _make_aggregate()
    frame = _build_frame(aggregate, now)

    framework = AISidecarFrameworkV0(checkpoint_interval=1)
    framework.register_default_mock_sidecars()
    outputs = framework.invoke_sidecar("maintenance-v0", frame, generated_at=now)
    certified = outputs[0]

    mediator = PolicyDrivenActionMediator(
        audit_sink=ActionMediationAuditSink(
            file_path=str(tmp_path / "sfc_mediation_audit.jsonl"),
            checkpoint_interval=1,
        )
    )
    proposal = mediator.create_proposal(
        certified,
        user_id="user-sfc-1",
        proposed_action_type="update_asset_state",
        target_resource="vehicle-sfc-1",
        requested_permissions=("perm:update",),
        risk_level=RiskLevel.MEDIUM,
        expiration=now + timedelta(minutes=30),
        domain_scope=(LifeDomainName.VEHICLES.value,),
        asset_scope=("vehicle-sfc-1",),
        capability_scope=("mobility",),
        generated_at=now,
    )
    reviewed, _ = mediator.evaluate_policy(
        proposal,
        _build_mediation_policy(now),
        user_permissions=("perm:update",),
        advisor_trust_level=3,
        now=now,
    )
    approved, decision = mediator.apply_user_decision(
        reviewed,
        decision=UserDecisionType.APPROVE,
        reason="approve",
        decided_at=now + timedelta(minutes=1),
    )
    _, command = mediator.generate_command_artifact(
        approved,
        decision,
        permissions_used=("perm:update",),
        generated_at=now + timedelta(minutes=2),
    )

    trace_id = certified.output.trace_id
    framework.register_mediation_trace(trace_id, proposal, decision, command)
    invocation_id = framework.audit_log[-1].invocation_id

    return framework, invocation_id, trace_id


def test_invocation_tampering_detected(tmp_path) -> None:
    now = datetime(2026, 5, 29, 22, 0, 0, tzinfo=timezone.utc)
    framework, invocation_id, _ = _build_trace_bundle(now, tmp_path)

    assert framework.verify_sidecar_integrity()

    invocation = framework._invocations[invocation_id]
    framework._invocations[invocation_id] = replace(invocation, record_hash="tampered")

    assert not framework.verify_sidecar_integrity()


def test_signature_tampering_detected(tmp_path) -> None:
    now = datetime(2026, 5, 29, 22, 5, 0, tzinfo=timezone.utc)
    framework, invocation_id, _ = _build_trace_bundle(now, tmp_path)

    invocation = framework._invocations[invocation_id]
    framework._invocations[invocation_id] = replace(invocation, signature="forged")

    assert not framework.verify_sidecar_integrity()


def test_trace_reconstruction_succeeds(tmp_path) -> None:
    now = datetime(2026, 5, 29, 22, 10, 0, tzinfo=timezone.utc)
    framework, _, trace_id = _build_trace_bundle(now, tmp_path)

    replay = framework.replay_trace(trace_id)

    assert replay["trace_id"] == trace_id
    assert replay["context_frame"]["certification_level"] == "VERIFIED_CONTEXT"
    assert replay["sidecar_invocation"]["signature_valid"] is True
    assert replay["action_proposal"] is not None
    assert replay["user_decision"] is not None
    assert replay["command_artifact"] is not None
    assert replay["verification"]["trace_continuity"] is True
    assert replay["verification"]["artifact_chain"] is True


def test_checkpoint_validation_succeeds(tmp_path) -> None:
    now = datetime(2026, 5, 29, 22, 15, 0, tzinfo=timezone.utc)
    framework, _, _ = _build_trace_bundle(now, tmp_path)

    assert len(framework.sidecar_checkpoints) >= 1
    assert framework.verify_sidecar_integrity()


def test_replay_remains_deterministic(tmp_path) -> None:
    now = datetime(2026, 5, 29, 22, 20, 0, tzinfo=timezone.utc)
    framework, _, trace_id = _build_trace_bundle(now, tmp_path)

    first = framework.replay_trace(trace_id)
    second = framework.replay_trace(trace_id)

    assert first == second
