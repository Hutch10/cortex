from backend.models.user_cortex import (
    AssetState,
    ContinuityRelationType,
    LifeDomainName,
    RootIdentity,
    UserCortexAggregate,
)


def make_aggregate() -> UserCortexAggregate:
    aggregate = UserCortexAggregate(root_identity=RootIdentity(continuity_id="user-vehicle-001"))
    aggregate.create_domain(LifeDomainName.VEHICLES, owner_id="owner-alpha")
    return aggregate


def test_vehicle_registration_as_assetnode_with_capabilities() -> None:
    aggregate = make_aggregate()

    aggregate.register_vehicle(
        vehicle_id="range-rover-2020",
        make="Land Rover",
        model="Range Rover",
        year=2020,
        ownership_status="OWNED",
        owner_id="owner-alpha",
        continuity_id="luxury-line-001",
        odometer=40210,
        fuel_battery_state="Fuel 58%",
    )

    node = aggregate.asset_nodes["range-rover-2020"]

    assert node.asset_type == "vehicle"
    assert node.lifecycle_state == AssetState.ACTIVE
    assert node.continuity_id == "luxury-line-001"
    assert node.capabilities["mobility"]["make"] == "Land Rover"
    assert node.capabilities["mobility"]["model"] == "Range Rover"
    assert node.capabilities["mobility"]["year"] == 2020
    assert node.capabilities["mobility"]["odometer"] == 40210
    assert "maintenance" in node.capabilities
    assert node.metadata["make"] == "Land Rover"
    assert node.metadata["year"] == 2020


def test_vehicle_transfer_uses_generic_asset_transfer() -> None:
    aggregate = make_aggregate()
    aggregate.register_vehicle(
        vehicle_id="fleet-ev-1",
        make="Cadillac",
        model="Escalade IQ",
        year=2025,
        ownership_status="OWNED",
        owner_id="owner-alpha",
        continuity_id="fleet-premium-01",
    )

    aggregate.transfer_vehicle("fleet-ev-1", new_owner_id="owner-beta", ownership_status="LEASED")

    node = aggregate.asset_nodes["fleet-ev-1"]

    assert node.owner_id == "owner-beta"
    assert node.ownership_status == "LEASED"
    assert node.lifecycle_state == AssetState.TRANSFERRED
    assert len(node.ownership_history) == 2


def test_vehicle_retirement_excluded_from_twin_current_state() -> None:
    aggregate = make_aggregate()
    aggregate.register_vehicle(
        vehicle_id="legacy-suv",
        make="Land Rover",
        model="Range Rover",
        year=2018,
        ownership_status="OWNED",
        owner_id="owner-alpha",
        continuity_id="fleet-legacy-88",
    )

    aggregate.retire_vehicle("legacy-suv", retired_reason="End of lifecycle")

    node = aggregate.asset_nodes["legacy-suv"]

    assert node.lifecycle_state == AssetState.RETIRED
    assert "legacy-suv" not in aggregate.digital_twin.current_state["asset_nodes"]
    assert any(
        "legacy-suv" in snapshot.state["asset_nodes"]
        for snapshot in aggregate.digital_twin.historical_state
    )


def test_continuity_preservation_and_replacement_edge() -> None:
    aggregate = make_aggregate()

    aggregate.register_vehicle(
        vehicle_id="range-rover-unit",
        make="Land Rover",
        model="Range Rover",
        year=2021,
        ownership_status="OWNED",
        owner_id="owner-alpha",
        continuity_id="premium-fleet-77",
    )
    aggregate.retire_vehicle("range-rover-unit", retired_reason="Strategic replacement")

    aggregate.register_vehicle(
        vehicle_id="escalade-iq-unit",
        make="Cadillac",
        model="Escalade IQ",
        year=2026,
        ownership_status="OWNED",
        owner_id="owner-alpha",
        continuity_id="premium-fleet-77",
    )

    chain = aggregate.continuity_chain("premium-fleet-77")

    assert [node.asset_id for node in chain] == ["range-rover-unit", "escalade-iq-unit"]
    assert chain[0].lifecycle_state == AssetState.RETIRED
    assert chain[1].lifecycle_state == AssetState.ACTIVE

    edges = aggregate.continuity_graph.get("range-rover-unit", [])
    assert len(edges) == 1
    assert edges[0].target_asset_id == "escalade-iq-unit"
    assert edges[0].relation == ContinuityRelationType.REPLACEMENT


