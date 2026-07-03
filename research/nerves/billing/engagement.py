"""
Engagement Telemetry Nerve
==========================
Python equivalent of the background pulse task (lib.rs analogue).

In a native/Rust context this would be a spawned async task writing to SQLite
on a 10-minute tick.  Here the tick is driven by the JS Page-Visibility-aware
timer in the Hub frontend, which POSTs to /api/telemetry/pulse every
PULSE_INTERVAL_MIN of active UI time.  This module handles:

  - Writing pulse events to the cortex telemetry DB
  - Loading per-tenant billing rates from tenant_config.json
  - Querying events and calculating the Project Total Investment
  - Formatting engagement summaries for the PDF appendix
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from hub.sqlite_utils import open_sqlite

# ── Paths ─────────────────────────────────────────────────────────────────────
_ROOT           = Path(__file__).resolve().parents[2]
_DB_PATH        = _ROOT / "data" / "cortex.sqlite"
_TENANT_CONFIG  = _ROOT / "tenant_config.json"

# ── Constants ─────────────────────────────────────────────────────────────────
PULSE_INTERVAL_MIN   = 10    # minutes each engagement_pulse represents
DEFAULT_HOURLY_RATE  = 250.0
MAX_APPENDIX_ROWS    = 25    # max event rows shown in the PDF table


# ── Tenant config ─────────────────────────────────────────────────────────────
def load_tenant_config() -> dict:
    if _TENANT_CONFIG.exists():
        try:
            raw = json.loads(_TENANT_CONFIG.read_text(encoding="utf-8"))
            # strip the _comment key
            return {k: v for k, v in raw.items() if not k.startswith("_")}
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def get_hourly_rate(tenant_slug: str) -> float:
    config = load_tenant_config()
    tenant = config.get(tenant_slug) or config.get("default") or {}
    try:
        return float(tenant.get("base_hourly_rate", DEFAULT_HOURLY_RATE))
    except (TypeError, ValueError):
        return DEFAULT_HOURLY_RATE


def get_tenant_name(tenant_slug: str) -> str:
    config = load_tenant_config()
    tenant = config.get(tenant_slug) or {}
    return tenant.get("name", tenant_slug)


def get_currency(tenant_slug: str) -> str:
    config = load_tenant_config()
    tenant = config.get(tenant_slug) or config.get("default") or {}
    return tenant.get("currency", "USD")


# ── DB helpers ────────────────────────────────────────────────────────────────
def _ensure_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS cortex_telemetry (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_slug  TEXT    NOT NULL,
            timestamp    TEXT    NOT NULL,
            event        TEXT    NOT NULL,
            payload      TEXT    NOT NULL DEFAULT '{}'
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ct_tenant_event ON cortex_telemetry (tenant_slug, event)"
    )
    conn.commit()


# ── Write ─────────────────────────────────────────────────────────────────────
def write_event(tenant_slug: str, event: str, payload: dict | None = None) -> None:
    """Write a telemetry event for the given tenant."""
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open_sqlite(_DB_PATH) as conn:
        _ensure_tables(conn)
        conn.execute(
            "INSERT INTO cortex_telemetry (tenant_slug, timestamp, event, payload) VALUES (?, ?, ?, ?)",
            (tenant_slug, now, event, json.dumps(payload or {})),
        )
        conn.commit()


# ── Query ─────────────────────────────────────────────────────────────────────
def query_events(
    tenant_slug: str,
    event_filter: list[str] | None = None,
    limit: int = 200,
) -> list[dict]:
    """Return events newest-first for the tenant, optionally filtered by event names."""
    if not _DB_PATH.exists():
        return []
    bounded = max(1, min(limit, 500))
    with open_sqlite(_DB_PATH) as conn:
        if event_filter:
            ph = ",".join("?" * len(event_filter))
            rows = conn.execute(
                f"""
                SELECT id, tenant_slug, timestamp, event, payload
                FROM cortex_telemetry
                WHERE tenant_slug = ? AND event IN ({ph})
                ORDER BY timestamp DESC, id DESC
                LIMIT ?
                """,
                [tenant_slug, *event_filter, bounded],
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, tenant_slug, timestamp, event, payload
                FROM cortex_telemetry
                WHERE tenant_slug = ?
                ORDER BY timestamp DESC, id DESC
                LIMIT ?
                """,
                [tenant_slug, bounded],
            ).fetchall()
    return [
        {
            "id": row[0],
            "tenant_slug": row[1],
            "timestamp": row[2],
            "event": row[3],
            "payload": json.loads(row[4]),
        }
        for row in rows
    ]


def total_pulse_count(tenant_slug: str) -> int:
    """Return the number of engagement_pulse events stored for the tenant."""
    if not _DB_PATH.exists():
        return 0
    with open_sqlite(_DB_PATH) as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM cortex_telemetry WHERE tenant_slug = ? AND event = 'engagement_pulse'",
            (tenant_slug,),
        ).fetchone()
    return int(row[0]) if row else 0


# ── Calculation ───────────────────────────────────────────────────────────────
def calculate_engagement(tenant_slug: str) -> dict:
    """
    Return full engagement summary for the tenant:
      pulse_count, report_count, total_minutes, total_hours, hourly_rate,
      currency, investment, events (newest-first, capped for PDF).
    """
    hourly_rate = get_hourly_rate(tenant_slug)
    currency    = get_currency(tenant_slug)
    events      = query_events(
        tenant_slug,
        event_filter=["engagement_pulse", "report_gen"],
        limit=500,
    )

    pulse_count  = sum(1 for e in events if e["event"] == "engagement_pulse")
    report_count = sum(1 for e in events if e["event"] == "report_gen")

    total_minutes = pulse_count * PULSE_INTERVAL_MIN
    total_hours   = total_minutes / 60
    investment    = round(total_hours * hourly_rate, 2)

    return {
        "tenant_slug":    tenant_slug,
        "tenant_name":    get_tenant_name(tenant_slug),
        "pulse_count":    pulse_count,
        "report_count":   report_count,
        "total_minutes":  total_minutes,
        "total_hours":    round(total_hours, 2),
        "hourly_rate":    hourly_rate,
        "currency":       currency,
        "investment":     investment,
        "events_preview": events[:MAX_APPENDIX_ROWS],
        "events_total":   len(events),
    }


# ── Formatters ────────────────────────────────────────────────────────────────
def format_duration(total_minutes: int) -> str:
    h, m = divmod(total_minutes, 60)
    if h and m:
        return f"{h}h {m}m"
    if h:
        return f"{h}h"
    return f"{m}m" if m else "0m"


def format_currency(amount: float, currency: str = "USD") -> str:
    symbol = {"USD": "$", "GBP": "£", "EUR": "€"}.get(currency, currency + " ")
    return f"{symbol}{amount:,.2f}"


def event_label(event: str) -> str:
    return {
        "engagement_pulse": "UI Engagement Session",
        "report_gen":       "Report Generated",
    }.get(event, event.replace("_", " ").title())
