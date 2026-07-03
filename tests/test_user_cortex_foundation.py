from backend.models.user_cortex import (
    AssetState,
    LifeDomainName,
    RootIdentity,
    UserCortexAggregate,
)


def make_aggregate() -> UserCortexAggregate:
    return UserCortexAggregate(root_identity=RootIdentity(continuity_id="user-123"))


def test_identity_continuity_persists_across_reconstruction() -> None:
    aggregate = make_aggregate()
    aggregate.create_domain(LifeDomainName.PERSONAL, owner_id="owner-a")
    aggregate.create_goal("goal-1", "Read 12 books", "books_read", 12)
    aggregate.track_goal_progress("goal-1", 12)

    rebuilt = UserCortexAggregate.rehydrate(aggregate.root_identity, aggregate.uncommitted_events)

    assert rebuilt.root_identity.continuity_id == "user-123"
    assert rebuilt.goals["goal-1"].completed is True


def test_asset_lifecycle_and_continuity_history() -> None:
    aggregate = make_aggregate()
    aggregate.create_domain(LifeDomainName.VEHICLES, owner_id="owner-a")
    aggregate.register_asset("asset-car-1", LifeDomainName.VEHICLES, owner_id="owner-a")
    aggregate.transfer_asset("asset-car-1", new_owner_id="owner-a")
    aggregate.retire_asset("asset-car-1", reason="decommissioned")

    asset = aggregate.assets["asset-car-1"]

    assert asset.continuity_id == "asset-car-1"
    assert asset.state == AssetState.RETIRED
    assert [record.state for record in asset.history] == [
        AssetState.ACTIVE,
        AssetState.TRANSFERRED,
        AssetState.RETIRED,
    ]


def test_domain_isolation_ownership_and_querying() -> None:
    aggregate = make_aggregate()
    aggregate.create_domain(LifeDomainName.PERSONAL, owner_id="owner-a")
    aggregate.create_domain(LifeDomainName.BUSINESS, owner_id="owner-b")

    assert aggregate.is_domain_owned_by(LifeDomainName.PERSONAL, owner_id="owner-a")
    assert not aggregate.is_domain_owned_by(LifeDomainName.BUSINESS, owner_id="owner-a")

    domains_for_a = aggregate.query_domains(owner_id="owner-a")

    assert len(domains_for_a) == 1
    assert domains_for_a[0].name == LifeDomainName.PERSONAL


def test_persona_switching_with_priority_conflict_resolution() -> None:
    aggregate = make_aggregate()
    aggregate.register_persona("focus", "Focus Mode", priority=100)
    aggregate.register_persona("relaxed", "Relaxed Mode", priority=10)

    assert aggregate.activate_persona("focus") is not None
    assert aggregate.activate_persona("relaxed") is None

    active = aggregate.active_persona_id
    assert active == "focus"


def test_goal_tracking_to_completion() -> None:
    aggregate = make_aggregate()
    aggregate.create_goal("goal-fitness", "Train 20 hours", "hours", 20)

    assert aggregate.track_goal_progress("goal-fitness", 5) is None
    completed = aggregate.track_goal_progress("goal-fitness", 20)

    assert completed is not None
    assert aggregate.goals["goal-fitness"].completed is True


def test_digital_twin_deterministic_reconstruction() -> None:
    aggregate = make_aggregate()
    aggregate.create_domain(LifeDomainName.RESEARCH, owner_id="owner-r")
    aggregate.register_asset("asset-notes", LifeDomainName.RESEARCH, owner_id="owner-r")
    aggregate.create_goal("goal-paper", "Draft paper", "percent", 100)
    aggregate.track_goal_progress("goal-paper", 100)

    events = aggregate.uncommitted_events
    rebuilt = UserCortexAggregate.rehydrate(aggregate.root_identity, events)

    assert rebuilt.digital_twin.current_state == aggregate.digital_twin.current_state
    assert len(rebuilt.digital_twin.historical_state) == len(events)

    projection = rebuilt.digital_twin.build_projection_stub()
    assert projection["status"] == "stub"
