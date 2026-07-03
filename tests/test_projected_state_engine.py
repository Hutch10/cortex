from copy import deepcopy
from datetime import datetime, timedelta, timezone

from backend.models.user_cortex import (
    ContextFrameAssembler,
    ContextFrameRequest,
    LifeDomainName,
    PolicyAction,
    ProjectionType,
    RootIdentity,
    TypedPermissionPolicy,
    UserCortexAggregate,
)


def _make_aggregate() -> UserCortexAggregate:
    aggregate = UserCortexAggregate(root_identity=RootIdentity(continuity_id="user-proj-1"))
    aggregate.create_domain(LifeDomainName.TRAVEL, owner_id="owner-a")
    aggregate.create_domain(LifeDomainName.VEHICLES, owner_id="owner-a")
    aggregate.register_vehicle(
        vehicle_id="vehicle-1",
        make="Cadillac",
        model="Escalade IQ",
        year=2026,
        ownership_status="OWNED",
        owner_id="owner-a",
        continuity_id="proj-chain-1",
        odometer=1200,
        fuel_battery_state="Battery 92%",
    )
    aggregate.create_goal("goal-maint", "Reduce maintenance events", "count", 2)
    return aggregate


def _frame_policies(now: datetime) -> tuple[TypedPermissionPolicy, ...]:
    return (
        TypedPermissionPolicy(
            subject="advisor-proj",
            action=PolicyAction.READ_CONTEXT,
            resource="*",
            grant_source="test",
        ),
        TypedPermissionPolicy(
            subject="advisor-proj",
            action=PolicyAction.READ_DOMAIN,
            resource="*",
            domain_scope=(LifeDomainName.TRAVEL.value, LifeDomainName.VEHICLES.value),
            grant_source="test",
        ),
        TypedPermissionPolicy(
            subject="advisor-proj",
            action=PolicyAction.READ_ASSET,
            resource="*",
            asset_scope=("vehicle-1",),
            grant_source="test",
        ),
        TypedPermissionPolicy(
            subject="advisor-proj",
            action=PolicyAction.READ_GOAL,
            resource="*",
            grant_source="test",
            expiration=now + timedelta(hours=1),
        ),
    )


def test_projection_creation_supports_all_categories() -> None:
    aggregate = _make_aggregate()
    now = datetime(2026, 5, 29, 20, 0, 0, tzinfo=timezone.utc)

    categories = [
        ProjectionType.GOAL_PROJECTION,
        ProjectionType.ASSET_PROJECTION,
        ProjectionType.SCHEDULE_PROJECTION,
        ProjectionType.MAINTENANCE_PROJECTION,
        ProjectionType.TRAVEL_PROJECTION,
    ]

    for index, category in enumerate(categories):
        projection = aggregate.create_projection(
            projection_type=category,
            projection_inputs={"index": index, "asset_id": "vehicle-1"},
            ttl_seconds=600,
            trace_id=f"trace-proj-{index}",
            generated_at=now,
        )
        assert projection.projection_type == category
        assert projection.source_state_hash
        assert 0.6 <= projection.confidence_score <= 0.99
        assert projection.expires_at > projection.generated_at


def test_expiration_behavior_and_active_context_filtering() -> None:
    aggregate = _make_aggregate()
    generated_at = datetime(2026, 5, 29, 20, 5, 0, tzinfo=timezone.utc)

    active_projection = aggregate.create_projection(
        projection_type=ProjectionType.TRAVEL_PROJECTION,
        projection_inputs={"trip": "east-coast"},
        ttl_seconds=300,
        trace_id="trace-active",
        generated_at=generated_at,
    )
    expired_projection = aggregate.create_projection(
        projection_type=ProjectionType.MAINTENANCE_PROJECTION,
        projection_inputs={"vehicle_id": "vehicle-1"},
        ttl_seconds=60,
        trace_id="trace-expired",
        generated_at=generated_at,
    )

    later = generated_at + timedelta(seconds=120)
    assert aggregate.digital_twin.is_projection_active(active_projection.projection_id, later)
    assert not aggregate.digital_twin.is_projection_active(expired_projection.projection_id, later)

    frame = ContextFrameAssembler().generate(
        aggregate,
        ContextFrameRequest(
            user_id="user-proj-1",
            requesting_interface="advisor-proj",
            domain_scope=(LifeDomainName.TRAVEL.value, LifeDomainName.VEHICLES.value),
            goal_scope=("goal-maint",),
            asset_scope=("vehicle-1",),
            policies=_frame_policies(generated_at),
        ),
        generated_at=later,
    )

    visible_projection_ids = [
        item["projection_id"]
        for item in frame.context_payload["user_owned_facts"]["projections"]
    ]
    assert active_projection.projection_id in visible_projection_ids
    assert expired_projection.projection_id not in visible_projection_ids


