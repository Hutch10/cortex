from datetime import datetime, timedelta, timezone

import pytest

from backend.models.user_cortex import (
    ActionMediationAuditSink,
    ActionMediationPolicy,
    ActionPolicyEffect,
    AdvisorOutput,
    AdvisorOutputGovernor,
    AdvisorOutputType,
    CommandExecutionStatus,
    ContextFrameAssembler,
    ContextFrameRequest,
    LifeDomainName,
    MediationStage,
    OutputCertificationStage,
    PolicyAction,
    PolicyDrivenActionMediator,
    RiskLevel,
    RootIdentity,
    TypedPermissionPolicy,
    UserCortexAggregate,
    UserDecisionType,
)


def make_aggregate() -> UserCortexAggregate:
    aggregate = UserCortexAggregate(root_identity=RootIdentity(continuity_id="user-med-1"))
    aggregate.create_domain(LifeDomainName.VEHICLES, owner_id="owner-alpha")
    aggregate.register_vehicle(
        vehicle_id="vehicle-1",
        make="Cadillac",
        model="Escalade IQ",
        year=2026,
        ownership_status="OWNED",
        owner_id="owner-alpha",
        continuity_id="fleet-chain-m1",
        odometer=3200,
        fuel_battery_state="Battery 87%",
    )
    return aggregate


def make_certified_output(now: datetime):
    aggregate = make_aggregate()
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
    frame_request = ContextFrameRequest(
        user_id="user-med-1",
        requesting_interface="advisor-alpha",
        domain_scope=(LifeDomainName.VEHICLES.value,),
        asset_scope=("vehicle-1",),
        policies=frame_policies,
    )
    frame = ContextFrameAssembler().generate(aggregate, frame_request, generated_at=now)

    output = AdvisorOutput(
        advisor_id="fleet-ops-advisor",
        advisor_version="1.1.0",
        frame_id=frame.frame_id,
        output_type=AdvisorOutputType.RECOMMENDATION,
        confidence=0.9,
        evidence_references=("ev:maint-window",),
        generated_at=now,
        expiration=now + timedelta(hours=4),
        trace_id="trace-med-1",
        recommendation="Pause nonessential usage until maintenance check.",
        intent="risk_reduction",
        observation="Telemetry shows elevated anomaly confidence.",
    )
    certified = AdvisorOutputGovernor().certify(
        output,
        frame,
        supporting_evidence={"metric": "anomaly_score", "value": 0.82},
    )
    return certified


def make_mediation_policies(now: datetime):
    return (
        ActionMediationPolicy(
            subject="user-med-1",
            proposed_action_type="update_asset_state",
            target_resource="vehicle-1",
            domain_scope=(LifeDomainName.VEHICLES.value,),
            asset_scope=("vehicle-1",),
            capability_scope=("mobility",),
            min_advisor_trust_level=3,
            max_risk_level=RiskLevel.HIGH,
            expiration=now + timedelta(hours=1),
            grant_source="test",
            effect=ActionPolicyEffect.ALLOW,
        ),
    )


def test_uncertified_advisor_output_cannot_create_proposal(tmp_path) -> None:
    now = datetime(2026, 5, 29, 14, 0, 0, tzinfo=timezone.utc)
    certified = make_certified_output(now)
    uncertified = certified.__class__(
        output=certified.output,
        certification_stage=OutputCertificationStage.TRACEABLE,
        certification_path=certified.certification_path,
        evidence_binding=certified.evidence_binding,
    )
    mediator = PolicyDrivenActionMediator(
        audit_sink=ActionMediationAuditSink(str(tmp_path / "mediation_audit.jsonl"))
    )

    with pytest.raises(ValueError, match="uncertified"):
        mediator.create_proposal(
            uncertified,
            user_id="user-med-1",
            proposed_action_type="update_asset_state",
            target_resource="vehicle-1",
            requested_permissions=("perm:update_asset",),
            risk_level=RiskLevel.MEDIUM,
            expiration=now + timedelta(minutes=30),
        )


