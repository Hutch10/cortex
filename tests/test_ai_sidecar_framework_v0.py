from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from backend.models.user_cortex import (
    AISidecarFrameworkV0,
    AdvisorOutputType,
    ContextFrameAssembler,
    ContextFrameRequest,
    LifeDomainName,
    OutputCertificationStage,
    PolicyAction,
    SidecarModel,
    SidecarOutputDraft,
    SidecarStatus,
    SidecarType,
    TypedPermissionPolicy,
    UserCortexAggregate,
    RootIdentity,
)


def _make_aggregate() -> UserCortexAggregate:
    aggregate = UserCortexAggregate(root_identity=RootIdentity(continuity_id="user-sidecar-1"))
    aggregate.create_domain(LifeDomainName.RESEARCH, owner_id="owner-a")
    aggregate.create_domain(LifeDomainName.TRAVEL, owner_id="owner-a")
    aggregate.create_domain(LifeDomainName.VEHICLES, owner_id="owner-a")
    aggregate.register_vehicle(
        vehicle_id="vehicle-sidecar-1",
        make="Cadillac",
        model="Escalade IQ",
        year=2026,
        ownership_status="OWNED",
        owner_id="owner-a",
        continuity_id="sidecar-chain-1",
        odometer=1200,
        fuel_battery_state="Battery 91%",
    )
    aggregate.create_goal("goal-sidecar", "Reduce Risk", "risk", 1)
    return aggregate


def _make_frame(aggregate: UserCortexAggregate, now: datetime):
    policies = (
        TypedPermissionPolicy(
            subject="advisor-sidecar",
            action=PolicyAction.READ_CONTEXT,
            resource="*",
            grant_source="test",
        ),
        TypedPermissionPolicy(
            subject="advisor-sidecar",
            action=PolicyAction.READ_DOMAIN,
            resource="*",
            domain_scope=(LifeDomainName.RESEARCH.value, LifeDomainName.TRAVEL.value, LifeDomainName.VEHICLES.value),
            grant_source="test",
        ),
        TypedPermissionPolicy(
            subject="advisor-sidecar",
            action=PolicyAction.READ_ASSET,
            resource="*",
            asset_scope=("vehicle-sidecar-1",),
            grant_source="test",
        ),
        TypedPermissionPolicy(
            subject="advisor-sidecar",
            action=PolicyAction.READ_CAPABILITY,
            resource="*",
            capability_scope=("mobility", "maintenance"),
            grant_source="test",
        ),
        TypedPermissionPolicy(
            subject="advisor-sidecar",
            action=PolicyAction.READ_GOAL,
            resource="goal-sidecar",
            grant_source="test",
            expiration=now + timedelta(hours=1),
        ),
    )
    return ContextFrameAssembler().generate(
        aggregate,
        ContextFrameRequest(
            user_id="user-sidecar-1",
            requesting_interface="advisor-sidecar",
            domain_scope=(LifeDomainName.RESEARCH.value, LifeDomainName.TRAVEL.value, LifeDomainName.VEHICLES.value),
            goal_scope=("goal-sidecar",),
            asset_scope=("vehicle-sidecar-1",),
            policies=policies,
        ),
        generated_at=now,
    )


def test_sidecars_only_receive_verified_context() -> None:
    now = datetime(2026, 5, 29, 21, 0, 0, tzinfo=timezone.utc)
    aggregate = _make_aggregate()
    frame = _make_frame(aggregate, now)
    framework = AISidecarFrameworkV0()
    framework.register_default_mock_sidecars()

    uncertified = replace(frame, certification_level="HASH_VERIFIED")
    with pytest.raises(PermissionError, match="VERIFIED_CONTEXT"):
        framework.invoke_sidecar("research-v0", uncertified, generated_at=now)


def test_sidecars_cannot_access_digital_twin() -> None:
    now = datetime(2026, 5, 29, 21, 5, 0, tzinfo=timezone.utc)
    aggregate = _make_aggregate()
    frame = _make_frame(aggregate, now)
    framework = AISidecarFrameworkV0()

    class IntrospectiveSidecar:
        def invoke(self, context, generated_at):
            with pytest.raises(AttributeError):
                _ = context.digital_twin
            with pytest.raises(AttributeError):
                _ = context.ledger
            with pytest.raises(AttributeError):
                _ = context.snapshots
            with pytest.raises(AttributeError):
                _ = context.audit_records
            return (
                SidecarOutputDraft(
                    output_type=AdvisorOutputType.OBSERVATION,
                    recommendation="r",
                    intent="i",
                    observation="o",
                    confidence=0.75,
                    evidence_references=("ev:introspective",),
                ),
            )

    framework.register_sidecar(
        model=SidecarModel(
            sidecar_id="inspect-v0",
            sidecar_name="Inspect Sidecar",
            sidecar_type=SidecarType.RESEARCH,
            sidecar_version="0.1.0",
            trust_level=1,
            supported_personas=("researcher",),
            supported_domains=("Research",),
            status=SidecarStatus.ACTIVE,
        ),
        implementation=IntrospectiveSidecar(),
    )

    outputs = framework.invoke_sidecar("inspect-v0", frame, generated_at=now)
    assert len(outputs) == 1


