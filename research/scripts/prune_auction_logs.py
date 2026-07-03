"""
prune_auction_logs.py — PAC Management Pruning Script v1.0

Parses PAC auction CSV files and writes normalized rows into marine.sqlite.
Mapped fields:
- Commission -> billable_pulse
- Item Type  -> engagement_category
- engagement_type is fixed to PAC_AUCTION with drift_pct=0.0
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "marine.sqlite"

_CREATE_PAC_AUCTION_LOGS = """
CREATE TABLE IF NOT EXISTS pac_auction_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_file TEXT,
    row_number INTEGER,
    auction_date TEXT NOT NULL,
    item_type TEXT NOT NULL,
    final_hammer_price REAL NOT NULL DEFAULT 0.0,
    commission REAL NOT NULL DEFAULT 0.0,
    billable_pulse REAL NOT NULL DEFAULT 0.0,
    engagement_category TEXT NOT NULL,
    engagement_type TEXT NOT NULL DEFAULT 'PAC_AUCTION',
    drift_pct REAL NOT NULL DEFAULT 0.0,
    ingested_at TEXT NOT NULL
)
"""

_CREATE_PAC_AUCTION_LOGS_IDX = """
CREATE INDEX IF NOT EXISTS idx_pac_auction_logs_date
    ON pac_auction_logs (auction_date DESC, id DESC)
"""


def _money(value: str | None) -> float:
    text = str(value or "").strip()
    if not text:
        return 0.0
    text = text.replace(",", "")
    match = re.search(r"-?\$?\s*([0-9]+(?:\.[0-9]+)?)", text)
    if not match:
        return 0.0
    try:
        return round(float(match.group(1)), 2)
    except (TypeError, ValueError):
        return 0.0


def _date_iso(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    formats = [
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%m/%d/%y",
        "%Y/%m/%d",
        "%d-%b-%Y",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _field(row: dict, *aliases: str) -> str:
    lowered = {str(k).strip().lower(): v for k, v in row.items()}
    for key in aliases:
        if key.lower() in lowered:
            return str(lowered[key.lower()] or "").strip()
    return ""


def _parse_csv(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for index, row in enumerate(reader, start=2):
            auction_date = _date_iso(_field(row, "Date", "Auction Date"))
            item_type = _field(row, "Item Type", "Category", "Lot Type") or "Unknown"
            hammer = _money(_field(row, "Final Hammer Price", "Hammer Price", "Final Price"))
            commission = _money(_field(row, "Commission", "Commission Amount", "Fee"))
            rows.append(
                {
                    "source_file": str(path),
                    "row_number": index,
                    "auction_date": auction_date,
                    "item_type": item_type,
                    "final_hammer_price": hammer,
                    "commission": commission,
                    "billable_pulse": commission,
                    "engagement_category": item_type,
                    "engagement_type": "PAC_AUCTION",
                    "drift_pct": 0.0,
                    "ingested_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                }
            )
    return rows


def _upsert_rows(db_path: Path, rows: list[dict]) -> int:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(_CREATE_PAC_AUCTION_LOGS)
        conn.execute(_CREATE_PAC_AUCTION_LOGS_IDX)
        for row in rows:
            conn.execute(
                """
                INSERT INTO pac_auction_logs (
                    source_file, row_number, auction_date, item_type,
                    final_hammer_price, commission, billable_pulse,
                    engagement_category, engagement_type, drift_pct, ingested_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["source_file"],
                    row["row_number"],
                    row["auction_date"],
                    row["item_type"],
                    row["final_hammer_price"],
                    row["commission"],
                    row["billable_pulse"],
                    row["engagement_category"],
                    row["engagement_type"],
                    row["drift_pct"],
                    row["ingested_at"],
                ),
            )
        conn.commit()
        return len(rows)
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest PAC auction CSV logs into marine.sqlite")
    parser.add_argument("csv", nargs="+", help="CSV file path(s) to ingest")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="Target marine sqlite path")
    args = parser.parse_args()

    csv_paths = [Path(p).resolve() for p in args.csv]
    missing = [str(p) for p in csv_paths if not p.exists()]
    if missing:
        raise SystemExit(f"Missing CSV file(s): {', '.join(missing)}")

    all_rows: list[dict] = []
    for path in csv_paths:
        all_rows.extend(_parse_csv(path))

    ingested = _upsert_rows(Path(args.db).resolve(), all_rows)
    summary = {
        "status": "ok",
        "ingested_rows": ingested,
        "db_path": str(Path(args.db).resolve()),
        "csv_count": len(csv_paths),
        "event_type": "PAC_AUCTION",
        "zero_drift_pct": 0.0,
    }
    print(json.dumps(summary, ensure_ascii=True))


if __name__ == "__main__":
    main()
