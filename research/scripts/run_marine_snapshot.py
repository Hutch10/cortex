from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hub.app import _marine_snapshot_dir, _query_reef_alerts, _summarize_reef_alerts
from nerves.marine_data_ingestion.main import DATASET_CONFIGS, current_timestamp, ingest_dataset


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run marine ingest and capture a reef-alert snapshot.")
    parser.add_argument(
        "--dataset",
        action="append",
        choices=sorted(DATASET_CONFIGS),
        help="Dataset to ingest. Repeat for multiple datasets. Defaults to sst then buoy.",
    )
    parser.add_argument(
        "--input-file",
        action="append",
        default=[],
        help="Optional local fixture override in dataset=path form, for example --input-file sst=tests/fixtures/noaa_sst_sample.csv",
    )
    parser.add_argument("--minimum-priority", default="", choices=["", "attention", "priority"])
    parser.add_argument("--limit", type=int, default=25)
    return parser.parse_args(argv)


def _parse_input_files(raw_items: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for item in raw_items:
        if "=" not in item:
            raise ValueError("Each --input-file must use dataset=path form.")
        dataset, path = item.split("=", 1)
        dataset = dataset.strip()
        path = path.strip()
        if dataset not in DATASET_CONFIGS:
            raise ValueError(f"Unsupported dataset '{dataset}' in --input-file.")
        mapping[dataset] = path
    return mapping


def build_snapshot(
    *,
    datasets: list[str],
    minimum_priority: str = "",
    limit: int = 25,
    input_files: dict[str, str] | None = None,
) -> dict:
    datasets = datasets or ["sst", "buoy"]
    input_files = input_files or {}
    ingest_results = []
    for dataset in datasets:
        payload_override = None
        if dataset in input_files:
            payload_override = Path(input_files[dataset]).read_text(encoding="utf-8")
        ingest_results.append(ingest_dataset(dataset, payload_override=payload_override))

    reef_alerts = _query_reef_alerts(limit=limit, minimum_priority=minimum_priority)
    snapshot = {
        "generated_at": current_timestamp(),
        "datasets_run": datasets,
        "rows_ingested": {
            result["dataset"]: result["rows_ingested"]
            for result in ingest_results
        },
        "ingest_results": ingest_results,
        "reef_alert_summary": _summarize_reef_alerts(reef_alerts),
        "top_reef_alerts": reef_alerts[: max(1, min(limit, 50))],
        "minimum_priority": minimum_priority or None,
        "limit": max(1, min(limit, 250)),
        "note": "Deterministic monitoring summary based on marine ingest plus reef-alert prioritization. Not an ecological diagnosis.",
    }
    return snapshot


def load_previous_snapshot() -> tuple[dict | None, Path | None]:
    snapshot_dir = _marine_snapshot_dir()
    latest_path = snapshot_dir / "latest.json"
    if not latest_path.exists():
        return None, None
    return json.loads(latest_path.read_text(encoding="utf-8")), latest_path


def derive_alert_event(
    *,
    snapshot: dict,
    snapshot_path: Path,
    previous_snapshot: dict | None = None,
    previous_snapshot_path: Path | None = None,
) -> dict | None:
    current_priority_count = int(snapshot.get("reef_alert_summary", {}).get("priority", 0))
    previous_priority_count = int((previous_snapshot or {}).get("reef_alert_summary", {}).get("priority", 0))
    current_attention_count = int(snapshot.get("reef_alert_summary", {}).get("attention", 0))
    previous_attention_count = int((previous_snapshot or {}).get("reef_alert_summary", {}).get("attention", 0))

    current_priority_ids = {
        row.get("station_id")
        for row in snapshot.get("top_reef_alerts", [])
        if row.get("priority_status") == "priority" and row.get("station_id")
    }
    previous_priority_ids = {
        row.get("station_id")
        for row in (previous_snapshot or {}).get("top_reef_alerts", [])
        if row.get("priority_status") == "priority" and row.get("station_id")
    }
    new_priority_station_ids = sorted(current_priority_ids - previous_priority_ids)

    priority_increased = current_priority_count > previous_priority_count
    attention_increased = current_attention_count > previous_attention_count
    if not priority_increased and not new_priority_station_ids and not attention_increased:
        return None

    reasons = []
    if priority_increased:
        reasons.append("priority_count_increased")
    if new_priority_station_ids:
        reasons.append("new_priority_station_ids")
    if attention_increased:
        reasons.append("attention_count_increased")

    return {
        "generated_at": snapshot["generated_at"],
        "snapshot_path": str(snapshot_path),
        "previous_snapshot_path": str(previous_snapshot_path) if previous_snapshot_path else None,
        "priority_count": current_priority_count,
        "previous_priority_count": previous_priority_count,
        "attention_count": current_attention_count,
        "previous_attention_count": previous_attention_count,
        "priority_increased": priority_increased,
        "attention_increased": attention_increased,
        "new_priority_station_ids": new_priority_station_ids,
        "notification_reason": ", ".join(reasons),
    }


def write_alert_event(event: dict) -> Path:
    snapshot_dir = _marine_snapshot_dir()
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    latest_event_path = snapshot_dir / "latest_alert_event.json"
    latest_event_path.write_text(json.dumps(event, indent=2), encoding="utf-8")
    return latest_event_path


def write_snapshot(snapshot: dict) -> Path:
    snapshot_dir = _marine_snapshot_dir()
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    timestamp_token = snapshot["generated_at"].replace(":", "").replace("-", "").replace(".", "")
    snapshot_path = snapshot_dir / f"marine_snapshot_{timestamp_token}.json"
    latest_path = snapshot_dir / "latest.json"
    payload = json.dumps(snapshot, indent=2)
    snapshot_path.write_text(payload, encoding="utf-8")
    latest_path.write_text(payload, encoding="utf-8")
    return snapshot_path


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    input_files = _parse_input_files(args.input_file)
    datasets = args.dataset or ["sst", "buoy"]
    snapshot = build_snapshot(
        datasets=datasets,
        minimum_priority=args.minimum_priority,
        limit=args.limit,
        input_files=input_files,
    )
    previous_snapshot, previous_snapshot_path = load_previous_snapshot()
    snapshot_path = write_snapshot(snapshot)
    alert_event = derive_alert_event(
        snapshot=snapshot,
        snapshot_path=snapshot_path,
        previous_snapshot=previous_snapshot,
        previous_snapshot_path=previous_snapshot_path,
    )
    latest_event_path = None
    if alert_event is not None:
        latest_event_path = write_alert_event(alert_event)
        print(
            f"[marine-alert-event] {alert_event['notification_reason']} "
            f"priority={alert_event['priority_count']} new={len(alert_event['new_priority_station_ids'])}",
            file=sys.stderr,
        )
    print(
        json.dumps(
            {
                "ok": True,
                "snapshot_path": str(snapshot_path),
                "latest_path": str(snapshot_path.parent / "latest.json"),
                "latest_alert_event_path": str(latest_event_path) if latest_event_path else None,
                "snapshot": snapshot,
                "alert_event": alert_event,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
