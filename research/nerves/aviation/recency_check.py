"""
Aviation Recency Check Nerve
============================
Queries the internal tenant vault for oil analysis events and computes
maintenance status for one or more tail numbers against a 120-day
overdue threshold.

Status colours:
    CURRENT  -> #26A69A  (teal green)
    OVERDUE  -> #EF4444  (safety red)
    UNKNOWN  -> #9E9E9E  (grey - no records)

Also surfaces the 38 ppm Iron (Fe) baseline delta if a newer analysis
has been ingested since the baseline was recorded.

Usage
-----
    from nerves.aviation.recency_check import RecencyChecker

    checker = RecencyChecker()
    status  = checker.check()
    print(status.summary())

CLI:
    python nerves/aviation/recency_check.py
    python nerves/aviation/recency_check.py --json
"""

from __future__ import annotations

import json
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ── Paths ─────────────────────────────────────────────────────────────────────
_ROOT        = Path(__file__).resolve().parents[3]
_APPDATA     = Path.home() / "AppData" / "Roaming"
_VAULT_ROOT  = _APPDATA / "Aero Cortex Hub" / "data" / "tenants"
_INTERNAL_DB = _VAULT_ROOT / "internal" / "marine.sqlite"

# ── Constants ─────────────────────────────────────────────────────────────────
PRIMARY_TAIL_NUMBER    = "N6424P"
SHADOW_TAIL_NUMBER     = "SHADOW-TAIL"
DEFAULT_TAIL_NUMBERS   = [PRIMARY_TAIL_NUMBER, SHADOW_TAIL_NUMBER]
# Backward-compatible alias used in existing imports.
TAIL_NUMBER            = PRIMARY_TAIL_NUMBER
OVERDUE_THRESHOLD_DAYS = 120
WARNING_DAYS_REMAINING = 15      # 🟠 WARNING when < 15 days left before overdue
BASELINE_IRON_PPM      = 38.0    # Fe baseline from ICP report
STATUS_CURRENT         = "CURRENT"
STATUS_WARNING         = "WARNING"
STATUS_OVERDUE         = "OVERDUE"
STATUS_UNKNOWN         = "UNKNOWN"

# Status colours (hex) for PDF / UI consumers
COLOUR_CURRENT = "#26A69A"
COLOUR_WARNING = "#F97316"   # 🟠 orange
COLOUR_OVERDUE = "#EF4444"
COLOUR_UNKNOWN = "#9E9E9E"


# ── Data classes ──────────────────────────────────────────────────────────────
@dataclass
class OilReading:
    timestamp: str
    iron_ppm: Optional[float]
    report_name: Optional[str]
    source_pdf: Optional[str]
    raw_payload: dict = field(default_factory=dict)

    @property
    def iron_delta_ppm(self) -> Optional[float]:
        """Delta from the 38 ppm Fe baseline. Positive = increase."""
        if self.iron_ppm is None:
            return None
        return round(self.iron_ppm - BASELINE_IRON_PPM, 2)

    @property
    def delta_flag(self) -> str:
        """Traffic-light flag for the Fe delta."""
        d = self.iron_delta_ppm
        if d is None:
            return "UNKNOWN"
        if abs(d) <= 5:
            return "STABLE"
        if d > 0:
            return "ELEVATED"
        return "REDUCED"


@dataclass
class RecencyStatus:
    status: str                        # CURRENT / WARNING / OVERDUE / UNKNOWN
    colour: str                        # hex colour for PDF/UI
    days_since_analysis: Optional[int]
    days_remaining: Optional[int]      # days until 120-day limit; None when unknown/overdue
    last_analysis_date: Optional[str]
    overdue_threshold_days: int
    tail_number: str
    baseline_iron_ppm: float
    latest_reading: Optional[OilReading]

    def is_overdue(self) -> bool:
        return self.status == STATUS_OVERDUE

    def is_warning(self) -> bool:
        return self.status == STATUS_WARNING

    def status_label(self) -> str:
        if self.status == STATUS_CURRENT:
            return (
                f"Current  ({self.days_since_analysis} days since last analysis, "
                f"{self.days_remaining} days remaining)"
            )
        if self.status == STATUS_WARNING:
            return (
                f"🟠 WARNING  ({self.days_remaining} days remaining until overdue — "
                f"{self.days_since_analysis} days since last analysis)"
            )
        if self.status == STATUS_OVERDUE:
            days = self.days_since_analysis
            if days is not None:
                return f"OVERDUE  ({days} days since last analysis — threshold {self.overdue_threshold_days}d)"
            return "OVERDUE  (no oil analysis on record)"
        return "UNKNOWN  (vault not accessible or no records)"

    def summary(self) -> str:
        lines = [
            f"Tail Number     : {self.tail_number}",
            f"Status          : {self.status_label()}",
            f"Threshold       : {self.overdue_threshold_days} days",
            f"Days Remaining  : {self.days_remaining if self.days_remaining is not None else 'N/A'}",
            f"Baseline Fe     : {self.baseline_iron_ppm} ppm",
        ]
        if self.latest_reading:
            r = self.latest_reading
            lines.append(f"Last Analysis   : {r.timestamp[:10]}")
            if r.iron_ppm is not None:
                delta_str = f"{r.iron_delta_ppm:+.1f} ppm vs baseline"
                lines.append(f"Fe Reading      : {r.iron_ppm} ppm  ({delta_str})  [{r.delta_flag}]")
            if r.report_name:
                lines.append(f"Report Name     : {r.report_name}")
        else:
            lines.append("Last Analysis   : No records found")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        reading = None
        if self.latest_reading:
            r = self.latest_reading
            reading = {
                "timestamp":       r.timestamp,
                "iron_ppm":        r.iron_ppm,
                "iron_delta_ppm":  r.iron_delta_ppm,
                "delta_flag":      r.delta_flag,
                "report_name":     r.report_name,
                "source_pdf":      r.source_pdf,
            }
        return {
            "tail_number":            self.tail_number,
            "status":                 self.status,
            "colour":                 self.colour,
            "days_since_analysis":    self.days_since_analysis,
            "days_remaining":         self.days_remaining,
            "last_analysis_date":     self.last_analysis_date,
            "overdue_threshold_days": self.overdue_threshold_days,
            "warning_days_remaining": WARNING_DAYS_REMAINING,
            "baseline_iron_ppm":      self.baseline_iron_ppm,
            "latest_reading":         reading,
            "is_overdue":             self.is_overdue(),
            "is_warning":             self.is_warning(),
        }