def test_confidence_reproducibility_is_deterministic() -> None:
    aggregate = _make_aggregate()
    now = datetime(2026, 5, 29, 20, 10, 0, tzinfo=timezone.utc)

    one = aggregate.create_projection(
        projection_type=ProjectionType.ASSET_PROJECTION,
        projection_inputs={"asset_id": "vehicle-1", "horizon_days": 30},
        ttl_seconds=900,
        trace_id="trace-same",
        generated_at=now,
    )
    two = aggregate.create_projection(
        projection_type=ProjectionType.ASSET_PROJECTION,
        projection_inputs={"asset_id": "vehicle-1", "horizon_days": 30},
        ttl_seconds=900,
        trace_id="trace-same",
        generated_at=now,
    )

    assert one.confidence_score == two.confidence_score
    assert one.confidence_calculation == two.confidence_calculation


def test_replay_reconstructs_inputs_confidence_and_expiration() -> None:
    aggregate = _make_aggregate()
    now = datetime(2026, 5, 29, 20, 15, 0, tzinfo=timezone.utc)

    projection = aggregate.create_projection(
        projection_type=ProjectionType.GOAL_PROJECTION,
        projection_inputs={"goal_id": "goal-maint", "target_delta": -1},
        ttl_seconds=120,
        trace_id="trace-replay",
        generated_at=now,
    )

    replay = aggregate.replay_projection(
        projection.projection_id,
        at=now + timedelta(seconds=180),
    )

    assert replay["source_truth"]["source_state_hash"] == projection.source_state_hash
    assert replay["projection_inputs"] == projection.projection_inputs
    assert replay["confidence_calculations"]["confidence_score"] == projection.confidence_score
    assert replay["expiration_state"]["is_expired"] is True


def test_truth_projection_separation_is_preserved() -> None:
    aggregate = _make_aggregate()
    now = datetime(2026, 5, 29, 20, 20, 0, tzinfo=timezone.utc)
    original_current = deepcopy(aggregate.digital_twin.current_state)
    original_historical = deepcopy(aggregate.digital_twin.historical_state)

    aggregate.create_projection(
        projection_type=ProjectionType.SCHEDULE_PROJECTION,
        projection_inputs={"window": "next_7_days"},
        ttl_seconds=240,
        trace_id="trace-separation",
        generated_at=now,
    )

    assert aggregate.digital_twin.current_state == original_current
    assert aggregate.digital_twin.historical_state == original_historical


def test_projection_audit_generation() -> None:
    aggregate = _make_aggregate()
    now = datetime(2026, 5, 29, 20, 25, 0, tzinfo=timezone.utc)

    projection = aggregate.create_projection(
        projection_type=ProjectionType.MAINTENANCE_PROJECTION,
        projection_inputs={"vehicle_id": "vehicle-1", "service_cycle_days": 90},
        ttl_seconds=600,
        trace_id="trace-audit",
        generated_at=now,
    )

    audits = [item for item in aggregate.digital_twin.projection_audit if item.projection_id == projection.projection_id]
    assert len(audits) == 1
    assert audits[0].source_state_hash == projection.source_state_hash
    assert audits[0].trace_id == "trace-audit"
    assert bool(audits[0].audit_hash)
