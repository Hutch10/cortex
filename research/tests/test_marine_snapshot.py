from __future__ import annotations

import json
import sqlite3
import unittest
import uuid
import warnings
from pathlib import Path

from hub.app import app
from hub.sqlite_utils import open_sqlite
from nerves.marine_data_ingestion.main import ensure_db
from scripts.run_marine_snapshot import build_snapshot, derive_alert_event, write_alert_event, write_snapshot


class MarineSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).parent
        self.db_path = self.root / f"marine-snapshot-{uuid.uuid4().hex}.sqlite"
        self.snapshot_dir = self.root / f"marine-snapshot-out-{uuid.uuid4().hex}"
        self.reef_path = self.root / f"reef-snapshot-{uuid.uuid4().hex}.json"
        self.original_testing = app.config.get("TESTING")
        self.original_db_path = app.config.get("MARINE_DB_PATH")
        self.original_reef_path = app.config.get("REEF_REFERENCE_PATH")
        self.original_snapshot_dir = app.config.get("MARINE_SNAPSHOT_DIR")
        self.reef_path.write_text(
            json.dumps(
                [
                    {
                        "reef_id": "reef-test-near-46002",
                        "reef_name": "Test Reef Near 46002",
                        "latitude": 42.7,
                        "longitude": -130.4,
                        "region": "Test Pacific",
                    }
                ]
            ),
            encoding="utf-8",
        )
        with open_sqlite(self.db_path) as conn:
            ensure_db(conn)

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

    def test_snapshot_runner_generates_expected_shape(self) -> None:
        snapshot = build_snapshot(
            datasets=["sst"],
            minimum_priority="attention",
            limit=5,
            input_files={"sst": str(self.root / "fixtures" / "noaa_sst_sample.csv")},
        )
        self.assertEqual(["sst"], snapshot["datasets_run"])
        self.assertIn("reef_alert_summary", snapshot)
        self.assertIn("top_reef_alerts", snapshot)
        self.assertIn("rows_ingested", snapshot)
        self.assertEqual("attention", snapshot["minimum_priority"])

    def test_latest_snapshot_endpoint_safe_when_empty(self) -> None:
        response = self.client.get("/api/marine/snapshots/latest")
        self.assertEqual(200, response.status_code)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertIsNone(payload["snapshot"])

    def test_latest_snapshot_endpoint_returns_snapshot(self) -> None:
        snapshot = build_snapshot(
            datasets=["sst"],
            limit=5,
            input_files={"sst": str(self.root / "fixtures" / "noaa_sst_sample.csv")},
        )
        write_snapshot(snapshot)
        response = self.client.get("/api/marine/snapshots/latest")
        self.assertEqual(200, response.status_code)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(snapshot["generated_at"], payload["snapshot"]["generated_at"])
        self.assertIn("reef_alert_summary", payload["snapshot"])

    def test_snapshot_page_empty_state(self) -> None:
        response = self.client.get("/marine/snapshots")
        self.assertEqual(200, response.status_code)
        self.assertIn("No marine snapshot is available yet", response.get_data(as_text=True))

    def test_snapshot_page_renders_latest_snapshot(self) -> None:
        snapshot = build_snapshot(
            datasets=["sst"],
            limit=5,
            input_files={"sst": str(self.root / "fixtures" / "noaa_sst_sample.csv")},
        )
        write_snapshot(snapshot)
        response = self.client.get("/marine/snapshots")
        self.assertEqual(200, response.status_code)
        html = response.get_data(as_text=True)
        self.assertIn("Latest Snapshot", html)
        self.assertIn("Open Latest Snapshot JSON", html)

    def test_alert_event_generated_when_priority_count_increases(self) -> None:
        previous_snapshot = {
            "generated_at": "2026-03-15T02:00:00.000Z",
            "reef_alert_summary": {"attention": 0, "priority": 0},
            "top_reef_alerts": [],
        }
        current_snapshot = {
            "generated_at": "2026-03-15T03:00:00.000Z",
            "reef_alert_summary": {"attention": 0, "priority": 1},
            "top_reef_alerts": [{"station_id": "46002", "priority_status": "priority"}],
        }
        event = derive_alert_event(
            snapshot=current_snapshot,
            snapshot_path=self.snapshot_dir / "current.json",
            previous_snapshot=previous_snapshot,
            previous_snapshot_path=self.snapshot_dir / "latest.json",
        )
        self.assertIsNotNone(event)
        self.assertTrue(event["priority_increased"])
        self.assertEqual(["46002"], event["new_priority_station_ids"])

    def test_no_false_positive_event_when_priority_state_unchanged(self) -> None:
        previous_snapshot = {
            "generated_at": "2026-03-15T02:00:00.000Z",
            "reef_alert_summary": {"attention": 0, "priority": 1},
            "top_reef_alerts": [{"station_id": "46002", "priority_status": "priority"}],
        }
        current_snapshot = {
            "generated_at": "2026-03-15T03:00:00.000Z",
            "reef_alert_summary": {"attention": 0, "priority": 1},
            "top_reef_alerts": [{"station_id": "46002", "priority_status": "priority"}],
        }
        event = derive_alert_event(
            snapshot=current_snapshot,
            snapshot_path=self.snapshot_dir / "current.json",
            previous_snapshot=previous_snapshot,
            previous_snapshot_path=self.snapshot_dir / "latest.json",
        )
        self.assertIsNone(event)

    def test_latest_alert_event_endpoint_safe_when_empty(self) -> None:
        response = self.client.get("/api/marine/alerts/latest-event")
        self.assertEqual(200, response.status_code)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertIsNone(payload["event"])

    def test_latest_alert_event_endpoint_returns_event(self) -> None:
        event = {
            "generated_at": "2026-03-15T03:00:00.000Z",
            "snapshot_path": str(self.snapshot_dir / "current.json"),
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
        write_alert_event(event)
        response = self.client.get("/api/marine/alerts/latest-event")
        self.assertEqual(200, response.status_code)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual("2026-03-15T03:00:00.000Z", payload["event"]["generated_at"])


if __name__ == "__main__":
    unittest.main()