@dataclass
class FleetRecencyStatus:
    primary_tail: str
    tails: list[RecencyStatus]
    detected_tail_count: int
    fleet_alert: str
    fleet_colour: str

    def to_dict(self) -> dict:
        return {
            "primary_tail": self.primary_tail,
            "detected_tail_count": self.detected_tail_count,
            "fleet_alert": self.fleet_alert,
            "fleet_colour": self.fleet_colour,
            "tails": [tail.to_dict() for tail in self.tails],
        }


# ── Recency Checker ───────────────────────────────────────────────────────────
class RecencyChecker:
    """
    Queries the internal tenant SQLite vault for oil_analysis events and
    computes N6424P maintenance status.
    """

    def __init__(
        self,
        db_path: Path = _INTERNAL_DB,
        tail_numbers: Optional[list[str]] = None,
        primary_tail: str = PRIMARY_TAIL_NUMBER,
    ):
        self.db_path = db_path
        self.primary_tail = (primary_tail or PRIMARY_TAIL_NUMBER).strip().upper() or PRIMARY_TAIL_NUMBER
        source = tail_numbers if tail_numbers else DEFAULT_TAIL_NUMBERS
        cleaned = []
        for tail in source:
            t = (tail or "").strip().upper()
            if t and t not in cleaned:
                cleaned.append(t)
        if self.primary_tail not in cleaned:
            cleaned.insert(0, self.primary_tail)
        self.tail_numbers = cleaned

    def _days_since(self, iso_ts: str) -> int:
        """Return calendar days between an ISO-8601 timestamp and today (UTC)."""
        try:
            date_part = iso_ts[:10]
            then = datetime.strptime(date_part, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            now  = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            return (now - then).days
        except (ValueError, TypeError):
            return 9999

    def _extract_payload_tail(self, payload: dict) -> str:
        for key in ("tail_number", "tail", "registration", "aircraft_tail"):
            raw = payload.get(key)
            if raw:
                return str(raw).strip().upper()
        # Backward compatibility: older rows were single-tail and implicitly N6424P.
        return self.primary_tail

    def _latest_oil_reading(self, conn: sqlite3.Connection, tail_number: str) -> Optional[OilReading]:
        """Return the most recent oil_analysis event matching the requested tail."""
        rows = conn.execute(
            """
            SELECT timestamp, payload
            FROM   telemetry
            WHERE  event LIKE 'oil_analysis%'
            ORDER  BY timestamp DESC, id DESC
            LIMIT  500
            """
        ).fetchall()
        if not rows:
            return None

        wanted = (tail_number or self.primary_tail).strip().upper() or self.primary_tail
        for ts, payload_raw in rows:
            try:
                payload = json.loads(payload_raw)
            except (json.JSONDecodeError, TypeError):
                payload = {}

            row_tail = self._extract_payload_tail(payload)
            if row_tail != wanted:
                continue

            iron_ppm = None
            for key in ("iron_ppm", "iron", "Fe", "fe"):
                val = payload.get(key)
                if val is not None:
                    try:
                        iron_ppm = float(val)
                        break
                    except (TypeError, ValueError):
                        pass

            return OilReading(
                timestamp   = ts,
                iron_ppm    = iron_ppm,
                report_name = payload.get("report_name"),
                source_pdf  = payload.get("source_pdf"),
                raw_payload = payload,
            )
        return None

    def _status_when_unknown(self, tail_number: str) -> RecencyStatus:
        return RecencyStatus(
            status                 = STATUS_UNKNOWN,
            colour                 = COLOUR_UNKNOWN,
            days_since_analysis    = None,
            days_remaining         = None,
            last_analysis_date     = None,
            overdue_threshold_days = OVERDUE_THRESHOLD_DAYS,
            tail_number            = tail_number,
            baseline_iron_ppm      = BASELINE_IRON_PPM,
            latest_reading         = None,
        )

    def _status_from_connection(self, conn: sqlite3.Connection, tail_number: str) -> RecencyStatus:
        reading = self._latest_oil_reading(conn, tail_number=tail_number)
        if reading is None:
            return RecencyStatus(
                status                 = STATUS_OVERDUE,
                colour                 = COLOUR_OVERDUE,
                days_since_analysis    = None,
                days_remaining         = None,
                last_analysis_date     = None,
                overdue_threshold_days = OVERDUE_THRESHOLD_DAYS,
                tail_number            = tail_number,
                baseline_iron_ppm      = BASELINE_IRON_PPM,
                latest_reading         = None,
            )

        days = self._days_since(reading.timestamp)
        days_remaining = max(0, OVERDUE_THRESHOLD_DAYS - days)

        if days >= OVERDUE_THRESHOLD_DAYS:
            status = STATUS_OVERDUE
            colour = COLOUR_OVERDUE
            days_remaining = 0
        elif days_remaining < WARNING_DAYS_REMAINING:
            status = STATUS_WARNING
            colour = COLOUR_WARNING
        else:
            status = STATUS_CURRENT
            colour = COLOUR_CURRENT

        return RecencyStatus(
            status                 = status,
            colour                 = colour,
            days_since_analysis    = days,
            days_remaining         = days_remaining,
            last_analysis_date     = reading.timestamp[:10],
            overdue_threshold_days = OVERDUE_THRESHOLD_DAYS,
            tail_number            = tail_number,
            baseline_iron_ppm      = BASELINE_IRON_PPM,
            latest_reading         = reading,
        )

    def check(self, tail_number: Optional[str] = None) -> RecencyStatus:
        """Run recency check for a single tail (defaults to the primary tail)."""
        target_tail = (tail_number or self.primary_tail).strip().upper() or self.primary_tail

        if not self.db_path.exists():
            return self._status_when_unknown(target_tail)

        try:
            conn = sqlite3.connect(str(self.db_path))
        except sqlite3.Error:
            return self._status_when_unknown(target_tail)

        try:
            return self._status_from_connection(conn, tail_number=target_tail)
        finally:
            conn.close()

    def check_fleet(self) -> FleetRecencyStatus:
        """Run recency check across configured tails and return a fleet summary."""
        if not self.db_path.exists():
            unknown = [self._status_when_unknown(tail) for tail in self.tail_numbers]
            return FleetRecencyStatus(
                primary_tail=self.primary_tail,
                tails=unknown,
                detected_tail_count=0,
                fleet_alert="CRITICAL",
                fleet_colour=COLOUR_OVERDUE,
            )

        try:
            conn = sqlite3.connect(str(self.db_path))
        except sqlite3.Error:
            unknown = [self._status_when_unknown(tail) for tail in self.tail_numbers]
            return FleetRecencyStatus(
                primary_tail=self.primary_tail,
                tails=unknown,
                detected_tail_count=0,
                fleet_alert="CRITICAL",
                fleet_colour=COLOUR_OVERDUE,
            )

        try:
            statuses = [self._status_from_connection(conn, tail_number=tail) for tail in self.tail_numbers]
        finally:
            conn.close()

        detected = [s for s in statuses if s.latest_reading is not None]
        considered = detected if detected else [statuses[0]]

        if any(s.status in {STATUS_OVERDUE, STATUS_UNKNOWN} for s in considered):
            fleet_alert = "CRITICAL"
            fleet_colour = COLOUR_OVERDUE
        elif any(s.status == STATUS_WARNING for s in considered):
            fleet_alert = "WARNING"
            fleet_colour = COLOUR_WARNING
        else:
            fleet_alert = "OK"
            fleet_colour = COLOUR_CURRENT

        return FleetRecencyStatus(
            primary_tail=self.primary_tail,
            tails=statuses,
            detected_tail_count=len(detected),
            fleet_alert=fleet_alert,
            fleet_colour=fleet_colour,
        )


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Fleet Oil Analysis Recency Check")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    parser.add_argument(
        "--db", default=str(_INTERNAL_DB),
        help="Path to internal tenant SQLite DB"
    )
    args = parser.parse_args()

    checker = RecencyChecker(db_path=Path(args.db))
    result  = checker.check_fleet()

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print()
        print(f"  Fleet Maintenance Recency Check")
        print(f"  =================================")
        print()
        print(f"  Fleet Alert    : {result.fleet_alert}")
        print(f"  Active Tails   : {result.detected_tail_count}")
        print()
        for tail_status in result.tails:
            for line in tail_status.summary().splitlines():
                print(f"  {line}")
            print()
        print()
        if result.fleet_alert == "CRITICAL":
            print(f"  *** OIL ANALYSIS OVERDUE - Schedule immediately ***")
            print()
