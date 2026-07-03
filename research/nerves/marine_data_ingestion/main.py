"""
Marine data ingestion nerve.

Responsibilities:
- fetch selected NOAA ERDDAP datasets
- normalize rows into a shared marine_observations schema
- persist observations + telemetry into data/marine.sqlite

Example:
    python nerves/marine_data_ingestion/main.py --dataset sst
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sqlite3
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from hub.sqlite_utils import open_sqlite

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "marine.sqlite"

DEFAULT_TIMEOUT_SECONDS = 20

DATASET_CONFIGS = {
    "sst": {
        "dataset_name": "noaa_erddap_sst",
        "source": "NOAA ERDDAP",
        "endpoint": "https://erddap.aoml.noaa.gov/hdb/erddap/tabledap/moorings_2022_smd_v2.csv",
        "query": "station_id,longitude,latitude,time,WTMP&time>=2022-01-01T00:00:00Z&time<=2022-01-02T00:00:00Z&WTMP!=999.0",
        "metric_name": "sea_surface_temperature",
        "raw_field": "WTMP",
        "baseline_window": 12,
        "watch_threshold": 1.5,
        "anomaly_threshold": 3.0,
    },
    "buoy": {
        "dataset_name": "noaa_erddap_buoy_observations",
        "source": "NOAA ERDDAP",
        "endpoint": "https://erddap.aoml.noaa.gov/hdb/erddap/tabledap/moorings_2022_smd_v2.csv",
        "query": "station_id,longitude,latitude,time,WSPD&time>=2022-01-01T00:00:00Z&time<=2022-01-02T00:00:00Z&WSPD!=999.0",
        "metric_name": "wind_speed",
        "raw_field": "WSPD",
        "baseline_window": 12,
        "watch_threshold": 3.0,
        "anomaly_threshold": 6.0,
    },
}


@dataclass(frozen=True)
class NormalizedObservation:
    dataset_name: str
    timestamp: str
    latitude: float
    longitude: float
    metric_name: str
    metric_value: float
    source: str
    station_id: str
    baseline: float | None
    deviation: float | None
    anomaly_status: str

    def to_dict(self) -> dict:
        return {
            "dataset_name": self.dataset_name,
            "timestamp": self.timestamp,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "metric_name": self.metric_name,
            "metric_value": self.metric_value,
            "source": self.source,
            "station_id": self.station_id,
            "baseline": self.baseline,
            "deviation": self.deviation,
            "anomaly_status": self.anomaly_status,
        }


def current_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def ensure_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS marine_observations (
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
            ingested_at TEXT NOT NULL,
            UNIQUE(dataset_name, timestamp, latitude, longitude, metric_name, station_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS telemetry (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            event TEXT NOT NULL,
            payload TEXT NOT NULL
        )
        """
    )
    conn.commit()


def build_url(config: dict) -> str:
    return f"{config['endpoint']}?{urllib.parse.quote(config['query'], safe='?,=&!:()')}"