def test_goal_integration_uses_attach_asset_state_to_goal() -> None:
    aggregate = make_aggregate()
    aggregate.register_vehicle(
        vehicle_id="fleet-cost-1",
        make="Cadillac",
        model="Escalade IQ",
        year=2026,
        ownership_status="OWNED",
        owner_id="owner-alpha",
        continuity_id="cost-fleet-1",
        odometer=8000,
        fuel_battery_state="Battery 84%",
    )
    aggregate.create_goal("goal-fleet-cost", "Reduce Fleet Costs", "cost_index", 20)

    snapshot = aggregate.attach_asset_state_to_goal("goal-fleet-cost", "fleet-cost-1")

    assert snapshot["goal_id"] == "goal-fleet-cost"
    assert snapshot["asset_id"] == "fleet-cost-1"
    assert snapshot["asset_type"] == "vehicle"
    assert snapshot["lifecycle_state"] == AssetState.ACTIVE.value
    assert len(aggregate.goal_asset_state_attachments["goal-fleet-cost"]) == 1


def test_replay_reconstruction_keeps_deterministic_twin_materialization() -> None:
    aggregate = make_aggregate()
    aggregate.register_vehicle(
        vehicle_id="replay-vehicle-1",
        make="Land Rover",
        model="Range Rover",
        year=2022,
        ownership_status="OWNED",
        owner_id="owner-alpha",
        continuity_id="replay-chain-1",
        odometer=15000,
    )
    aggregate.update_vehicle("replay-vehicle-1", odometer=18500, fuel_battery_state="Fuel 40%")
    aggregate.service_vehicle("replay-vehicle-1", "Oil and filter", service_at_odometer=18600)

    events = aggregate.uncommitted_events
    rebuilt = UserCortexAggregate.rehydrate(aggregate.root_identity, events)

    assert rebuilt.asset_nodes["replay-vehicle-1"].capabilities["mobility"]["odometer"] == 18600
    assert rebuilt.digital_twin.current_state == aggregate.digital_twin.current_state
    assert len(rebuilt.digital_twin.historical_state) == len(events)


def test_generic_asset_lifecycle_replay_is_deterministic() -> None:
    aggregate = make_aggregate()
    aggregate.register_asset_node(
        asset_id="generic-asset-1",
        asset_type="generic",
        owner_id="owner-alpha",
        domain_id=LifeDomainName.VEHICLES.value,
        ownership_status="OWNED",
        continuity_id="generic-chain-1",
        capabilities={"telemetry": {"metrics": {"temp": 41}}},
        metadata={"label": "generic"},
    )
    aggregate.update_asset_node(
        asset_id="generic-asset-1",
        capabilities_patch={"telemetry": {"metrics": {"temp": 42}}},
        metadata_patch={"revision": 2},
    )
    aggregate.transfer_asset_node(
        asset_id="generic-asset-1",
        new_owner_id="owner-beta",
        ownership_status="LEASED",
    )
    aggregate.retire_asset_node("generic-asset-1", reason="retired")

    rebuilt = UserCortexAggregate.rehydrate(aggregate.root_identity, aggregate.uncommitted_events)

    assert rebuilt.asset_nodes["generic-asset-1"].owner_id == "owner-beta"
    assert rebuilt.asset_nodes["generic-asset-1"].lifecycle_state == AssetState.RETIRED
    assert rebuilt.asset_nodes["generic-asset-1"].metadata["revision"] == 2
    assert rebuilt.digital_twin.current_state == aggregate.digital_twin.current_state


def test_continuity_graph_generic_relations_without_vehicle_logic() -> None:
    aggregate = make_aggregate()
    aggregate.register_asset_node(
        asset_id="entity-a",
        asset_type="entity",
        owner_id="owner-alpha",
        domain_id=LifeDomainName.VEHICLES.value,
        ownership_status="OWNED",
        continuity_id="entity-chain-1",
    )
    aggregate.register_asset_node(
        asset_id="entity-b",
        asset_type="entity",
        owner_id="owner-alpha",
        domain_id=LifeDomainName.VEHICLES.value,
        ownership_status="OWNED",
        continuity_id="entity-chain-1",
    )

    aggregate.link_continuity("entity-a", "entity-b", ContinuityRelationType.MERGE)
    aggregate.link_continuity("entity-b", "entity-a", ContinuityRelationType.SPLIT)

    edges_a = aggregate.continuity_graph.get("entity-a", [])
    edges_b = aggregate.continuity_graph.get("entity-b", [])

    assert any(edge.relation == ContinuityRelationType.SUCCESSION for edge in edges_a)
    assert any(edge.relation == ContinuityRelationType.MERGE for edge in edges_a)
    assert any(edge.relation == ContinuityRelationType.SPLIT for edge in edges_b)
