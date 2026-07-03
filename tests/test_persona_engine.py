from copy import deepcopy
from datetime import datetime, timedelta, timezone

from backend.models.user_cortex import (
    ActionPolicyEffect,
    ContextFrameAssembler,
    ContextFrameRequest,
    LifeDomainName,
    PersonaActivationMode,
    PersonaType,
    PolicyAction,
    RootIdentity,
    TypedPermissionPolicy,
    UserCortexAggregate,
)


def _make_aggregate() -> UserCortexAggregate:
    aggregate = UserCortexAggregate(root_identity=RootIdentity(continuity_id="user-persona-1"))
    aggregate.create_domain(LifeDomainName.PERSONAL, owner_id="owner-a")
    aggregate.create_domain(LifeDomainName.BUSINESS, owner_id="owner-a")
    aggregate.create_domain(LifeDomainName.TRAVEL, owner_id="owner-a")

    aggregate.register_asset_node(
        asset_id="asset-personal-1",
        asset_type="device",
        owner_id="owner-a",
        domain_id=LifeDomainName.PERSONAL.value,
        ownership_status="OWNED",
        capabilities={"telemetry": {"state": "ok"}},
    )
    aggregate.register_asset_node(
        asset_id="asset-business-1",
        asset_type="device",
        owner_id="owner-a",
        domain_id=LifeDomainName.BUSINESS.value,
        ownership_status="OWNED",
        capabilities={"telemetry": {"state": "ok"}},
    )

    aggregate.create_goal("goal-personal", "Personal Goal", "x", 10)
    aggregate.create_goal("goal-business", "Business Goal", "x", 10)

    aggregate.memory.working.put(
        "recommendations",
        [
            {
                "recommendation_id": "rec-personal",
                "domain_id": LifeDomainName.PERSONAL.value,
                "goal_id": "goal-personal",
                "asset_id": "asset-personal-1",
                "tags": ["personal", "wellbeing"],
            },
            {
                "recommendation_id": "rec-business",
                "domain_id": LifeDomainName.BUSINESS.value,
                "goal_id": "goal-business",
                "asset_id": "asset-business-1",
                "tags": ["business", "finance"],
            },
        ],
    )

    aggregate.register_persona(
        persona_id="personal",
        label="Personal Persona",
        persona_type=PersonaType.PERSONAL,
        priority=20,
        domain_scope=(LifeDomainName.PERSONAL.value,),
        goal_scope=("goal-personal",),
        asset_scope=("asset-personal-1",),
        visibility_rules={"allowed_recommendation_tags": ["personal"]},
    )
    aggregate.register_persona(
        persona_id="business",
        label="Business Persona",
        persona_type=PersonaType.BUSINESS,
        priority=100,
        domain_scope=(LifeDomainName.BUSINESS.value,),
        goal_scope=("goal-business",),
        asset_scope=("asset-business-1",),
        visibility_rules={"allowed_recommendation_tags": ["business"]},
    )
    aggregate.register_persona(
        persona_id="traveler",
        label="Traveler Persona",
        persona_type=PersonaType.TRAVELER,
        priority=60,
        activation_rules={
            "schedule_windows": [
                {
                    "start_hour": 8,
                    "end_hour": 18,
                    "days": [0, 1, 2, 3, 4],
                }
            ]
        },
        domain_scope=(LifeDomainName.TRAVEL.value,),
    )
    aggregate.register_persona(
        persona_id="pilot",
        label="Pilot Persona",
        persona_type=PersonaType.PILOT,
        priority=60,
        domain_scope=(LifeDomainName.TRAVEL.value,),
    )
    aggregate.register_persona(
        persona_id="researcher",
        label="Researcher Persona",
        persona_type=PersonaType.RESEARCHER,
        priority=50,
        domain_scope=(LifeDomainName.BUSINESS.value,),
    )
    return aggregate


def _policies(now: datetime) -> tuple[TypedPermissionPolicy, ...]:
    return (
        TypedPermissionPolicy(
            subject="advisor-alpha",
            action=PolicyAction.READ_CONTEXT,
            resource="*",
            grant_source="test",
        ),
        TypedPermissionPolicy(
            subject="advisor-alpha",
            action=PolicyAction.READ_DOMAIN,
            resource="*",
            domain_scope=(
                LifeDomainName.PERSONAL.value,
                LifeDomainName.BUSINESS.value,
                LifeDomainName.TRAVEL.value,
            ),
            grant_source="test",
        ),
        TypedPermissionPolicy(
            subject="advisor-alpha",
            action=PolicyAction.READ_ASSET,
            resource="*",
            asset_scope=("asset-personal-1", "asset-business-1"),
            grant_source="test",
        ),
        TypedPermissionPolicy(
            subject="advisor-alpha",
            action=PolicyAction.READ_GOAL,
            resource="*",
            grant_source="test",
            expiration=now + timedelta(hours=1),
        ),
        TypedPermissionPolicy(
            subject="advisor-alpha",
            action=PolicyAction.READ_PERSONA,
            resource="*",
            persona_scope=("personal", "business", "traveler", "pilot", "researcher"),
            grant_source="test",
        ),
    )