def fetch_dataset_text(dataset: str, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> str:
    config = DATASET_CONFIGS[dataset]
    request = urllib.request.Request(
        build_url(config),
        headers={"User-Agent": "HutchSolves-Cortex/0.1 (marine-ingestion)"},
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        return response.read().decode("utf-8", errors="replace")


def parse_csv_payload(payload: str) -> list[dict[str, str]]:
    lines = [line for line in payload.splitlines() if line.strip()]
    if len(lines) < 3:
        return []
    # ERDDAP CSV returns header row + units row; drop units for parsing.
    reader = csv.DictReader(lines[2:], fieldnames=[item.strip() for item in lines[0].split(",")])
    return [{key: (value.strip() if isinstance(value, str) else value) for key, value in row.items()} for row in reader]


def classify_anomaly(metric_value: float, baseline: float | None, watch_threshold: float, anomaly_threshold: float) -> tuple[float | None, str]:
    if baseline is None:
        return None, "normal"

    deviation = round(metric_value - baseline, 3)
    magnitude = abs(deviation)
    if magnitude >= anomaly_threshold:
        return deviation, "anomaly"
    if magnitude >= watch_threshold:
        return deviation, "watch"
    return deviation, "normal"


def lookup_baseline(
    conn: sqlite3.Connection,
    dataset_name: str,
    metric_name: str,
    station_id: str,
    window: int,
) -> float | None:
    rows = conn.execute(
        """
        SELECT metric_value
        FROM marine_observations
        WHERE dataset_name = ? AND metric_name = ? AND station_id = ?
        ORDER BY timestamp DESC, id DESC
        LIMIT ?
        """,
        (dataset_name, metric_name, station_id, window),
    ).fetchall()
    if not rows:
        return None
    values = [float(row[0]) for row in rows]
    return round(sum(values) / len(values), 3)


def normalize_row(raw_row: dict[str, str], dataset: str, conn: sqlite3.Connection) -> NormalizedObservation:
    config = DATASET_CONFIGS[dataset]
    station_id = raw_row.get("station_id", "").strip()
    metric_value = float(raw_row[config["raw_field"]])
    baseline = lookup_baseline(
        conn,
        dataset_name=config["dataset_name"],
        metric_name=config["metric_name"],
        station_id=station_id,
        window=config["baseline_window"],
    )
    deviation, anomaly_status = classify_anomaly(
        metric_value=metric_value,
        baseline=baseline,
        watch_threshold=config["watch_threshold"],
        anomaly_threshold=config["anomaly_threshold"],
    )
    return NormalizedObservation(
        dataset_name=config["dataset_name"],
        timestamp=raw_row["time"],
        latitude=float(raw_row["latitude"]),
        longitude=float(raw_row["longitude"]),
        metric_name=config["metric_name"],
        metric_value=metric_value,
        source=config["source"],
        station_id=station_id,
        baseline=baseline,
        deviation=deviation,
        anomaly_status=anomaly_status,
    )


def insert_observations(conn: sqlite3.Connection, observations: Iterable[NormalizedObservation]) -> int:
    ingested_at = current_timestamp()
    inserted = 0
    for observation in observations:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO marine_observations (
                dataset_name, timestamp, latitude, longitude, metric_name,
                metric_value, source, station_id, baseline, deviation,
                anomaly_status, ingested_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                observation.dataset_name,
                observation.timestamp,
                observation.latitude,
                observation.longitude,
                observation.metric_name,
                observation.metric_value,
                observation.source,
                observation.station_id,
                observation.baseline,
                observation.deviation,
                observation.anomaly_status,
                ingested_at,
            ),
        )
        inserted += int(cursor.rowcount > 0)
    conn.commit()
    return inserted


def emit_telemetry(conn: sqlite3.Connection, event: str, payload: dict) -> None:
    conn.execute(
        "INSERT INTO telemetry (timestamp, event, payload) VALUES (?, ?, ?)",
        (current_timestamp(), event, json.dumps(payload)),
    )
    conn.commit()


def ingest_dataset(dataset: str, payload_override: str | None = None) -> dict:
    if dataset not in DATASET_CONFIGS:
        raise ValueError(f"Unsupported dataset '{dataset}'. Expected one of: {', '.join(sorted(DATASET_CONFIGS))}")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open_sqlite(DB_PATH) as conn:
        ensure_db(conn)
        payload = payload_override if payload_override is not None else fetch_dataset_text(dataset)
        raw_rows = parse_csv_payload(payload)
        observations = [normalize_row(row, dataset, conn) for row in raw_rows]
        inserted = insert_observations(conn, observations)
        timestamp = current_timestamp()
        telemetry_payload = {
            "dataset": dataset,
            "rows_ingested": inserted,
            "timestamp": timestamp,
        }
        emit_telemetry(conn, "dataset_ingest", telemetry_payload)
        return {
            "ok": True,
            "dataset": dataset,
            "rows_received": len(raw_rows),
            "rows_ingested": inserted,
            "timestamp": timestamp,
            "sample_rows": [obs.to_dict() for obs in observations[:3]],
        }


def fetch_telemetry(limit: int = 10, event: str = "") -> list[dict]:
    if not DB_PATH.exists():
        return []
    with open_sqlite(DB_PATH) as conn:
        ensure_db(conn)
        if event:
            rows = conn.execute(
                "SELECT id, timestamp, event, payload FROM telemetry WHERE event = ? ORDER BY id DESC LIMIT ?",
                (event, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, timestamp, event, payload FROM telemetry ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
    return [
        {
            "id": row[0],
            "timestamp": row[1],
            "event": row[2],
            "payload": json.loads(row[3]),
        }
        for row in rows
    ]


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Marine data ingestion nerve")
    parser.add_argument("--dataset", choices=sorted(DATASET_CONFIGS), help="Dataset to ingest")
    parser.add_argument("--action", choices=["ingest", "fetch-telemetry"], default="ingest")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--event", default="")
    parser.add_argument("--input-file", default="", help="Optional local CSV fixture path for parsing/ingest validation")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        if args.action == "fetch-telemetry":
            print(json.dumps(fetch_telemetry(limit=args.limit, event=args.event), indent=2))
            return 0

        if not args.dataset:
            raise ValueError("--dataset is required when --action ingest is used.")

        payload_override = None
        if args.input_file:
            payload_override = Path(args.input_file).read_text(encoding="utf-8")

        print(json.dumps(ingest_dataset(args.dataset, payload_override=payload_override), indent=2))
        return 0
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