def test_sidecars_cannot_mutate_state() -> None:
    now = datetime(2026, 5, 29, 21, 10, 0, tzinfo=timezone.utc)
    aggregate = _make_aggregate()
    frame = _make_frame(aggregate, now)
    framework = AISidecarFrameworkV0()
    framework.register_default_mock_sidecars()

    before_current = deepcopy(aggregate.digital_twin.current_state)
    before_historical = deepcopy(aggregate.digital_twin.historical_state)
    before_projections = deepcopy(aggregate.digital_twin.projections)

    framework.invoke_sidecar("maintenance-v0", frame, generated_at=now)

    assert aggregate.digital_twin.current_state == before_current
    assert aggregate.digital_twin.historical_state == before_historical
    assert aggregate.digital_twin.projections == before_projections


def test_outputs_enter_advisor_governance_correctly() -> None:
    now = datetime(2026, 5, 29, 21, 15, 0, tzinfo=timezone.utc)
    aggregate = _make_aggregate()
    frame = _make_frame(aggregate, now)
    framework = AISidecarFrameworkV0()
    framework.register_default_mock_sidecars()

    outputs = framework.invoke_sidecar("research-v0", frame, generated_at=now)

    assert len(outputs) == 1
    certified = outputs[0]
    assert certified.certification_stage == OutputCertificationStage.CERTIFIED_OUTPUT
    assert certified.output.output_type in {
        AdvisorOutputType.RECOMMENDATION,
        AdvisorOutputType.INTENT,
        AdvisorOutputType.OBSERVATION,
    }
    assert certified.output.attestation is not None


def test_replay_reconstruction_works() -> None:
    now = datetime(2026, 5, 29, 21, 20, 0, tzinfo=timezone.utc)
    aggregate = _make_aggregate()
    frame = _make_frame(aggregate, now)
    framework = AISidecarFrameworkV0()
    framework.register_default_mock_sidecars()

    outputs = framework.invoke_sidecar("travel-v0", frame, generated_at=now)
    invocation_id = framework.audit_log[-1].invocation_id

    replay = framework.replay_invocation(invocation_id)

    assert replay["which_sidecar_was_invoked"]["sidecar_id"] == "travel-v0"
    assert replay["which_contextframe_was_consumed"] == frame.frame_id
    assert len(replay["which_outputs_were_generated"]) == len(outputs)


def test_audit_artifacts_generated() -> None:
    now = datetime(2026, 5, 29, 21, 25, 0, tzinfo=timezone.utc)
    aggregate = _make_aggregate()
    frame = _make_frame(aggregate, now)
    framework = AISidecarFrameworkV0()
    framework.register_default_mock_sidecars()

    framework.invoke_sidecar("maintenance-v0", frame, generated_at=now)

    assert len(framework.audit_log) == 1
    audit = framework.audit_log[0]
    assert audit.frame_id == frame.frame_id
    assert audit.sidecar_id == "maintenance-v0"
    assert len(audit.output_ids) == 1
    assert bool(audit.audit_hash)


def test_mock_sidecar_outputs_are_deterministic_and_execution_blocked() -> None:
    now = datetime(2026, 5, 29, 21, 30, 0, tzinfo=timezone.utc)
    aggregate = _make_aggregate()
    frame = _make_frame(aggregate, now)
    framework = AISidecarFrameworkV0()
    framework.register_default_mock_sidecars()

    first = framework.invoke_sidecar("research-v0", frame, generated_at=now)
    second = framework.invoke_sidecar("research-v0", frame, generated_at=now)

    assert first[0].output.recommendation == second[0].output.recommendation
    assert first[0].output.intent == second[0].output.intent
    assert first[0].output.observation == second[0].output.observation

    with pytest.raises(PermissionError, match="may not execute commands"):
        framework.execute_command()
