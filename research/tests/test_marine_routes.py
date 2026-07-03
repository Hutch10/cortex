from __future__ import annotations

import json
import sqlite3
import unittest
import warnings
from pathlib import Path
import uuid

from hub.app import app, _derive_reef_stress_fields, _build_reef_context, _derive_reef_alerts, _load_reef_reference
from hub.sqlite_utils import open_sqlite


SCHEMA_SQL = [
    """
    CREATE TABLE marine_observations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        dataset_name TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        latitude REAL NOT NULL,
        longitude REAL NOT NULL,
        metric_name TEXT NOT NULL,
        metric_value REAL NOT NULL,
        source TEXT NOT NULL,
        station_id TEXT NOT NULL DEFAULT '',
        baseline REAL,
        deviation REAL,
        anomaly_status TEXT NOT NULL DEFAULT 'normal',
        ingested_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE telemetry (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        event TEXT NOT NULL,
        payload TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE marine_investigations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        scope_type TEXT NOT NULL,
        dataset TEXT,
        station_id TEXT,
        limit_value INTEGER NOT NULL,
        path TEXT NOT NULL,
        query_string TEXT NOT NULL
    )
    """,
]


class MarineRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db_path = Path(__file__).parent / f"marine-routes-{uuid.uuid4().hex}.sqlite"
        self.reef_path = Path(__file__).parent / f"reef-routes-{uuid.uuid4().hex}.json"
        self.snapshot_dir = Path(__file__).parent / f"marine-snapshots-{uuid.uuid4().hex}"
        self.original_testing = app.config.get("TESTING")
        self.original_db_path = app.config.get("MARINE_DB_PATH")
        self.original_reef_path = app.config.get("REEF_REFERENCE_PATH")
        self.original_snapshot_dir = app.config.get("MARINE_SNAPSHOT_DIR")
        with open_sqlite(self.db_path) as conn:
            for statement in SCHEMA_SQL:
                conn.execute(statement)
            conn.commit()
        self.reef_path.write_text(
            json.dumps([
                {
                    "reef_id": "reef-test-near-46002",
                    "reef_name": "Test Reef Near 46002",
                    "latitude": 42.7,
                    "longitude": -130.4,
                    "region": "Test Pacific",
                }
            ]),
            encoding="utf-8",
        )

        app.config["TESTING"] = True
        app.config["MARINE_DB_PATH"] = str(self.db_path)
        app.config["REEF_REFERENCE_PATH"] = str(self.reef_path)
        app.config["MARINE_SNAPSHOT_DIR"] = str(self.snapshot_dir)
        self.client = app.test_client()

    def tearDown(self) -> None:
        app.config["TESTING"] = self.original_testing
        app.config["MARINE_DB_PATH"] = self.original_db_path
        app.config["REEF_REFERENCE_PATH"] = self.original_reef_path
        app.config["MARINE_SNAPSHOT_DIR"] = self.original_snapshot_dir
        if self.db_path.exists():
            try:
                self.db_path.unlink()
            except PermissionError as exc:
                warnings.warn(
                    f"Could not delete test DB {self.db_path}: {exc}",
                    ResourceWarning,
                    stacklevel=2,
                )
        if self.reef_path.exists():
            try:
                self.reef_path.unlink()
            except PermissionError as exc:
                warnings.warn(
                    f"Could not delete test reef file {self.reef_path}: {exc}",
                    ResourceWarning,
                    stacklevel=2,
                )
        if self.snapshot_dir.exists():
            for item in self.snapshot_dir.glob("*"):
                try:
                    item.unlink()
                except PermissionError as exc:
                    warnings.warn(
                        f"Could not delete test snapshot file {item}: {exc}",
                        ResourceWarning,
                        stacklevel=2,
                    )
            try:
                self.snapshot_dir.rmdir()
            except OSError as exc:
                warnings.warn(
                    f"Could not delete test snapshot dir {self.snapshot_dir}: {exc}",
                    ResourceWarning,
                    stacklevel=2,
                )

    def seed_sample_data(self) -> None:
        with open_sqlite(self.db_path) as conn:
            conn.executemany(
                """
                INSERT INTO marine_observations (
                    dataset_name, timestamp, latitude, longitude, metric_name,
                    metric_value, source, station_id, baseline, deviation,
                    anomaly_status, ingested_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        "noaa_erddap_sst",
                        "2022-01-01T05:00:00Z",
                        42.662,
                        -130.507,
                        "sea_surface_temperature",
                        10.7,
                        "NOAA ERDDAP",
                        "46002",
                        9.9,
                        0.8,
                        "watch",
                        "2026-03-14T00:00:00.000Z",
                    ),
                    (
                        "noaa_erddap_sst",
                        "2022-01-01T05:20:00Z",
                        42.662,
                        -130.507,
                        "sea_surface_temperature",
                        12.2,
                        "NOAA ERDDAP",
                        "46002",
                        9.9,
                        2.3,
                        "anomaly",
                        "2026-03-14T00:02:00.000Z",
                    ),
                    (
                        "noaa_erddap_buoy_observations",
                        "2022-01-01T05:10:00Z",
                        42.662,
                        -130.507,
                        "wind_speed",
                        18.2,
                        "NOAA ERDDAP",
                        "46002",
                        10.0,
                        8.2,
                        "anomaly",
                        "2026-03-14T00:01:00.000Z",
                    ),
                ],
            )
            conn.execute(
                "INSERT INTO telemetry (timestamp, event, payload) VALUES (?, ?, ?)",
                (
                    "2026-03-14T21:25:30.479Z",
                    "dataset_ingest",
                    json.dumps({"dataset": "sst", "rows_ingested": 343, "timestamp": "2026-03-14T21:25:30.479Z"}),
                ),
            )
            conn.commit()

    def write_snapshot_fixture(self) -> None:
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        (self.snapshot_dir / "latest.json").write_text(
            json.dumps(
                {
                    "generated_at": "2026-03-15T02:59:34.032Z",
                    "datasets_run": ["sst"],
                    "reef_alert_summary": {
                        "near_reef_total": 1,
                        "attention": 0,
                        "priority": 1,
                    },
                    "top_reef_alerts": [],
                    "limit": 5,
                    "note": "Deterministic monitoring summary based on marine ingest plus reef-alert prioritization. Not an ecological diagnosis.",
                }
            ),
            encoding="utf-8",
        )

    def write_alert_event_fixture(self) -> None:
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        (self.snapshot_dir / "latest_alert_event.json").write_text(
            json.dumps(
                {
                    "generated_at": "2026-03-15T03:05:00.000Z",
                    "snapshot_path": str(self.snapshot_dir / "marine_snapshot_20260315T030500000Z.json"),
                    "previous_snapshot_path": str(self.snapshot_dir / "latest.json"),
                    "priority_count": 1,
                    "previous_priority_count": 0,
                    "attention_count": 0,
                    "previous_attention_count": 0,
                    "priority_increased": True,
                    "attention_increased": False,
                    "new_priority_station_ids": ["46002"],
                    "notification_reason": "priority_count_increased, new_priority_station_ids",
                }
            ),
            encoding="utf-8",
        )

    def test_api_marine_observations_returns_rows(self) -> None:
        self.seed_sample_data()
        response = self.client.get("/api/marine/observations")
        self.assertEqual(200, response.status_code)
        payload = response.get_json()
        self.assertEqual(3, len(payload))
        self.assertEqual("46002", payload[0]["station_id"])

    def test_api_marine_observations_filters_by_dataset(self) -> None:
        self.seed_sample_data()
        response = self.client.get("/api/marine/observations?dataset=sst")
        self.assertEqual(200, response.status_code)
        payload = response.get_json()
        self.assertEqual(2, len(payload))
        self.assertEqual("noaa_erddap_sst", payload[0]["dataset_name"])

    def test_api_marine_telemetry_returns_ingest_events(self) -> None:
        self.seed_sample_data()
        response = self.client.get("/api/marine/telemetry")
        self.assertEqual(200, response.status_code)
        payload = response.get_json()
        self.assertEqual("dataset_ingest", payload[0]["event"])
        self.assertEqual("sst", payload[0]["payload"]["dataset"])

    def test_marine_page_renders_sample_data(self) -> None:
        self.seed_sample_data()
        response = self.client.get("/marine")
        self.assertEqual(200, response.status_code)
        html = response.get_data(as_text=True)
        self.assertIn("Marine Workspace", html)
        self.assertIn("noaa_erddap_sst", html)
        self.assertIn("46002", html)
        self.assertIn("watch", html)
        self.assertIn("Anomaly Summary In Current Scope", html)
        self.assertIn(">3</strong>", html)
        self.assertIn(">1</strong>", html)

    def test_marine_page_empty_state(self) -> None:
        response = self.client.get("/marine")
        self.assertEqual(200, response.status_code)
        html = response.get_data(as_text=True)
        self.assertIn("No marine observations found", html)
        self.assertIn("No marine ingest telemetry found yet", html)
        self.assertIn("No anomaly summary is available", html)
        self.assertIn("No snapshot available yet", html)
        self.assertIn("No monitoring change event is available yet", html)

    def test_api_marine_map_points_returns_map_ready_rows(self) -> None:
        self.seed_sample_data()
        response = self.client.get("/api/marine/map-points?limit=2")
        self.assertEqual(200, response.status_code)
        payload = response.get_json()
        self.assertEqual(2, len(payload))
        self.assertIn("latitude", payload[0])
        self.assertIn("longitude", payload[0])
        self.assertIn("anomaly_status", payload[0])

    def test_api_marine_map_points_filters_by_dataset(self) -> None:
        self.seed_sample_data()
        response = self.client.get("/api/marine/map-points?dataset=buoy")
        self.assertEqual(200, response.status_code)
        payload = response.get_json()
        self.assertEqual(1, len(payload))
        self.assertEqual("noaa_erddap_buoy_observations", payload[0]["dataset_name"])

    def test_ocean_map_route_renders(self) -> None:
        response = self.client.get("/ocean-map")
        self.assertEqual(200, response.status_code)
        html = response.get_data(as_text=True)
        self.assertIn("Ocean Map", html)
        self.assertIn("/api/marine/map-points", html)

    def test_api_marine_station_series_requires_station_id(self) -> None:
        response = self.client.get("/api/marine/station-series")
        self.assertEqual(400, response.status_code)

    def test_api_marine_station_series_orders_oldest_to_newest(self) -> None:
        self.seed_sample_data()
        response = self.client.get("/api/marine/station-series?station_id=46002")
        self.assertEqual(200, response.status_code)
        payload = response.get_json()
        self.assertEqual(
            ["2022-01-01T05:00:00Z", "2022-01-01T05:10:00Z", "2022-01-01T05:20:00Z"],
            [row["timestamp"] for row in payload],
        )

    def test_marine_station_page_renders_sample_data(self) -> None:
        self.seed_sample_data()
        response = self.client.get("/marine/station/46002")
        self.assertEqual(200, response.status_code)
        html = response.get_data(as_text=True)
        self.assertIn("Station 46002", html)
        self.assertIn("Station Timeline", html)
        self.assertIn("sea_surface_temperature", html)
        self.assertIn("wind_speed", html)

    def test_marine_station_page_empty_state(self) -> None:
        response = self.client.get("/marine/station/99999")
        self.assertEqual(200, response.status_code)
        html = response.get_data(as_text=True)
        self.assertIn("No marine observations are available for station 99999", html)

    def test_api_marine_export_returns_bundle_shape(self) -> None:
        self.seed_sample_data()
        response = self.client.get("/api/marine/export")
        self.assertEqual(200, response.status_code)
        payload = response.get_json()
        self.assertIn("meta", payload)
        self.assertIn("telemetry", payload)
        self.assertIn("summary", payload)
        self.assertIn("observations", payload)
        self.assertIn("map_points", payload)
        self.assertIn("station_series", payload)

    def test_api_marine_export_respects_dataset_filter(self) -> None:
        self.seed_sample_data()
        response = self.client.get("/api/marine/export?dataset=sst")
        self.assertEqual(200, response.status_code)
        payload = response.get_json()
        self.assertEqual(2, len(payload["observations"]))
        self.assertEqual("noaa_erddap_sst", payload["observations"][0]["dataset_name"])

    def test_api_marine_export_includes_station_series_only_when_station_provided(self) -> None:
        self.seed_sample_data()
        base_response = self.client.get("/api/marine/export")
        station_response = self.client.get("/api/marine/export?station_id=46002")
        self.assertEqual([], base_response.get_json()["station_series"])
        self.assertEqual(3, len(station_response.get_json()["station_series"]))

    def test_api_marine_export_empty_scope_is_safe(self) -> None:
        response = self.client.get("/api/marine/export?dataset=sst&station_id=99999")
        self.assertEqual(200, response.status_code)
        payload = response.get_json()
        self.assertEqual(0, payload["summary"]["total"])
        self.assertEqual([], payload["observations"])
        self.assertEqual([], payload["map_points"])

    def test_export_links_render_on_marine_pages(self) -> None:
        response = self.client.get("/marine")
        self.assertEqual(200, response.status_code)
        html = response.get_data(as_text=True)
        self.assertIn("/api/marine/export", html)

        station_response = self.client.get("/marine/station/46002")
        self.assertEqual(200, station_response.status_code)
        station_html = station_response.get_data(as_text=True)
        self.assertIn("/api/marine/export", station_html)

    def test_manifest_save_list_and_lookup(self) -> None:
        create_response = self.client.post(
            "/api/marine/investigations",
            json={
                "name": "North Pacific SST",
                "scope_type": "marine",
                "dataset": "sst",
                "station_id": "",
                "limit": 25,
                "path": "/marine",
                "query_string": "dataset=sst&limit=25",
            },
        )
        self.assertEqual(201, create_response.status_code)
        manifest = create_response.get_json()
        manifest_id = manifest["id"]

        list_response = self.client.get("/api/marine/investigations")
        self.assertEqual(200, list_response.status_code)
        manifests = list_response.get_json()
        self.assertEqual(manifest_id, manifests[0]["id"])

        detail_response = self.client.get(f"/api/marine/investigations/{manifest_id}")
        self.assertEqual(200, detail_response.status_code)
        detail = detail_response.get_json()
        self.assertEqual("/marine?dataset=sst&limit=25", detail["open_url"])

    def test_manifest_lookup_missing_id_is_safe(self) -> None:
        response = self.client.get("/api/marine/investigations/99999")
        self.assertEqual(404, response.status_code)

    def test_saved_manifest_open_redirects(self) -> None:
        create_response = self.client.post(
            "/api/marine/investigations",
            json={
                "name": "Station Scope",
                "scope_type": "station",
                "dataset": "",
                "station_id": "46002",
                "limit": 50,
                "path": "/marine/station/46002",
                "query_string": "limit=50",
            },
        )
        manifest_id = create_response.get_json()["id"]
        open_response = self.client.get(f"/marine/investigations/{manifest_id}/open")
        self.assertEqual(302, open_response.status_code)
        self.assertIn("/marine/station/46002?limit=50", open_response.location)

    def test_saved_manifest_controls_render(self) -> None:
        response = self.client.get("/marine")
        self.assertEqual(200, response.status_code)
        html = response.get_data(as_text=True)
        self.assertIn("Save Investigation", html)

    def test_reef_stress_rule_logic_for_sst(self) -> None:
        derived = _derive_reef_stress_fields({
            "dataset_name": "noaa_erddap_sst",
            "metric_name": "sea_surface_temperature",
            "metric_value": 30.2,
            "baseline": 27.8,
            "deviation": 2.4,
        })
        self.assertEqual("stress", derived["reef_stress_status"])
        self.assertEqual("sst_deviation_ge_2.0C", derived["reef_stress_reason"]["threshold_exceeded"])

    def test_reef_stress_safe_when_baseline_missing(self) -> None:
        derived = _derive_reef_stress_fields({
            "dataset_name": "noaa_erddap_sst",
            "metric_name": "sea_surface_temperature",
            "metric_value": 10.7,
            "baseline": None,
            "deviation": None,
        })
        self.assertEqual("normal", derived["reef_stress_status"])
        self.assertIsNone(derived["reef_stress_reason"]["threshold_exceeded"])

    def test_reef_stress_renders_on_marine_page(self) -> None:
        self.seed_sample_data()
        response = self.client.get("/marine")
        html = response.get_data(as_text=True)
        self.assertIn("Reef Stress", html)

    def test_reef_stress_renders_on_station_page(self) -> None:
        self.seed_sample_data()
        response = self.client.get("/marine/station/46002")
        html = response.get_data(as_text=True)
        self.assertIn("reef stress", html.lower())

    def test_export_includes_reef_stress_fields_for_sst_scope(self) -> None:
        self.seed_sample_data()
        response = self.client.get("/api/marine/export?dataset=sst")
        payload = response.get_json()
        self.assertIn("reef_stress_summary", payload)
        self.assertIn("reef_stress_status", payload["observations"][0])
        self.assertIn("reef_stress_reason", payload["observations"][0])

    def test_api_marine_station_context_returns_one_row_per_station(self) -> None:
        self.seed_sample_data()
        response = self.client.get("/api/marine/station-context")
        self.assertEqual(200, response.status_code)
        payload = response.get_json()
        self.assertEqual(1, len(payload))
        self.assertEqual("46002", payload[0]["station_id"])

    def test_station_context_uses_latest_reef_stress_and_anomaly(self) -> None:
        self.seed_sample_data()
        response = self.client.get("/api/marine/station-context?station_id=46002")
        payload = response.get_json()
        self.assertEqual("stress", payload[0]["latest_reef_stress_status"])
        self.assertEqual("anomaly", payload[0]["latest_anomaly_status"])

    def test_ocean_map_renders_station_context_text(self) -> None:
        response = self.client.get("/ocean-map")
        html = response.get_data(as_text=True)
        self.assertIn("Station Context Summary", html)
        self.assertIn("/api/marine/station-context", html)

    def test_ocean_map_renders_reef_context_text(self) -> None:
        response = self.client.get("/ocean-map")
        html = response.get_data(as_text=True)
        self.assertIn("Reef Context Summary", html)
        self.assertIn("/api/marine/reef-context", html)

    def test_export_includes_station_context(self) -> None:
        self.seed_sample_data()
        response = self.client.get("/api/marine/export")
        payload = response.get_json()
        self.assertIn("station_context", payload)
        self.assertIn("station_context_summary", payload)

    def test_reef_reference_loading(self) -> None:
        reefs = _load_reef_reference()
        self.assertGreaterEqual(len(reefs), 1)
        self.assertIn("reef_id", reefs[0])

    def test_reef_context_proximity_logic(self) -> None:
        reef_context = _build_reef_context(
            [
                {
                    "station_id": "46002",
                    "latitude": 42.662,
                    "longitude": -130.507,
                    "latest_timestamp": "2022-01-01T05:20:00Z",
                    "latest_anomaly_status": "anomaly",
                    "latest_reef_stress_status": "stress",
                    "datasets_present": ["noaa_erddap_sst"],
                }
            ],
            _load_reef_reference(),
            threshold_km=1000.0,
        )
        self.assertEqual("near_reef", reef_context[0]["reef_proximity_status"])
        self.assertIsNotNone(reef_context[0]["nearest_reef_name"])

    def test_api_marine_reef_context(self) -> None:
        self.seed_sample_data()
        response = self.client.get("/api/marine/reef-context")
        self.assertEqual(200, response.status_code)
        payload = response.get_json()
        self.assertEqual(1, len(payload))
        self.assertIn("reef_proximity_status", payload[0])

    def test_export_includes_reef_context(self) -> None:
        self.seed_sample_data()
        response = self.client.get("/api/marine/export")
        payload = response.get_json()
        self.assertIn("reef_context", payload)
        self.assertIn("reef_context_summary", payload)

    def test_reef_alert_classification_logic(self) -> None:
        alerts = _derive_reef_alerts([
            {
                "station_id": "46002",
                "latitude": 42.662,
                "longitude": -130.507,
                "latest_timestamp": "2022-01-01T05:20:00Z",
                "latest_anomaly_status": "anomaly",
                "latest_reef_stress_status": "stress",
                "nearest_reef_id": "reef-1",
                "nearest_reef_name": "Test Reef",
                "nearest_reef_distance_km": 12.4,
                "reef_proximity_status": "near_reef",
            }
        ])
        self.assertEqual("priority", alerts[0]["priority_status"])
        self.assertEqual("near_reef + reef_stress=stress", alerts[0]["priority_reason"])

    def test_api_marine_reef_alerts(self) -> None:
        self.seed_sample_data()
        response = self.client.get("/api/marine/reef-alerts")
        self.assertEqual(200, response.status_code)
        payload = response.get_json()
        self.assertEqual(1, len(payload))
        self.assertIn("priority_status", payload[0])

    def test_reef_alert_minimum_priority_filter(self) -> None:
        self.seed_sample_data()
        response = self.client.get("/api/marine/reef-alerts?minimum_priority=priority")
        self.assertEqual(200, response.status_code)
        payload = response.get_json()
        self.assertEqual(1, len(payload))
        self.assertEqual("priority", payload[0]["priority_status"])

    def test_export_includes_reef_alerts(self) -> None:
        self.seed_sample_data()
        response = self.client.get("/api/marine/export")
        payload = response.get_json()
        self.assertIn("reef_alerts", payload)
        self.assertIn("reef_alert_summary", payload)

    def test_priority_summary_renders_text(self) -> None:
        response = self.client.get("/marine")
        html = response.get_data(as_text=True)
        self.assertIn("Reef Alert Priority Summary", html)

    def test_marine_page_renders_latest_snapshot_summary(self) -> None:
        self.write_snapshot_fixture()
        response = self.client.get("/marine")
        self.assertEqual(200, response.status_code)
        html = response.get_data(as_text=True)
        self.assertIn("Latest Monitoring Snapshot", html)
        self.assertIn("2026-03-15T02:59:34.032Z", html)
        self.assertIn("/marine/snapshots", html)

    def test_marine_page_renders_latest_alert_event(self) -> None:
        self.write_alert_event_fixture()
        response = self.client.get("/marine")
        self.assertEqual(200, response.status_code)
        html = response.get_data(as_text=True)
        self.assertIn("Latest Monitoring Change Event", html)
        self.assertIn("2026-03-15T03:05:00.000Z", html)
        self.assertIn("New Priority Stations", html)

    def test_marine_alerts_page_renders(self) -> None:
        self.seed_sample_data()
        response = self.client.get("/marine/alerts")
        self.assertEqual(200, response.status_code)
        html = response.get_data(as_text=True)
        self.assertIn("Marine Alerts", html)
        self.assertIn("Alert Summary", html)
        self.assertIn("Export Alerts JSON", html)
        self.assertIn("No snapshot available yet", html)
        self.assertIn("No monitoring change event is available yet", html)

    def test_marine_alerts_page_renders_latest_snapshot_summary(self) -> None:
        self.seed_sample_data()
        self.write_snapshot_fixture()
        response = self.client.get("/marine/alerts")
        self.assertEqual(200, response.status_code)
        html = response.get_data(as_text=True)
        self.assertIn("Latest Monitoring Snapshot", html)
        self.assertIn("2026-03-15T02:59:34.032Z", html)
        self.assertIn("/marine/snapshots", html)

    def test_marine_alerts_page_renders_latest_alert_event(self) -> None:
        self.seed_sample_data()
        self.write_alert_event_fixture()
        response = self.client.get("/marine/alerts")
        self.assertEqual(200, response.status_code)
        html = response.get_data(as_text=True)
        self.assertIn("Latest Monitoring Change Event", html)
        self.assertIn("2026-03-15T03:05:00.000Z", html)
        self.assertIn("/marine/snapshots", html)

    def test_marine_alerts_page_orders_priority_first(self) -> None:
        self.seed_sample_data()
        with open_sqlite(self.db_path) as conn:
            conn.executemany(
                """
                INSERT INTO marine_observations (
                    dataset_name, timestamp, latitude, longitude, metric_name,
                    metric_value, source, station_id, baseline, deviation,
                    anomaly_status, ingested_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        "noaa_erddap_sst",
                        "2022-01-01T05:30:00Z",
                        42.71,
                        -130.41,
                        "sea_surface_temperature",
                        11.3,
                        "NOAA ERDDAP",
                        "46003",
                        10.1,
                        1.2,
                        "watch",
                        "2026-03-14T00:03:00.000Z",
                    )
                ],
            )
            conn.commit()

        response = self.client.get("/marine/alerts")
        self.assertEqual(200, response.status_code)
        html = response.get_data(as_text=True)
        self.assertLess(html.index("46002"), html.index("46003"))

    def test_marine_alerts_page_filter_behavior(self) -> None:
        self.seed_sample_data()
        with open_sqlite(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO marine_observations (
                    dataset_name, timestamp, latitude, longitude, metric_name,
                    metric_value, source, station_id, baseline, deviation,
                    anomaly_status, ingested_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "noaa_erddap_sst",
                    "2022-01-01T05:30:00Z",
                    42.71,
                    -130.41,
                    "sea_surface_temperature",
                    11.3,
                    "NOAA ERDDAP",
                    "46003",
                    10.1,
                    1.2,
                    "watch",
                    "2026-03-14T00:03:00.000Z",
                ),
            )
            conn.commit()
        response = self.client.get("/marine/alerts?minimum_priority=priority")
        self.assertEqual(200, response.status_code)
        html = response.get_data(as_text=True)
        self.assertIn("46002", html)
        self.assertNotIn("46003", html)

    def test_marine_briefing_page_returns_200(self) -> None:
        response = self.client.get("/marine/briefing")
        self.assertEqual(200, response.status_code)

    def test_marine_briefing_renders_snapshot_and_event_text(self) -> None:
        self.seed_sample_data()
        self.write_snapshot_fixture()
        self.write_alert_event_fixture()
        response = self.client.get("/marine/briefing")
        self.assertEqual(200, response.status_code)
        html = response.get_data(as_text=True)
        self.assertIn("Marine Briefing", html)
        self.assertIn("Latest Monitoring Snapshot", html)
        self.assertIn("Latest Monitoring Change Event", html)
        self.assertIn("2026-03-15T02:59:34.032Z", html)
        self.assertIn("2026-03-15T03:05:00.000Z", html)

    def test_marine_briefing_renders_priority_station_list(self) -> None:
        self.seed_sample_data()
        response = self.client.get("/marine/briefing")
        self.assertEqual(200, response.status_code)
        html = response.get_data(as_text=True)
        self.assertIn("Highest-Priority Reef-Alert Stations", html)
        self.assertIn("46002", html)
        self.assertIn("/marine/station/46002", html)

    def test_marine_briefing_empty_state_is_safe(self) -> None:
        response = self.client.get("/marine/briefing")
        self.assertEqual(200, response.status_code)
        html = response.get_data(as_text=True)
        self.assertIn("No monitoring snapshot is available yet", html)
        self.assertIn("No monitoring change event is available yet", html)
        self.assertIn("No current priority reef-alert stations are available for briefing", html)


if __name__ == "__main__":
    unittest.main()
