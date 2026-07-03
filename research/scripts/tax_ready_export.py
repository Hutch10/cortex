"""
tax_ready_export.py — Generate tax-ready CSV for Lakeside Legal revenue vs business aviation expenses.

Usage:
  python scripts/tax_ready_export.py
  python scripts/tax_ready_export.py --start-date 2026-01-01 --end-date 2026-03-31
  python scripts/tax_ready_export.py --output outputs/reports/tax/custom.csv
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hub.sqlite_utils import open_sqlite
from nerves.billing.engagement import PULSE_INTERVAL_MIN, get_hourly_rate

CORTEX_DB = ROOT / "data" / "cortex.sqlite"
AVIATION_DB = (
    Path.home() / "AppData" / "Roaming" / "Aero Cortex Hub"
    / "data" / "tenants" / "internal" / "marine.sqlite"
)

FUEL_COST_PER_GAL_USD = 6.75
OIL_COST_PER_QT_USD = 12.0
SAMPLE_KIT_COST_USD = 18.0


def _parse_day(raw: str) -> datetime:
    dt = datetime.strptime(raw, "%Y-%m-%d")
    return dt.replace(tzinfo=timezone.utc)


def _quarter_bounds(now: datetime) -> tuple[datetime, datetime]:
    quarter_start_month = ((now.month - 1) // 3) * 3 + 1
    start = datetime(now.year, quarter_start_month, 1, tzinfo=timezone.utc)
    if quarter_start_month == 10:
        end = datetime(now.year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(now.year, quarter_start_month + 3, 1, tzinfo=timezone.utc)
    return start, end


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_revenue_by_day(start_iso: str, end_iso: str) -> tuple[dict[str, float], dict[str, int]]:
    revenue = defaultdict(float)
    pulses = defaultdict(int)
    if not CORTEX_DB.exists():
        return dict(revenue), dict(pulses)

    hourly = get_hourly_rate("lakeside-legal")
    pulse_revenue = hourly * (PULSE_INTERVAL_MIN / 60.0)

    try:
        with open_sqlite(CORTEX_DB) as conn:
            rows = conn.execute(
                """
                SELECT timestamp
                FROM cortex_telemetry
                WHERE tenant_slug = 'lakeside-legal'
                  AND event = 'engagement_pulse'
                  AND timestamp >= ?
                  AND timestamp < ?
                ORDER BY timestamp ASC
                """,
                (start_iso, end_iso),
            ).fetchall()
    except sqlite3.DatabaseError:
        rows = []

    for (ts,) in rows:
        day = str(ts)[:10]
        revenue[day] += pulse_revenue
        pulses[day] += 1

    return dict(revenue), dict(pulses)


def _load_expenses_by_day(start_iso: str, end_iso: str) -> tuple[dict[str, float], dict[str, str]]:
    expenses = defaultdict(float)
    notes = defaultdict(list)
    if not AVIATION_DB.exists():
        return dict(expenses), {k: ", ".join(v) for k, v in notes.items()}

    try:
        conn = sqlite3.connect(str(AVIATION_DB))
        try:
            fuel_rows = conn.execute(
                """
                SELECT timestamp, COALESCE(gallons_added, 0.0)
                FROM fuel_logs
                WHERE timestamp >= ? AND timestamp < ?
                """,
                (start_iso, end_iso),
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.DatabaseError:
        fuel_rows = []

    for ts, gallons in fuel_rows:
        day = str(ts)[:10]
        expenses[day] += float(gallons or 0.0) * FUEL_COST_PER_GAL_USD
        notes[day].append("fuel")

    try:
        conn = sqlite3.connect(str(AVIATION_DB))
        try:
            event_rows = conn.execute(
                """
                SELECT timestamp, item_key, delta_quantity
                FROM mission_consumable_events
                WHERE timestamp >= ? AND timestamp < ?
                """,
                (start_iso, end_iso),
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.DatabaseError:
        event_rows = []

    for ts, item_key, delta in event_rows:
        if delta is None:
            continue
        delta_f = float(delta)
        if delta_f >= 0:
            continue
        day = str(ts)[:10]
        if item_key == "oil_quarts":
            expenses[day] += abs(delta_f) * OIL_COST_PER_QT_USD
            notes[day].append("oil")
        elif item_key == "sample_kits":
            expenses[day] += abs(delta_f) * SAMPLE_KIT_COST_USD
            notes[day].append("kits")

    return dict(expenses), {k: ", ".join(sorted(set(v))) for k, v in notes.items()}


def generate_tax_ready_csv(start_date: str | None, end_date: str | None, output: Path | None) -> Path:
    now = datetime.now(timezone.utc)
    if start_date and end_date:
        start_dt = _parse_day(start_date)
        end_dt_exclusive = _parse_day(end_date) + timedelta(days=1)
    else:
        start_dt, end_dt_exclusive = _quarter_bounds(now)

    if end_dt_exclusive <= start_dt:
        raise ValueError("end date must be after start date")

    start_iso = _iso(start_dt)
    end_iso = _iso(end_dt_exclusive)

    revenue_by_day, pulse_count_by_day = _load_revenue_by_day(start_iso, end_iso)
    expense_by_day, expense_notes = _load_expenses_by_day(start_iso, end_iso)

    all_days = sorted(set(revenue_by_day) | set(expense_by_day))

    if output is None:
        tax_dir = ROOT / "outputs" / "reports" / "tax"
        tax_dir.mkdir(parents=True, exist_ok=True)
        output = tax_dir / f"tax_ready_{start_dt.strftime('%Y%m%d')}_{(end_dt_exclusive - timedelta(days=1)).strftime('%Y%m%d')}.csv"
    else:
        output.parent.mkdir(parents=True, exist_ok=True)

    total_revenue = 0.0
    total_expense = 0.0

    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "date",
            "lakeside_legal_revenue_usd",
            "business_aviation_expense_usd",
            "net_usd",
            "revenue_pulse_count",
            "expense_notes",
        ])

        for day in all_days:
            rev = float(revenue_by_day.get(day, 0.0))
            exp = float(expense_by_day.get(day, 0.0))
            pulses = int(pulse_count_by_day.get(day, 0))
            note = expense_notes.get(day, "")
            writer.writerow([day, f"{rev:.2f}", f"{exp:.2f}", f"{(rev - exp):.2f}", pulses, note])
            total_revenue += rev
            total_expense += exp

        writer.writerow([
            "TOTAL",
            f"{total_revenue:.2f}",
            f"{total_expense:.2f}",
            f"{(total_revenue - total_expense):.2f}",
            sum(pulse_count_by_day.values()),
            "",
        ])

    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate tax-ready export for Lakeside Legal revenue vs aviation expenses")
    parser.add_argument("--start-date", help="Start date YYYY-MM-DD")
    parser.add_argument("--end-date", help="End date YYYY-MM-DD")
    parser.add_argument("--output", help="Output CSV path")
    args = parser.parse_args()

    output = Path(args.output) if args.output else None
    path = generate_tax_ready_csv(args.start_date, args.end_date, output)
    print(f"Tax-ready CSV written: {path}")


if __name__ == "__main__":
    main()