def test_expired_proposal_cannot_be_approved(tmp_path) -> None:
    now = datetime(2026, 5, 29, 14, 30, 0, tzinfo=timezone.utc)
    certified = make_certified_output(now)
    mediator = PolicyDrivenActionMediator(
        audit_sink=ActionMediationAuditSink(str(tmp_path / "mediation_audit.jsonl"))
    )

    proposal = mediator.create_proposal(
        certified,
        user_id="user-med-1",
        proposed_action_type="update_asset_state",
        target_resource="vehicle-1",
        requested_permissions=("perm:update_asset",),
        risk_level=RiskLevel.MEDIUM,
        expiration=now + timedelta(minutes=5),
        domain_scope=(LifeDomainName.VEHICLES.value,),
        asset_scope=("vehicle-1",),
        capability_scope=("mobility",),
        generated_at=now,
    )

    checked, _ = mediator.evaluate_policy(
        proposal,
        make_mediation_policies(now),
        user_permissions=("perm:update_asset",),
        advisor_trust_level=5,
        now=now + timedelta(minutes=6),
    )

    assert checked.mediation_stage == MediationStage.EXPIRED


def test_deny_policy_blocks_proposal(tmp_path) -> None:
    now = datetime(2026, 5, 29, 15, 0, 0, tzinfo=timezone.utc)
    certified = make_certified_output(now)
    mediator = PolicyDrivenActionMediator(
        audit_sink=ActionMediationAuditSink(str(tmp_path / "mediation_audit.jsonl"))
    )

    proposal = mediator.create_proposal(
        certified,
        user_id="user-med-1",
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

    policies = make_mediation_policies(now) + (
        ActionMediationPolicy(
            subject="user-med-1",
            proposed_action_type="update_asset_state",
            target_resource="vehicle-1",
            domain_scope=(LifeDomainName.VEHICLES.value,),
            asset_scope=("vehicle-1",),
            capability_scope=("mobility",),
            min_advisor_trust_level=0,
            max_risk_level=RiskLevel.CRITICAL,
            expiration=now + timedelta(hours=1),
            grant_source="test",
            effect=ActionPolicyEffect.DENY,
        ),
    )

    blocked, _ = mediator.evaluate_policy(
        proposal,
        policies,
        user_permissions=("perm:update_asset",),
        advisor_trust_level=5,
        now=now,
    )

    assert blocked.mediation_stage == MediationStage.REJECTED


def test_high_risk_action_requires_explicit_user_approval(tmp_path) -> None:
    now = datetime(2026, 5, 29, 15, 30, 0, tzinfo=timezone.utc)
    certified = make_certified_output(now)
    mediator = PolicyDrivenActionMediator(
        audit_sink=ActionMediationAuditSink(str(tmp_path / "mediation_audit.jsonl"))
    )

    proposal = mediator.create_proposal(
        certified,
        user_id="user-med-1",
        proposed_action_type="update_asset_state",
        target_resource="vehicle-1",
        requested_permissions=("perm:update_asset",),
        risk_level=RiskLevel.HIGH,
        expiration=now + timedelta(minutes=30),
        domain_scope=(LifeDomainName.VEHICLES.value,),
        asset_scope=("vehicle-1",),
        capability_scope=("mobility",),
        generated_at=now,
    )

    review_required, _ = mediator.evaluate_policy(
        proposal,
        make_mediation_policies(now),
        user_permissions=("perm:update_asset",),
        advisor_trust_level=5,
        now=now,
    )

    assert review_required.mediation_stage == MediationStage.USER_REVIEW_REQUIRED


def test_rejected_proposal_never_creates_command(tmp_path) -> None:
    now = datetime(2026, 5, 29, 16, 0, 0, tzinfo=timezone.utc)
    certified = make_certified_output(now)
    mediator = PolicyDrivenActionMediator(
        audit_sink=ActionMediationAuditSink(str(tmp_path / "mediation_audit.jsonl"))
    )

    proposal = mediator.create_proposal(
        certified,
        user_id="user-med-1",
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
        make_mediation_policies(now),
        user_permissions=("perm:update_asset",),
        advisor_trust_level=5,
        now=now,
    )
    rejected, decision = mediator.apply_user_decision(
        review_required,
        decision=UserDecisionType.REJECT,
        reason="user declined",
        decided_at=now + timedelta(minutes=1),
    )

    assert rejected.mediation_stage == MediationStage.REJECTED
    with pytest.raises(ValueError, match="approved proposal"):
        mediator.generate_command_artifact(
            rejected,
            decision,
            permissions_used=("perm:update_asset",),
            generated_at=now + timedelta(minutes=2),
        )


def test_approved_proposal_creates_not_executed_command_artifact(tmp_path) -> None:
    now = datetime(2026, 5, 29, 16, 30, 0, tzinfo=timezone.utc)
    certified = make_certified_output(now)
    mediator = PolicyDrivenActionMediator(
        audit_sink=ActionMediationAuditSink(str(tmp_path / "mediation_audit.jsonl"))
    )

    proposal = mediator.create_proposal(
        certified,
        user_id="user-med-1",
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
        make_mediation_policies(now),
        user_permissions=("perm:update_asset",),
        advisor_trust_level=5,
        now=now,
    )
    approved, decision = mediator.apply_user_decision(
        review_required,
        decision=UserDecisionType.APPROVE,
        reason="user approved",
        decided_at=now + timedelta(minutes=1),
    )
    command_ready, command = mediator.generate_command_artifact(
        approved,
        decision,
        permissions_used=("perm:update_asset",),
        generated_at=now + timedelta(minutes=2),
    )

    assert command_ready.mediation_stage == MediationStage.COMMAND_READY
    assert command.execution_status == CommandExecutionStatus.NOT_EXECUTED


def test_audit_trail_reconstructs_full_mediation_path(tmp_path) -> None:
    now = datetime(2026, 5, 29, 17, 0, 0, tzinfo=timezone.utc)
    certified = make_certified_output(now)
    sink = ActionMediationAuditSink(str(tmp_path / "mediation_audit.jsonl"))
    mediator = PolicyDrivenActionMediator(audit_sink=sink)

    proposal = mediator.create_proposal(
        certified,
        user_id="user-med-1",
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
    review_required, decisions = mediator.evaluate_policy(
        proposal,
        make_mediation_policies(now),
        user_permissions=("perm:update_asset",),
        advisor_trust_level=5,
        now=now,
    )
    approved, user_decision = mediator.apply_user_decision(
        review_required,
        decision=UserDecisionType.APPROVE,
        reason="approved",
        decided_at=now + timedelta(minutes=1),
    )
    _, command = mediator.generate_command_artifact(
        approved,
        user_decision,
        permissions_used=("perm:update_asset",),
        generated_at=now + timedelta(minutes=2),
    )

    replay = mediator.replay_mediation(certified, proposal, user_decision, command)

    assert replay["what_was_recommended"]["advisor_output_id"] == certified.evidence_binding.output_hash
    assert len(replay["which_policies_were_evaluated"]) > 0
    assert replay["what_user_decided"]["decision"] == "approve"
    assert replay["whether_command_was_created"] is True


def test_no_command_execution_occurs(tmp_path) -> None:
    now = datetime(2026, 5, 29, 17, 30, 0, tzinfo=timezone.utc)
    certified = make_certified_output(now)
    mediator = PolicyDrivenActionMediator(
        audit_sink=ActionMediationAuditSink(str(tmp_path / "mediation_audit.jsonl"))
    )

    proposal = mediator.create_proposal(
        certified,
        user_id="user-med-1",
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
        make_mediation_policies(now),
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

    with pytest.raises(PermissionError, match="no command execution"):
        mediator.execute_command(command)