def test_activation_and_deactivation() -> None:
    aggregate = _make_aggregate()

    activation = aggregate.activate_persona("personal", reason="user selected")
    assert activation is not None
    assert activation.activation_mode == PersonaActivationMode.MANUAL.value
    assert aggregate.active_persona_id == "personal"

    deactivation = aggregate.deactivate_persona(reason="user switched off")
    assert deactivation is not None
    assert aggregate.active_persona_id is None


def test_priority_resolution_for_competing_manual_activation() -> None:
    aggregate = _make_aggregate()

    assert aggregate.activate_persona("business", reason="first") is not None
    blocked = aggregate.activate_persona("personal", reason="lower priority challenge")

    assert blocked is None
    assert aggregate.active_persona_id == "business"


def test_context_activation_and_conflict_handling_is_deterministic() -> None:
    aggregate = _make_aggregate()

    event = aggregate.activate_persona_for_context(
        domain_scope=(LifeDomainName.BUSINESS.value, LifeDomainName.TRAVEL.value),
        goal_scope=("goal-business",),
        asset_scope=("asset-business-1",),
        reason="context demand",
    )
    assert event is not None
    assert event.activation_mode == PersonaActivationMode.CONTEXT.value
    assert aggregate.active_persona_id == "business"


def test_scheduled_activation_selects_expected_persona() -> None:
    aggregate = _make_aggregate()
    monday_noon = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

    event = aggregate.activate_persona_for_schedule(at=monday_noon, reason="schedule window")

    assert event is not None
    assert event.activation_mode == PersonaActivationMode.SCHEDULED.value
    assert aggregate.active_persona_id == "traveler"


def test_context_filtering_does_not_mutate_digital_twin_truth() -> None:
    now = datetime(2026, 5, 29, 12, 0, 0, tzinfo=timezone.utc)
    aggregate = _make_aggregate()
    aggregate.activate_persona("business", reason="manual")

    original_current = deepcopy(aggregate.digital_twin.current_state)
    original_historical = deepcopy(aggregate.digital_twin.historical_state)
    original_projection = deepcopy(aggregate.digital_twin.projected_state)

    frame = ContextFrameAssembler().generate(
        aggregate,
        ContextFrameRequest(
            user_id="user-persona-1",
            requesting_interface="advisor-alpha",
            domain_scope=(LifeDomainName.PERSONAL.value, LifeDomainName.BUSINESS.value),
            goal_scope=("goal-personal", "goal-business"),
            asset_scope=("asset-personal-1", "asset-business-1"),
            persona_scope=("business",),
            policies=_policies(now),
        ),
        generated_at=now,
    )

    user_facts = frame.context_payload["user_owned_facts"]
    visible_assets = [item["asset_id"] for item in user_facts["assets"]]
    visible_goals = [item["goal_id"] for item in user_facts["goals"]]
    visible_recs = [item["recommendation_id"] for item in user_facts["visible_recommendations"]]

    assert visible_assets == ["asset-business-1"]
    assert visible_goals == ["goal-business"]
    assert visible_recs == ["rec-business"]

    assert aggregate.digital_twin.current_state == original_current
    assert aggregate.digital_twin.historical_state == original_historical
    assert aggregate.digital_twin.projected_state == original_projection


def test_replayability_and_audit_generation() -> None:
    aggregate = _make_aggregate()
    aggregate.activate_persona_for_context(
        domain_scope=(LifeDomainName.BUSINESS.value,),
        goal_scope=("goal-business",),
        asset_scope=("asset-business-1",),
        reason="replay check",
    )

    replay = aggregate.replay_persona_audit()

    assert replay["active_persona"] == "business"
    assert replay["activation_reason"] == "replay check"
    assert len(replay["conflict_resolution_path"]) > 0
    assert replay["visible_context"]["active_persona"] == "business"
    assert len(replay["audit_artifacts"]) > 0
