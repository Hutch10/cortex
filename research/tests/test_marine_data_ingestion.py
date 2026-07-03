from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path

from nerves.marine_data_ingestion.main import (
    classify_anomaly,
    ensure_db,
    insert_observations,
    normalize_row,
    parse_csv_payload,
)


class MarineDataIngestionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        ensure_db(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def fixture_text(self, name: str) -> str:
        return (Path(__file__).parent / "fixtures" / name).read_text(encoding="utf-8")

    def test_parse_csv_payload_skips_units_row(self) -> None:
        rows = parse_csv_payload(self.fixture_text("noaa_sst_sample.csv"))
        self.assertEqual(2, len(rows))
        self.assertEqual("46002", rows[0]["station_id"])
        self.assertEqual("10.7", rows[0]["WTMP"])

    def test_normalize_row_maps_sst_schema(self) -> None:
        row = parse_csv_payload(self.fixture_text("noaa_sst_sample.csv"))[0]
        normalized = normalize_row(row, "sst", self.conn)
        self.assertEqual("noaa_erddap_sst", normalized.dataset_name)
        self.assertEqual("sea_surface_temperature", normalized.metric_name)
        self.assertEqual(10.7, normalized.metric_value)
        self.assertIsNone(normalized.baseline)
        self.assertIsNone(normalized.deviation)
        self.assertEqual("normal", normalized.anomaly_status)

    def test_sqlite_insertion_persists_normalized_records(self) -> None:
        rows = parse_csv_payload(self.fixture_text("noaa_buoy_sample.csv"))
        observations = [normalize_row(row, "buoy", self.conn) for row in rows]
        inserted = insert_observations(self.conn, observations)
        count = self.conn.execute("SELECT COUNT(*) FROM marine_observations").fetchone()[0]
        self.assertEqual(2, inserted)
        self.assertEqual(2, count)

    def test_anomaly_classification_is_threshold_based(self) -> None:
        deviation, status = classify_anomaly(14.2, 10.0, watch_threshold=1.5, anomaly_threshold=3.0)
        self.assertEqual(4.2, deviation)
        self.assertEqual("anomaly", status)

    def test_duplicate_insert_is_ignored(self) -> None:
        row = parse_csv_payload(self.fixture_text("noaa_sst_sample.csv"))[0]
        observation = normalize_row(row, "sst", self.conn)
        first = insert_observations(self.conn, [observation])
        second = insert_observations(self.conn, [observation])
        self.assertEqual(1, first)
        self.assertEqual(0, second)


if __name__ == "__main__":
    unittest.main()
