"""
Cortex Hub — Flask application
Serves the Business Workflow view and exposes the Report Generator API.
"""

from __future__ import annotations

import sys
import json
import math
import hashlib
import os
import re
import secrets
import sqlite3
import time
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib import error as urlerror
from urllib import parse as urlparse
from urllib import request as urlrequest

# Ensure project root is on sys.path
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from flask import Flask, render_template, request, jsonify, send_file, abort, redirect, has_request_context, g
try:
    from flask_socketio import SocketIO
except Exception:  # pragma: no cover - optional dependency safety
    SocketIO = None

from hub.sqlite_utils import open_sqlite
from nerves.consulting.drift_optimizer import DriftOptimizer
from nerves.consulting.report_gen import ReportGenerator
from nerves.billing.engagement import (
    write_event, calculate_engagement, total_pulse_count,
    get_hourly_rate, format_duration, format_currency, get_tenant_name,
    get_currency, query_events, event_label, PULSE_INTERVAL_MIN,
)

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["SECRET_KEY"] = "cortex-dev-key"
app.config["MARINE_DB_PATH"] = str(_ROOT / "data" / "marine.sqlite")
app.config["REEF_REFERENCE_PATH"] = str(_ROOT / "data" / "reef_reference.json")
app.config["MARINE_SNAPSHOT_DIR"] = str(_ROOT / "outputs" / "marine_snapshots")

# ── Autonomous Pulse Config (config.json) ──────────────────────────────────────
_CONFIG_JSON_PATH = _ROOT / "config.json"

def _load_hub_config() -> dict:
    if _CONFIG_JSON_PATH.exists():
        try:
            return json.loads(_CONFIG_JSON_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}

_HUB_CONFIG: dict = _load_hub_config()


class _NoopSocketIO:
    def emit(self, *_args, **_kwargs) -> None:
        return None

    def run(self, flask_app: Flask, **kwargs) -> None:
        flask_app.run(**kwargs)


socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading") if SocketIO else _NoopSocketIO()


def _emit_realtime(event: str, payload: dict) -> None:
    try:
        socketio.emit(event, payload)
    except Exception:
        pass

_VAULT_HEALTH_STATUS_PATH = _ROOT / "outputs" / "vault_health_status.json"


def _append_briefing_latency_audit(entry: dict) -> None:
    _BRIEFING_LATENCY_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _BRIEFING_LATENCY_LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=True) + "\n")


@app.before_request
def _start_briefing_latency_monitor() -> None:
    if request.path.startswith("/api/briefing"):
        g._briefing_latency_started = time.perf_counter()


@app.after_request
def _record_briefing_latency(response):
    if not request.path.startswith("/api/briefing"):
        return response

    started = getattr(g, "_briefing_latency_started", None)
    if started is None:
        return response

    latency_ms = (time.perf_counter() - started) * 1000.0
    if latency_ms > _BRIEFING_LATENCY_THRESHOLD_MS:
        audit_row = {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "path": request.path,
            "method": request.method,
            "latency_ms": round(latency_ms, 2),
            "threshold_ms": _BRIEFING_LATENCY_THRESHOLD_MS,
            "optimization_flag": "OPTIMIZE",
            "tenant_id": request.args.get("tenant_id") or request.args.get("tenant_slug") or "default",
            "organization_id": request.args.get("organization_id") or request.args.get("org_id") or "legacy",
            "status_code": int(getattr(response, "status_code", 0) or 0),
        }
        try:
            _append_briefing_latency_audit(audit_row)
        except OSError:
            pass

        response.headers["X-Briefing-Latency-Flag"] = "OPTIMIZE"
        response.headers["X-Briefing-Latency-Ms"] = f"{latency_ms:.2f}"

    return response


# ── Aviation DB (AppData tenant store) ────────────────────────────────────────
_DATA_HUB_ROOT = Path.home() / "AppData" / "Roaming" / "Aero Cortex Hub" / "data"
_TENANTS_ROOT = _DATA_HUB_ROOT / "tenants"
_ORGANIZATIONS_ROOT = _DATA_HUB_ROOT / "organizations"
_DEFAULT_TENANT_ID = "internal"
_DEFAULT_ORGANIZATION_ID = "internal"
_AVIATION_DB = _TENANTS_ROOT / _DEFAULT_TENANT_ID / "marine.sqlite"
_GLOBAL_NODE_DB = _DATA_HUB_ROOT / "global_node.sqlite"
_GOVERNANCE_DB = _DATA_HUB_ROOT / "system_governance.sqlite"
_GOVERNANCE_SYSTEM_ADMIN_USERNAMES: frozenset[str] = frozenset({"joshua", "hutch"})
_ORG_THEME_FILENAME = "theme.json"
_ORG_METADATA_FILENAME = "org_metadata.json"
_DIGITAL_GUARDIAN_PULSE_PATH = _ROOT / "outputs" / "digital_guardian_pulse.json"

# Navigator mission-map airport references (lightweight, no external dependency).
# These are used to approximate the nearest airport for aviation report markers.
_HOME_AIRPORT = {
    "code": "KICT",
    "name": "Wichita Dwight D. Eisenhower National",
    "latitude": 37.6499,
    "longitude": -97.4331,
}

_AIRPORT_REFERENCE = {
    "KICT": {"name": "Wichita Dwight D. Eisenhower National", "latitude": 37.6499, "longitude": -97.4331},
    "KIXD": {"name": "New Century AirCenter", "latitude": 38.8318, "longitude": -94.8903},
    "KUKL": {"name": "Coffey County Airport", "latitude": 38.3026, "longitude": -95.7243},
    "KHUT": {"name": "Hutchinson Municipal", "latitude": 38.0655, "longitude": -97.8606},
    "KSLN": {"name": "Salina Regional", "latitude": 38.7910, "longitude": -97.6522},
    "KRSL": {"name": "Russell Municipal", "latitude": 38.8721, "longitude": -98.8118},
    "KDDC": {"name": "Dodge City Regional", "latitude": 37.7634, "longitude": -99.9656},
    "KAPA": {"name": "Centennial", "latitude": 39.5701, "longitude": -104.8490},
    "KDEN": {"name": "Denver International", "latitude": 39.8561, "longitude": -104.6737},
}

_AIRPORT_CODE_PATTERN = re.compile(r"\bK[A-Z0-9]{3}\b")

# ── Navigator Pre-Flight constants (N6424P planning model) ───────────────────
_N6424P_EMPTY_WEIGHT_LBS = 1665.0
_N6424P_MAX_GROSS_LBS = 2300.0
_N6424P_BASE_CREW_LBS = 390.0
_N6424P_BASE_MISC_LBS = 35.0
_N6424P_BASE_FUEL_GAL = 30.0
_N6424P_MAX_FUEL_GAL = 38.0
_N6424P_FUEL_BURN_GPH = 8.5
_AVGAS_LBS_PER_GAL = 6.0

_LOAD_PROFILE_SPECIMEN_LBS = {
    "standard": 0.0,
    "high-yield": 50.0,
    "custom": 50.0,
}

# ── Navigator: Rockhounding Expeditions ──────────────────────────────────────
_CREATE_EXPEDITIONS = """
CREATE TABLE IF NOT EXISTS rockhounding_expeditions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL DEFAULT 1,
    timestamp      TEXT NOT NULL,
    location_name  TEXT,
    latitude       REAL,
    longitude      REAL,
    specimen_types TEXT,
    yield_rating   REAL
)
"""
_CREATE_EXPEDITIONS_IDX = """
CREATE INDEX IF NOT EXISTS idx_re_timestamp
    ON rockhounding_expeditions (timestamp)
"""
_CREATE_EXPEDITION_GUEST_TOKENS = """
CREATE TABLE IF NOT EXISTS expedition_guest_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    expedition_id INTEGER NOT NULL,
    tenant_id TEXT NOT NULL,
    external_email TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    redeemed_at TEXT,
    actor TEXT,
    FOREIGN KEY(expedition_id) REFERENCES rockhounding_expeditions(id) ON DELETE CASCADE
)
"""
_CREATE_EXPEDITION_GUEST_TOKENS_IDX = """
CREATE INDEX IF NOT EXISTS idx_expedition_guest_tokens_lookup
    ON expedition_guest_tokens (token_hash, expires_at, redeemed_at)
"""
_CREATE_FUEL_LOGS = """
CREATE TABLE IF NOT EXISTS fuel_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tail_number TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    hobbs_time REAL,
    tach_time REAL,
    gallons_added REAL NOT NULL,
    fuel_after_gal REAL,
    burn_rate_gph REAL,
    notes TEXT
)
"""
_CREATE_FUEL_LOGS_IDX = """
CREATE INDEX IF NOT EXISTS idx_fuel_logs_tail_time
    ON fuel_logs (tail_number, timestamp DESC)
"""
_CREATE_FLEET_READINESS_HISTORY = """
CREATE TABLE IF NOT EXISTS fleet_readiness_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL DEFAULT 1,
    snapshot_date TEXT NOT NULL,
    readiness_pct REAL NOT NULL,
    status TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE(user_id, snapshot_date)
)
"""
_CREATE_FLEET_READINESS_HISTORY_IDX = """
CREATE INDEX IF NOT EXISTS idx_fleet_readiness_history_date
    ON fleet_readiness_history (snapshot_date DESC)
"""
_CREATE_SPECIMEN_INVENTORY = """
CREATE TABLE IF NOT EXISTS specimen_inventory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    expedition_id INTEGER,
    timestamp TEXT NOT NULL,
    image_path TEXT,
    yield_stars INTEGER NOT NULL,
    color TEXT,
    hardness REAL,
    specific_gravity REAL,
    mineral_class TEXT,
    market_value_usd REAL,
    notes TEXT,
    latitude REAL,
    longitude REAL,
    transport_suggestion_json TEXT,
    FOREIGN KEY(expedition_id) REFERENCES rockhounding_expeditions(id) ON DELETE SET NULL
)
"""
_CREATE_SPECIMEN_INVENTORY_IDX = """
CREATE INDEX IF NOT EXISTS idx_specimen_inventory_timestamp
    ON specimen_inventory (timestamp DESC)
"""
_CREATE_MISSION_CONSUMABLES = """
CREATE TABLE IF NOT EXISTS mission_consumables (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_key TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    quantity REAL NOT NULL,
    unit TEXT NOT NULL,
    restock_threshold REAL NOT NULL,
    updated_at TEXT NOT NULL,
    notes TEXT
)
"""
_CREATE_MISSION_CONSUMABLES_IDX = """
CREATE INDEX IF NOT EXISTS idx_mission_consumables_item_key
    ON mission_consumables (item_key)
"""
_CREATE_MISSION_CONSUMABLE_EVENTS = """
CREATE TABLE IF NOT EXISTS mission_consumable_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_key TEXT NOT NULL,
    delta_quantity REAL NOT NULL,
    quantity_after REAL NOT NULL,
    unit TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    source TEXT,
    notes TEXT
)
"""
_CREATE_MISSION_CONSUMABLE_EVENTS_IDX = """
CREATE INDEX IF NOT EXISTS idx_mission_consumable_events_time
    ON mission_consumable_events (timestamp DESC)
"""
_CREATE_FUEL_MARKET_LOGS = """
CREATE TABLE IF NOT EXISTS fuel_market_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    airport_code TEXT NOT NULL,
    fuel_type TEXT NOT NULL,
    price_per_gal_usd REAL NOT NULL,
    fetched_at TEXT NOT NULL,
    source TEXT,
    raw_payload_json TEXT
)
"""
_CREATE_FUEL_MARKET_LOGS_IDX = """
CREATE INDEX IF NOT EXISTS idx_fuel_market_logs_airport_time
    ON fuel_market_logs (airport_code, fuel_type, fetched_at DESC)
"""
_CREATE_USER_PROFILES = """
CREATE TABLE IF NOT EXISTS user_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL,
    home_base_icao TEXT,
    share_signals INTEGER NOT NULL DEFAULT 0,
    mentor_mesh TEXT,
    permissions_json TEXT
)
"""
_CREATE_MISSION_SCOPES = """
CREATE TABLE IF NOT EXISTS mission_scopes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    scope_type TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY(user_id) REFERENCES user_profiles(id) ON DELETE CASCADE,
    UNIQUE(user_id, scope_type)
)
"""
_CREATE_GUEST_ORACLE_SUBMISSIONS = """
CREATE TABLE IF NOT EXISTS guest_oracle_submissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    submission_type TEXT NOT NULL,
    drift_pct REAL,
    discovery_note TEXT,
    private_location_label TEXT,
    private_latitude REAL,
    private_longitude REAL,
    submitted_at TEXT NOT NULL,
    source TEXT,
    FOREIGN KEY(user_id) REFERENCES user_profiles(id) ON DELETE CASCADE
)
"""
_CREATE_GUEST_ORACLE_SUBMISSIONS_IDX = """
CREATE INDEX IF NOT EXISTS idx_guest_oracle_submissions_user_time
    ON guest_oracle_submissions (user_id, submitted_at DESC)
"""
_CREATE_GUEST_SIGNAL_INBOX = """
CREATE TABLE IF NOT EXISTS guest_signal_inbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    tenant_token TEXT NOT NULL,
    signal_kind TEXT NOT NULL,
    message TEXT NOT NULL,
    emitted_at TEXT NOT NULL,
    source TEXT,
    is_read INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY(user_id) REFERENCES user_profiles(id) ON DELETE CASCADE
)
"""
_CREATE_GUEST_SIGNAL_INBOX_IDX = """
CREATE INDEX IF NOT EXISTS idx_guest_signal_inbox_user_time
    ON guest_signal_inbox (user_id, emitted_at DESC)
"""
_CREATE_OBSERVATORY_SIGNALS = """
CREATE TABLE IF NOT EXISTS observatory_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    emitted_at TEXT NOT NULL,
    tenant_token TEXT NOT NULL,
    role_label TEXT NOT NULL,
    signal_type TEXT NOT NULL,
    general_region TEXT NOT NULL,
    source TEXT
)
"""
_CREATE_OBSERVATORY_SIGNALS_IDX = """
CREATE INDEX IF NOT EXISTS idx_observatory_signals_recent
    ON observatory_signals (emitted_at DESC, id DESC)
"""
_CREATE_OBSERVATORY_SIGNAL_VOUCHES = """
CREATE TABLE IF NOT EXISTS observatory_signal_vouches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id INTEGER NOT NULL,
    tenant_token TEXT NOT NULL,
    vouched_at TEXT NOT NULL,
    evidence_count INTEGER NOT NULL DEFAULT 0,
    UNIQUE(signal_id, tenant_token),
    FOREIGN KEY(signal_id) REFERENCES observatory_signals(id) ON DELETE CASCADE
)
"""
_CREATE_OBSERVATORY_SIGNAL_VOUCHES_IDX = """
CREATE INDEX IF NOT EXISTS idx_observatory_signal_vouches_signal
    ON observatory_signal_vouches (signal_id, tenant_token)
"""
_CREATE_PHILOSOPHICAL_SIGNALS = """
CREATE TABLE IF NOT EXISTS philosophical_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    emitted_at TEXT NOT NULL,
    tenant_token TEXT NOT NULL,
    mentor_mesh TEXT NOT NULL,
    quote_text TEXT NOT NULL,
    broadcast_count INTEGER NOT NULL DEFAULT 0,
    source TEXT
)
"""
_CREATE_PHILOSOPHICAL_SIGNALS_IDX = """
CREATE INDEX IF NOT EXISTS idx_philosophical_signals_recent
    ON philosophical_signals (emitted_at DESC, id DESC)
"""
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
_DROP_MISSION_COSTS_VIEW = "DROP VIEW IF EXISTS mission_costs"
_CREATE_MISSION_COSTS_VIEW = """
CREATE VIEW mission_costs AS
SELECT
    e.id AS expedition_id,
    e.timestamp AS expedition_timestamp,
    e.location_name,
    COALESCE(f.flight_expense_usd, 0.0) AS transport_flight_expense_usd,
    COALESCE(c.consumables_cost_usd, 0.0) AS consumables_cost_usd,
    COALESCE(f.flight_expense_usd, 0.0) + COALESCE(c.consumables_cost_usd, 0.0) AS total_mission_cost_usd,
    COALESCE(s.specimen_count, 0) AS specimen_count,
    COALESCE(s.five_star_count, 0) AS five_star_count,
    COALESCE(s.total_estimated_weight_lbs, 0.0) AS total_estimated_weight_lbs
FROM rockhounding_expeditions e
LEFT JOIN (
    SELECT
        substr(timestamp, 1, 10) AS mission_day,
        SUM(COALESCE(gallons_added, 0.0) * 6.75) AS flight_expense_usd
    FROM fuel_logs
    GROUP BY substr(timestamp, 1, 10)
) f ON f.mission_day = substr(e.timestamp, 1, 10)
LEFT JOIN (
    SELECT
        substr(timestamp, 1, 10) AS mission_day,
        SUM(
            CASE
                WHEN item_key = 'oil_quarts' AND delta_quantity < 0 THEN ABS(delta_quantity) * 12.0
                WHEN item_key = 'sample_kits' AND delta_quantity < 0 THEN ABS(delta_quantity) * 18.0
                ELSE 0.0
            END
        ) AS consumables_cost_usd
    FROM mission_consumable_events
    GROUP BY substr(timestamp, 1, 10)
) c ON c.mission_day = substr(e.timestamp, 1, 10)
LEFT JOIN (
    SELECT
        COALESCE(expedition_id, -1) AS expedition_id,
        COUNT(*) AS specimen_count,
        SUM(CASE WHEN yield_stars >= 5 THEN 1 ELSE 0 END) AS five_star_count,
        SUM(COALESCE(estimated_weight_lbs, 0.0)) AS total_estimated_weight_lbs
    FROM specimen_inventory
    GROUP BY COALESCE(expedition_id, -1)
) s ON s.expedition_id = e.id
"""

_DEFAULT_FUEL_COST_PER_GAL_USD = 6.75
_DEFAULT_CONSUMABLE_UNIT_COST_USD = {
    "oil_quarts": 12.0,
    "sample_kits": 18.0,
}
_AI_PULSE_TELEMETRY_WINDOW_HOURS = 24
_AI_PULSE_ACTION_TYPE = "ai_pulse"
_AI_PULSE_ACK_ACTION_TYPE = "ai_pulse_ack"
_EXPEDITION_GUEST_TOKEN_TTL_HOURS = 24
_SPECIMEN_MARKET_RATES_USD_PER_LB = {
    "agate": 16.0,
    "jasper": 14.0,
}
_PRIMARY_ICAO_CODES = ("KIXD", "KUKL")
_PRIMARY_FUEL_TYPE = "100LL"
_FUEL_MARKET_HISTORY_WINDOW = 5
_FUEL_MARKET_FALLBACK_USD = {
    "KIXD": 6.42,
    "KUKL": 6.38,
}
_FUEL_MARKET_API_URL_TEMPLATE = "https://api.aviationapi.com/v1/airports?apt={codes}"
_GEMINI_MODEL = "gemini-1.5-flash"
_GEMINI_API_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
_PAC_AUCTION_EVENT = "PAC_AUCTION"
_ROLE_NORMALISATION = {
    "admin": "Admin",
    "administrator": "Admin",
    "operations director": "Operations Director",
    "operations-director": "Operations Director",
    "operations_director": "Operations Director",
    "org admin": "Operations Director",
    "org-admin": "Operations Director",
    "org_admin": "Operations Director",
    "organization admin": "Operations Director",
    "organisation admin": "Operations Director",
    "lead analyst": "Lead Analyst",
    "lead-analyst": "Lead Analyst",
    "lead_analyst": "Lead Analyst",
    "scientist": "Lead Analyst",
    "guest scientist": "Guest Scientist",
    "guest_scientist": "Guest Scientist",
    "guest-scientist": "Guest Scientist",
    "guest": "Guest Scientist",
    "associate": "Associate",
    "tourist": "Associate",
}
_ROLE_DISPLAY_LABEL = {
    "Admin": "Role: Administrator (Hutch).",
    "Operations Director": "Role: Operations Director.",
    "Lead Analyst": "Role: Lead Analyst.",
    "Guest Scientist": "Role: Guest Scientist (Mentored).",
    "Associate": "Role: Associate.",
}
_GUEST_AUDIT_SCOPES = ["Discovery", "Systems Oracle Audit"]
_GUEST_DEFAULT_MENTOR_MESH = "fungal-outreach"
_LEGACY_PRIMARY_USER_ALIASES = ("joshua", "hutch")
_LEGACY_INACTIVITY_DAYS = 14
_MENTORSHIP_PERMISSION_PROFILES = {
    "Admin": {
        "can_submit_drift": True,
        "can_submit_discovery": True,
        "can_view_honey_hole": True,
        "can_broadcast_philosophical_signal": True,
        "permissions_profile": "admin",
    },
    "Operations Director": {
        "can_submit_drift": True,
        "can_submit_discovery": True,
        "can_view_honey_hole": True,
        "can_broadcast_philosophical_signal": True,
        "permissions_profile": "operations_director",
    },
    "Lead Analyst": {
        "can_submit_drift": True,
        "can_submit_discovery": True,
        "can_view_honey_hole": True,
        "can_broadcast_philosophical_signal": False,
        "permissions_profile": "lead_analyst",
    },
    "Guest Scientist": {
        "can_submit_drift": True,
        "can_submit_discovery": True,
        "can_view_honey_hole": False,
        "can_broadcast_philosophical_signal": False,
        "permissions_profile": "guest_scientist_restricted",
    },
    "Associate": {
        "can_submit_drift": False,
        "can_submit_discovery": False,
        "can_view_honey_hole": False,
        "can_broadcast_philosophical_signal": False,
        "permissions_profile": "associate",
    },
}
_TENANT_ID_SANITIZER = re.compile(r"[^a-z0-9_-]+")
_ORGANIZATION_ID_SANITIZER = re.compile(r"[^a-z0-9_-]+")
_SYSTEMS_ORACLE_MANUSCRIPT_PATH = _ROOT / "data" / "mycology_to_your_ecology_manuscript.txt"
_EXTERNAL_PHILOSOPHY_FILENAME = "external_philosophy.json"
_BRIEFING_LATENCY_THRESHOLD_MS = 100.0
_BRIEFING_LATENCY_LOG_PATH = _ROOT / "outputs" / "briefing_latency_audit.jsonl"

# ── Governance Ledger SQL schemas ─────────────────────────────────────────────
_CREATE_GOVERNANCE_LEDGER = """
CREATE TABLE IF NOT EXISTS governance_ledger (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id       TEXT NOT NULL UNIQUE,
    timestamp      TEXT NOT NULL,
    org_id         TEXT NOT NULL,
    actor          TEXT NOT NULL,
    action_type    TEXT NOT NULL,
    payload_json   TEXT NOT NULL,
    checksum       TEXT NOT NULL,
    rationale_hash TEXT
)
"""
_CREATE_GOVERNANCE_DELETE_GUARD = """
CREATE TRIGGER IF NOT EXISTS governance_ledger_immutable_delete
BEFORE DELETE ON governance_ledger
BEGIN
    SELECT RAISE(ABORT, 'governance_ledger is immutable: DELETE prohibited');
END
"""
_CREATE_GOVERNANCE_UPDATE_GUARD = """
CREATE TRIGGER IF NOT EXISTS governance_ledger_immutable_update
BEFORE UPDATE ON governance_ledger
BEGIN
    SELECT RAISE(ABORT, 'governance_ledger is immutable: UPDATE prohibited');
END
"""
_CREATE_METERED_USAGE = """
CREATE TABLE IF NOT EXISTS metered_usage (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id          TEXT NOT NULL,
    metric          TEXT NOT NULL,
    period          TEXT NOT NULL,
    count           INTEGER NOT NULL DEFAULT 0,
    last_updated_at TEXT NOT NULL,
    UNIQUE(org_id, metric, period)
)
"""
_ORACLE_CALL_RATE_USD = 0.05   # $0.05 per Systems Oracle API call
_EXPEDITION_RATE_USD  = 0.02   # $0.02 per Navigator Expedition

_SYSTEMS_ORACLE_FALLBACK_PRINCIPLES = [
    "Healthy systems move like mycelium through distributed nodes and shared memory.",
    "Administrative drift emerges when one branch hoards load and blocks flow.",
    "Discovery grows at network edges where exploratory probes test uncertain terrain.",
    "Pruning stale pathways restores nutrient flow and resilience.",
]

_MISSION_CONSUMABLE_DEFAULTS = [
    {"item_key": "oil_quarts", "display_name": "Oil Quarts", "quantity": 12.0, "unit": "qt", "restock_threshold": 4.0},
    {"item_key": "sample_kits", "display_name": "Sample Kits", "quantity": 10.0, "unit": "kits", "restock_threshold": 3.0},
    {"item_key": "field_bags", "display_name": "Field Bags", "quantity": 8.0, "unit": "bags", "restock_threshold": 2.0},
]

_HIGH_RISK_SIGNAL_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Equipment Failure": (
        "equipment failure",
        "engine",
        "alternator",
        "hydraulic",
        "avionics failure",
        "brake failure",
        "tailstrike",
    ),
    "Hazardous Weather": (
        "hazardous weather",
        "microburst",
        "wind shear",
        "icing",
        "severe turbulence",
        "hail",
        "thunderstorm",
        "convective",
    ),
    "Safety Incident": (
        "runway incursion",
        "bird strike",
        "near miss",
        "safety incident",
        "emergency diversion",
        "fuel contamination",
    ),
}


def _normalise_user_id(value: object, default: int = 1) -> int:
    try:
        parsed = int(value)
        if parsed > 0:
            return parsed
    except (TypeError, ValueError):
        pass
    return default


def _normalise_tenant_id(value: object, default: str = _DEFAULT_TENANT_ID) -> str:
    token = str(value or "").strip().lower()
    cleaned = _TENANT_ID_SANITIZER.sub("-", token).strip("-")
    if not cleaned:
        fallback = _TENANT_ID_SANITIZER.sub("-", str(default or _DEFAULT_TENANT_ID).strip().lower()).strip("-")
        cleaned = fallback or _DEFAULT_TENANT_ID
    return cleaned[:64]


def _normalise_organization_id(value: object, default: str = _DEFAULT_ORGANIZATION_ID) -> str:
    token = str(value or "").strip().lower()
    cleaned = _ORGANIZATION_ID_SANITIZER.sub("-", token).strip("-")
    if not cleaned:
        fallback = _ORGANIZATION_ID_SANITIZER.sub("-", str(default or _DEFAULT_ORGANIZATION_ID).strip().lower()).strip("-")
        cleaned = fallback or _DEFAULT_ORGANIZATION_ID
    return cleaned[:64]


def _org_tenants_root(organization_id: object | None) -> Path:
    org_id = _normalise_organization_id(organization_id)
    return _ORGANIZATIONS_ROOT / org_id / "tenants"


def _org_tenant_db_path(*, organization_id: object | None, tenant_id: object | None) -> Path:
    resolved_tenant_id = _normalise_tenant_id(tenant_id, default=_DEFAULT_TENANT_ID)
    return _org_tenants_root(organization_id) / resolved_tenant_id / "marine.sqlite"


def _legacy_tenant_db_path(tenant_id: object | None) -> Path:
    resolved_tenant_id = _normalise_tenant_id(tenant_id, default=_DEFAULT_TENANT_ID)
    return _TENANTS_ROOT / resolved_tenant_id / "marine.sqlite"


def _iter_tenant_db_paths() -> list[Path]:
    paths: list[Path] = []

    if _TENANTS_ROOT.exists():
        for tenant_dir in _TENANTS_ROOT.iterdir():
            if not tenant_dir.is_dir():
                continue
            db_path = tenant_dir / "marine.sqlite"
            if db_path.exists():
                paths.append(db_path)

    if _ORGANIZATIONS_ROOT.exists():
        for org_dir in _ORGANIZATIONS_ROOT.iterdir():
            if not org_dir.is_dir():
                continue
            tenants_dir = org_dir / "tenants"
            if not tenants_dir.exists() or not tenants_dir.is_dir():
                continue
            for tenant_dir in tenants_dir.iterdir():
                if not tenant_dir.is_dir():
                    continue
                db_path = tenant_dir / "marine.sqlite"
                if db_path.exists() and db_path not in paths:
                    paths.append(db_path)

    return paths


def _coerce_bool(value: object, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(int(value))

    token = str(value or "").strip().lower()
    if token in {"1", "true", "yes", "y", "on"}:
        return True
    if token in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _tenant_token(tenant_id: object | None) -> str:
    normalised = _normalise_tenant_id(tenant_id)
    digest = hashlib.sha256(normalised.encode("utf-8")).hexdigest()
    return digest[:16]


def _global_node_db_path() -> Path:
    db_path = _GLOBAL_NODE_DB
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return db_path


def _normalise_mentor_mesh(value: object | None, default: str = _GUEST_DEFAULT_MENTOR_MESH) -> str:
    token = str(value or "").strip().lower()
    cleaned = _TENANT_ID_SANITIZER.sub("-", token).strip("-")
    if not cleaned:
        fallback = _TENANT_ID_SANITIZER.sub("-", str(default or _GUEST_DEFAULT_MENTOR_MESH).strip().lower()).strip("-")
        cleaned = fallback or _GUEST_DEFAULT_MENTOR_MESH
    return cleaned[:64]


def _default_role_permissions(role: str) -> dict:
    base = _MENTORSHIP_PERMISSION_PROFILES.get(role, _MENTORSHIP_PERMISSION_PROFILES["Admin"])
    return dict(base)


def _permissions_from_json(value: object, *, role: str) -> dict:
    defaults = _default_role_permissions(role)
    if value in (None, ""):
        return defaults
    try:
        payload = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return defaults
    if not isinstance(payload, dict):
        return defaults
    merged = dict(defaults)
    for key in defaults:
        if key in payload:
            merged[key] = payload.get(key)
    return merged


def _ensure_user_profile_columns(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(user_profiles)").fetchall()}
    if "share_signals" not in cols:
        conn.execute("ALTER TABLE user_profiles ADD COLUMN share_signals INTEGER NOT NULL DEFAULT 0")
    if "created_at" not in cols:
        conn.execute("ALTER TABLE user_profiles ADD COLUMN created_at TEXT NOT NULL DEFAULT ''")
    if "mentor_mesh" not in cols:
        conn.execute("ALTER TABLE user_profiles ADD COLUMN mentor_mesh TEXT")
    if "permissions_json" not in cols:
        conn.execute("ALTER TABLE user_profiles ADD COLUMN permissions_json TEXT")
    conn.commit()


def _ensure_guest_oracle_tables(conn: sqlite3.Connection) -> None:
    _ensure_identity_tables(conn)
    conn.execute(_CREATE_GUEST_ORACLE_SUBMISSIONS)
    conn.execute(_CREATE_GUEST_ORACLE_SUBMISSIONS_IDX)
    conn.commit()


def _ensure_guest_signal_inbox_table(conn: sqlite3.Connection) -> None:
    _ensure_identity_tables(conn)
    conn.execute(_CREATE_GUEST_SIGNAL_INBOX)
    conn.execute(_CREATE_GUEST_SIGNAL_INBOX_IDX)
    conn.commit()


def _ensure_global_node_schema() -> None:
    db_path = _global_node_db_path()
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(_CREATE_OBSERVATORY_SIGNALS)
        conn.execute(_CREATE_OBSERVATORY_SIGNALS_IDX)
        conn.execute(_CREATE_OBSERVATORY_SIGNAL_VOUCHES)
        conn.execute(_CREATE_OBSERVATORY_SIGNAL_VOUCHES_IDX)
        conn.execute(_CREATE_PHILOSOPHICAL_SIGNALS)
        conn.execute(_CREATE_PHILOSOPHICAL_SIGNALS_IDX)
        conn.commit()
    finally:
        conn.close()


def _normalise_signal_type(value: object, default: str = "Specimen") -> str:
    token = str(value or "").strip()
    if not token:
        token = default
    cleaned = re.sub(r"[^A-Za-z0-9\s\-_/]+", "", token).strip()
    return (cleaned or default)[:64]


def _signal_tokens(value: object) -> set[str]:
    cleaned = re.sub(r"[^a-z0-9\s]+", " ", str(value or "").strip().lower())
    return {token for token in cleaned.split() if len(token) >= 3}


def _normalise_region_key(value: object | None) -> str:
    return str(value or "").strip().lower()


def _query_local_signal_profile(tenant_id: object | None = None) -> dict:
    class_counts: dict[str, int] = {}
    region_class_counts: dict[str, dict[str, int]] = {}
    home_base_icao = _PRIMARY_ICAO_CODES[0]

    db_path = _aviation_db_path(tenant_id)
    if not db_path.exists():
        return {
            "class_counts": class_counts,
            "region_class_counts": region_class_counts,
            "sample_count": 0,
        }

    conn = sqlite3.connect(str(db_path))
    try:
        _ensure_identity_tables(conn)
        _ensure_expeditions_table(conn)
        _ensure_specimen_inventory_table(conn)

        row = conn.execute(
            "SELECT home_base_icao FROM user_profiles WHERE id = 1"
        ).fetchone()
        if row and row[0]:
            home_base_icao = str(row[0]).strip().upper()

        rows = conn.execute(
            """
            SELECT s.mineral_class, s.latitude, s.longitude, e.location_name
            FROM specimen_inventory s
            LEFT JOIN rockhounding_expeditions e ON e.id = s.expedition_id
            WHERE s.mineral_class IS NOT NULL
              AND TRIM(s.mineral_class) <> ''
            """
        ).fetchall()
    finally:
        conn.close()

    for row in rows:
        mineral_class = row[0]
        lat = _safe_float(row[1])
        lon = _safe_float(row[2])
        location_name = row[3]
        tokens = _signal_tokens(mineral_class)
        if not tokens:
            continue

        region = _resolve_general_region(
            location_name=location_name,
            latitude=lat,
            longitude=lon,
            home_base_icao=home_base_icao,
        )
        region_key = _normalise_region_key(region)
        region_bucket = region_class_counts.setdefault(region_key, {})

        for token in tokens:
            class_counts[token] = class_counts.get(token, 0) + 1
            region_bucket[token] = region_bucket.get(token, 0) + 1

    return {
        "class_counts": class_counts,
        "region_class_counts": region_class_counts,
        "sample_count": len(rows),
    }


def _count_local_signal_evidence(
    *,
    tenant_id: object | None,
    signal_type: str,
    general_region: str,
    local_profile: dict | None = None,
) -> int:
    profile = local_profile or _query_local_signal_profile(tenant_id=tenant_id)
    tokens = _signal_tokens(signal_type)
    if not tokens:
        return 0

    region_key = _normalise_region_key(general_region)
    class_counts = profile.get("class_counts") or {}
    region_counts = (profile.get("region_class_counts") or {}).get(region_key, {}) if region_key else {}

    class_match = max((int(class_counts.get(token, 0)) for token in tokens), default=0)
    region_match = max((int(region_counts.get(token, 0)) for token in tokens), default=0)
    return max(class_match, region_match)


def signal_probability(
    signal: dict,
    *,
    tenant_id: object | None,
    local_profile: dict | None = None,
) -> dict:
    profile = local_profile or _query_local_signal_profile(tenant_id=tenant_id)
    tokens = _signal_tokens(signal.get("signal_type"))
    region_key = _normalise_region_key(signal.get("general_region"))
    class_counts = profile.get("class_counts") or {}
    region_counts = (profile.get("region_class_counts") or {}).get(region_key, {}) if region_key else {}

    class_match = max((int(class_counts.get(token, 0)) for token in tokens), default=0)
    region_match = max((int(region_counts.get(token, 0)) for token in tokens), default=0)

    if region_match >= 2:
        base_confidence = 100
    elif region_match == 1:
        base_confidence = 88
    elif class_match >= 3:
        base_confidence = 72
    elif class_match >= 1:
        base_confidence = 58
    else:
        base_confidence = 22

    vouch_count = int(signal.get("vouch_count") or 0)
    confidence = min(100, int(round(base_confidence + min(vouch_count * 4, 12))))

    if confidence >= 85:
        status = "Verified"
    elif confidence >= 55:
        status = "Plausible"
    else:
        status = "Anomaly"

    return {
        "status": status,
        "confidence_pct": confidence,
        "class_match_count": class_match,
        "region_match_count": region_match,
    }


def _has_vouched_signal(signal_id: int, tenant_id: object | None) -> bool:
    _ensure_global_node_schema()
    conn = sqlite3.connect(str(_global_node_db_path()))
    try:
        row = conn.execute(
            "SELECT 1 FROM observatory_signal_vouches WHERE signal_id = ? AND tenant_token = ? LIMIT 1",
            (int(signal_id), _tenant_token(tenant_id)),
        ).fetchone()
    finally:
        conn.close()
    return bool(row)


def _record_signal_vouch(*, signal_id: int, tenant_id: object | None, evidence_count: int) -> None:
    _ensure_global_node_schema()
    conn = sqlite3.connect(str(_global_node_db_path()))
    try:
        conn.execute(
            """
            INSERT INTO observatory_signal_vouches (signal_id, tenant_token, vouched_at, evidence_count)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(signal_id, tenant_token) DO NOTHING
            """,
            (
                int(signal_id),
                _tenant_token(tenant_id),
                datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                max(0, int(evidence_count)),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _query_observatory_signal(signal_id: int) -> dict | None:
    _ensure_global_node_schema()
    conn = sqlite3.connect(str(_global_node_db_path()))
    try:
        row = conn.execute(
            """
            SELECT s.id, s.emitted_at, s.tenant_token, s.role_label, s.signal_type, s.general_region,
                   COALESCE(v.vouch_count, 0) AS vouch_count
            FROM observatory_signals s
            LEFT JOIN (
                SELECT signal_id, COUNT(*) AS vouch_count
                FROM observatory_signal_vouches
                GROUP BY signal_id
            ) v ON v.signal_id = s.id
            WHERE s.id = ?
            """,
            (int(signal_id),),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        return None

    return {
        "id": int(row[0]),
        "emitted_at": row[1],
        "tenant_token": row[2],
        "role": row[3],
        "signal_type": row[4],
        "general_region": row[5],
        "vouch_count": int(row[6] or 0),
        "message": f"{row[3]} in {row[5]} found high-yield {row[4]}.",
    }


def _resolve_general_region(
    *,
    location_name: str | None,
    latitude: float | None,
    longitude: float | None,
    home_base_icao: str | None,
) -> str:
    airport_code = None
    for raw_value in (location_name, home_base_icao):
        text = str(raw_value or "").upper()
        match = _AIRPORT_CODE_PATTERN.search(text)
        if match:
            airport_code = match.group(0)
            break

    if not airport_code:
        airport_code = _extract_airport_code(location_name, home_base_icao)
    if not airport_code and latitude is not None and longitude is not None:
        nearest = _nearest_airport_from_coords(latitude, longitude)
        airport_code = str(nearest.get("code") or "").strip().upper() or None
    if not airport_code:
        airport_code = str(home_base_icao or _PRIMARY_ICAO_CODES[0]).strip().upper() or _PRIMARY_ICAO_CODES[0]
    return f"{airport_code} region"


def _query_user_profile(user_id: int, tenant_id: object | None = None) -> dict | None:
    db_path = _aviation_db_path(tenant_id)
    if not db_path.exists():
        return None

    uid = _normalise_user_id(user_id)
    conn = sqlite3.connect(str(db_path))
    try:
        _ensure_identity_tables(conn)
        _ensure_user_profile_columns(conn)
        row = conn.execute(
            """
            SELECT id, username, role, home_base_icao, share_signals, mentor_mesh, permissions_json
            FROM user_profiles
            WHERE id = ?
            """,
            (uid,),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        return None

    return {
        "id": int(row[0]),
        "username": row[1],
        "role": _normalise_user_role(row[2]),
        "home_base_icao": row[3],
        "share_signals": bool(int(row[4] or 0)),
        "mentor_mesh": _normalise_mentor_mesh(row[5], default=_GUEST_DEFAULT_MENTOR_MESH) if row[5] else None,
        "permissions": _permissions_from_json(row[6], role=_normalise_user_role(row[2])),
    }


def _upsert_user_share_signals(*, user_id: int, tenant_id: object | None, share_signals: bool) -> dict:
    db_path = _aviation_db_path(tenant_id)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    uid = _normalise_user_id(user_id)
    share_val = 1 if share_signals else 0

    conn = sqlite3.connect(str(db_path))
    try:
        _ensure_identity_tables(conn)
        _ensure_user_profile_columns(conn)
        existing = conn.execute(
            "SELECT username, role, home_base_icao, mentor_mesh, permissions_json FROM user_profiles WHERE id = ?",
            (uid,),
        ).fetchone()
        if existing is None:
            default_permissions = json.dumps(_default_role_permissions("Lead Analyst"))
            conn.execute(
                """
                INSERT INTO user_profiles (id, username, role, home_base_icao, share_signals, mentor_mesh, permissions_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (uid, f"user-{uid}", "Lead Analyst", _PRIMARY_ICAO_CODES[0], share_val, None, default_permissions),
            )
        else:
            conn.execute(
                "UPDATE user_profiles SET share_signals = ? WHERE id = ?",
                (share_val, uid),
            )
        conn.commit()
    finally:
        conn.close()

    profile = _query_user_profile(uid, tenant_id=tenant_id)
    if profile is None:
        return {
            "id": uid,
            "username": f"user-{uid}",
            "role": "Lead Analyst",
            "home_base_icao": _PRIMARY_ICAO_CODES[0],
            "share_signals": share_signals,
            "mentor_mesh": None,
            "permissions": _default_role_permissions("Lead Analyst"),
        }
    return profile


def mentorship_onboarding(
    *,
    conn: sqlite3.Connection,
    username: str,
    role: str,
    home_base_icao: str,
    scopes: list[str] | None = None,
    user_id: int | None = None,
    share_signals: bool = False,
    mentor_mesh: str | None = None,
) -> dict:
    """Onboard/update a mentor or guest profile with role-aware permissions and scopes."""
    _ensure_identity_tables(conn)
    _ensure_guest_oracle_tables(conn)
    _ensure_guest_signal_inbox_table(conn)

    normalised_role = _normalise_user_role(role)
    scoped_permissions = _default_role_permissions(normalised_role)
    resolved_scopes = [scope for scope in (scopes or []) if str(scope).strip()]
    if normalised_role == "Guest Scientist":
        resolved_scopes = list(_GUEST_AUDIT_SCOPES)
        share_signals = True
        scoped_permissions["allowed_scopes"] = list(_GUEST_AUDIT_SCOPES)
        scoped_permissions["systems_oracle_audit_enabled"] = True

    if not resolved_scopes:
        resolved_scopes = ["Marine", "Aviation", "Mineral"]

    resolved_home_base = (home_base_icao or _PRIMARY_ICAO_CODES[0]).strip().upper() or _PRIMARY_ICAO_CODES[0]
    resolved_mesh = _normalise_mentor_mesh(mentor_mesh, default=_GUEST_DEFAULT_MENTOR_MESH)
    stored_mesh = resolved_mesh if normalised_role == "Guest Scientist" else (resolved_mesh if mentor_mesh else None)
    share_value = 1 if bool(share_signals) else 0
    permissions_blob = json.dumps(scoped_permissions, sort_keys=True)

    if user_id is not None:
        uid = _normalise_user_id(user_id)
        conn.execute(
            """
            INSERT INTO user_profiles (id, username, role, home_base_icao, share_signals, mentor_mesh, permissions_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                username = excluded.username,
                role = excluded.role,
                home_base_icao = excluded.home_base_icao,
                share_signals = excluded.share_signals,
                mentor_mesh = excluded.mentor_mesh,
                permissions_json = excluded.permissions_json
            """,
            (uid, username, normalised_role, resolved_home_base, share_value, stored_mesh, permissions_blob),
        )
    else:
        conn.execute(
            """
            INSERT INTO user_profiles (username, role, home_base_icao, share_signals, mentor_mesh, permissions_json)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(username) DO UPDATE SET
                role = excluded.role,
                home_base_icao = excluded.home_base_icao,
                share_signals = excluded.share_signals,
                mentor_mesh = excluded.mentor_mesh,
                permissions_json = excluded.permissions_json
            """,
            (username, normalised_role, resolved_home_base, share_value, stored_mesh, permissions_blob),
        )

    row = conn.execute("SELECT id FROM user_profiles WHERE username = ?", (username,)).fetchone()
    if row is None:
        raise RuntimeError("Unable to resolve mentorship onboarding user id")
    resolved_user_id = int(row[0])

    for scope in resolved_scopes:
        conn.execute(
            """
            INSERT INTO mission_scopes (user_id, scope_type, is_active)
            VALUES (?, ?, 1)
            ON CONFLICT(user_id, scope_type) DO UPDATE SET
                is_active = 1
            """,
            (resolved_user_id, scope),
        )

    conn.commit()
    return {
        "user_id": resolved_user_id,
        "username": username,
        "role": normalised_role,
        "home_base_icao": resolved_home_base,
        "share_signals": bool(share_value),
        "mentor_mesh": stored_mesh,
        "permissions": scoped_permissions,
        "scopes": resolved_scopes,
    }


def _query_guest_nodes(
    *,
    tenant_id: object | None,
    mentor_mesh: str | None = None,
    active_window_days: int = 7,
) -> list[dict]:
    db_path = _aviation_db_path(tenant_id)
    if not db_path.exists():
        return []

    cutoff_dt = datetime.now(timezone.utc) - timedelta(days=max(1, int(active_window_days or 7)))
    resolved_mesh = _normalise_mentor_mesh(mentor_mesh, default=_GUEST_DEFAULT_MENTOR_MESH) if mentor_mesh else None

    conn = sqlite3.connect(str(db_path))
    try:
        _ensure_identity_tables(conn)
        _ensure_guest_oracle_tables(conn)
        if resolved_mesh:
            rows = conn.execute(
                """
                SELECT u.id, u.username, u.mentor_mesh, u.permissions_json, MAX(g.submitted_at) AS last_submitted_at
                FROM user_profiles u
                LEFT JOIN guest_oracle_submissions g ON g.user_id = u.id
                WHERE LOWER(TRIM(u.role)) = 'guest scientist'
                  AND COALESCE(u.share_signals, 0) = 1
                  AND LOWER(TRIM(COALESCE(u.mentor_mesh, ''))) = ?
                GROUP BY u.id, u.username, u.mentor_mesh, u.permissions_json
                ORDER BY u.id ASC
                """,
                (resolved_mesh,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT u.id, u.username, u.mentor_mesh, u.permissions_json, MAX(g.submitted_at) AS last_submitted_at
                FROM user_profiles u
                LEFT JOIN guest_oracle_submissions g ON g.user_id = u.id
                WHERE LOWER(TRIM(u.role)) = 'guest scientist'
                  AND COALESCE(u.share_signals, 0) = 1
                GROUP BY u.id, u.username, u.mentor_mesh, u.permissions_json
                ORDER BY u.id ASC
                """
            ).fetchall()
    finally:
        conn.close()

    nodes: list[dict] = []
    for row in rows:
        submitted_at = _parse_utc_timestamp(row[4]) if row[4] else None
        is_active = bool(submitted_at and submitted_at >= cutoff_dt)
        nodes.append(
            {
                "user_id": int(row[0]),
                "username": row[1],
                "mentor_mesh": row[2],
                "permissions": _permissions_from_json(row[3], role="Guest Scientist"),
                "last_submitted_at": row[4],
                "is_active": is_active,
            }
        )
    return nodes


def _resolve_primary_user_for_legacy(conn: sqlite3.Connection) -> tuple[int, str]:
    _ensure_identity_tables(conn)
    row = conn.execute(
        """
        SELECT id, username
        FROM user_profiles
        WHERE LOWER(TRIM(COALESCE(username, ''))) IN (?, ?)
        ORDER BY
            CASE
                WHEN LOWER(TRIM(COALESCE(username, ''))) = ? THEN 0
                WHEN LOWER(TRIM(COALESCE(username, ''))) = ? THEN 1
                ELSE 2
            END,
            id ASC
        LIMIT 1
        """,
        (
            _LEGACY_PRIMARY_USER_ALIASES[0],
            _LEGACY_PRIMARY_USER_ALIASES[1],
            _LEGACY_PRIMARY_USER_ALIASES[0],
            _LEGACY_PRIMARY_USER_ALIASES[1],
        ),
    ).fetchone()
    if row is None:
        return 1, "Joshua"

    user_id = _normalise_user_id(row[0], default=1)
    username = str(row[1] or "").strip()
    if not username:
        username = "Joshua"
    return user_id, username


def _query_primary_user_last_active(*, conn: sqlite3.Connection, user_id: int) -> str | None:
    _ensure_expeditions_table(conn)
    _ensure_specimen_inventory_table(conn)
    _ensure_guest_oracle_tables(conn)

    ts_candidates: list[str] = []
    rows = [
        conn.execute(
            "SELECT MAX(timestamp) FROM rockhounding_expeditions WHERE user_id = ?",
            (int(user_id),),
        ).fetchone(),
        conn.execute(
            """
            SELECT MAX(s.timestamp)
            FROM specimen_inventory s
            JOIN rockhounding_expeditions e ON e.id = s.expedition_id
            WHERE e.user_id = ?
            """,
            (int(user_id),),
        ).fetchone(),
        conn.execute(
            "SELECT MAX(submitted_at) FROM guest_oracle_submissions WHERE user_id = ?",
            (int(user_id),),
        ).fetchone(),
    ]

    for row in rows:
        token = str((row or [None])[0] or "").strip()
        if token:
            ts_candidates.append(token)

    if not ts_candidates:
        return None
    return max(ts_candidates)


def _promote_senior_guest_to_temporary_mentor(
    *,
    conn: sqlite3.Connection,
    mentor_mesh: str | None,
) -> dict | None:
    _ensure_identity_tables(conn)
    _ensure_guest_oracle_tables(conn)
    resolved_mesh = _normalise_mentor_mesh(mentor_mesh, default=_GUEST_DEFAULT_MENTOR_MESH) if mentor_mesh else None

    if resolved_mesh:
        row = conn.execute(
            """
            SELECT
                u.id,
                u.username,
                u.mentor_mesh,
                u.permissions_json,
                MAX(g.submitted_at) AS last_submitted_at,
                COUNT(g.id) AS submission_count
            FROM user_profiles u
            LEFT JOIN guest_oracle_submissions g ON g.user_id = u.id
            WHERE LOWER(TRIM(u.role)) = 'guest scientist'
              AND COALESCE(u.share_signals, 0) = 1
              AND LOWER(TRIM(COALESCE(u.mentor_mesh, ''))) = ?
            GROUP BY u.id, u.username, u.mentor_mesh, u.permissions_json
            ORDER BY
                CASE WHEN LOWER(TRIM(COALESCE(u.username, ''))) LIKE '%senior%' THEN 0 ELSE 1 END,
                CASE WHEN LOWER(TRIM(COALESCE(u.username, ''))) LIKE '%alpha%' THEN 0 ELSE 1 END,
                COALESCE(MAX(g.submitted_at), '') DESC,
                COUNT(g.id) DESC,
                u.id ASC
            LIMIT 1
            """,
            (resolved_mesh,),
        ).fetchone()
    else:
        row = conn.execute(
            """
            SELECT
                u.id,
                u.username,
                u.mentor_mesh,
                u.permissions_json,
                MAX(g.submitted_at) AS last_submitted_at,
                COUNT(g.id) AS submission_count
            FROM user_profiles u
            LEFT JOIN guest_oracle_submissions g ON g.user_id = u.id
            WHERE LOWER(TRIM(u.role)) = 'guest scientist'
              AND COALESCE(u.share_signals, 0) = 1
            GROUP BY u.id, u.username, u.mentor_mesh, u.permissions_json
            ORDER BY
                CASE WHEN LOWER(TRIM(COALESCE(u.username, ''))) LIKE '%senior%' THEN 0 ELSE 1 END,
                CASE WHEN LOWER(TRIM(COALESCE(u.username, ''))) LIKE '%alpha%' THEN 0 ELSE 1 END,
                COALESCE(MAX(g.submitted_at), '') DESC,
                COUNT(g.id) DESC,
                u.id ASC
            LIMIT 1
            """
        ).fetchone()

    if row is None:
        return None

    guest_id = _normalise_user_id(row[0], default=1)
    guest_username = str(row[1] or f"guest-{guest_id}").strip() or f"guest-{guest_id}"
    guest_mesh = _normalise_mentor_mesh(row[2], default=_GUEST_DEFAULT_MENTOR_MESH) if row[2] else _GUEST_DEFAULT_MENTOR_MESH
    permissions = _permissions_from_json(row[3], role="Guest Scientist")
    permissions["can_submit_drift"] = True
    permissions["can_submit_discovery"] = True
    permissions["can_broadcast_philosophical_signal"] = True
    permissions["systems_oracle_audit_enabled"] = True
    permissions["temporary_mentor"] = True
    permissions["permissions_profile"] = "temporary_mentor_guest"
    permissions["allowed_scopes"] = list(_GUEST_AUDIT_SCOPES)

    conn.execute(
        """
        UPDATE user_profiles
        SET mentor_mesh = ?,
            permissions_json = ?,
            share_signals = 1
        WHERE id = ?
        """,
        (guest_mesh, json.dumps(permissions, sort_keys=True), guest_id),
    )
    conn.commit()

    return {
        "user_id": guest_id,
        "username": guest_username,
        "mentor_mesh": guest_mesh,
        "status": "temporary_mentor",
        "last_submitted_at": row[4],
        "submission_count": int(row[5] or 0),
    }


def legacy_heartbeat_check(
    *,
    tenant_id: object | None,
    tenant_slug: str | None = None,
    inactivity_days: int = _LEGACY_INACTIVITY_DAYS,
    mentor_mesh: str | None = None,
) -> dict:
    threshold = max(1, int(inactivity_days or _LEGACY_INACTIVITY_DAYS))
    now_utc = datetime.now(timezone.utc)
    db_path = _aviation_db_path(tenant_id)

    conn = sqlite3.connect(str(db_path))
    try:
        _ensure_identity_tables(conn)
        primary_user_id, primary_username = _resolve_primary_user_for_legacy(conn)
        last_active_raw = _query_primary_user_last_active(conn=conn, user_id=primary_user_id)
        last_active_dt = _parse_utc_timestamp(last_active_raw) if last_active_raw else None

        if last_active_dt is None:
            days_since_activity = threshold + 1
        else:
            delta_days = int((now_utc - last_active_dt).total_seconds() // 86400)
            days_since_activity = max(0, delta_days)

        is_legacy_mode = days_since_activity > threshold
        promoted_guest = None
        if is_legacy_mode:
            promoted_guest = _promote_senior_guest_to_temporary_mentor(
                conn=conn,
                mentor_mesh=mentor_mesh,
            )
    finally:
        conn.close()

    legacy_label = (
        "Lighthouse Status: Market Standard. The Mesh is the Industry. Joshua R Hutchison: Founder & Architect."
        if is_legacy_mode
        else "Lighthouse Status: Primary Active. Legacy Protocol Standing By."
    )
    return {
        "status": "LEGACY_MODE" if is_legacy_mode else "PRIMARY_ACTIVE",
        "is_legacy_mode": is_legacy_mode,
        "label": legacy_label,
        "autonomous_quorum_enabled": is_legacy_mode,
        "inactivity_threshold_days": threshold,
        "days_since_primary_activity": days_since_activity,
        "last_primary_activity_at": last_active_raw,
        "primary_user": {
            "id": primary_user_id,
            "username": primary_username,
            "display_name": "Joshua",
        },
        "temporary_mentor": promoted_guest,
    }


def _insert_guest_oracle_submission(
    *,
    tenant_id: object | None,
    user_id: int,
    submission_type: str,
    drift_pct: float | None,
    discovery_note: str | None,
    private_location_label: str | None,
    private_latitude: float | None,
    private_longitude: float | None,
    source: str = "api",
) -> dict:
    db_path = _aviation_db_path(tenant_id)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    uid = _normalise_user_id(user_id)
    submitted_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    submission_kind = (submission_type or "DISCOVERY").strip().upper()

    conn = sqlite3.connect(str(db_path))
    try:
        _ensure_guest_oracle_tables(conn)
        cur = conn.execute(
            """
            INSERT INTO guest_oracle_submissions (
                user_id, submission_type, drift_pct, discovery_note,
                private_location_label, private_latitude, private_longitude,
                submitted_at, source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uid,
                submission_kind,
                drift_pct,
                discovery_note,
                private_location_label,
                private_latitude,
                private_longitude,
                submitted_at,
                source,
            ),
        )
        conn.commit()
        row_id = int(cur.lastrowid)
    finally:
        conn.close()

    return {
        "id": row_id,
        "user_id": uid,
        "submission_type": submission_kind,
        "drift_pct": drift_pct,
        "discovery_note": discovery_note,
        "private_location_label": private_location_label,
        "private_latitude": private_latitude,
        "private_longitude": private_longitude,
        "submitted_at": submitted_at,
        "source": source,
    }


def _query_guest_oracle_submissions_for_user(
    *,
    tenant_id: object | None,
    user_id: int,
    limit: int = 25,
) -> list[dict]:
    db_path = _aviation_db_path(tenant_id)
    if not db_path.exists():
        return []

    uid = _normalise_user_id(user_id)
    conn = sqlite3.connect(str(db_path))
    try:
        _ensure_guest_oracle_tables(conn)
        rows = conn.execute(
            """
            SELECT id, user_id, submission_type, drift_pct, discovery_note, submitted_at, source
            FROM guest_oracle_submissions
            WHERE user_id = ?
            ORDER BY submitted_at DESC, id DESC
            LIMIT ?
            """,
            (uid, max(1, min(int(limit or 25), 250))),
        ).fetchall()
    finally:
        conn.close()

    return [
        {
            "id": int(row[0]),
            "user_id": int(row[1]),
            "submission_type": row[2],
            "drift_pct": _safe_float(row[3]),
            "discovery_note": row[4],
            "submitted_at": row[5],
            "source": row[6],
        }
        for row in rows
    ]


def _query_network_health(*, tenant_id: object | None, mentor_mesh: str | None = None) -> dict:
    nodes = _query_guest_nodes(tenant_id=tenant_id, mentor_mesh=mentor_mesh, active_window_days=7)
    active_nodes = [node for node in nodes if bool(node.get("is_active"))]

    db_path = _aviation_db_path(tenant_id)
    drift_samples: list[float] = []
    discovery_count = 0
    if db_path.exists() and active_nodes:
        node_ids = [int(node.get("user_id") or 0) for node in active_nodes if int(node.get("user_id") or 0) > 0]
        placeholders = ",".join(["?"] * len(node_ids))
        if placeholders:
            conn = sqlite3.connect(str(db_path))
            try:
                _ensure_guest_oracle_tables(conn)
                cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
                rows = conn.execute(
                    f"""
                    SELECT submission_type, drift_pct, discovery_note
                    FROM guest_oracle_submissions
                    WHERE submitted_at >= ?
                      AND user_id IN ({placeholders})
                    """,
                    [cutoff, *node_ids],
                ).fetchall()
            finally:
                conn.close()

            for row in rows:
                drift_value = _safe_float(row[1])
                if drift_value is not None:
                    drift_samples.append(max(0.0, min(100.0, float(drift_value))))
                note = str(row[2] or "").strip()
                if note:
                    discovery_count += 1

    global_card = _build_global_node_card(tenant_id=tenant_id, limit=3)
    base_integrity = float(global_card.get("mesh_integrity_pct") or 100.0)
    if active_nodes:
        base_integrity = max(base_integrity, 82.0)
    avg_drift = (sum(drift_samples) / len(drift_samples)) if drift_samples else 0.0
    drift_penalty = min(25.0, avg_drift * 0.8)
    discovery_bonus = min(12.0, float(discovery_count) * 1.5)
    node_bonus = min(8.0, float(len(active_nodes)) * 1.2)
    mesh_integrity = int(max(0.0, min(100.0, round(base_integrity - drift_penalty + discovery_bonus + node_bonus))))

    if active_nodes and mesh_integrity >= 75:
        status = "FLOURISHING"
        status_label = "Network Status: Flourishing."
    elif active_nodes:
        status = "STABILIZING"
        status_label = "Network Status: Stabilizing."
    else:
        status = "DORMANT"
        status_label = "Network Status: Dormant."

    return {
        "status": status,
        "status_label": status_label,
        "active_guest_nodes": len(active_nodes),
        "guest_nodes_total": len(nodes),
        "mesh_integrity_pct": mesh_integrity,
        "mesh_integrity_label": f"Mesh Integrity: {mesh_integrity}%.",
        "network_health_label": f"Network Health: {mesh_integrity}%.",
        "discovery_count_7d": discovery_count,
        "avg_drift_pct_7d": round(avg_drift, 1),
        "mentor_mesh": _normalise_mentor_mesh(mentor_mesh, default=_GUEST_DEFAULT_MENTOR_MESH) if mentor_mesh else None,
    }


def _query_active_mission_scopes(*, tenant_id: object | None, user_id: int) -> list[str]:
    db_path = _aviation_db_path(tenant_id)
    if not db_path.exists():
        return []

    uid = _normalise_user_id(user_id)
    conn = sqlite3.connect(str(db_path))
    try:
        _ensure_identity_tables(conn)
        rows = conn.execute(
            """
            SELECT scope_type
            FROM mission_scopes
            WHERE user_id = ?
              AND COALESCE(is_active, 0) = 1
            ORDER BY scope_type ASC
            """,
            (uid,),
        ).fetchall()
    finally:
        conn.close()

    return [str(row[0]).strip() for row in rows if str(row[0] or "").strip()]


def _derive_writable_scopes(*, profile: dict, active_scopes: list[str]) -> list[str]:
    role = str(profile.get("role") or "Admin")
    permissions = profile.get("permissions") or _default_role_permissions(role)

    writable: set[str] = set()
    if bool(permissions.get("can_submit_discovery")):
        writable.update(active_scopes)
        writable.update({"Discovery", "Marine", "Aviation", "Mineral"})
    if bool(permissions.get("can_submit_drift")):
        writable.add("Systems Oracle Audit")
        writable.add("Discovery")
    if role in {"Admin", "Operations Director"}:
        writable.update({"Discovery", "Marine", "Aviation", "Mineral", "Systems Oracle Audit"})

    return sorted(scope for scope in writable if scope)


def _classify_workflow_pattern(*, submission_type: str, discovery_note: str | None) -> dict:
    kind = str(submission_type or "").upper()
    note = str(discovery_note or "").strip().lower()

    if "DRIFT" in kind:
        return {
            "pattern_key": "oracle_drift_review_pruner",
            "required_scope": "Systems Oracle Audit",
            "pattern_label": "Oracle drift review triage",
        }

    keyword_patterns = [
        (("invoice", "admin", "paperwork", "calendar", "follow-up", "backlog"), "admin_backlog_pruner", "Discovery", "administrative backlog triage"),
        (("marine", "reef", "ocean", "buoy", "sst"), "marine_snapshot_pruner", "Marine", "marine snapshot consolidation"),
        (("flight", "aviation", "hangar", "preflight", "tail"), "aviation_ops_pruner", "Aviation", "aviation ops prep consolidation"),
        (("specimen", "mineral", "agate", "jasper", "ore", "rock"), "mineral_catalog_pruner", "Mineral", "specimen catalog normalization"),
    ]
    for keywords, key, scope, label in keyword_patterns:
        if any(token in note for token in keywords):
            return {
                "pattern_key": key,
                "required_scope": scope,
                "pattern_label": label,
            }

    return {
        "pattern_key": "discovery_log_pruner",
        "required_scope": "Discovery",
        "pattern_label": "discovery log hygiene",
    }


def _query_mesh_bottlenecks(
    *,
    tenant_id: object | None,
    mentor_mesh: str | None,
    horizon_days: int = 30,
) -> dict:
    resolved_mesh = _normalise_mentor_mesh(mentor_mesh, default=_GUEST_DEFAULT_MENTOR_MESH)
    nodes = _query_guest_nodes(tenant_id=tenant_id, mentor_mesh=resolved_mesh, active_window_days=30)
    if not nodes:
        return {
            "label": "Mesh Bottlenecks: Insufficient mesh drift signatures.",
            "top_patterns": [],
            "mentor_mesh": resolved_mesh,
            "horizon_days": max(1, int(horizon_days or 30)),
        }

    db_path = _aviation_db_path(tenant_id)
    if not db_path.exists():
        return {
            "label": "Mesh Bottlenecks: Insufficient mesh drift signatures.",
            "top_patterns": [],
            "mentor_mesh": resolved_mesh,
            "horizon_days": max(1, int(horizon_days or 30)),
        }

    node_ids = [int(node.get("user_id") or 0) for node in nodes if int(node.get("user_id") or 0) > 0]
    if not node_ids:
        return {
            "label": "Mesh Bottlenecks: Insufficient mesh drift signatures.",
            "top_patterns": [],
            "mentor_mesh": resolved_mesh,
            "horizon_days": max(1, int(horizon_days or 30)),
        }

    cutoff = (datetime.now(timezone.utc) - timedelta(days=max(1, int(horizon_days or 30)))).strftime("%Y-%m-%dT%H:%M:%SZ")
    placeholders = ",".join(["?"] * len(node_ids))
    conn = sqlite3.connect(str(db_path))
    try:
        _ensure_guest_oracle_tables(conn)
        rows = conn.execute(
            f"""
            SELECT submission_type, discovery_note
            FROM guest_oracle_submissions
            WHERE submitted_at >= ?
              AND user_id IN ({placeholders})
            """,
            [cutoff, *node_ids],
        ).fetchall()
    finally:
        conn.close()

    counts: dict[str, int] = {}
    for row in rows:
        classified = _classify_workflow_pattern(
            submission_type=str(row[0] or ""),
            discovery_note=row[1],
        )
        label = str(classified.get("pattern_label") or "workflow drift")
        counts[label] = counts.get(label, 0) + 1

    ranked = sorted(counts.items(), key=lambda item: item[1], reverse=True)[:3]
    top_patterns = [{"pattern_label": label, "count": count} for label, count in ranked]
    if top_patterns:
        summary = ", ".join(f"{row['pattern_label']} ({row['count']})" for row in top_patterns)
        label = f"Mesh Bottlenecks: {summary}."
    else:
        label = "Mesh Bottlenecks: Insufficient mesh drift signatures."

    return {
        "label": label,
        "top_patterns": top_patterns,
        "mentor_mesh": resolved_mesh,
        "horizon_days": max(1, int(horizon_days or 30)),
    }


def suggest_workflow_automation(
    *,
    tenant_id: object | None,
    user_id: int,
    horizon_days: int = 30,
    mentor_mesh: str | None = None,
) -> dict:
    uid = _normalise_user_id(user_id)
    profile = _query_user_profile(uid, tenant_id=tenant_id) or {
        "id": uid,
        "role": "Admin",
        "permissions": _default_role_permissions("Admin"),
        "mentor_mesh": None,
    }
    active_scopes = _query_active_mission_scopes(tenant_id=tenant_id, user_id=uid)
    writable_scopes = _derive_writable_scopes(profile=profile, active_scopes=active_scopes)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max(1, int(horizon_days or 30)))).strftime("%Y-%m-%dT%H:%M:%SZ")

    db_path = _aviation_db_path(tenant_id)
    rows: list[tuple] = []
    if db_path.exists():
        conn = sqlite3.connect(str(db_path))
        try:
            _ensure_guest_oracle_tables(conn)
            rows = conn.execute(
                """
                SELECT submission_type, drift_pct, discovery_note, submitted_at
                FROM guest_oracle_submissions
                WHERE user_id = ?
                  AND submitted_at >= ?
                ORDER BY submitted_at DESC, id DESC
                """,
                (uid, cutoff),
            ).fetchall()
        finally:
            conn.close()

    pattern_rollup: dict[str, dict] = {}
    for row in rows:
        classified = _classify_workflow_pattern(
            submission_type=str(row[0] or ""),
            discovery_note=row[2],
        )
        key = str(classified.get("pattern_key") or "discovery_log_pruner")
        bucket = pattern_rollup.setdefault(
            key,
            {
                "pattern_key": key,
                "pattern_label": str(classified.get("pattern_label") or "workflow drift"),
                "required_scope": str(classified.get("required_scope") or "Discovery"),
                "occurrences": 0,
                "drift_samples": [],
            },
        )
        bucket["occurrences"] = int(bucket.get("occurrences") or 0) + 1
        drift_value = _safe_float(row[1])
        if drift_value is not None:
            bucket["drift_samples"].append(float(drift_value))

    suggestions: list[dict] = []
    for bucket in pattern_rollup.values():
        occurrences = int(bucket.get("occurrences") or 0)
        if occurrences <= 0:
            continue
        weekly_hours = max(0.5, round((occurrences / max(1, int(horizon_days or 30))) * 7.0 * 0.5, 1))
        drift_samples = bucket.get("drift_samples") or []
        avg_drift = round(sum(drift_samples) / len(drift_samples), 1) if drift_samples else 0.0
        pattern_label = str(bucket.get("pattern_label") or "workflow drift")
        proposal = (
            f"I notice you spend {weekly_hours:.1f} hours/week on {pattern_label}; "
            "would you like me to build a pruner for it?"
        )
        suggestions.append(
            {
                "key": bucket.get("pattern_key"),
                "pattern_label": pattern_label,
                "required_scope": str(bucket.get("required_scope") or "Discovery"),
                "occurrences": occurrences,
                "hours_per_week": weekly_hours,
                "avg_drift_pct": avg_drift,
                "proposal": proposal,
            }
        )

    suggestions.sort(
        key=lambda row: (
            int(row.get("occurrences") or 0),
            float(row.get("avg_drift_pct") or 0.0),
        ),
        reverse=True,
    )
    authorized = [row for row in suggestions if str(row.get("required_scope") or "") in set(writable_scopes)]
    filtered_unauthorized_count = max(0, len(suggestions) - len(authorized))
    primary = authorized[0] if authorized else None
    collective = _query_mesh_bottlenecks(
        tenant_id=tenant_id,
        mentor_mesh=mentor_mesh or profile.get("mentor_mesh"),
        horizon_days=horizon_days,
    )

    return {
        "status": "ENABLED",
        "architect_mode_label": "Architect Mode: Enabled. Suggestions Pending.",
        "proposed_automation_label": (
            f"Proposed Automation: {primary.get('pattern_label')}" if primary else "Proposed Automation: Awaiting recurring drift signatures."
        ),
        "proposal_message": (
            str(primary.get("proposal") or "") if primary else "Collecting 30-day drift cadence before recommending a targeted pruner."
        ),
        "suggestions": authorized,
        "primary_suggestion_key": primary.get("key") if primary else None,
        "writable_scopes": writable_scopes,
        "write_permission_verified": all(str(row.get("required_scope") or "") in set(writable_scopes) for row in authorized),
        "filtered_unauthorized_count": filtered_unauthorized_count,
        "collective_intelligence": collective,
        "can_deploy": bool(primary),
        "horizon_days": max(1, int(horizon_days or 30)),
    }


def _deploy_suggested_pruner(*, tenant_id: object | None, user_id: int, suggestion: dict) -> dict:
    uid = _normalise_user_id(user_id)
    tenant_norm = _normalise_tenant_id(tenant_id)
    key = str(suggestion.get("key") or "workflow_pruner")
    scope = str(suggestion.get("required_scope") or "Discovery")
    label = str(suggestion.get("pattern_label") or "workflow drift")

    generated_dir = _ROOT / "scripts" / "generated"
    generated_dir.mkdir(parents=True, exist_ok=True)
    script_path = generated_dir / f"auto_pruner_{key}_{tenant_norm}_u{uid}.py"
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    content = (
        '"""Auto-generated by HutchSolves Architect Mode.\n\n'
        f"Scope: {scope}\n"
        f"Pattern: {label}\n"
        f"Generated: {generated_at}\n"
        '"""\n\n'
        "from __future__ import annotations\n\n"
        "import json\n"
        "from datetime import datetime, timezone\n\n"
        "def run() -> None:\n"
        f"    payload = {{\"status\": \"ready\", \"scope\": {scope!r}, \"pattern\": {label!r}, \"generated_at\": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}}\n"
        "    print(json.dumps(payload))\n\n"
        "if __name__ == \"__main__\":\n"
        "    run()\n"
    )
    script_path.write_text(content, encoding="utf-8")

    return {
        "status": "deployed",
        "script_path": str(script_path.relative_to(_ROOT)).replace("\\", "/"),
        "scope": scope,
        "pattern_label": label,
        "generated_at": generated_at,
    }


def _write_sandbox_execution_script(*, tenant_id: object | None, user_id: int, suggestion: dict) -> Path:
    uid = _normalise_user_id(user_id)
    tenant_norm = _normalise_tenant_id(tenant_id)
    scope = str(suggestion.get("required_scope") or "Discovery")
    label = str(suggestion.get("pattern_label") or "workflow drift")
    key = str(suggestion.get("key") or "workflow_pruner")
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    generated_dir = _ROOT / "scripts" / "generated"
    generated_dir.mkdir(parents=True, exist_ok=True)
    script_path = generated_dir / "sandbox_execution.py"
    content = (
        '"""Sandbox execution generated by HutchSolves Architect Mode.\n\n'
        "Dry-run only. No persistent writes are permitted from this script.\n"
        '"""\n\n'
        "from __future__ import annotations\n\n"
        "import json\n"
        "import os\n"
        "from datetime import datetime, timezone\n\n"
        "def run() -> None:\n"
        "    payload = {\n"
        "        \"mode\": \"dry_run\",\n"
        f"        \"tenant_id\": {tenant_norm!r},\n"
        f"        \"user_id\": {uid},\n"
        f"        \"suggestion_key\": {key!r},\n"
        f"        \"scope\": {scope!r},\n"
        f"        \"pattern_label\": {label!r},\n"
        f"        \"generated_at\": {generated_at!r},\n"
        "        \"executed_at\": datetime.now(timezone.utc).strftime(\"%Y-%m-%dT%H:%M:%SZ\"),\n"
        "        \"safe_virtual_env\": bool(os.environ.get(\"VIRTUAL_ENV\") or os.environ.get(\"CORTEX_SANDBOX_MODE\")),\n"
        "        \"actions\": [\n"
        "            \"scan_recent_submissions\",\n"
        "            \"classify_pruning_targets\",\n"
        "            \"simulate_prune_plan\",\n"
        "        ],\n"
        "        \"result\": \"simulation_complete\",\n"
        "    }\n"
        "    print(json.dumps(payload))\n\n"
        "if __name__ == \"__main__\":\n"
        "    run()\n"
    )
    script_path.write_text(content, encoding="utf-8")
    return script_path


def _dry_run_suggested_pruner(*, tenant_id: object | None, user_id: int, suggestion: dict) -> dict:
    script_path = _write_sandbox_execution_script(
        tenant_id=tenant_id,
        user_id=user_id,
        suggestion=suggestion,
    )
    env = os.environ.copy()
    env["CORTEX_SANDBOX_MODE"] = "1"
    result = subprocess.run(
        [sys.executable, str(script_path)],
        cwd=str(_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    parsed_output: dict | str
    if stdout:
        try:
            parsed_output = json.loads(stdout)
        except json.JSONDecodeError:
            parsed_output = stdout
    else:
        parsed_output = ""

    return {
        "status": "dry_run_complete" if result.returncode == 0 else "dry_run_failed",
        "return_code": int(result.returncode),
        "sandbox_script_path": str(script_path.relative_to(_ROOT)).replace("\\", "/"),
        "stdout": parsed_output,
        "stderr": stderr,
    }


def _broadcast_philosophical_signal(
    *,
    tenant_id: object | None,
    mentor_mesh: str | None,
    quote_text: str,
    source: str = "api",
) -> dict:
    _ensure_global_node_schema()
    resolved_mesh = _normalise_mentor_mesh(mentor_mesh, default=_GUEST_DEFAULT_MENTOR_MESH)
    trimmed_quote = str(quote_text or "").strip()
    if not trimmed_quote:
        raise ValueError("quote_text is required")
    quote = trimmed_quote[:600]

    tenant_token = _tenant_token(tenant_id)
    emitted_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    global_conn = sqlite3.connect(str(_global_node_db_path()))
    try:
        _ensure_global_node_schema()
        cur = global_conn.execute(
            """
            INSERT INTO philosophical_signals (emitted_at, tenant_token, mentor_mesh, quote_text, broadcast_count, source)
            VALUES (?, ?, ?, ?, 0, ?)
            """,
            (emitted_at, tenant_token, resolved_mesh, quote, source),
        )
        signal_id = int(cur.lastrowid)
        global_conn.commit()
    finally:
        global_conn.close()

    target_count = 0
    for db_path in _iter_tenant_db_paths():
        conn = sqlite3.connect(str(db_path))
        try:
            _ensure_guest_signal_inbox_table(conn)
            rows = conn.execute(
                """
                SELECT id
                FROM user_profiles
                WHERE LOWER(TRIM(role)) = 'guest scientist'
                  AND COALESCE(share_signals, 0) = 1
                  AND LOWER(TRIM(COALESCE(mentor_mesh, ''))) = ?
                """,
                (resolved_mesh,),
            ).fetchall()

            for row in rows:
                conn.execute(
                    """
                    INSERT INTO guest_signal_inbox (user_id, tenant_token, signal_kind, message, emitted_at, source, is_read)
                    VALUES (?, ?, 'PHILOSOPHICAL_SIGNAL', ?, ?, ?, 0)
                    """,
                    (int(row[0]), tenant_token, quote, emitted_at, source),
                )
                target_count += 1

            conn.commit()
        finally:
            conn.close()

    global_conn = sqlite3.connect(str(_global_node_db_path()))
    try:
        global_conn.execute(
            "UPDATE philosophical_signals SET broadcast_count = ? WHERE id = ?",
            (target_count, signal_id),
        )
        global_conn.commit()
    finally:
        global_conn.close()

    return {
        "id": signal_id,
        "emitted_at": emitted_at,
        "mentor_mesh": resolved_mesh,
        "quote_text": quote,
        "broadcast_count": target_count,
        "status": "BROADCAST",
    }


def _emit_observatory_signal(
    *,
    tenant_id: object | None,
    user_id: int,
    signal_type: str | None,
    location_name: str | None,
    latitude: float | None,
    longitude: float | None,
    user_role: str | None = None,
    general_region: str | None = None,
    source: str = "api",
) -> dict:
    profile = _query_user_profile(_normalise_user_id(user_id), tenant_id=tenant_id)
    if profile is None:
        return {"status": "skipped", "reason": "user_not_found"}

    legacy_state = legacy_heartbeat_check(
        tenant_id=tenant_id,
        inactivity_days=_LEGACY_INACTIVITY_DAYS,
        mentor_mesh=profile.get("mentor_mesh"),
    )
    autonomous_quorum_enabled = bool(legacy_state.get("autonomous_quorum_enabled"))

    if not profile.get("share_signals") and not autonomous_quorum_enabled:
        return {"status": "skipped", "reason": "share_signals_disabled"}

    tenant_token = _tenant_token(tenant_id)
    role_label = _normalise_user_role(user_role or profile.get("role") or "Lead Analyst")
    signal_label = _normalise_signal_type(signal_type or "Specimen")
    region_label = (
        str(general_region).strip()
        if str(general_region or "").strip()
        else _resolve_general_region(
            location_name=location_name,
            latitude=latitude,
            longitude=longitude,
            home_base_icao=profile.get("home_base_icao"),
        )
    )
    emitted_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    _ensure_global_node_schema()
    conn = sqlite3.connect(str(_global_node_db_path()))
    try:
        cur = conn.execute(
            """
            INSERT INTO observatory_signals (
                emitted_at, tenant_token, role_label, signal_type, general_region, source
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (emitted_at, tenant_token, role_label, signal_label, region_label, source),
        )
        conn.commit()
        signal_id = int(cur.lastrowid)
    finally:
        conn.close()

    evidence_count = 0
    auto_verified = False
    if autonomous_quorum_enabled:
        evidence_count = _count_local_signal_evidence(
            tenant_id=tenant_id,
            signal_type=signal_label,
            general_region=region_label,
        )
        already_vouched = _has_vouched_signal(signal_id, tenant_id=tenant_id)
        if evidence_count > 0 and not already_vouched:
            _record_signal_vouch(signal_id=signal_id, tenant_id=tenant_id, evidence_count=evidence_count)
            auto_verified = True

    refreshed_signal = _query_observatory_signal(signal_id) or {
        "id": signal_id,
        "emitted_at": emitted_at,
        "tenant_token": tenant_token,
        "role": role_label,
        "signal_type": signal_label,
        "general_region": region_label,
        "vouch_count": 0,
    }
    probability = signal_probability(refreshed_signal, tenant_id=tenant_id)

    signal_payload = {
        "id": signal_id,
        "tenant_id": _normalise_tenant_id(tenant_id),
        "emitted_at": emitted_at,
        "role": role_label,
        "signal_type": signal_label,
        "general_region": region_label,
        "vouch_count": int(refreshed_signal.get("vouch_count") or 0),
        "probability_status": probability.get("status") or "Anomaly",
        "confidence_pct": int(probability.get("confidence_pct") or 0),
        "autonomous_quorum_enabled": autonomous_quorum_enabled,
        "auto_verified": auto_verified,
        "evidence_count": evidence_count,
        "message": f"{role_label} in {region_label} found high-yield {signal_label}.",
    }
    _emit_realtime("observatory_signal", signal_payload)

    return {
        "status": "created",
        "signal": signal_payload,
    }


def _query_global_discovery_feed(*, tenant_id: object | None, limit: int = 3) -> list[dict]:
    _ensure_global_node_schema()
    exclude_token = _tenant_token(tenant_id)
    capped_limit = max(1, min(int(limit or 3), 10))

    conn = sqlite3.connect(str(_global_node_db_path()))
    try:
        rows = conn.execute(
            """
            SELECT s.id, s.emitted_at, s.role_label, s.signal_type, s.general_region,
                   COALESCE(v.vouch_count, 0) AS vouch_count
            FROM observatory_signals s
            LEFT JOIN (
                SELECT signal_id, COUNT(*) AS vouch_count
                FROM observatory_signal_vouches
                GROUP BY signal_id
            ) v ON v.signal_id = s.id
            WHERE s.tenant_token <> ?
            ORDER BY s.emitted_at DESC, s.id DESC
            LIMIT ?
            """,
            (exclude_token, capped_limit),
        ).fetchall()
    finally:
        conn.close()

    return [
        {
            "id": int(row[0]),
            "emitted_at": row[1],
            "role": row[2],
            "signal_type": row[3],
            "general_region": row[4],
            "vouch_count": int(row[5] or 0),
            "message": f"{row[2]} in {row[4]} found high-yield {row[3]}.",
        }
        for row in rows
    ]


def _build_global_node_card(*, tenant_id: object | None, limit: int = 3) -> dict:
    local_profile = _query_local_signal_profile(tenant_id=tenant_id)
    legacy_state = legacy_heartbeat_check(tenant_id=tenant_id, inactivity_days=_LEGACY_INACTIVITY_DAYS)
    autonomous_quorum_enabled = bool(legacy_state.get("autonomous_quorum_enabled"))
    signals = _query_global_discovery_feed(tenant_id=tenant_id, limit=limit)
    enriched_signals: list[dict] = []
    confidence_values: list[int] = []

    for signal in signals:
        evidence_count = _count_local_signal_evidence(
            tenant_id=tenant_id,
            signal_type=str(signal.get("signal_type") or ""),
            general_region=str(signal.get("general_region") or ""),
            local_profile=local_profile,
        )
        already_vouched = _has_vouched_signal(int(signal.get("id") or 0), tenant_id=tenant_id)
        if autonomous_quorum_enabled and evidence_count > 0 and not already_vouched:
            _record_signal_vouch(
                signal_id=int(signal.get("id") or 0),
                tenant_id=tenant_id,
                evidence_count=evidence_count,
            )
            refreshed_signal = _query_observatory_signal(int(signal.get("id") or 0))
            if refreshed_signal is not None:
                signal["vouch_count"] = int(refreshed_signal.get("vouch_count") or signal.get("vouch_count") or 0)
            already_vouched = True

        probability = signal_probability(signal, tenant_id=tenant_id, local_profile=local_profile)
        confidence_pct = int(probability.get("confidence_pct") or 0)
        confidence_values.append(confidence_pct)
        enriched_signals.append(
            {
                **signal,
                "probability_status": probability.get("status") or "Anomaly",
                "confidence_pct": confidence_pct,
                "can_vouch": evidence_count > 0 and not already_vouched and not autonomous_quorum_enabled,
                "already_vouched": already_vouched,
                "evidence_count": evidence_count,
            }
        )

    mesh_integrity_pct = max(confidence_values) if confidence_values else 100
    return {
        "status": "CONNECTED",
        "label": "Global Pulse: Connected.",
        "mesh_integrity_pct": mesh_integrity_pct,
        "mesh_integrity_label": f"Mesh Integrity: {mesh_integrity_pct}%.",
        "autonomous_quorum_enabled": autonomous_quorum_enabled,
        "signals": enriched_signals,
        "signal_count": len(enriched_signals),
    }


def _signal_risk_category(*, signal_type: object | None, message: object | None = None) -> str | None:
    signal_blob = f"{signal_type or ''} {message or ''}".strip().lower()
    if not signal_blob:
        return None
    for category, keywords in _HIGH_RISK_SIGNAL_KEYWORDS.items():
        if any(keyword in signal_blob for keyword in keywords):
            return category
    return None


def _query_regional_high_risk_signals(
    *,
    tenant_id: object | None,
    general_region: str,
    limit: int = 5,
) -> list[dict]:
    region_key = _normalise_region_key(general_region)
    if not region_key:
        return []

    _ensure_global_node_schema()
    conn = sqlite3.connect(str(_global_node_db_path()))
    try:
        rows = conn.execute(
            """
            SELECT s.id, s.emitted_at, s.role_label, s.signal_type, s.general_region, s.source
            FROM observatory_signals s
            WHERE s.tenant_token <> ?
              AND LOWER(TRIM(s.general_region)) = ?
            ORDER BY s.emitted_at DESC, s.id DESC
            LIMIT 25
            """,
            (_tenant_token(tenant_id), region_key),
        ).fetchall()
    finally:
        conn.close()

    high_risk: list[dict] = []
    for row in rows:
        signal_type = row[3]
        message = f"{row[2]} in {row[4]} reported {row[3]}."
        risk_category = _signal_risk_category(signal_type=signal_type, message=message)
        if not risk_category:
            continue
        high_risk.append(
            {
                "id": int(row[0]),
                "emitted_at": row[1],
                "role": row[2],
                "signal_type": signal_type,
                "general_region": row[4],
                "source": row[5],
                "risk_category": risk_category,
                "message": message,
            }
        )
        if len(high_risk) >= max(1, min(int(limit or 5), 10)):
            break
    return high_risk


def _default_global_trend_summary(signals: list[dict]) -> str:
    if not signals:
        return (
            "Global Pulse is stable with no major cross-tenant anomaly reports in the latest mesh window. "
            "Intelligence Synthesis remains nominal while routine mission monitoring stays active."
        )

    type_counts: dict[str, int] = {}
    region_counts: dict[str, int] = {}
    verified_count = 0
    high_risk_count = 0
    for signal in signals:
        signal_type = str(signal.get("signal_type") or "Unknown signal").strip()
        region = str(signal.get("general_region") or "Unknown region").strip()
        status = str(signal.get("probability_status") or "").strip().lower()
        type_counts[signal_type] = type_counts.get(signal_type, 0) + 1
        region_counts[region] = region_counts.get(region, 0) + 1
        if status == "verified":
            verified_count += 1
        if _signal_risk_category(signal_type=signal_type, message=signal.get("message")):
            high_risk_count += 1

    top_type = max(type_counts.items(), key=lambda item: item[1])[0]
    top_region = max(region_counts.items(), key=lambda item: item[1])[0]
    sentence_one = (
        f"Global Pulse shows {len(signals)} recent mesh signals, led by {top_type} activity around {top_region}."
    )
    if high_risk_count > 0:
        sentence_two = (
            f"{high_risk_count} high-risk report(s) are in circulation, so run regional pre-checks before launch decisions."
        )
    elif verified_count > 0:
        sentence_two = (
            f"Confidence remains strong with {verified_count} verified signal(s), supporting nominal synthesis posture."
        )
    else:
        sentence_two = "Signals remain plausible and trending stable, so maintain normal monitoring cadence."
    return f"{sentence_one} {sentence_two}"


def _ensure_two_sentence_summary(candidate: str, *, fallback: str) -> str:
    text = re.sub(r"\s+", " ", str(candidate or "").strip())
    if not text:
        text = fallback

    sentences = [chunk.strip() for chunk in re.split(r"(?<=[.!?])\s+", text) if chunk.strip()]
    if len(sentences) >= 2:
        return f"{sentences[0]} {sentences[1]}"
    if len(sentences) == 1:
        second = re.split(r"(?<=[.!?])\s+", fallback.strip())
        second_sentence = next((part.strip() for part in second if part.strip()), "Intelligence Synthesis remains nominal.")
        if sentences[0].endswith((".", "!", "?")):
            return f"{sentences[0]} {second_sentence}"
        return f"{sentences[0]}. {second_sentence}"
    return fallback


def _extract_gemini_text(payload: dict) -> str:
    candidates = payload.get("candidates") or []
    for candidate in candidates:
        content = candidate.get("content") or {}
        parts = content.get("parts") or []
        snippets = [str(part.get("text") or "").strip() for part in parts if isinstance(part, dict)]
        text = " ".join(piece for piece in snippets if piece)
        if text:
            return text
    return ""


def summarize_global_trends(
    *,
    tenant_id: object | None,
    user_id: int = 1,
    signal_limit: int = 10,
) -> dict:
    """
    v2.9 Global Trend Summarizer.
    Uses Gemini (when configured) to synthesize the latest Global Node signals
    into a concise two-sentence Global Pulse summary.
    """
    _ = _normalise_user_id(user_id, default=1)
    signals = _query_global_discovery_feed(
        tenant_id=tenant_id,
        limit=max(1, min(int(signal_limit or 10), 10)),
    )
    fallback_summary = _default_global_trend_summary(signals)
    api_key = str(os.environ.get("GEMINI_API_KEY") or "").strip()

    if not signals:
        return {
            "status": "NOMINAL",
            "label": "Intelligence Synthesis: Nominal.",
            "global_pulse_summary": _ensure_two_sentence_summary(fallback_summary, fallback=fallback_summary),
            "summary_source": "FALLBACK",
            "signal_count": 0,
        }

    if not api_key:
        return {
            "status": "NOMINAL",
            "label": "Intelligence Synthesis: Nominal.",
            "global_pulse_summary": _ensure_two_sentence_summary(fallback_summary, fallback=fallback_summary),
            "summary_source": "FALLBACK",
            "signal_count": len(signals),
        }

    compact_signals = [
        {
            "id": int(signal.get("id") or 0),
            "signal_type": signal.get("signal_type"),
            "general_region": signal.get("general_region"),
            "vouch_count": int(signal.get("vouch_count") or 0),
            "message": signal.get("message"),
        }
        for signal in signals
    ]
    prompt = (
        "You are the HutchSolves Intelligence Synthesis Engine. "
        "Analyze the last global mesh signals and return exactly two concise operational sentences. "
        "Sentence one should summarize global trend momentum. "
        "Sentence two should mention material risk posture in plain language. "
        f"Signals JSON: {json.dumps(compact_signals, ensure_ascii=True)}"
    )

    try:
        url = _GEMINI_API_URL_TEMPLATE.format(model=_GEMINI_MODEL, api_key=api_key)
        req = urlrequest.Request(
            url,
            data=json.dumps(
                {
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "temperature": 0.2,
                        "maxOutputTokens": 180,
                    },
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlrequest.urlopen(req, timeout=5.0) as response:
            payload = json.loads(response.read().decode("utf-8"))
        generated = _extract_gemini_text(payload)
        summary = _ensure_two_sentence_summary(generated, fallback=fallback_summary)
        source = "GEMINI" if generated else "FALLBACK"
    except (urlerror.URLError, TimeoutError, ValueError, OSError, json.JSONDecodeError):
        summary = _ensure_two_sentence_summary(fallback_summary, fallback=fallback_summary)
        source = "FALLBACK"

    return {
        "status": "NOMINAL",
        "label": "Intelligence Synthesis: Nominal.",
        "global_pulse_summary": summary,
        "summary_source": source,
        "signal_count": len(signals),
    }


def _load_systems_oracle_manuscript(max_chars: int = 2800) -> dict:
    path = _SYSTEMS_ORACLE_MANUSCRIPT_PATH
    if not path.exists():
        return {
            "loaded": False,
            "title": "Mycology to Your Ecology",
            "excerpt": "",
            "principles": [],
            "path": str(path.relative_to(_ROOT)).replace("\\", "/"),
        }

    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError:
        return {
            "loaded": False,
            "title": "Mycology to Your Ecology",
            "excerpt": "",
            "principles": [],
            "path": str(path.relative_to(_ROOT)).replace("\\", "/"),
        }

    cleaned = re.sub(r"\r\n?", "\n", raw_text).strip()
    if not cleaned:
        return {
            "loaded": False,
            "title": "Mycology to Your Ecology",
            "excerpt": "",
            "principles": [],
            "path": str(path.relative_to(_ROOT)).replace("\\", "/"),
        }

    lines = [line.strip() for line in cleaned.split("\n") if line.strip()]
    title = lines[0] if lines else "Mycology to Your Ecology"
    principles: list[str] = []
    for line in lines:
        if line.startswith(("-", "*")):
            principle = line.lstrip("-* ").strip()
            if principle:
                principles.append(principle)

    excerpt = cleaned[: max(600, min(int(max_chars or 2800), 6000))]
    return {
        "loaded": True,
        "title": title,
        "excerpt": excerpt,
        "principles": principles[:12],
        "path": str(path.relative_to(_ROOT)).replace("\\", "/"),
    }


def _external_philosophy_path(*, tenant_id: object | None, organization_id: object | None = None) -> Path:
    tenant_db = _aviation_db_path(tenant_id=tenant_id, organization_id=organization_id)
    return tenant_db.parent / _EXTERNAL_PHILOSOPHY_FILENAME


def _load_external_philosophy(
    *,
    tenant_id: object | None,
    organization_id: object | None = None,
    max_values: int = 10,
) -> dict:
    path = _external_philosophy_path(tenant_id=tenant_id, organization_id=organization_id)

    try:
        display_path = str(path.relative_to(_ROOT)).replace("\\", "/")
    except ValueError:
        display_path = str(path)

    if not path.exists():
        return {
            "loaded": False,
            "title": "Corporate Values",
            "values": [],
            "weight": 0.35,
            "version": "missing",
            "content_hash": None,
            "path": display_path,
        }

    try:
        raw_text = path.read_text(encoding="utf-8")
        payload = json.loads(raw_text)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {
            "loaded": False,
            "title": "Corporate Values",
            "values": [],
            "weight": 0.35,
            "version": "invalid",
            "content_hash": None,
            "path": display_path,
        }

    if not isinstance(payload, dict):
        payload = {}

    content_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()[:12]
    version = str(payload.get("version") or f"sha256:{content_hash}").strip()[:64] or f"sha256:{content_hash}"

    raw_values = payload.get("values")
    values: list[str] = []
    if isinstance(raw_values, list):
        for value in raw_values:
            token = str(value or "").strip()
            if token:
                values.append(token[:220])

    weight = _safe_float(payload.get("weight"))
    if weight is None:
        weight = 0.35
    weight = max(0.05, min(float(weight), 0.95))

    title = str(payload.get("title") or "Corporate Values").strip() or "Corporate Values"
    capped_values = values[: max(1, min(int(max_values or 10), 20))]

    return {
        "loaded": bool(capped_values),
        "title": title[:120],
        "values": capped_values,
        "weight": round(weight, 2),
        "version": version,
        "content_hash": content_hash,
        "path": display_path,
    }


def _build_ai_pulse_telemetry_window(
    *,
    tenant_id: object | None,
    hours: int = _AI_PULSE_TELEMETRY_WINDOW_HOURS,
) -> dict:
    resolved_hours = max(1, min(int(hours or _AI_PULSE_TELEMETRY_WINDOW_HOURS), 168))
    ended_at_dt = datetime.now(timezone.utc)
    started_at_dt = ended_at_dt - timedelta(hours=resolved_hours)
    started_at = started_at_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    ended_at = ended_at_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    counts = {
        "expeditions": 0,
        "specimens": 0,
        "observatory_signals": 0,
        "philosophical_signals": 0,
    }

    db_path = _aviation_db_path(tenant_id=tenant_id)
    if db_path.exists():
        try:
            conn = sqlite3.connect(str(db_path))
            try:
                _ensure_expeditions_table(conn)
                _ensure_specimen_inventory_table(conn)
                _ensure_guest_oracle_tables(conn)
                counts["expeditions"] = int(
                    conn.execute(
                        "SELECT COUNT(*) FROM rockhounding_expeditions WHERE timestamp >= ?",
                        (started_at,),
                    ).fetchone()[0]
                    or 0
                )
                counts["specimens"] = int(
                    conn.execute(
                        "SELECT COUNT(*) FROM specimen_inventory WHERE timestamp >= ?",
                        (started_at,),
                    ).fetchone()[0]
                    or 0
                )
                counts["observatory_signals"] = int(
                    conn.execute(
                        "SELECT COUNT(*) FROM observatory_signals WHERE emitted_at >= ?",
                        (started_at,),
                    ).fetchone()[0]
                    or 0
                )
                counts["philosophical_signals"] = int(
                    conn.execute(
                        "SELECT COUNT(*) FROM philosophical_signals WHERE emitted_at >= ?",
                        (started_at,),
                    ).fetchone()[0]
                    or 0
                )
            finally:
                conn.close()
        except Exception:
            pass

    return {
        "hours": resolved_hours,
        "started_at": started_at,
        "ended_at": ended_at,
        "counts": counts,
        "total_events": sum(counts.values()),
    }


def _build_ai_pulse_provenance(
    *,
    tenant_id: object | None,
    organization_id: object | None,
    pulse: dict,
    telemetry_window_hours: int = _AI_PULSE_TELEMETRY_WINDOW_HOURS,
) -> dict:
    philosophy = _load_external_philosophy(
        tenant_id=tenant_id,
        organization_id=organization_id,
        max_values=10,
    )
    telemetry_window = _build_ai_pulse_telemetry_window(
        tenant_id=tenant_id,
        hours=telemetry_window_hours,
    )
    # Hash includes philosophy_weights (the actual weight value + values list) and
    # telemetry_payload (full per-event counts) so every hash is deterministically
    # tied to the exact state of the inference inputs at emission time.
    # Philosophy version is mapped at load time: "missing" if file not found, "invalid" if
    # parse error, or the explicit version from the file. This ensures rationale_hash is
    # deterministic and auditable even when philosophy is unavailable (e.g., CI/test contexts).
    philosophy_version = str(philosophy.get("version") or "unknown").strip() or "unknown"
    philosophy_weights = {
        "weight": philosophy.get("weight"),
        "values": philosophy.get("values") or [],
        "version": philosophy_version,
    }
    telemetry_payload = telemetry_window  # full counts dict is the payload
    rationale_basis = {
        "organization_id": _normalise_organization_id(organization_id or _DEFAULT_ORGANIZATION_ID),
        "tenant_id": _normalise_tenant_id(tenant_id or _DEFAULT_TENANT_ID),
        "source": str(pulse.get("source") or "unknown"),
        "label": str(pulse.get("label") or ""),
        "summary": str(pulse.get("summary") or ""),
        "philosophy_weights": philosophy_weights,
        "telemetry_payload": telemetry_payload,
    }
    rationale_hash = hashlib.sha256(
        json.dumps(rationale_basis, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return {
        "rationale_hash": rationale_hash,
        "external_philosophy_path": philosophy.get("path"),
        "external_philosophy_version": philosophy.get("version"),
        "telemetry_window": telemetry_window,
    }


# ── Governance Ledger ──────────────────────────────────────────────────────────

def _ensure_governance_db() -> None:
    """Create system_governance.sqlite with immutable-ledger schema if not present.
    
    Uses WAL (Write-Ahead Logging) mode to optimize write throughput for rationale_hash
    entries and prevent pulse broadcasts from blocking on governance ledger I/O.
    """
    db_path = _GOVERNANCE_DB
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        # Enable WAL mode for fast-path governance ledger writes (v14.1 optimization).
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(_CREATE_GOVERNANCE_LEDGER)
        conn.execute(_CREATE_GOVERNANCE_DELETE_GUARD)
        conn.execute(_CREATE_GOVERNANCE_UPDATE_GUARD)
        conn.execute(_CREATE_METERED_USAGE)
        try:
            conn.execute("ALTER TABLE governance_ledger ADD COLUMN rationale_hash TEXT")
        except Exception:
            pass  # column already exists on pre-v14 databases
        conn.commit()
    finally:
        conn.close()


def _govern_log(
    *,
    org_id: str,
    actor: str,
    action_type: str,
    payload: dict,
    rationale_hash: str | None = None,
) -> dict:
    """Append an immutable record to the governance ledger. Returns the record header."""
    try:
        _ensure_governance_db()
        rh = rationale_hash or (payload.get("rationale_hash") if isinstance(payload, dict) else None) or None
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        raw = f"{now}|{org_id}|{actor}|{action_type}|{payload_json}"
        checksum = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        event_id = hashlib.sha256(
            f"{now}-{org_id}-{actor}-{action_type}".encode("utf-8")
        ).hexdigest()[:32]
        conn = sqlite3.connect(str(_GOVERNANCE_DB))
        try:
            conn.execute(
                "INSERT OR IGNORE INTO governance_ledger "
                "(event_id, timestamp, org_id, actor, action_type, payload_json, checksum, rationale_hash) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (event_id, now, org_id, actor, action_type, payload_json, checksum, rh),
            )
            conn.commit()
        finally:
            conn.close()
        return {
            "event_id": event_id,
            "timestamp": now,
            "org_id": org_id,
            "actor": actor,
            "action_type": action_type,
            "checksum": checksum,
        }
    except Exception:
        return {}


def _query_governance_entries(
    *,
    org_id: str | None = None,
    action_types: list[str] | None = None,
    limit: int = 100,
) -> list[dict]:
    try:
        _ensure_governance_db()
        conn = sqlite3.connect(str(_GOVERNANCE_DB))
        try:
            filters: list[str] = []
            params: list[object] = []
            if org_id:
                filters.append("org_id = ?")
                params.append(_normalise_organization_id(org_id))
            if action_types:
                cleaned = [str(action_type).strip() for action_type in action_types if str(action_type).strip()]
                if cleaned:
                    placeholders = ",".join(["?"] * len(cleaned))
                    filters.append(f"action_type IN ({placeholders})")
                    params.extend(cleaned)

            where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
            params.append(max(1, min(int(limit or 100), 2000)))
            rows = conn.execute(
                f"""
                SELECT event_id, timestamp, org_id, actor, action_type, payload_json, checksum, rationale_hash
                FROM governance_ledger
                {where_clause}
                ORDER BY id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        finally:
            conn.close()
    except Exception:
        return []

    entries: list[dict] = []
    for row in rows:
        payload = {}
        try:
            payload = json.loads(row[5]) if row[5] else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {"raw": payload}
        entries.append(
            {
                "event_id": row[0],
                "timestamp": row[1],
                "org_id": row[2],
                "actor": row[3],
                "action_type": row[4],
                "payload": payload,
                "checksum": row[6],
                "rationale_hash": row[7] or payload.get("rationale_hash"),
            }
        )
    return entries


def _format_duration_brief(seconds: float | None) -> str:
    if seconds is None:
        return "Awaiting action evidence"
    total_seconds = max(0, int(round(float(seconds))))
    minutes, secs = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def _build_mesh_risk_score_payload(period_days: int = 30) -> dict:
    resolved_period_days = max(1, min(int(period_days or 30), 365))
    period_ended_dt = datetime.now(timezone.utc)
    cutoff_dt = period_ended_dt - timedelta(days=resolved_period_days)
    entries = _query_governance_entries(
        action_types=[_AI_PULSE_ACTION_TYPE, _AI_PULSE_ACK_ACTION_TYPE],
        limit=1000,
    )

    pulse_index: dict[str, dict] = {}
    ack_index: dict[str, dict] = {}
    covered_orgs: set[str] = set()

    for entry in reversed(entries):
        entry_dt = _parse_utc_timestamp(entry.get("timestamp"))
        if entry_dt is None or entry_dt < cutoff_dt:
            continue
        payload = entry.get("payload") or {}
        action_type = str(entry.get("action_type") or "").strip()
        org_id = str(entry.get("org_id") or "")
        if org_id:
            covered_orgs.add(org_id)
        if action_type == _AI_PULSE_ACTION_TYPE:
            pulse_id = str(payload.get("id") or payload.get("pulse_id") or entry.get("event_id") or "").strip()
            if not pulse_id:
                continue
            pulse_index[pulse_id] = {
                "timestamp": _parse_utc_timestamp(payload.get("ingested_at") or entry.get("timestamp")),
                "rationale_hash": str(payload.get("rationale_hash") or ""),
            }
        elif action_type == _AI_PULSE_ACK_ACTION_TYPE:
            pulse_id = str(payload.get("pulse_id") or "").strip()
            rationale_hash = str(payload.get("rationale_hash") or "").strip()
            ack_dt = _parse_utc_timestamp(payload.get("acknowledged_at") or entry.get("timestamp"))
            key = pulse_id or rationale_hash
            if not key or ack_dt is None or key in ack_index:
                continue
            ack_index[key] = {
                "timestamp": ack_dt,
                "rationale_hash": rationale_hash,
            }

    response_times_seconds: list[float] = []
    open_pulse_count = 0
    for pulse_id, pulse in pulse_index.items():
        pulse_dt = pulse.get("timestamp")
        if pulse_dt is None:
            continue
        ack = ack_index.get(pulse_id)
        if ack is None and pulse.get("rationale_hash"):
            ack = ack_index.get(str(pulse.get("rationale_hash")))
        if ack is None:
            open_pulse_count += 1
            continue
        ack_dt = ack.get("timestamp")
        if ack_dt is None or ack_dt < pulse_dt:
            open_pulse_count += 1
            continue
        response_times_seconds.append((ack_dt - pulse_dt).total_seconds())

    pulse_count = len(pulse_index)
    acknowledged_count = len(response_times_seconds)
    # operational_uptime: proportion of pulses acknowledged — the primary fleet responsiveness metric.
    operational_uptime = (acknowledged_count / pulse_count) if pulse_count else 0.0
    avg_seconds = (sum(response_times_seconds) / len(response_times_seconds)) if response_times_seconds else None
    target_seconds = 300.0

    if pulse_count == 0:
        risk_score = 50.0
    else:
        # Weighted average: 40% Time-to-Action factor, 45% Operational Uptime factor, 15% open-pulse penalty.
        time_to_action_factor = min(1.75, ((avg_seconds or (target_seconds * 2.0)) / target_seconds))
        risk_score = min(
            100.0,
            max(
                8.0,
                (time_to_action_factor * 40.0)
                + ((1.0 - operational_uptime) * 45.0)
                + (open_pulse_count * 3.0),
            ),
        )

    risk_score = round(risk_score, 1)
    failure_rate_reduction_signal_pct = round(max(0.0, min(92.0, 100.0 - risk_score)), 1)
    if risk_score <= 30.0:
        risk_label = "Low Risk"
    elif risk_score <= 60.0:
        risk_label = "Guarded"
    else:
        risk_label = "Elevated"

    return {
        "generated_at": period_ended_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "period_days": resolved_period_days,
        "period_started_at": cutoff_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "period_ended_at": period_ended_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "mesh_org_count": len(covered_orgs),
        "pulse_count": pulse_count,
        "acknowledged_count": acknowledged_count,
        "open_pulse_count": open_pulse_count,
        "operational_uptime_pct": round(operational_uptime * 100.0, 1),
        "coverage_pct": round(operational_uptime * 100.0, 1),
        "average_time_to_action_seconds": round(avg_seconds, 1) if avg_seconds is not None else None,
        "average_time_to_action_label": _format_duration_brief(avg_seconds),
        "target_time_to_action_seconds": int(target_seconds),
        "risk_score": risk_score,
        "risk_label": risk_label,
        "failure_rate_reduction_signal_pct": failure_rate_reduction_signal_pct,
        "label": f"Risk Score: {risk_score:.1f} / 100 ({risk_label}).",
    }


# Public alias matching the v14.0.0 spec name for external/testing use.
calculate_fleet_risk_score = _build_mesh_risk_score_payload


def _metered_usage_increment(org_id: str, metric: str) -> None:
    """Increment the current-month metered usage counter. Never raises."""
    try:
        _ensure_governance_db()
        period = datetime.now(timezone.utc).strftime("%Y-%m")
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn = sqlite3.connect(str(_GOVERNANCE_DB))
        try:
            conn.execute(
                """
                INSERT INTO metered_usage (org_id, metric, period, count, last_updated_at)
                VALUES (?, ?, ?, 1, ?)
                ON CONFLICT(org_id, metric, period) DO UPDATE SET
                    count = count + 1,
                    last_updated_at = excluded.last_updated_at
                """,
                (org_id, metric, period, now),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass


def _metered_usage_query(org_id: str) -> dict:
    """Return current-month usage counts for an org. Returns {} on error."""
    try:
        _ensure_governance_db()
        period = datetime.now(timezone.utc).strftime("%Y-%m")
        conn = sqlite3.connect(str(_GOVERNANCE_DB))
        try:
            rows = conn.execute(
                "SELECT metric, count FROM metered_usage WHERE org_id = ? AND period = ?",
                (org_id, period),
            ).fetchall()
        finally:
            conn.close()
        return {row[0]: int(row[1]) for row in rows}
    except Exception:
        return {}


def _metered_usage_fleet_snapshot(period: str | None = None) -> dict:
    resolved_period = str(period or datetime.now(timezone.utc).strftime("%Y-%m")).strip()
    _ensure_governance_db()

    rows: list[tuple] = []
    conn = sqlite3.connect(str(_GOVERNANCE_DB))
    try:
        rows = conn.execute(
            """
            SELECT
                org_id,
                SUM(CASE WHEN metric = 'oracle_api_calls' THEN count ELSE 0 END) AS oracle_calls,
                SUM(CASE WHEN metric = 'navigator_expeditions' THEN count ELSE 0 END) AS navigator_logs
            FROM metered_usage
            WHERE period = ?
            GROUP BY org_id
            ORDER BY org_id ASC
            """,
            (resolved_period,),
        ).fetchall()
    finally:
        conn.close()

    orgs: list[dict] = []
    total_oracle = 0
    total_navigator = 0
    for row in rows:
        oracle_calls = int(row[1] or 0)
        navigator_logs = int(row[2] or 0)
        total_oracle += oracle_calls
        total_navigator += navigator_logs
        orgs.append(
            {
                "organization_id": str(row[0]),
                "oracle_api_calls": oracle_calls,
                "navigator_logs": navigator_logs,
            }
        )

    return {
        "period": resolved_period,
        "organizations": orgs,
        "totals": {
            "organization_count": len(orgs),
            "oracle_api_calls": total_oracle,
            "navigator_logs": total_navigator,
        },
    }


def _generate_billing_preview(org_id: str | None) -> dict:
    """Compute an estimated billing preview from metered usage for the current month."""
    if not org_id:
        return {"label": "Billing Preview: Unavailable.", "error": "no_org_id"}
    usage = _metered_usage_query(org_id)
    oracle_calls = usage.get("oracle_api_calls", 0)
    expeditions = usage.get("navigator_expeditions", 0)
    oracle_cost = round(oracle_calls * _ORACLE_CALL_RATE_USD, 2)
    expedition_cost = round(expeditions * _EXPEDITION_RATE_USD, 2)
    total = round(oracle_cost + expedition_cost, 2)
    period = datetime.now(timezone.utc).strftime("%Y-%m")
    return {
        "org_id": org_id,
        "period": period,
        "oracle_api_calls": oracle_calls,
        "navigator_expeditions": expeditions,
        "oracle_cost_usd": oracle_cost,
        "expedition_cost_usd": expedition_cost,
        "total_estimated_usd": total,
        "label": (
            f"Billing Preview: ${total:.2f} est. "
            f"({oracle_calls} Oracle calls, {expeditions} Expeditions)."
        ),
    }


# ── White-Label Theme ──────────────────────────────────────────────────────────

def _org_theme_path(org_id: str) -> Path:
    return _ORGANIZATIONS_ROOT / _normalise_organization_id(org_id) / _ORG_THEME_FILENAME


def _org_metadata_path(org_id: str) -> Path:
    return _ORGANIZATIONS_ROOT / _normalise_organization_id(org_id) / _ORG_METADATA_FILENAME


def _load_org_metadata(org_id: str | None) -> dict:
    defaults = {
        "org_id": _normalise_organization_id(org_id or _DEFAULT_ORGANIZATION_ID),
        "parent_org_id": None,
        "relationship_type": "root",
        "child_count": 0,
    }
    if not org_id:
        return defaults

    path = _org_metadata_path(org_id)
    if not path.exists():
        return defaults

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return defaults

    if not isinstance(raw, dict):
        return defaults

    parent_org_id = raw.get("parent_org_id")
    if parent_org_id not in (None, ""):
        parent_org_id = _normalise_organization_id(parent_org_id)
    else:
        parent_org_id = None

    return {
        **defaults,
        "org_id": _normalise_organization_id(raw.get("org_id") or org_id),
        "parent_org_id": parent_org_id,
        "relationship_type": "child" if parent_org_id else "root",
        "created_at": raw.get("created_at"),
    }


def _iter_org_metadata_docs() -> list[dict]:
    docs: list[dict] = []
    if not _ORGANIZATIONS_ROOT.exists():
        return docs

    for org_dir in _ORGANIZATIONS_ROOT.iterdir():
        if not org_dir.is_dir():
            continue
        org_id = _normalise_organization_id(org_dir.name)
        docs.append(_load_org_metadata(org_id))

    child_counts: dict[str, int] = {}
    for doc in docs:
        parent_org_id = doc.get("parent_org_id")
        if parent_org_id:
            child_counts[parent_org_id] = child_counts.get(parent_org_id, 0) + 1
    for doc in docs:
        doc["child_count"] = child_counts.get(doc["org_id"], 0)
    return sorted(docs, key=lambda item: (str(item.get("parent_org_id") or ""), str(item.get("org_id") or "")))


def _tenant_count_for_org(org_id: str) -> int:
    tenants_root = _org_tenants_root(org_id)
    if not tenants_root.exists():
        return 0
    return sum(1 for item in tenants_root.iterdir() if item.is_dir())


def _load_digital_guardian_pulse() -> dict | None:
    path = _DIGITAL_GUARDIAN_PULSE_PATH
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _persist_digital_guardian_pulse(pulse: dict) -> dict:
    payload = {
        "id": str(pulse.get("id") or hashlib.sha256(json.dumps(pulse, sort_keys=True).encode("utf-8")).hexdigest()[:16]),
        "severity": str(pulse.get("severity") or "info"),
        "label": str(pulse.get("label") or "Digital Guardian Pulse: External ingest completed."),
        "source": str(pulse.get("source") or "ingestor"),
        "tenant_id": _normalise_tenant_id(pulse.get("tenant_id") or _DEFAULT_TENANT_ID),
        "organization_id": _normalise_organization_id(pulse.get("organization_id") or _DEFAULT_ORGANIZATION_ID),
        "ingested_at": str(pulse.get("ingested_at") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")),
        "summary": str(pulse.get("summary") or ""),
    }
    provenance = _build_ai_pulse_provenance(
        tenant_id=payload["tenant_id"],
        organization_id=payload["organization_id"],
        pulse=payload,
        telemetry_window_hours=int(pulse.get("telemetry_window_hours") or _AI_PULSE_TELEMETRY_WINDOW_HOURS),
    )
    payload.update(provenance)
    ledger_record = _govern_log(
        org_id=payload["organization_id"],
        actor=str(payload.get("source") or "ingestor"),
        action_type=_AI_PULSE_ACTION_TYPE,
        payload=dict(payload),
    )
    if ledger_record:
        payload["ledger_record"] = ledger_record
    path = _DIGITAL_GUARDIAN_PULSE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


_SOC2_CONTROL_POINT_MAP: dict[str, dict[str, str]] = {
    "ai_pulse": {
        "control_point": "CC7.2",
        "category": "System Operations",
        "description": "AI pulse generation is attributable to a philosophy version and telemetry window.",
    },
    "ai_pulse_ack": {
        "control_point": "CC7.3",
        "category": "Response Monitoring",
        "description": "Pulse acknowledgements prove response timing and operational follow-through.",
    },
    "theme_update": {
        "control_point": "CC8.1",
        "category": "Change Management",
        "description": "Configuration and branding changes are authorized and logged.",
    },
    "digital_guardian_success_pdf": {
        "control_point": "CC3.2",
        "category": "Monitoring",
        "description": "Management reviews operational outcomes and retains decision evidence.",
    },
    "shadow_ingest_flight_log": {
        "control_point": "CC7.2",
        "category": "System Operations",
        "description": "Inbound operational data is monitored, logged, and evaluated for response.",
    },
    "navigator_expedition_guest_invite": {
        "control_point": "CC6.3",
        "category": "Access Management",
        "description": "Guest sharing is bounded to one-time access and scoped to a single record.",
    },
    "navigator_expedition_guest_redeem": {
        "control_point": "CC6.3",
        "category": "Access Management",
        "description": "Guest redemption is logged as single-use evidence for external access.",
    },
    "sentinel_verify": {
        "control_point": "CC7.3",
        "category": "Change Detection",
        "description": "Sentinel checks detect exceptions and validate safeguards.",
    },
    "philosophy_update": {
        "control_point": "CC1.2",
        "category": "Control Environment",
        "description": "Leadership-defined values and expectations are documented and propagated.",
    },
}


def _map_governance_event_to_soc2(action_type: object) -> dict:
    key = str(action_type or "").strip()
    mapped = _SOC2_CONTROL_POINT_MAP.get(key)
    if mapped:
        return {**mapped, "action_type": key}
    return {
        "action_type": key or "unknown",
        "control_point": "CC9.2",
        "category": "Audit Trail",
        "description": "Operational events are retained in the immutable Sovereign Ledger.",
    }


def _build_franchise_stats_payload(*, scope_org_id: str | None = None, period: str | None = None) -> dict:
    snapshot = _metered_usage_fleet_snapshot(period=period)
    usage_by_org = {
        str(row.get("organization_id") or ""): {
            "oracle_api_calls": int(row.get("oracle_api_calls") or 0),
            "navigator_logs": int(row.get("navigator_logs") or 0),
        }
        for row in (snapshot.get("organizations") or [])
    }

    docs = _iter_org_metadata_docs()
    docs_by_org = {str(doc.get("org_id") or ""): doc for doc in docs}
    for org_id in usage_by_org:
        docs_by_org.setdefault(
            org_id,
            {
                "org_id": org_id,
                "parent_org_id": None,
                "relationship_type": "root",
                "child_count": 0,
            },
        )

    if scope_org_id:
        scope = _normalise_organization_id(scope_org_id)
        visible_ids = {scope}
        visible_ids.update(
            doc_org_id
            for doc_org_id, doc in docs_by_org.items()
            if doc.get("parent_org_id") == scope
        )
    else:
        scope = None
        visible_ids = set(docs_by_org.keys())

    rows: list[dict] = []
    total_oracle = 0
    total_navigator = 0
    for org_id in sorted(visible_ids):
        doc = docs_by_org.get(org_id) or {
            "org_id": org_id,
            "parent_org_id": None,
            "relationship_type": "root",
            "child_count": 0,
        }
        usage = usage_by_org.get(org_id, {})
        oracle_api_calls = int(usage.get("oracle_api_calls") or 0)
        navigator_logs = int(usage.get("navigator_logs") or 0)
        total_oracle += oracle_api_calls
        total_navigator += navigator_logs
        rows.append(
            {
                "organization_id": org_id,
                "parent_org_id": doc.get("parent_org_id"),
                "relationship_type": doc.get("relationship_type") or ("child" if doc.get("parent_org_id") else "root"),
                "child_count": int(doc.get("child_count") or 0),
                "tenant_count": _tenant_count_for_org(org_id),
                "oracle_api_calls": oracle_api_calls,
                "navigator_logs": navigator_logs,
                "private_data_included": False,
            }
        )

    return {
        "period": snapshot.get("period"),
        "scope_org_id": scope,
        "private_data_included": False,
        "organizations": rows,
        "totals": {
            "organization_count": len(rows),
            "oracle_api_calls": total_oracle,
            "navigator_logs": total_navigator,
            "child_organization_count": sum(1 for row in rows if row.get("parent_org_id")),
        },
    }


def _compliance_access_permitted(role: object) -> bool:
    return _normalise_user_role(role) in {"Admin", "Operations Director"}


def _build_soc2_control_points(*, org_id: str | None = None, limit: int = 100) -> dict:
    _ensure_governance_db()
    resolved_limit = max(1, min(int(limit or 100), 500))
    conn = sqlite3.connect(str(_GOVERNANCE_DB))
    try:
        if org_id:
            rows = conn.execute(
                "SELECT event_id, timestamp, org_id, actor, action_type, checksum FROM governance_ledger WHERE org_id = ? ORDER BY id DESC LIMIT ?",
                (_normalise_organization_id(org_id), resolved_limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT event_id, timestamp, org_id, actor, action_type, checksum FROM governance_ledger ORDER BY id DESC LIMIT ?",
                (resolved_limit,),
            ).fetchall()
    finally:
        conn.close()

    entries: list[dict] = []
    control_points: dict[str, dict] = {}
    for row in rows:
        mapping = _map_governance_event_to_soc2(row[4])
        control_key = str(mapping.get("control_point") or "CC9.2")
        bucket = control_points.setdefault(
            control_key,
            {
                "control_point": control_key,
                "category": mapping.get("category"),
                "description": mapping.get("description"),
                "event_count": 0,
                "action_types": set(),
            },
        )
        bucket["event_count"] += 1
        bucket["action_types"].add(mapping.get("action_type"))
        entries.append(
            {
                "event_id": row[0],
                "timestamp": row[1],
                "org_id": row[2],
                "actor": row[3],
                "action_type": row[4],
                "checksum": row[5],
                **mapping,
            }
        )

    return {
        "org_id": _normalise_organization_id(org_id) if org_id else None,
        "entries": entries,
        "control_points": [
            {
                **bucket,
                "action_types": sorted(str(item) for item in bucket.get("action_types") or [] if item),
            }
            for bucket in sorted(control_points.values(), key=lambda item: str(item.get("control_point") or ""))
        ],
        "count": len(entries),
    }


def _load_org_theme(org_id: str | None) -> dict:
    """Load org theme. Returns palette defaults if no theme has been saved."""
    defaults: dict = {
        "primary_color": "#0f766e",
        "secondary_color": "#065F46",
        "logo_url": None,
        "org_id": org_id or "legacy",
    }
    if not org_id:
        return defaults
    path = _org_theme_path(org_id)
    if not path.exists():
        return defaults
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            allowed = {"primary_color", "secondary_color", "logo_url", "org_id"}
            return {**defaults, **{k: v for k, v in raw.items() if k in allowed}}
    except (OSError, json.JSONDecodeError):
        pass
    return defaults


def _save_org_theme(org_id: str, theme: dict, actor: str = "system") -> dict:
    """Persist org theme JSON and log the change to the governance ledger."""
    path = _org_theme_path(org_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "org_id": org_id,
        "primary_color": str(theme.get("primary_color") or "#0f766e")[:32],
        "secondary_color": str(theme.get("secondary_color") or "#065F46")[:32],
        "logo_url": str(theme.get("logo_url") or "")[:512] or None,
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    _govern_log(
        org_id=org_id,
        actor=actor,
        action_type="theme_update",
        payload={"primary_color": doc["primary_color"], "secondary_color": doc["secondary_color"]},
    )
    return doc


def _fallback_systems_oracle_overlay(
    *,
    discovery_forecast: dict,
    fleet_readiness: dict,
    optimization_pivot: dict,
    restock_alert: dict,
) -> tuple[str, str]:
    readiness_pct = int(fleet_readiness.get("readiness_pct") or 0)
    discovery_label = str(discovery_forecast.get("label") or "Discovery Forecast: Monitoring.")
    pivot_label = str(optimization_pivot.get("label") or "Strategy: Monitoring.")

    if "maintenance" in pivot_label.lower() or readiness_pct < 70:
        reflection = (
            "Systems-Thinking Reflection: Your administrative drift is mimicking mycelial overcrowding; "
            "prune the nodes to restore flow."
        )
    elif restock_alert.get("is_active"):
        reflection = (
            "Systems-Thinking Reflection: Nutrient channels are thinning; replenish constrained nodes "
            "before expanding the network edge."
        )
    elif bool(discovery_forecast.get("detected")):
        reflection = (
            "Systems-Thinking Reflection: Edge discoveries behave like exploratory hyphae; "
            "reinforce core operations while extending into high-yield zones."
        )
    else:
        reflection = (
            "Systems-Thinking Reflection: The network is stable; continue light pruning and keep "
            "signal-sharing active to prevent hidden drift pockets."
        )

    synthesis = (
        "Philosophical Synthesis: Current drift posture "
        f"({pivot_label}) and discovery posture ({discovery_label}) mirror fungal network strategy: "
        "stabilize stressed branches first, then grow toward verified nutrient paths."
    )
    return reflection, synthesis


def _extract_oracle_sections(text: str, *, fallback_reflection: str, fallback_synthesis: str) -> tuple[str, str]:
    compact = str(text or "").strip()
    if not compact:
        return fallback_reflection, fallback_synthesis

    reflection_match = re.search(
        r"Systems-Thinking Reflection\s*:\s*(.+?)(?=Philosophical Synthesis\s*:|$)",
        compact,
        flags=re.IGNORECASE | re.DOTALL,
    )
    synthesis_match = re.search(
        r"Philosophical Synthesis\s*:\s*(.+)$",
        compact,
        flags=re.IGNORECASE | re.DOTALL,
    )

    reflection_body = (reflection_match.group(1).strip() if reflection_match else "")
    synthesis_body = (synthesis_match.group(1).strip() if synthesis_match else "")

    if not reflection_body or not synthesis_body:
        sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", compact) if part.strip()]
        if not reflection_body and sentences:
            reflection_body = sentences[0]
        if not synthesis_body:
            if len(sentences) > 1:
                synthesis_body = " ".join(sentences[1:])
            else:
                synthesis_body = fallback_synthesis.replace("Philosophical Synthesis:", "", 1).strip()

    reflection = f"Systems-Thinking Reflection: {reflection_body}" if reflection_body else fallback_reflection
    synthesis = f"Philosophical Synthesis: {synthesis_body}" if synthesis_body else fallback_synthesis
    return reflection, synthesis


def systems_thinking_overlay(
    *,
    tenant_id: object | None,
    user_id: int,
    discovery_forecast: dict,
    fleet_readiness: dict,
    optimization_pivot: dict,
    restock_alert: dict,
    mesh_radar: dict,
    global_node: dict,
    organization_id: object | None = None,
) -> dict:
    # Track Oracle API usage for billing preview
    _metered_usage_increment(
        _normalise_organization_id(organization_id or _DEFAULT_ORGANIZATION_ID),
        "oracle_api_calls",
    )
    manuscript = _load_systems_oracle_manuscript()
    manuscript_principles = manuscript.get("principles") or []
    principles = manuscript_principles or _SYSTEMS_ORACLE_FALLBACK_PRINCIPLES
    external_philosophy = _load_external_philosophy(tenant_id=tenant_id, organization_id=organization_id)
    external_values = external_philosophy.get("values") or []
    external_loaded = bool(external_philosophy.get("loaded"))
    secondary_weight = float(external_philosophy.get("weight") or 0.35)

    reflection, synthesis = _fallback_systems_oracle_overlay(
        discovery_forecast=discovery_forecast,
        fleet_readiness=fleet_readiness,
        optimization_pivot=optimization_pivot,
        restock_alert=restock_alert,
    )

    if external_loaded:
        reflection = (
            f"{reflection} Corporate Values Lens ({external_philosophy.get('title')}): "
            f"{external_values[0]}."
        )
        synthesis = (
            f"{synthesis} Secondary weighting {int(round(secondary_weight * 100))}% from "
            f"{external_philosophy.get('title')} values."
        )

    manuscript_loaded = bool(manuscript.get("loaded"))
    label = (
        "Systems Oracle: Synced with Mycology to Your Ecology."
        if manuscript_loaded
        else "Systems Oracle: Manuscript Offline."
    )
    if manuscript_loaded and external_loaded:
        source = "MANUSCRIPT+EXTERNAL+FALLBACK"
    elif manuscript_loaded:
        source = "MANUSCRIPT+FALLBACK"
    elif external_loaded:
        source = "EXTERNAL+FALLBACK"
    else:
        source = "FALLBACK"

    api_key = str(os.environ.get("GEMINI_API_KEY") or "").strip()

    if manuscript_loaded and api_key:
        prompt_payload = {
            "tenant_id": _normalise_tenant_id(tenant_id),
            "organization_id": _normalise_organization_id(organization_id or _DEFAULT_ORGANIZATION_ID),
            "user_id": _normalise_user_id(user_id, default=1),
            "drift_label": str(optimization_pivot.get("label") or "Strategy: Monitoring."),
            "drift_rationale": str(optimization_pivot.get("rationale") or "Yield Velocity > Operational Cost."),
            "discovery_label": str(discovery_forecast.get("label") or "Discovery Forecast: Monitoring."),
            "mesh_radar": str(mesh_radar.get("label") or "Mesh Radar: Active."),
            "global_pulse": str(global_node.get("label") or "Global Pulse: Connected."),
            "fleet_readiness_pct": int(fleet_readiness.get("readiness_pct") or 0),
            "restock_active": bool(restock_alert.get("is_active")),
        }
        prompt = (
            "You are HutchSolves Systems Oracle. "
            "Use manuscript principles as the primary weight and corporate values as the secondary weight. "
            "Line 1 must start with 'Systems-Thinking Reflection:' and connect professional drift to ecological network dynamics. "
            "Line 2 must start with 'Philosophical Synthesis:' and explain discovery + maintenance tradeoffs using fungal-network logic. "
            f"Manuscript title: {manuscript.get('title')}. "
            f"Primary principles: {json.dumps(principles, ensure_ascii=True)}. "
            f"Secondary values title: {external_philosophy.get('title')}. "
            f"Secondary values weight: {secondary_weight}. "
            f"Secondary values: {json.dumps(external_values, ensure_ascii=True)}. "
            f"Operational payload: {json.dumps(prompt_payload, ensure_ascii=True)}"
        )

        try:
            url = _GEMINI_API_URL_TEMPLATE.format(model=_GEMINI_MODEL, api_key=api_key)
            req = urlrequest.Request(
                url,
                data=json.dumps(
                    {
                        "contents": [{"parts": [{"text": prompt}]}],
                        "generationConfig": {
                            "temperature": 0.2,
                            "maxOutputTokens": 220,
                        },
                    }
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlrequest.urlopen(req, timeout=5.0) as response:
                payload = json.loads(response.read().decode("utf-8"))
            generated = _extract_gemini_text(payload)
            reflection, synthesis = _extract_oracle_sections(
                generated,
                fallback_reflection=reflection,
                fallback_synthesis=synthesis,
            )
            if generated:
                source = "MANUSCRIPT+EXTERNAL+GEMINI" if external_loaded else "MANUSCRIPT+GEMINI"
        except (urlerror.URLError, TimeoutError, ValueError, OSError, json.JSONDecodeError):
            if manuscript_loaded and external_loaded:
                source = "MANUSCRIPT+EXTERNAL+FALLBACK"
            else:
                source = "MANUSCRIPT+FALLBACK"

    return {
        "status": "SYNCED" if manuscript_loaded else "DEGRADED",
        "label": label,
        "systems_reflection": reflection,
        "philosophical_synthesis": synthesis,
        "source": source,
        "book_title": manuscript.get("title") or "Mycology to Your Ecology",
        "manuscript": {
            "loaded": manuscript_loaded,
            "path": manuscript.get("path") or "",
            "principles_count": len(principles),
        },
        "external_philosophy": {
            "loaded": external_loaded,
            "path": external_philosophy.get("path") or "",
            "values_count": len(external_values),
            "weight": secondary_weight,
            "title": external_philosophy.get("title") or "Corporate Values",
        },
    }


def _recommend_local_action(
    *,
    regional_high_risk_signals: list[dict],
    discovery_forecast: dict,
    fleet_readiness: dict,
) -> str:
    if regional_high_risk_signals:
        top_risk = str((regional_high_risk_signals[0] or {}).get("risk_category") or "High-Risk")
        return f"Local Action: Hold launch and run pre-flight contingency review due to regional {top_risk} reports."

    if discovery_forecast.get("detected") and int(fleet_readiness.get("readiness_pct") or 0) >= 85:
        return "Local Action: Execute the suggested mission route and keep mesh monitoring active during transit."

    return "Local Action: Continue scheduled transects and monitor regional mesh updates for risk escalation."


def _component_tti_status(tti_hours: float) -> tuple[str, str, str, str]:
    if tti_hours < 10.0:
        return ("INSPECT_NOW", "Inspect Now", "🔴", "#B91C1C")
    if tti_hours < 25.0:
        return ("MONITOR", "Monitor", "🟡", "#CA8A04")
    return ("SAFE", "Safe", "🟢", "#15803D")


def _estimate_recent_flight_hours(fuel_logs: list[dict]) -> float:
    if not fuel_logs:
        return 0.0

    ordered = sorted(fuel_logs, key=lambda row: str(row.get("timestamp") or ""))
    hobbs_values = [
        _safe_float(row.get("hobbs_time"))
        for row in ordered
        if _safe_float(row.get("hobbs_time")) is not None
    ]
    if len(hobbs_values) >= 2:
        delta = float(hobbs_values[-1]) - float(hobbs_values[0])
        if delta > 0:
            return round(delta, 1)

    tach_values = [
        _safe_float(row.get("tach_time"))
        for row in ordered
        if _safe_float(row.get("tach_time")) is not None
    ]
    if len(tach_values) >= 2:
        delta = float(tach_values[-1]) - float(tach_values[0])
        if delta > 0:
            return round(delta, 1)

    return round(max(0.0, float(len(ordered)) * 1.2), 1)


def predict_component_failure(
    *,
    tenant_id: object | None,
    tail_number: str = "N6424P",
) -> dict:
    """
    v3.0 Component Lifecycle Engine.
    Uses oil telemetry and flight-log utilization to estimate Time to Inspect
    (TTI) for major engine components.
    """
    reports = _query_oil_sentinel_reports(limit=12, tenant_id=tenant_id)
    fuel_logs = _query_fuel_logs(tail_number=tail_number, limit=20, tenant_id=tenant_id)

    latest_iron = 0.0
    latest_copper = 0.0
    latest_aluminium = 0.0
    if reports:
        latest = reports[0]
        latest_iron = float(_safe_float(latest.get("iron")) or 0.0)
        latest_copper = float(_safe_float(latest.get("copper")) or 0.0)
        latest_aluminium = float(_safe_float(latest.get("aluminium")) or 0.0)

    prior_iron_values = [
        float(_safe_float(row.get("iron")) or 0.0)
        for row in reports[1:6]
        if _safe_float(row.get("iron")) is not None
    ]
    iron_trend = 0.0
    if prior_iron_values:
        iron_trend = max(0.0, latest_iron - (sum(prior_iron_values) / len(prior_iron_values)))

    burn_values = [
        float(_safe_float(row.get("burn_rate_gph")) or 0.0)
        for row in fuel_logs
        if _safe_float(row.get("burn_rate_gph")) is not None
    ]
    avg_burn_rate = (sum(burn_values) / len(burn_values)) if burn_values else _N6424P_FUEL_BURN_GPH
    recent_flight_hours = _estimate_recent_flight_hours(fuel_logs)

    wear_index = (
        max(0.0, (latest_iron - 30.0) * 3.4)
        + max(0.0, iron_trend * 2.2)
        + max(0.0, (avg_burn_rate - _N6424P_FUEL_BURN_GPH) * 4.5)
        + max(0.0, (recent_flight_hours - 18.0) * 0.65)
        + max(0.0, (latest_copper - 11.0) * 0.55)
        + max(0.0, (latest_aluminium - 8.0) * 0.4)
    )

    component_profiles = [
        {"key": "cylinders", "label": "Cylinders", "base_tti": 58.0, "wear_factor": 1.00},
        {"key": "oil_pump", "label": "Oil Pump", "base_tti": 76.0, "wear_factor": 0.74},
        {"key": "fuel_pump", "label": "Fuel Pump", "base_tti": 84.0, "wear_factor": 0.62},
        {"key": "valve_train", "label": "Valve Train", "base_tti": 66.0, "wear_factor": 0.86},
    ]

    components: list[dict] = []
    for profile in component_profiles:
        raw_tti = max(0.0, float(profile["base_tti"]) - (wear_index * float(profile["wear_factor"])))
        tti_hours = round(raw_tti, 1)
        status, status_label, emoji, color = _component_tti_status(tti_hours)
        progress_pct = int(max(0, min(100, round((tti_hours / float(profile["base_tti"])) * 100))))
        components.append(
            {
                "component_key": profile["key"],
                "component_label": profile["label"],
                "tti_hours": tti_hours,
                "status": status,
                "status_label": status_label,
                "status_emoji": emoji,
                "status_color": color,
                "progress_pct": progress_pct,
            }
        )

    due_components = [row for row in components if float(row.get("tti_hours") or 0.0) < 10.0]
    fleet_status_label = "Fleet Status: Gold Master."
    if due_components:
        fleet_status_label = "Fleet Status: Service Required."

    return {
        "status": "ACTIVE",
        "label": "Predictive Maintenance: Active.",
        "fleet_status_label": fleet_status_label,
        "tail_number": tail_number,
        "latest_iron_ppm": round(latest_iron, 1),
        "iron_trend_ppm": round(iron_trend, 1),
        "avg_burn_rate_gph": round(avg_burn_rate, 2),
        "recent_flight_hours": round(recent_flight_hours, 1),
        "components": components,
        "schedule_service_required": bool(due_components),
        "schedule_service_components": [row.get("component_label") for row in due_components],
    }


def correlate_global_signals(
    *,
    tenant_id: object | None,
    user_id: int = 1,
    expedition_records: list[dict] | None = None,
    specimen_records: list[dict] | None = None,
    signal_limit: int = 12,
    min_distant_km: float = 300.0,
) -> dict:
    """
    v2.8 Global Correlation Engine.
    Cross-reference private field observations with global mesh signals and tag
    records as globally significant when similar finds appear in distant regions.
    """
    uid = _normalise_user_id(user_id, default=1)
    expeditions = expedition_records if expedition_records is not None else _query_expeditions(limit=250, user_id=uid, tenant_id=tenant_id)
    specimens = specimen_records if specimen_records is not None else _query_specimen_inventory(limit=250, tenant_id=tenant_id)

    global_signals = _query_global_discovery_feed(
        tenant_id=tenant_id,
        limit=max(3, min(int(signal_limit or 12), 30)),
    )

    local_profile = _query_local_signal_profile(tenant_id=tenant_id)
    mesh_signals: list[dict] = []
    for signal in global_signals:
        center = _hotspot_region_center(signal.get("general_region"))
        if not center:
            continue
        probability = signal_probability(signal, tenant_id=tenant_id, local_profile=local_profile)
        mesh_signals.append(
            {
                "id": int(signal.get("id") or 0),
                "emitted_at": signal.get("emitted_at"),
                "signal_type": signal.get("signal_type"),
                "general_region": signal.get("general_region"),
                "message": signal.get("message"),
                "confidence_pct": int(probability.get("confidence_pct") or 0),
                "probability_status": probability.get("status") or "Plausible",
                "airport_code": center.get("airport_code"),
                "airport_name": center.get("airport_name"),
                "latitude": center.get("latitude"),
                "longitude": center.get("longitude"),
            }
        )

    expedition_index = {int(row.get("id")): row for row in expeditions if row.get("id") is not None}
    specimen_by_expedition: dict[int, list[dict]] = {}
    for specimen in specimens:
        expedition_id = specimen.get("expedition_id")
        if expedition_id is None:
            continue
        try:
            eid = int(expedition_id)
        except (TypeError, ValueError):
            continue
        specimen_by_expedition.setdefault(eid, []).append(specimen)

    def _is_distant(*, lat: float | None, lon: float | None, location_name: object | None, mesh_signal: dict) -> bool:
        mesh_lat = _safe_float(mesh_signal.get("latitude"))
        mesh_lon = _safe_float(mesh_signal.get("longitude"))
        mesh_code = str(mesh_signal.get("airport_code") or "").upper()

        if lat is not None and lon is not None and mesh_lat is not None and mesh_lon is not None:
            return _distance_km(lat, lon, mesh_lat, mesh_lon) >= float(min_distant_km)

        local_code = _extract_airport_code(location_name)
        if local_code and mesh_code:
            return local_code != mesh_code
        return False

    specimen_annotations: dict[int, dict] = {}
    for specimen in specimens:
        specimen_id = specimen.get("id")
        if specimen_id is None:
            continue
        tokens = _signal_tokens(specimen.get("mineral_class") or specimen.get("color") or "")
        if not tokens:
            continue

        lat = _safe_float(specimen.get("latitude"))
        lon = _safe_float(specimen.get("longitude"))
        location_name = specimen.get("location_name")
        expedition_id = specimen.get("expedition_id")
        expedition = expedition_index.get(int(expedition_id)) if expedition_id not in (None, "") else None
        if (lat is None or lon is None) and expedition:
            lat = _safe_float(expedition.get("latitude"))
            lon = _safe_float(expedition.get("longitude"))
            if not location_name:
                location_name = expedition.get("location_name")

        citations: list[int] = []
        for mesh_signal in mesh_signals:
            signal_tokens = _signal_tokens(mesh_signal.get("signal_type"))
            if not tokens.intersection(signal_tokens):
                continue
            if not _is_distant(lat=lat, lon=lon, location_name=location_name, mesh_signal=mesh_signal):
                continue
            citations.append(int(mesh_signal.get("id") or 0))

        deduped = sorted({cid for cid in citations if cid > 0})
        specimen_annotations[int(specimen_id)] = {
            "globally_significant": bool(deduped),
            "mesh_citations": deduped,
            "mesh_citation_count": len(deduped),
        }

    expedition_annotations: dict[int, dict] = {}
    for expedition in expeditions:
        expedition_id = expedition.get("id")
        if expedition_id is None:
            continue
        try:
            eid = int(expedition_id)
        except (TypeError, ValueError):
            continue

        text_tokens = _signal_tokens(expedition.get("specimen_types") or "")
        for specimen in specimen_by_expedition.get(eid, []):
            text_tokens.update(_signal_tokens(specimen.get("mineral_class") or specimen.get("color") or ""))
        if not text_tokens:
            expedition_annotations[eid] = {
                "globally_significant": False,
                "mesh_citations": [],
                "mesh_citation_count": 0,
            }
            continue

        lat = _safe_float(expedition.get("latitude"))
        lon = _safe_float(expedition.get("longitude"))
        location_name = expedition.get("location_name")
        citations: list[int] = []
        for mesh_signal in mesh_signals:
            signal_tokens = _signal_tokens(mesh_signal.get("signal_type"))
            if not text_tokens.intersection(signal_tokens):
                continue
            if not _is_distant(lat=lat, lon=lon, location_name=location_name, mesh_signal=mesh_signal):
                continue
            citations.append(int(mesh_signal.get("id") or 0))

        deduped = sorted({cid for cid in citations if cid > 0})
        expedition_annotations[eid] = {
            "globally_significant": bool(deduped),
            "mesh_citations": deduped,
            "mesh_citation_count": len(deduped),
        }

    return {
        "status": "ACTIVE",
        "label": "Mesh Radar: Active.",
        "mesh_signals": mesh_signals,
        "specimen_annotations": specimen_annotations,
        "expedition_annotations": expedition_annotations,
    }


def _apply_global_correlation_annotations(*, expeditions: list[dict], specimens: list[dict], correlation: dict) -> None:
    expedition_annotations = correlation.get("expedition_annotations") or {}
    specimen_annotations = correlation.get("specimen_annotations") or {}

    for expedition in expeditions:
        exp_id = expedition.get("id")
        try:
            exp_key = int(exp_id)
        except (TypeError, ValueError):
            continue
        annotation = expedition_annotations.get(exp_key) or {}
        citations = annotation.get("mesh_citations") or []
        expedition["globally_significant"] = bool(annotation.get("globally_significant"))
        expedition["mesh_citations"] = citations
        expedition["mesh_citation_count"] = int(annotation.get("mesh_citation_count") or len(citations))

    for specimen in specimens:
        specimen_id = specimen.get("id")
        try:
            specimen_key = int(specimen_id)
        except (TypeError, ValueError):
            continue
        annotation = specimen_annotations.get(specimen_key) or {}
        citations = annotation.get("mesh_citations") or []
        specimen["globally_significant"] = bool(annotation.get("globally_significant"))
        specimen["mesh_citations"] = citations
        specimen["mesh_citation_count"] = int(annotation.get("mesh_citation_count") or len(citations))


def _hotspot_region_center(general_region: object | None) -> dict | None:
    text = str(general_region or "").upper()
    match = _AIRPORT_CODE_PATTERN.search(text)
    if not match:
        return None
    code = match.group(0)
    if code not in _AIRPORT_REFERENCE:
        return None

    airport = _AIRPORT_REFERENCE[code]
    return {
        "airport_code": code,
        "airport_name": airport["name"],
        "latitude": airport["latitude"],
        "longitude": airport["longitude"],
    }


def predict_hotspots(*, months: int = 12, horizon_days: int = 30, limit: int = 5) -> list[dict]:
    _ensure_global_node_schema()
    rolling_days = max(30, min(int(months) * 30, 730))
    cutoff = (datetime.now(timezone.utc) - timedelta(days=rolling_days)).strftime("%Y-%m-%dT%H:%M:%SZ")

    conn = sqlite3.connect(str(_global_node_db_path()))
    try:
        rows = conn.execute(
            """
            SELECT s.id, s.emitted_at, s.signal_type, s.general_region,
                   COALESCE(v.vouch_count, 0) AS vouch_count
            FROM observatory_signals s
            LEFT JOIN (
                SELECT signal_id, COUNT(*) AS vouch_count
                FROM observatory_signal_vouches
                GROUP BY signal_id
            ) v ON v.signal_id = s.id
            WHERE s.emitted_at >= ?
            ORDER BY s.emitted_at DESC, s.id DESC
            """,
            (cutoff,),
        ).fetchall()
    finally:
        conn.close()

    clusters: dict[str, dict] = {}
    now = datetime.now(timezone.utc)
    for row in rows:
        emitted_dt = _parse_utc_timestamp(row[1])
        if emitted_dt is None:
            continue

        region_label = str(row[3] or "").strip() or "Unknown region"
        region_key = _normalise_region_key(region_label)
        days_ago = max(0.0, (now - emitted_dt).total_seconds() / 86400.0)

        if days_ago <= 30:
            recency_weight = 2.2
        elif days_ago <= 90:
            recency_weight = 1.6
        elif days_ago <= 180:
            recency_weight = 1.2
        else:
            recency_weight = 0.8

        vouch_count = int(row[4] or 0)
        score_delta = recency_weight + min(vouch_count * 0.2, 0.8)

        cluster = clusters.setdefault(
            region_key,
            {
                "region": region_label,
                "signal_count_12m": 0,
                "recent_count_90d": 0,
                "recent_count_30d": 0,
                "vouch_count": 0,
                "weighted_score": 0.0,
            },
        )
        cluster["signal_count_12m"] += 1
        cluster["vouch_count"] += vouch_count
        cluster["weighted_score"] += score_delta
        if days_ago <= 90:
            cluster["recent_count_90d"] += 1
        if days_ago <= 30:
            cluster["recent_count_30d"] += 1

    hotspots: list[dict] = []
    for cluster in clusters.values():
        probability_pct = int(
            min(
                100,
                round(
                    (cluster["weighted_score"] * 14.0)
                    + (cluster["signal_count_12m"] * 8.0)
                    + (cluster["recent_count_90d"] * 7.0)
                ),
            )
        )
        if cluster["signal_count_12m"] >= 3 and cluster["recent_count_90d"] >= 2:
            probability_pct = max(probability_pct, 90)
        if cluster["signal_count_12m"] >= 5 and cluster["recent_count_90d"] >= 3:
            probability_pct = max(probability_pct, 97)

        if probability_pct >= 85:
            confidence_band = "HIGH"
        elif probability_pct >= 60:
            confidence_band = "MEDIUM"
        else:
            confidence_band = "LOW"

        center = _hotspot_region_center(cluster.get("region"))
        hotspots.append(
            {
                "region": cluster.get("region"),
                "probability_pct": probability_pct,
                "confidence_band": confidence_band,
                "pulse_window_days": int(horizon_days),
                "signal_count_12m": int(cluster["signal_count_12m"]),
                "recent_count_90d": int(cluster["recent_count_90d"]),
                "recent_count_30d": int(cluster["recent_count_30d"]),
                "vouch_count": int(cluster["vouch_count"]),
                "weighted_score": round(float(cluster["weighted_score"]), 2),
                "airport_code": (center or {}).get("airport_code"),
                "airport_name": (center or {}).get("airport_name"),
                "latitude": (center or {}).get("latitude"),
                "longitude": (center or {}).get("longitude"),
            }
        )

    hotspots.sort(
        key=lambda row: (
            float(row.get("probability_pct") or 0.0),
            float(row.get("weighted_score") or 0.0),
            int(row.get("signal_count_12m") or 0),
        ),
        reverse=True,
    )
    return hotspots[: max(1, min(int(limit), 10))]


def _build_discovery_forecast(*, tenant_id: object | None, user_id: int, fleet_card: dict) -> dict:
    hotspots = predict_hotspots(months=12, horizon_days=30, limit=5)
    high_priority = [row for row in hotspots if int(row.get("probability_pct") or 0) >= 85]

    profile = _query_user_profile(user_id=user_id, tenant_id=tenant_id) or {}
    home_code = str(profile.get("home_base_icao") or _PRIMARY_ICAO_CODES[0]).strip().upper() or _PRIMARY_ICAO_CODES[0]
    home_airport = _AIRPORT_REFERENCE.get(home_code, _HOME_AIRPORT)

    primary_tail = str(fleet_card.get("primary_tail") or "N6424P")
    shadow_tail = next(
        (
            str(item.get("tail_number"))
            for item in (fleet_card.get("tails") or [])
            if item.get("tail_number") and str(item.get("tail_number")) != primary_tail
        ),
        "N733TR",
    )
    primary_range_km = 650.0
    shadow_range_km = 840.0

    route = None
    for hotspot in high_priority:
        lat = _safe_float(hotspot.get("latitude"))
        lon = _safe_float(hotspot.get("longitude"))
        if lat is None or lon is None:
            continue

        one_way_km = _distance_km(float(home_airport["latitude"]), float(home_airport["longitude"]), lat, lon)
        round_trip_km = round(one_way_km * 2.0, 1)

        selected_tail = None
        if round_trip_km <= primary_range_km:
            selected_tail = primary_tail
        elif round_trip_km <= shadow_range_km:
            selected_tail = shadow_tail

        if selected_tail:
            distance_nm = round(round_trip_km * 0.539957, 1)
            route = {
                "tail_number": selected_tail,
                "home_base_icao": home_code,
                "target_region": hotspot.get("region"),
                "route_label": f"Mission Route: {home_code} -> {hotspot.get('region')} -> {home_code} ({selected_tail})",
                "distance_km": round_trip_km,
                "distance_nm": distance_nm,
                "estimated_time_hr": round(round_trip_km / 185.0, 2),
                "hotspot_probability_pct": hotspot.get("probability_pct"),
            }
            break

    if route:
        status = "ACTIVE"
        label = "Discovery Forecast: High-Yield Zone Detected."
    elif high_priority:
        status = "TRACKING"
        label = "Discovery Forecast: High-Yield Zone Out of Range."
    else:
        status = "MONITORING"
        label = "Discovery Forecast: Monitoring."

    return {
        "status": status,
        "detected": bool(route),
        "label": label,
        "suggested_route": (route or {}).get("route_label") or "Mission Route: Continue scheduled transects",
        "hotspots": hotspots,
        "route": route,
    }


def _request_tenant_id(default: str = _DEFAULT_TENANT_ID) -> str:
    if not has_request_context():
        return _normalise_tenant_id(default)

    raw_query_tenant = request.args.get("tenant_id")
    if raw_query_tenant not in (None, ""):
        return _normalise_tenant_id(raw_query_tenant, default=default)

    raw_query_slug = request.args.get("tenant_slug")
    if raw_query_slug not in (None, ""):
        normalised_slug = _normalise_tenant_id(raw_query_slug, default=default)
        if normalised_slug != "default":
            return normalised_slug

    payload = request.get_json(silent=True) or {}
    if isinstance(payload, dict):
        raw_payload_tenant = payload.get("tenant_id")
        if raw_payload_tenant not in (None, ""):
            return _normalise_tenant_id(raw_payload_tenant, default=default)
        raw_payload_slug = payload.get("tenant_slug")
        if raw_payload_slug not in (None, ""):
            normalised_slug = _normalise_tenant_id(raw_payload_slug, default=default)
            if normalised_slug != "default":
                return normalised_slug

    return _normalise_tenant_id(default)


def _request_organization_id(default: str | None = _DEFAULT_ORGANIZATION_ID) -> str | None:
    if not has_request_context():
        if default is None:
            return None
        return _normalise_organization_id(default)

    raw_query_org = request.args.get("organization_id") or request.args.get("org_id")
    if raw_query_org not in (None, ""):
        if default is None:
            return _normalise_organization_id(raw_query_org)
        return _normalise_organization_id(raw_query_org, default=default)

    payload = request.get_json(silent=True) or {}
    if isinstance(payload, dict):
        raw_payload_org = payload.get("organization_id") or payload.get("org_id")
        if raw_payload_org not in (None, ""):
            if default is None:
                return _normalise_organization_id(raw_payload_org)
            return _normalise_organization_id(raw_payload_org, default=default)

    if default is None:
        return None
    return _normalise_organization_id(default)


def _ensure_tenant_database_initialised(db_path: Path) -> None:
    if db_path.exists():
        return

    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        _ensure_identity_tables(conn)
        _ensure_expeditions_table(conn)
        _ensure_fuel_logs_table(conn)
        _ensure_fleet_readiness_history_table(conn)
        _ensure_specimen_inventory_table(conn)
        _ensure_mission_consumables_table(conn)
        _ensure_fuel_market_logs_table(conn)
        conn.commit()
    finally:
        conn.close()


def _aviation_db_path(tenant_id: object | None = None, organization_id: object | None = None) -> Path:
    resolved_tenant_id = _normalise_tenant_id(tenant_id, default=_DEFAULT_TENANT_ID) if tenant_id is not None else _request_tenant_id()

    use_org_layout = False
    resolved_org_id: str | None = None
    if organization_id is not None:
        use_org_layout = True
        resolved_org_id = _normalise_organization_id(organization_id)
    elif has_request_context():
        requested_org = _request_organization_id(default=None)
        if requested_org is not None:
            use_org_layout = True
            resolved_org_id = requested_org

    if use_org_layout and resolved_org_id:
        db_path = _org_tenant_db_path(organization_id=resolved_org_id, tenant_id=resolved_tenant_id)
        legacy_path = _legacy_tenant_db_path(resolved_tenant_id)
        if not db_path.exists() and legacy_path.exists():
            db_path = legacy_path
    else:
        db_path = _legacy_tenant_db_path(resolved_tenant_id)

    _ensure_tenant_database_initialised(db_path)
    return db_path


def _normalise_user_role(value: object) -> str:
    key = str(value or "Admin").strip().lower()
    return _ROLE_NORMALISATION.get(key, "Admin")


def _is_associate_user(*, tenant_id: object | None, user_id: int) -> bool:
    profile = _query_user_profile(user_id=user_id, tenant_id=tenant_id)
    if not profile:
        return False
    return _normalise_user_role(profile.get("role")) == "Associate"


def _scoped_item_key(item_key: str, user_id: int) -> str:
    clean = (item_key or "").strip().lower()
    return f"u{_normalise_user_id(user_id)}:{clean}"


def _unscoped_item_key(stored_item_key: str) -> str:
    token = str(stored_item_key or "")
    if token.startswith("u") and ":" in token:
        return token.split(":", 1)[1]
    return token


def _ensure_identity_tables(conn: sqlite3.Connection) -> None:
    conn.execute(_CREATE_USER_PROFILES)
    conn.execute(_CREATE_MISSION_SCOPES)
    _ensure_user_profile_columns(conn)
    admin_permissions = json.dumps(_default_role_permissions("Admin"), sort_keys=True)
    conn.execute(
        """
            INSERT INTO user_profiles (id, username, role, home_base_icao, share_signals, mentor_mesh, permissions_json, created_at)
            VALUES (1, 'hutch', 'Admin', ?, 0, NULL, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            username = excluded.username,
            role = excluded.role,
            home_base_icao = excluded.home_base_icao,
            permissions_json = COALESCE(user_profiles.permissions_json, excluded.permissions_json)
        """,
            (_PRIMARY_ICAO_CODES[0], admin_permissions, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")),
    )
    for scope in ("Marine", "Aviation", "Mineral"):
        conn.execute(
            """
            INSERT INTO mission_scopes (user_id, scope_type, is_active)
            VALUES (1, ?, 1)
            ON CONFLICT(user_id, scope_type) DO UPDATE SET
                is_active = excluded.is_active
            """,
            (scope,),
        )


def _seed_mission_consumables_for_user(conn: sqlite3.Connection, user_id: int) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    uid = _normalise_user_id(user_id)
    for item in _MISSION_CONSUMABLE_DEFAULTS:
        conn.execute(
            """
            INSERT INTO mission_consumables (
                item_key, display_name, quantity, unit, restock_threshold, updated_at, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(item_key) DO NOTHING
            """,
            (
                _scoped_item_key(item["item_key"], uid),
                item["display_name"],
                item["quantity"],
                item["unit"],
                item["restock_threshold"],
                now,
                None,
            ),
        )


def _ensure_expeditions_table(conn: sqlite3.Connection) -> None:
    _ensure_identity_tables(conn)
    conn.execute(_CREATE_EXPEDITIONS)
    conn.execute(_CREATE_EXPEDITIONS_IDX)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(rockhounding_expeditions)").fetchall()}
    if "user_id" not in cols:
        conn.execute("ALTER TABLE rockhounding_expeditions ADD COLUMN user_id INTEGER NOT NULL DEFAULT 1")
    conn.commit()


def _ensure_expedition_guest_tokens_table(conn: sqlite3.Connection) -> None:
    _ensure_expeditions_table(conn)
    conn.execute(_CREATE_EXPEDITION_GUEST_TOKENS)
    conn.execute(_CREATE_EXPEDITION_GUEST_TOKENS_IDX)
    conn.commit()


def _ensure_fuel_logs_table(conn: sqlite3.Connection) -> None:
    conn.execute(_CREATE_FUEL_LOGS)
    conn.execute(_CREATE_FUEL_LOGS_IDX)
    conn.commit()


def _ensure_fleet_readiness_history_table(conn: sqlite3.Connection) -> None:
    conn.execute(_CREATE_FLEET_READINESS_HISTORY)
    conn.execute(_CREATE_FLEET_READINESS_HISTORY_IDX)
    conn.commit()


def _ensure_specimen_inventory_table(conn: sqlite3.Connection) -> None:
    conn.execute(_CREATE_SPECIMEN_INVENTORY)
    conn.execute(_CREATE_SPECIMEN_INVENTORY_IDX)

    cols = {row[1] for row in conn.execute("PRAGMA table_info(specimen_inventory)").fetchall()}
    if "estimated_weight_lbs" not in cols:
        conn.execute("ALTER TABLE specimen_inventory ADD COLUMN estimated_weight_lbs REAL")
    if "market_value_usd" not in cols:
        conn.execute("ALTER TABLE specimen_inventory ADD COLUMN market_value_usd REAL")
    if "specific_gravity" not in cols:
        conn.execute("ALTER TABLE specimen_inventory ADD COLUMN specific_gravity REAL")

    conn.commit()


def _ensure_mission_consumables_table(conn: sqlite3.Connection) -> None:
    _ensure_identity_tables(conn)
    conn.execute(_CREATE_MISSION_CONSUMABLES)
    conn.execute(_CREATE_MISSION_CONSUMABLES_IDX)
    conn.execute(_CREATE_MISSION_CONSUMABLE_EVENTS)
    conn.execute(_CREATE_MISSION_CONSUMABLE_EVENTS_IDX)
    _seed_mission_consumables_for_user(conn, 1)
    _ensure_mission_costs_view(conn)
    conn.commit()


def _ensure_mission_costs_view(conn: sqlite3.Connection) -> None:
    conn.execute(_DROP_MISSION_COSTS_VIEW)
    conn.execute(_CREATE_MISSION_COSTS_VIEW)
    conn.commit()


def _ensure_fuel_market_logs_table(conn: sqlite3.Connection) -> None:
    conn.execute(_CREATE_FUEL_MARKET_LOGS)
    conn.execute(_CREATE_FUEL_MARKET_LOGS_IDX)
    conn.commit()


def _ensure_pac_auction_logs_table(conn: sqlite3.Connection) -> None:
    conn.execute(_CREATE_PAC_AUCTION_LOGS)
    conn.execute(_CREATE_PAC_AUCTION_LOGS_IDX)
    conn.commit()


def _parse_market_price(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        price = float(value)
        return price if 1.0 <= price <= 20.0 else None
    text = str(value).strip()
    if not text:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)", text)
    if not match:
        return None
    try:
        price = float(match.group(1))
    except (TypeError, ValueError):
        return None
    return price if 1.0 <= price <= 20.0 else None


def _extract_100ll_price(payload: object) -> float | None:
    fuel_tokens = ("100ll", "ll100", "avgas")
    price_tokens = ("price", "retail", "self", "full", "usd", "amount", "value")

    if isinstance(payload, dict):
        for key, value in payload.items():
            key_l = str(key).lower()
            if any(token in key_l for token in fuel_tokens):
                direct_price = _parse_market_price(value)
                if direct_price is not None:
                    return direct_price
                if isinstance(value, dict):
                    for price_key, price_value in value.items():
                        price_key_l = str(price_key).lower()
                        if any(token in price_key_l for token in price_tokens):
                            nested_price = _parse_market_price(price_value)
                            if nested_price is not None:
                                return nested_price
                if isinstance(value, list):
                    for item in value:
                        nested_price = _extract_100ll_price(item)
                        if nested_price is not None:
                            return nested_price
            elif "fuel" in key_l and isinstance(value, (dict, list)):
                nested_price = _extract_100ll_price(value)
                if nested_price is not None:
                    return nested_price
        return None

    if isinstance(payload, list):
        for item in payload:
            nested_price = _extract_100ll_price(item)
            if nested_price is not None:
                return nested_price

    return None


def _fetch_100ll_market_snapshot() -> list[dict]:
    codes = [str(code).strip().upper() for code in _PRIMARY_ICAO_CODES if str(code).strip()]
    if not codes:
        return []

    payload = None
    endpoint = ""
    try:
        endpoint_template = os.environ.get("HUTCH_100LL_API_URL", _FUEL_MARKET_API_URL_TEMPLATE)
        endpoint = endpoint_template.format(codes=",".join(codes))
        req = urlrequest.Request(endpoint, headers={"User-Agent": "HutchSolves-Cortex/1.7"})
        with urlrequest.urlopen(req, timeout=3.0) as res:
            payload = json.loads(res.read().decode("utf-8"))
    except (KeyError, ValueError, OSError, json.JSONDecodeError, urlerror.URLError, TimeoutError):
        payload = None

    rows: list[dict] = []
    for code in codes:
        scoped = payload
        if isinstance(payload, dict) and code in payload:
            scoped = payload.get(code)

        parsed_price = _extract_100ll_price(scoped)
        if parsed_price is None and isinstance(payload, dict):
            parsed_price = _extract_100ll_price(payload)

        if parsed_price is not None:
            rows.append(
                {
                    "airport_code": code,
                    "fuel_type": _PRIMARY_FUEL_TYPE,
                    "price_per_gal_usd": round(parsed_price, 3),
                    "source": endpoint or "aviationapi.com",
                    "raw_payload_json": json.dumps(payload)[:2000] if payload is not None else None,
                }
            )
            continue

        fallback_price = _FUEL_MARKET_FALLBACK_USD.get(code, _DEFAULT_FUEL_COST_PER_GAL_USD)
        rows.append(
            {
                "airport_code": code,
                "fuel_type": _PRIMARY_FUEL_TYPE,
                "price_per_gal_usd": round(float(fallback_price), 3),
                "source": "fallback-static",
                "raw_payload_json": json.dumps(payload)[:2000] if payload is not None else None,
            }
        )

    return rows


def _classify_specimen_market_class(mineral_class: str | None) -> str | None:
    if not mineral_class:
        return None
    text = mineral_class.strip().lower()
    for key in _SPECIMEN_MARKET_RATES_USD_PER_LB.keys():
        if key in text:
            return key
    return None


def _estimate_specimen_market_value(mineral_class: str | None, estimated_weight_lbs: float | None) -> float | None:
    market_class = _classify_specimen_market_class(mineral_class)
    if market_class is None:
        return None
    if estimated_weight_lbs is None:
        return None
    if estimated_weight_lbs <= 0:
        return 0.0
    rate = _SPECIMEN_MARKET_RATES_USD_PER_LB[market_class]
    return round(float(estimated_weight_lbs) * float(rate), 2)


def _build_specimen_portfolio_summary(specimens: list[dict]) -> dict:
    total_value = 0.0
    valued_count = 0
    class_totals = {"agate": 0.0, "jasper": 0.0}
    for specimen in specimens:
        value = _safe_float(specimen.get("market_value_usd"))
        if value is None:
            continue
        total_value += value
        valued_count += 1
        cls = _classify_specimen_market_class(specimen.get("mineral_class"))
        if cls in class_totals:
            class_totals[cls] += value

    return {
        "portfolio_value_usd": round(total_value, 2),
        "valued_specimen_count": valued_count,
        "total_specimen_count": len(specimens),
        "agate_value_usd": round(class_totals["agate"], 2),
        "jasper_value_usd": round(class_totals["jasper"], 2),
        "rates_usd_per_lb": dict(_SPECIMEN_MARKET_RATES_USD_PER_LB),
    }


def _query_recent_fuel_market_average(conn: sqlite3.Connection, airport_code: str, lookback: int = _FUEL_MARKET_HISTORY_WINDOW) -> float | None:
    rows = conn.execute(
        """
        SELECT price_per_gal_usd
        FROM fuel_market_logs
        WHERE airport_code = ? AND fuel_type = ?
        ORDER BY fetched_at DESC, id DESC
        LIMIT ?
        """,
        (airport_code, _PRIMARY_FUEL_TYPE, max(1, int(lookback))),
    ).fetchall()
    if not rows:
        return None
    prices = [float(row[0]) for row in rows]
    return sum(prices) / len(prices)


def _build_fuel_market_alert() -> dict:
    snapshots = _fetch_100ll_market_snapshot()
    if not snapshots:
        return {
            "is_refuel_alert": False,
            "label": "Fuel Market: Nominal.",
            "local_airport": _PRIMARY_ICAO_CODES[0],
            "fuel_type": _PRIMARY_FUEL_TYPE,
            "current_price_usd": None,
            "five_log_avg_usd": None,
            "quotes": [],
        }

    fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    enriched_quotes: list[dict] = []
    db_path = _aviation_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        conn = sqlite3.connect(str(db_path))
        try:
            _ensure_fuel_market_logs_table(conn)
            for quote in snapshots:
                code = str(quote.get("airport_code") or "").upper()
                price = float(quote.get("price_per_gal_usd") or 0.0)
                prior_avg = _query_recent_fuel_market_average(conn, code, lookback=_FUEL_MARKET_HISTORY_WINDOW)
                is_below = prior_avg is not None and price < prior_avg
                conn.execute(
                    """
                    INSERT INTO fuel_market_logs (
                        airport_code, fuel_type, price_per_gal_usd, fetched_at, source, raw_payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        code,
                        quote.get("fuel_type") or _PRIMARY_FUEL_TYPE,
                        price,
                        fetched_at,
                        quote.get("source"),
                        quote.get("raw_payload_json"),
                    ),
                )
                enriched_quotes.append(
                    {
                        **quote,
                        "fetched_at": fetched_at,
                        "five_log_avg_usd": round(prior_avg, 3) if prior_avg is not None else None,
                        "is_below_5_log_avg": is_below,
                    }
                )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        for quote in snapshots:
            enriched_quotes.append(
                {
                    **quote,
                    "fetched_at": fetched_at,
                    "five_log_avg_usd": None,
                    "is_below_5_log_avg": False,
                }
            )

    primary_quote = next((q for q in enriched_quotes if q.get("airport_code") == _PRIMARY_ICAO_CODES[0]), None)
    if primary_quote is None and enriched_quotes:
        primary_quote = enriched_quotes[0]

    if primary_quote is None:
        return {
            "is_refuel_alert": False,
            "label": "Fuel Market: Nominal.",
            "local_airport": _PRIMARY_ICAO_CODES[0],
            "fuel_type": _PRIMARY_FUEL_TYPE,
            "current_price_usd": None,
            "five_log_avg_usd": None,
            "quotes": enriched_quotes,
        }

    is_refuel_alert = bool(primary_quote.get("is_below_5_log_avg"))
    if is_refuel_alert:
        label = (
            f"Refuel Alert: {primary_quote.get('airport_code')} {_PRIMARY_FUEL_TYPE} "
            f"${float(primary_quote.get('price_per_gal_usd') or 0.0):.2f}/gal "
            f"(5-log avg ${float(primary_quote.get('five_log_avg_usd') or 0.0):.2f})"
        )
    else:
        label = "Fuel Market: Nominal."

    return {
        "is_refuel_alert": is_refuel_alert,
        "label": label,
        "local_airport": primary_quote.get("airport_code"),
        "fuel_type": _PRIMARY_FUEL_TYPE,
        "current_price_usd": round(float(primary_quote.get("price_per_gal_usd") or 0.0), 3),
        "five_log_avg_usd": (
            round(float(primary_quote.get("five_log_avg_usd")), 3)
            if primary_quote.get("five_log_avg_usd") is not None
            else None
        ),
        "quotes": enriched_quotes,
    }


def _taf_weather_signal(taf_text: str | None) -> tuple[int, str]:
    if not taf_text:
        return 62, "mixed TAF confidence"

    raw = taf_text.upper()
    if any(token in raw for token in (" TS", "+TS", "SQ", "FC", "GR")):
        return 28, "convective risk in TAF"
    if any(token in raw for token in ("FG", "FZFG", "1/2SM", "1SM", "2SM", "OVC00", "OVC01", "BKN00", "BKN01")):
        return 40, "low-visibility TAF signals"
    if any(token in raw for token in ("BR", "3SM", "4SM", "5SM", "OVC02", "BKN02", "OVC03", "BKN03")):
        return 68, "marginal cloud/visibility profile"
    return 90, "clear-sky leaning TAF profile"


def _build_weather_forecast_windows(airport_code: str, horizon_days: int = 5) -> list[dict]:
    weather = _fetch_weather_bundle(airport_code)
    taf = weather.get("taf")
    base_score, signal_reason = _taf_weather_signal(taf)
    windows: list[dict] = []
    start_day = datetime.now(timezone.utc).date()

    for offset in range(max(1, min(horizon_days, 7))):
        day = start_day + timedelta(days=offset)
        weekend_bonus = 4 if day.weekday() >= 5 else 0
        fallback_penalty = -8 if weather.get("is_fallback") else 0
        score = max(0, min(100, int(base_score + weekend_bonus + fallback_penalty)))
        if score >= 75:
            label = "Clear Skies"
        elif score >= 55:
            label = "Mixed Weather"
        else:
            label = "Weather Risk"

        windows.append(
            {
                "date": day.isoformat(),
                "airport_code": weather.get("airport_code") or airport_code,
                "weather_score": score,
                "weather_label": label,
                "weather_reason": signal_reason,
                "taf_source": weather.get("source") or "unknown",
            }
        )

    return windows


def _extract_event_day(value: str | None) -> str | None:
    if not value:
        return None
    parsed = _parse_utc_timestamp(value)
    if parsed is None:
        return None
    return parsed.strftime("%Y-%m-%d")


def _is_zero_drift_engagement_event(event: dict) -> bool:
    event_name = str(event.get("event") or "").strip().upper()
    if event_name == _PAC_AUCTION_EVENT:
        return True
    payload = event.get("payload")
    if isinstance(payload, dict):
        engagement_type = str(payload.get("engagement_type") or "").strip().upper()
        if engagement_type == _PAC_AUCTION_EVENT:
            return True
    return False


def _query_pac_pruning_metrics(*, target_date: datetime | None = None) -> dict:
    db_path = _marine_db_path()
    day = (target_date or datetime.now(timezone.utc)).strftime("%Y-%m-%d")
    if not db_path.exists():
        return {
            "pruned_today_count": 0,
            "pruned_today_billable_pulse": 0.0,
            "engagement_categories": [],
            "recorded_drift_pct": 0.0,
            "professional_ecology_label": "Professional Ecology: Monitoring.",
            "status": "MONITORING",
        }

    with open_sqlite(db_path) as conn:
        _ensure_pac_auction_logs_table(conn)
        rows = conn.execute(
            """
            SELECT auction_date, engagement_category, billable_pulse, drift_pct
            FROM pac_auction_logs
            WHERE auction_date = ?
            ORDER BY id DESC
            """,
            (day,),
        ).fetchall()

    categories = sorted({str(row[1]) for row in rows if row[1]})
    total_billable = round(sum(float(row[2] or 0.0) for row in rows), 2)
    # PAC_AUCTION is explicitly treated as zero-drift once pruning automation is active.
    avg_drift = 0.0
    is_pruned = len(rows) > 0
    return {
        "pruned_today_count": len(rows),
        "pruned_today_billable_pulse": total_billable,
        "engagement_categories": categories,
        "recorded_drift_pct": avg_drift,
        "professional_ecology_label": (
            "Professional Ecology: Pruned and Flowing." if is_pruned else "Professional Ecology: Monitoring."
        ),
        "status": "PRUNED" if is_pruned else "MONITORING",
    }


def _build_consulting_drift_windows(horizon_days: int = 5) -> tuple[list[dict], dict]:
    events = query_events("lakeside-legal", limit=4000)
    pulses_by_day: dict[str, int] = {}
    for event in events:
        if _is_zero_drift_engagement_event(event):
            continue
        if event.get("event") != "engagement_pulse":
            continue
        day = _extract_event_day(event.get("timestamp"))
        if day is None:
            continue
        pulses_by_day[day] = pulses_by_day.get(day, 0) + 1

    weekday_minutes: dict[int, list[int]] = {idx: [] for idx in range(7)}
    for day_text, pulses in pulses_by_day.items():
        try:
            day_obj = datetime.strptime(day_text, "%Y-%m-%d").date()
        except ValueError:
            continue
        weekday_minutes[day_obj.weekday()].append(int(pulses * PULSE_INTERVAL_MIN))

    weekday_avg_minutes = {
        idx: (sum(values) / len(values) if values else 45.0)
        for idx, values in weekday_minutes.items()
    }

    windows: list[dict] = []
    start_day = datetime.now(timezone.utc).date()
    for offset in range(max(1, min(horizon_days, 7))):
        day = start_day + timedelta(days=offset)
        projected_minutes = float(weekday_avg_minutes.get(day.weekday(), 45.0))
        drift_score = max(0, min(100, round(100.0 - (projected_minutes / 180.0) * 100.0, 1)))
        if drift_score >= 70:
            drift_label = "Low Consulting Drift"
        elif drift_score >= 45:
            drift_label = "Moderate Consulting Drift"
        else:
            drift_label = "High Consulting Drift"

        windows.append(
            {
                "date": day.isoformat(),
                "projected_billable_min": round(projected_minutes, 1),
                "drift_score": drift_score,
                "drift_label": drift_label,
            }
        )

    today = datetime.now(timezone.utc)
    cutoff_24h = (today - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S")
    pulses_24h = sum(1 for e in events if e.get("event") == "engagement_pulse" and str(e.get("timestamp") or "") >= cutoff_24h)
    zero_drift_events_24h = sum(
        1 for e in events if _is_zero_drift_engagement_event(e) and str(e.get("timestamp") or "") >= cutoff_24h
    )
    current_billable_min_24h = int(pulses_24h * PULSE_INTERVAL_MIN)
    baseline_daily_min = round(sum(weekday_avg_minutes.values()) / max(1, len(weekday_avg_minutes)), 1)
    load_ratio = round(current_billable_min_24h / baseline_daily_min, 2) if baseline_daily_min > 0 else 0.0

    return windows, {
        "tenant_slug": "lakeside-legal",
        "current_billable_min_24h": current_billable_min_24h,
        "baseline_daily_billable_min": baseline_daily_min,
        "load_ratio": load_ratio,
        "zero_drift_events_24h": zero_drift_events_24h,
    }


def _score_fuel_market_trend(fuel_market: dict) -> dict:
    current_price = _safe_float(fuel_market.get("current_price_usd"))
    avg_price = _safe_float(fuel_market.get("five_log_avg_usd"))
    if current_price is None:
        return {
            "fuel_score": 50.0,
            "fuel_label": "Fuel Trend Unknown",
            "current_price_usd": None,
            "five_log_avg_usd": avg_price,
            "delta_vs_avg_usd": None,
        }

    if avg_price is None:
        return {
            "fuel_score": 55.0,
            "fuel_label": "Low Fuel Prices" if not fuel_market.get("is_refuel_alert") else "Fuel Trend Mixed",
            "current_price_usd": round(current_price, 3),
            "five_log_avg_usd": None,
            "delta_vs_avg_usd": None,
        }

    delta = round(avg_price - current_price, 3)
    score = max(0.0, min(100.0, round(50.0 + (delta * 40.0), 1)))
    label = "Low Fuel Prices" if delta >= 0 else "Rising Fuel Prices"
    return {
        "fuel_score": score,
        "fuel_label": label,
        "current_price_usd": round(current_price, 3),
        "five_log_avg_usd": round(avg_price, 3),
        "delta_vs_avg_usd": delta,
    }


def _build_mission_forecast(*, fuel_market: dict | None = None, horizon_days: int = 5) -> dict:
    active_fuel_market = fuel_market or _build_fuel_market_alert()
    fuel_score_block = _score_fuel_market_trend(active_fuel_market)
    weather_windows = _build_weather_forecast_windows(
        airport_code=active_fuel_market.get("local_airport") or _PRIMARY_ICAO_CODES[0],
        horizon_days=horizon_days,
    )
    drift_windows, drift_profile = _build_consulting_drift_windows(horizon_days=horizon_days)

    combined_windows: list[dict] = []
    for idx in range(min(len(weather_windows), len(drift_windows))):
        weather = weather_windows[idx]
        drift = drift_windows[idx]
        launch_score = round(
            (float(weather.get("weather_score") or 0.0) * 0.50)
            + (float(fuel_score_block.get("fuel_score") or 0.0) * 0.25)
            + (float(drift.get("drift_score") or 0.0) * 0.25),
            1,
        )
        detail_breakdown = f"{weather.get('weather_label')} + {fuel_score_block.get('fuel_label')} + {drift.get('drift_label')}."
        combined_windows.append(
            {
                "date": weather.get("date"),
                "launch_score": launch_score,
                "breakdown_summary": "Clear Skies + Low Fuel Prices + Low Consulting Drift.",
                "score_breakdown": detail_breakdown,
                "weather": weather,
                "fuel": fuel_score_block,
                "consulting_drift": drift,
            }
        )

    if not combined_windows:
        return {
            "suggested_date": None,
            "label": "Suggested Launch: unavailable",
            "breakdown_summary": "Clear Skies + Low Fuel Prices + Low Consulting Drift.",
            "horizon_days": horizon_days,
            "windows": [],
            "drift_profile": drift_profile,
            "fuel_market": active_fuel_market,
        }

    best = max(combined_windows, key=lambda row: float(row.get("launch_score") or 0.0))
    return {
        "suggested_date": best.get("date"),
        "label": f"Suggested Launch: {best.get('date')}",
        "breakdown_summary": "Clear Skies + Low Fuel Prices + Low Consulting Drift.",
        "score_breakdown": best.get("score_breakdown") or "Mixed Weather + Low Fuel Prices + Low Consulting Drift.",
        "horizon_days": horizon_days,
        "windows": combined_windows,
        "drift_profile": drift_profile,
        "fuel_market": active_fuel_market,
    }


def _query_expeditions(limit: int = 100, user_id: int = 1, tenant_id: object | None = None) -> list[dict]:
    """Return expedition records, newest-first."""
    db_path = _aviation_db_path(tenant_id)
    if not db_path.exists():
        return []
    uid = _normalise_user_id(user_id)
    try:
        conn = sqlite3.connect(str(db_path))
        try:
            _ensure_expeditions_table(conn)
            rows = conn.execute(
                "SELECT id, user_id, timestamp, location_name, latitude, longitude, "
                "specimen_types, yield_rating FROM rockhounding_expeditions "
                "WHERE user_id = ? "
                "ORDER BY timestamp DESC LIMIT ?",
                (uid, limit),
            ).fetchall()
        finally:
            conn.close()
    except Exception:
        return []
    cols = ["id", "user_id", "timestamp", "location_name", "latitude", "longitude", "specimen_types", "yield_rating"]
    expeditions = [dict(zip(cols, row)) for row in rows]
    if expeditions:
        candidates = _collect_transport_flight_candidates(limit=300, tenant_id=tenant_id)
        mission_cost_index = _query_mission_cost_index(
            [int(exp["id"]) for exp in expeditions if exp.get("id") is not None],
            tenant_id=tenant_id,
        )
        for expedition in expeditions:
            expedition["transport_flight_suggestion"] = _build_transport_flight_suggestion(
                expedition.get("timestamp"),
                candidates=candidates,
                tenant_id=tenant_id,
            )
            expedition["mission_cost"] = mission_cost_index.get(expedition.get("id"), {
                "transport_flight_expense_usd": 0.0,
                "consumables_cost_usd": 0.0,
                "total_mission_cost_usd": 0.0,
                "five_star_count": 0,
                "cost_per_5_star_usd": None,
                "specimen_count": 0,
            })
    return expeditions


def _query_shared_expedition_by_id(expedition_id: int, tenant_id: object | None = None) -> dict | None:
    db_path = _aviation_db_path(tenant_id)
    if not db_path.exists():
        return None
    try:
        conn = sqlite3.connect(str(db_path))
        try:
            _ensure_expeditions_table(conn)
            row = conn.execute(
                "SELECT id, user_id, timestamp, location_name, latitude, longitude, specimen_types, yield_rating "
                "FROM rockhounding_expeditions WHERE id = ? LIMIT 1",
                (int(expedition_id),),
            ).fetchone()
        finally:
            conn.close()
    except Exception:
        return None

    if row is None:
        return None

    expedition = {
        "id": row[0],
        "user_id": row[1],
        "timestamp": row[2],
        "location_name": row[3],
        "latitude": row[4],
        "longitude": row[5],
        "specimen_types": row[6],
        "yield_rating": row[7],
    }
    expedition["transport_flight_suggestion"] = _build_transport_flight_suggestion(
        expedition.get("timestamp"),
        tenant_id=tenant_id,
    )
    expedition["mission_cost"] = _query_mission_cost_index([int(expedition["id"])], tenant_id=tenant_id).get(
        int(expedition["id"]),
        {
            "transport_flight_expense_usd": 0.0,
            "consumables_cost_usd": 0.0,
            "total_mission_cost_usd": 0.0,
            "five_star_count": 0,
            "cost_per_5_star_usd": None,
            "specimen_count": 0,
        },
    )
    return expedition


def _hash_one_time_access_token(token: str) -> str:
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


def _mask_external_email(value: str) -> str:
    text = str(value or "").strip()
    if "@" not in text:
        return "external guest"
    local, domain = text.split("@", 1)
    masked_local = f"{local[:1]}***" if local else "***"
    return f"{masked_local}@{domain}"


def _create_expedition_guest_invite(
    *,
    tenant_id: object | None,
    expedition_id: int,
    external_email: str,
    actor: str,
) -> dict | None:
    resolved_tenant_id = _normalise_tenant_id(tenant_id or _DEFAULT_TENANT_ID)
    expedition = _query_shared_expedition_by_id(expedition_id=expedition_id, tenant_id=resolved_tenant_id)
    if expedition is None:
        return None

    now_dt = datetime.now(timezone.utc)
    created_at = now_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    expires_at = (now_dt + timedelta(hours=_EXPEDITION_GUEST_TOKEN_TTL_HOURS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    token = secrets.token_urlsafe(24)
    token_hash = _hash_one_time_access_token(token)
    db_path = _aviation_db_path(resolved_tenant_id)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    try:
        _ensure_expedition_guest_tokens_table(conn)
        cur = conn.execute(
            """
            INSERT INTO expedition_guest_tokens (
                expedition_id, tenant_id, external_email, token_hash,
                created_at, expires_at, redeemed_at, actor
            ) VALUES (?, ?, ?, ?, ?, ?, NULL, ?)
            """,
            (
                int(expedition_id),
                resolved_tenant_id,
                str(external_email).strip().lower(),
                token_hash,
                created_at,
                expires_at,
                actor,
            ),
        )
        conn.commit()
        invite_id = int(cur.lastrowid)
    finally:
        conn.close()

    return {
        "invite_id": invite_id,
        "token": token,
        "tenant_id": resolved_tenant_id,
        "expedition_id": int(expedition_id),
        "created_at": created_at,
        "expires_at": expires_at,
        "external_email": str(external_email).strip().lower(),
        "external_email_hint": _mask_external_email(external_email),
        "expedition": expedition,
    }


def _redeem_expedition_guest_invite(*, tenant_id: object | None, token: str) -> dict | None:
    resolved_tenant_id = _normalise_tenant_id(tenant_id or _DEFAULT_TENANT_ID)
    db_path = _aviation_db_path(resolved_tenant_id)
    if not db_path.exists():
        return None
    token_hash = _hash_one_time_access_token(token)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    conn = sqlite3.connect(str(db_path))
    try:
        _ensure_expedition_guest_tokens_table(conn)
        row = conn.execute(
            """
            SELECT id, expedition_id, external_email, created_at, expires_at, redeemed_at
            FROM expedition_guest_tokens
            WHERE token_hash = ?
            LIMIT 1
            """,
            (token_hash,),
        ).fetchone()
        if row is None:
            return None
        if row[5]:
            return {
                "status": "already_redeemed",
                "invite_id": int(row[0]),
                "expedition_id": int(row[1]),
                "external_email": row[2],
                "created_at": row[3],
                "expires_at": row[4],
                "redeemed_at": row[5],
            }
        if str(row[4]) < now:
            return {
                "status": "expired",
                "invite_id": int(row[0]),
                "expedition_id": int(row[1]),
                "external_email": row[2],
                "created_at": row[3],
                "expires_at": row[4],
                "redeemed_at": row[5],
            }

        conn.execute(
            "UPDATE expedition_guest_tokens SET redeemed_at = ? WHERE id = ?",
            (now, int(row[0])),
        )
        conn.commit()
    finally:
        conn.close()

    expedition = _query_shared_expedition_by_id(expedition_id=int(row[1]), tenant_id=resolved_tenant_id)
    return {
        "status": "granted",
        "invite_id": int(row[0]),
        "tenant_id": resolved_tenant_id,
        "expedition_id": int(row[1]),
        "external_email": row[2],
        "external_email_hint": _mask_external_email(row[2]),
        "created_at": row[3],
        "expires_at": row[4],
        "redeemed_at": now,
        "expedition": expedition,
    }


def _insert_expedition(
    *,
    tenant_id: object | None,
    user_id: int,
    timestamp: str,
    location_name: str | None,
    latitude: float | None,
    longitude: float | None,
    specimen_types: str | None,
    yield_rating: float | None,
) -> dict:
    resolved_tenant_id = _normalise_tenant_id(tenant_id or _request_tenant_id())
    db_path = _aviation_db_path(resolved_tenant_id)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        _ensure_expeditions_table(conn)
        cur = conn.execute(
            "INSERT INTO rockhounding_expeditions "
            "(user_id, timestamp, location_name, latitude, longitude, specimen_types, yield_rating) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, timestamp, location_name, latitude, longitude, specimen_types, yield_rating),
        )
        conn.commit()
        new_id = cur.lastrowid
    finally:
        conn.close()

    return {
        "id": new_id,
        "user_id": user_id,
        "tenant_id": resolved_tenant_id,
        "timestamp": timestamp,
        "location_name": location_name,
        "latitude": latitude,
        "longitude": longitude,
        "specimen_types": specimen_types,
        "yield_rating": yield_rating,
        "status": "created",
        "transport_flight_suggestion": _build_transport_flight_suggestion(timestamp, tenant_id=resolved_tenant_id),
    }


def _query_mission_cost_index(expedition_ids: list[int], tenant_id: object | None = None) -> dict[int, dict]:
    db_path = _aviation_db_path(tenant_id)
    if not expedition_ids or not db_path.exists():
        return {}
    placeholders = ",".join(["?"] * len(expedition_ids))
    try:
        conn = sqlite3.connect(str(db_path))
        try:
            _ensure_expeditions_table(conn)
            _ensure_fuel_logs_table(conn)
            _ensure_specimen_inventory_table(conn)
            _ensure_mission_consumables_table(conn)
            rows = conn.execute(
                f"""
                SELECT expedition_id, transport_flight_expense_usd, consumables_cost_usd,
                       total_mission_cost_usd, specimen_count, five_star_count
                FROM mission_costs
                WHERE expedition_id IN ({placeholders})
                """,
                expedition_ids,
            ).fetchall()
        finally:
            conn.close()
    except Exception:
        return {}

    out: dict[int, dict] = {}
    for row in rows:
        expedition_id = int(row[0])
        transport_cost = float(row[1] or 0.0)
        consumables_cost = float(row[2] or 0.0)
        total_cost = float(row[3] or 0.0)
        specimen_count = int(row[4] or 0)
        five_star_count = int(row[5] or 0)
        out[expedition_id] = {
            "transport_flight_expense_usd": round(transport_cost, 2),
            "consumables_cost_usd": round(consumables_cost, 2),
            "total_mission_cost_usd": round(total_cost, 2),
            "specimen_count": specimen_count,
            "five_star_count": five_star_count,
            "cost_per_5_star_usd": round(transport_cost / five_star_count, 2) if five_star_count > 0 else None,
        }
    return out


def _query_specimen_inventory(limit: int = 100, tenant_id: object | None = None) -> list[dict]:
    db_path = _aviation_db_path(tenant_id)
    if not db_path.exists():
        return []
    try:
        conn = sqlite3.connect(str(db_path))
        try:
            _ensure_expeditions_table(conn)
            _ensure_specimen_inventory_table(conn)
            rows = conn.execute(
                """
                SELECT s.id, s.expedition_id, s.timestamp, s.image_path,
                       s.yield_stars, s.color, s.hardness, s.specific_gravity, s.mineral_class,
                       s.estimated_weight_lbs, s.market_value_usd, s.notes, s.latitude, s.longitude, s.transport_suggestion_json,
                       e.location_name
                FROM specimen_inventory s
                LEFT JOIN rockhounding_expeditions e ON e.id = s.expedition_id
                ORDER BY s.timestamp DESC, s.id DESC
                LIMIT ?
                """,
                (max(1, min(limit, 500)),),
            ).fetchall()
        finally:
            conn.close()
    except Exception:
        return []

    result = []
    for row in rows:
        suggestion = None
        if row[14]:
            try:
                suggestion = json.loads(row[14])
            except (TypeError, ValueError, json.JSONDecodeError):
                suggestion = None

        estimated_weight = _safe_float(row[9])
        market_value = _safe_float(row[10])
        if market_value is None:
            market_value = _estimate_specimen_market_value(row[8], estimated_weight)
        result.append(
            {
                "id": row[0],
                "expedition_id": row[1],
                "timestamp": row[2],
                "image_path": row[3],
                "yield_stars": row[4],
                "color": row[5],
                "hardness": row[6],
                "specific_gravity": _safe_float(row[7]),
                "mineral_class": row[8],
                "estimated_weight_lbs": estimated_weight,
                "market_value_usd": market_value,
                "notes": row[11],
                "latitude": row[12],
                "longitude": row[13],
                "transport_flight_suggestion": suggestion,
                "location_name": row[15],
            }
        )
    return result


def _insert_specimen_inventory(
    *,
    expedition_id: int | None,
    timestamp: str,
    image_path: str | None,
    yield_stars: int,
    estimated_weight_lbs: float | None,
    market_value_usd: float | None,
    color: str | None,
    hardness: float | None,
    specific_gravity: float | None,
    mineral_class: str | None,
    notes: str | None,
    latitude: float | None,
    longitude: float | None,
    tenant_id: object | None = None,
) -> dict:
    db_path = _aviation_db_path(tenant_id)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    suggestion = _build_transport_flight_suggestion(timestamp, tenant_id=tenant_id)
    suggestion_blob = json.dumps(suggestion) if suggestion else None

    conn = sqlite3.connect(str(db_path))
    try:
        _ensure_expeditions_table(conn)
        _ensure_specimen_inventory_table(conn)
        resolved_market_value = market_value_usd
        if resolved_market_value is None:
            resolved_market_value = _estimate_specimen_market_value(mineral_class, estimated_weight_lbs)
        cur = conn.execute(
            """
            INSERT INTO specimen_inventory (
                expedition_id, timestamp, image_path, yield_stars, color,
                hardness, specific_gravity, mineral_class, estimated_weight_lbs, market_value_usd, notes, latitude, longitude,
                transport_suggestion_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                expedition_id,
                timestamp,
                image_path,
                yield_stars,
                color,
                hardness,
                specific_gravity,
                mineral_class,
                estimated_weight_lbs,
                resolved_market_value,
                notes,
                latitude,
                longitude,
                suggestion_blob,
            ),
        )
        conn.commit()
        specimen_id = cur.lastrowid
    finally:
        conn.close()

    latest = _query_specimen_inventory(limit=1, tenant_id=tenant_id)
    if latest and latest[0].get("id") == specimen_id:
        return latest[0]
    return {
        "id": specimen_id,
        "expedition_id": expedition_id,
        "timestamp": timestamp,
        "image_path": image_path,
        "yield_stars": yield_stars,
        "estimated_weight_lbs": estimated_weight_lbs,
        "market_value_usd": market_value_usd if market_value_usd is not None else _estimate_specimen_market_value(mineral_class, estimated_weight_lbs),
        "color": color,
        "hardness": hardness,
        "specific_gravity": specific_gravity,
        "mineral_class": mineral_class,
        "notes": notes,
        "latitude": latitude,
        "longitude": longitude,
        "transport_flight_suggestion": suggestion,
    }


def _query_mission_consumables(limit: int = 25, user_id: int = 1, tenant_id: object | None = None) -> list[dict]:
    db_path = _aviation_db_path(tenant_id)
    if not db_path.exists():
        return []
    uid = _normalise_user_id(user_id)
    try:
        conn = sqlite3.connect(str(db_path))
        try:
            _ensure_mission_consumables_table(conn)
            _seed_mission_consumables_for_user(conn, uid)
            rows = conn.execute(
                """
                SELECT id, item_key, display_name, quantity, unit,
                       restock_threshold, updated_at, notes
                FROM mission_consumables
                WHERE item_key LIKE ?
                ORDER BY display_name ASC
                LIMIT ?
                """,
                (f"u{uid}:%", max(1, min(limit, 250))),
            ).fetchall()
            conn.commit()
        finally:
            conn.close()
    except Exception:
        return []

    out = []
    for row in rows:
        quantity = _safe_float(row[3]) or 0.0
        threshold = _safe_float(row[5]) or 0.0
        out.append(
            {
                "id": row[0],
                "item_key": _unscoped_item_key(row[1]),
                "display_name": row[2],
                "quantity": quantity,
                "unit": row[4],
                "restock_threshold": threshold,
                "updated_at": row[6],
                "notes": row[7],
                "is_low": quantity <= threshold,
            }
        )
    return out


def _upsert_mission_consumable(
    *,
    user_id: int,
    item_key: str,
    display_name: str,
    quantity: float,
    unit: str,
    restock_threshold: float,
    notes: str | None,
    updated_at: str,
    source: str = "manual",
    tenant_id: object | None = None,
) -> dict:
    db_path = _aviation_db_path(tenant_id)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    uid = _normalise_user_id(user_id)
    stored_item_key = _scoped_item_key(item_key, uid)
    conn = sqlite3.connect(str(db_path))
    try:
        _ensure_mission_consumables_table(conn)
        _seed_mission_consumables_for_user(conn, uid)

        prev_row = conn.execute(
            "SELECT quantity FROM mission_consumables WHERE item_key = ?",
            (stored_item_key,),
        ).fetchone()
        prev_quantity = float(prev_row[0]) if prev_row is not None else quantity
        delta_quantity = float(quantity) - prev_quantity

        conn.execute(
            """
            INSERT INTO mission_consumables (
                item_key, display_name, quantity, unit, restock_threshold, updated_at, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(item_key) DO UPDATE SET
                display_name = excluded.display_name,
                quantity = excluded.quantity,
                unit = excluded.unit,
                restock_threshold = excluded.restock_threshold,
                updated_at = excluded.updated_at,
                notes = excluded.notes
            """,
            (stored_item_key, display_name, quantity, unit, restock_threshold, updated_at, notes),
        )

        if abs(delta_quantity) > 0.00001:
            conn.execute(
                """
                INSERT INTO mission_consumable_events (
                    item_key, delta_quantity, quantity_after, unit, timestamp, source, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (item_key, delta_quantity, quantity, unit, updated_at, source, notes),
            )

        conn.commit()
    finally:
        conn.close()

    rows = _query_mission_consumables(limit=250, user_id=uid, tenant_id=tenant_id)
    for row in rows:
        if row.get("item_key") == item_key:
            return row
    return {
        "item_key": item_key,
        "display_name": display_name,
        "quantity": quantity,
        "unit": unit,
        "restock_threshold": restock_threshold,
        "updated_at": updated_at,
        "notes": notes,
        "is_low": quantity <= restock_threshold,
    }


def _build_restock_alert(consumables: list[dict]) -> dict:
    watch_keys = {"oil_quarts", "sample_kits"}
    low_items = [
        row for row in consumables
        if row.get("item_key") in watch_keys and bool(row.get("is_low"))
    ]
    low_labels = [row.get("display_name") or row.get("item_key") for row in low_items]
    return {
        "is_active": bool(low_items),
        "label": "Restock Needed" if low_items else "Systems Nominal",
        "low_items": low_items,
        "low_item_labels": low_labels,
        "watch_items": [row for row in consumables if row.get("item_key") in watch_keys],
    }


def auto_restock_check(*, consumables: list[dict], discovery_forecast: dict | None = None) -> dict:
    """
    v2.6 — Predictive Restock Engine.
    If a high-yield zone is detected, compare mission consumables against
    predicted route needs and emit a mission-readiness status.
    """
    forecast = discovery_forecast or {}
    route = forecast.get("route") or {}
    detected_hotspot = bool(forecast.get("detected")) and bool(route)

    route_km = _safe_float(route.get("distance_km")) or 0.0
    route_km = max(route_km, 0.0)
    route_nm = _safe_float(route.get("distance_nm"))
    if route_nm is None and route_km > 0:
        route_nm = round(route_km * 0.539957, 1)

    if detected_hotspot:
        mission_scale = max(1, int(math.ceil(max(route_km, 120.0) / 120.0)))
        required_sample_kits = int(min(12, 2 + mission_scale))
        required_oil_quarts = int(min(12, 2 + int(math.ceil(max(route_km, 160.0) / 160.0))))
    else:
        required_sample_kits = 0
        required_oil_quarts = 0

    stock_by_key = {
        str(item.get("item_key") or ""): float(item.get("quantity") or 0.0)
        for item in consumables
    }
    available_sample_kits = float(stock_by_key.get("sample_kits") or 0.0)
    available_oil_quarts = float(stock_by_key.get("oil_quarts") or 0.0)

    sample_ratio = 1.0 if required_sample_kits <= 0 else min(1.0, available_sample_kits / max(required_sample_kits, 1))
    oil_ratio = 1.0 if required_oil_quarts <= 0 else min(1.0, available_oil_quarts / max(required_oil_quarts, 1))
    consumable_readiness_pct = int(max(0, min(100, round(((sample_ratio + oil_ratio) / 2.0) * 100.0))))

    kits_ready = available_sample_kits >= float(required_sample_kits)
    oil_ready = available_oil_quarts >= float(required_oil_quarts)
    is_ready_for_mission = True if not detected_hotspot else bool(kits_ready and oil_ready)

    shortfall_items: list[str] = []
    if detected_hotspot and not kits_ready:
        shortfall_items.append("Sample Kits")
    if detected_hotspot and not oil_ready:
        shortfall_items.append("Oil Quarts")

    status = "READY" if is_ready_for_mission else "RESUPPLY_REQUIRED"
    status_label = "Ready for Mission" if is_ready_for_mission else "Resupply Required"

    return {
        "status": status,
        "status_label": status_label,
        "detected_hotspot": detected_hotspot,
        "is_ready_for_mission": is_ready_for_mission,
        "readiness_pct": consumable_readiness_pct,
        "required": {
            "sample_kits": required_sample_kits,
            "oil_quarts": required_oil_quarts,
        },
        "available": {
            "sample_kits": round(available_sample_kits, 2),
            "oil_quarts": round(available_oil_quarts, 2),
        },
        "shortfall_items": shortfall_items,
        "route_distance_km": round(route_km, 1),
        "route_distance_nm": route_nm,
    }


def _aircraft_health_component(*, fleet_card: dict | None, aviation_card: dict | None) -> float:
    fleet = fleet_card or {}
    fleet_alert = str(fleet.get("fleet_alert") or "").upper()
    if "CRITICAL" in fleet_alert:
        return 45.0
    if "WARNING" in fleet_alert or "ATTENTION" in fleet_alert:
        return 75.0

    av = aviation_card or {}
    av_status = str(av.get("status") or "").upper()
    if "CRITICAL" in av_status or "OVERDUE" in av_status:
        return 45.0
    if "WARNING" in av_status or "ATTENTION" in av_status:
        return 75.0
    return 100.0


def _build_fleet_readiness_gauge(
    *,
    fuel_market: dict | None,
    fleet_card: dict | None,
    aviation_card: dict | None,
    discovery_forecast: dict | None,
    auto_restock: dict | None,
) -> dict:
    fuel = fuel_market or {}
    forecast = discovery_forecast or {}
    restock = auto_restock or {}

    fuel_component = 45.0 if fuel.get("is_refuel_alert") else 100.0
    consumables_component = float(restock.get("readiness_pct") or 100.0)
    aircraft_component = _aircraft_health_component(fleet_card=fleet_card, aviation_card=aviation_card)

    route = forecast.get("route") or {}
    hotspot_distance_nm = _safe_float(route.get("distance_nm"))
    if hotspot_distance_nm is None:
        route_km = _safe_float(route.get("distance_km"))
        if route_km is not None:
            hotspot_distance_nm = round(route_km * 0.539957, 1)

    distance_factor = 1.0
    if bool(forecast.get("detected")) and hotspot_distance_nm and hotspot_distance_nm > 0:
        distance_factor = max(1.0, float(hotspot_distance_nm) / 100.0)

    readiness_raw = ((fuel_component + consumables_component + aircraft_component) / 3.0) / distance_factor
    readiness_pct = int(max(0, min(100, round(readiness_raw))))

    mission_ready = bool(restock.get("is_ready_for_mission")) and readiness_pct >= 85
    status_label = "Mission Ready" if mission_ready else "Prep Required"

    return {
        "label": f"Fleet Readiness: {readiness_pct}% ({status_label}).",
        "status": "MISSION_READY" if mission_ready else "PREP_REQUIRED",
        "readiness_pct": readiness_pct,
        "fuel_component_pct": int(round(fuel_component)),
        "consumables_component_pct": int(round(consumables_component)),
        "aircraft_component_pct": int(round(aircraft_component)),
        "hotspot_distance_nm": hotspot_distance_nm,
        "distance_factor": round(distance_factor, 3),
    }


def _record_fleet_readiness_snapshot(*, tenant_id: object | None, user_id: int, fleet_readiness: dict) -> None:
    db_path = _aviation_db_path(tenant_id)
    if not db_path.exists():
        return

    uid = _normalise_user_id(user_id)
    snapshot_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    readiness_pct = float(fleet_readiness.get("readiness_pct") or 0.0)
    status = str(fleet_readiness.get("status") or "PREP_REQUIRED")

    try:
        conn = sqlite3.connect(str(db_path))
        try:
            _ensure_fleet_readiness_history_table(conn)
            conn.execute(
                """
                INSERT INTO fleet_readiness_history (user_id, snapshot_date, readiness_pct, status, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id, snapshot_date) DO UPDATE SET
                    readiness_pct = excluded.readiness_pct,
                    status = excluded.status,
                    updated_at = excluded.updated_at
                """,
                (uid, snapshot_date, readiness_pct, status, updated_at),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        return


def _query_low_readiness_streak_days(*, tenant_id: object | None, user_id: int, threshold_pct: float = 70.0) -> int:
    db_path = _aviation_db_path(tenant_id)
    if not db_path.exists():
        return 0

    uid = _normalise_user_id(user_id)
    try:
        conn = sqlite3.connect(str(db_path))
        try:
            _ensure_fleet_readiness_history_table(conn)
            rows = conn.execute(
                """
                SELECT snapshot_date, readiness_pct
                FROM fleet_readiness_history
                WHERE user_id = ?
                ORDER BY snapshot_date DESC
                LIMIT 14
                """,
                (uid,),
            ).fetchall()
        finally:
            conn.close()
    except Exception:
        return 0

    parsed: list[tuple[datetime.date, float]] = []
    for row in rows:
        try:
            day = datetime.strptime(str(row[0]), "%Y-%m-%d").date()
            pct = float(row[1] or 0.0)
            parsed.append((day, pct))
        except (TypeError, ValueError):
            continue

    if len(parsed) < 2:
        return 1 if parsed and parsed[0][1] < threshold_pct else 0

    # Look for the strongest recent consecutive low-readiness streak.
    max_streak = 0
    for idx in range(len(parsed) - 1):
        start_day, start_pct = parsed[idx]
        if start_pct >= threshold_pct:
            continue
        streak = 1
        prev_day = start_day
        for j in range(idx + 1, len(parsed)):
            day, pct = parsed[j]
            if pct >= threshold_pct:
                break
            if (prev_day - day).days != 1:
                break
            streak += 1
            prev_day = day
        max_streak = max(max_streak, streak)

    return max_streak


def optimization_pivot(*, tenant_id: object | None, user_id: int, fleet_readiness: dict) -> dict:
    """
    v2.7 Mission Pivot Engine.
    Compare rockhounding yield velocity vs aviation operational cost over 90 days
    and produce a strategic recommendation for the Morning Card.
    """
    end_day = datetime.now(timezone.utc).date()
    start_day = end_day - timedelta(days=90)
    roi = _query_mission_roi(start_day.isoformat(), end_day.isoformat(), tenant_id=tenant_id)

    recent_expeditions = _query_expeditions(limit=500, user_id=user_id, tenant_id=tenant_id)
    cutoff_iso = datetime.combine(start_day, datetime.min.time(), tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    recent_yields: list[float] = []
    for exp in recent_expeditions:
        ts = str(exp.get("timestamp") or "")
        if ts and ts < cutoff_iso:
            continue
        score = _safe_float(exp.get("yield_rating"))
        if score is not None:
            recent_yields.append(score)

    avg_yield = round((sum(recent_yields) / len(recent_yields)), 2) if recent_yields else 0.0
    five_star_count = int(roi.get("five_star_count") or 0)
    specimen_count = int(roi.get("specimen_count") or 0)
    total_cost = float(roi.get("total_cost_usd") or 0.0)

    yield_velocity_score = min(100.0, round((avg_yield * 12.0) + (five_star_count * 8.0) + (specimen_count * 1.5), 1))
    if not recent_yields and specimen_count == 0 and five_star_count == 0:
        yield_velocity_score = 60.0
    operational_cost_score = min(100.0, round(total_cost / 40.0, 1))

    low_readiness_streak_days = _query_low_readiness_streak_days(
        tenant_id=tenant_id,
        user_id=user_id,
        threshold_pct=70.0,
    )
    readiness_pct = int(fleet_readiness.get("readiness_pct") or 0)

    if low_readiness_streak_days >= 2:
        pivot = "Prioritize Maintenance"
        status = "MAINTENANCE"
        label = "Strategy: Maintenance Focus."
        rationale = "Fleet Readiness <70 for two consecutive days."
    elif readiness_pct < 70:
        pivot = "Prioritize Maintenance"
        status = "MAINTENANCE"
        label = "Strategy: Maintenance Focus."
        rationale = "Operational Cost > Yield Velocity."
    elif yield_velocity_score + 5.0 >= operational_cost_score:
        pivot = "Shift to Mineral Mission"
        status = "OPTIMIZED"
        label = "Strategy: Optimized."
        rationale = "Yield Velocity > Operational Cost."
    else:
        pivot = "Prioritize Maintenance"
        status = "MAINTENANCE"
        label = "Strategy: Maintenance Focus."
        rationale = "Operational Cost > Yield Velocity."

    return {
        "status": status,
        "label": label,
        "pivot": pivot,
        "rationale": rationale,
        "yield_velocity_score": yield_velocity_score,
        "operational_cost_score": operational_cost_score,
        "low_readiness_streak_days": low_readiness_streak_days,
        "window_days": 90,
        "roi": roi,
    }


def _normalise_date_range(start_date: str | None, end_date: str | None) -> tuple[str, str, str]:
    now = datetime.now(timezone.utc)

    def _parse_day(raw: str | None, fallback: datetime) -> datetime:
        if not raw:
            return fallback
        try:
            parsed = datetime.strptime(raw, "%Y-%m-%d")
            return parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return fallback

    fallback_start = (now - timedelta(days=30)).replace(hour=0, minute=0, second=0, microsecond=0)
    start_dt = _parse_day(start_date, fallback_start)
    end_dt = _parse_day(end_date, now.replace(hour=0, minute=0, second=0, microsecond=0))
    if end_dt < start_dt:
        start_dt, end_dt = end_dt, start_dt

    end_exclusive = end_dt + timedelta(days=1)
    start_iso = start_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    end_iso = end_exclusive.strftime("%Y-%m-%dT%H:%M:%SZ")
    label = f"{start_dt.strftime('%Y-%m-%d')}..{end_dt.strftime('%Y-%m-%d')}"
    return start_iso, end_iso, label


def _query_mission_roi(start_date: str | None, end_date: str | None, tenant_id: object | None = None) -> dict:
    start_iso, end_iso, label = _normalise_date_range(start_date, end_date)
    db_path = _aviation_db_path(tenant_id)
    if not db_path.exists():
        return {
            "range": label,
            "start": start_iso,
            "end_exclusive": end_iso,
            "fuel_cost_usd": 0.0,
            "consumables_cost_usd": 0.0,
            "total_cost_usd": 0.0,
            "specimen_count": 0,
            "five_star_count": 0,
            "cost_per_5_star_usd": None,
        }

    try:
        conn = sqlite3.connect(str(db_path))
        try:
            _ensure_expeditions_table(conn)
            _ensure_fuel_logs_table(conn)
            _ensure_specimen_inventory_table(conn)
            _ensure_mission_consumables_table(conn)

            roi_row = conn.execute(
                """
                SELECT
                    COALESCE(SUM(transport_flight_expense_usd), 0.0),
                    COALESCE(SUM(consumables_cost_usd), 0.0),
                    COALESCE(SUM(total_mission_cost_usd), 0.0),
                    COALESCE(SUM(specimen_count), 0),
                    COALESCE(SUM(five_star_count), 0)
                FROM mission_costs
                WHERE expedition_timestamp >= ? AND expedition_timestamp < ?
                """,
                (start_iso, end_iso),
            ).fetchone()
        finally:
            conn.close()
    except Exception:
        roi_row = (0.0, 0.0, 0.0, 0, 0)

    fuel_cost = float(roi_row[0] or 0.0)
    cons_cost = float(roi_row[1] or 0.0)
    total_cost = float(roi_row[2] or 0.0)
    specimen_count = int(roi_row[3] or 0)
    five_star_count = int(roi_row[4] or 0)

    return {
        "range": label,
        "start": start_iso,
        "end_exclusive": end_iso,
        "fuel_cost_usd": round(float(fuel_cost or 0.0), 2),
        "consumables_cost_usd": round(float(cons_cost or 0.0), 2),
        "total_cost_usd": round(total_cost, 2),
        "specimen_count": specimen_count,
        "five_star_count": five_star_count,
        "cost_per_5_star_usd": round(total_cost / five_star_count, 2) if five_star_count > 0 else None,
    }


def _query_fuel_logs(tail_number: str = "", limit: int = 100, tenant_id: object | None = None) -> list[dict]:
    db_path = _aviation_db_path(tenant_id)
    if not db_path.exists():
        return []

    filters = ""
    params: list[object] = []
    if tail_number.strip():
        filters = "WHERE tail_number = ?"
        params.append(tail_number.strip().upper())

    params.append(max(1, min(limit, 500)))

    try:
        conn = sqlite3.connect(str(db_path))
        try:
            _ensure_fuel_logs_table(conn)
            rows = conn.execute(
                f"""
                SELECT id, tail_number, timestamp, hobbs_time, tach_time,
                       gallons_added, fuel_after_gal, burn_rate_gph, notes
                FROM fuel_logs
                {filters}
                ORDER BY timestamp DESC, id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        finally:
            conn.close()
    except Exception:
        return []

    cols = [
        "id", "tail_number", "timestamp", "hobbs_time", "tach_time",
        "gallons_added", "fuel_after_gal", "burn_rate_gph", "notes",
    ]
    return [dict(zip(cols, row)) for row in rows]


def _compute_burn_rate_gph(conn: sqlite3.Connection, tail_number: str, hobbs_time: float | None, tach_time: float | None, gallons_added: float) -> float | None:
    if hobbs_time is None and tach_time is None:
        return None

    prev = conn.execute(
        """
        SELECT hobbs_time, tach_time, gallons_added
        FROM fuel_logs
        WHERE tail_number = ?
        ORDER BY timestamp DESC, id DESC
        LIMIT 1
        """,
        (tail_number,),
    ).fetchone()
    if prev is None:
        return None

    prev_hobbs, prev_tach, _prev_added = prev

    if hobbs_time is not None and prev_hobbs is not None:
        delta = float(hobbs_time) - float(prev_hobbs)
    elif tach_time is not None and prev_tach is not None:
        delta = float(tach_time) - float(prev_tach)
    else:
        return None

    if delta <= 0:
        return None
    return round(gallons_added / delta, 2)


def _insert_fuel_log(
    *,
    tail_number: str,
    timestamp: str,
    hobbs_time: float | None,
    tach_time: float | None,
    gallons_added: float,
    fuel_after_gal: float | None,
    notes: str | None,
    tenant_id: object | None = None,
) -> dict:
    db_path = _aviation_db_path(tenant_id)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        _ensure_fuel_logs_table(conn)
        burn_rate_gph = _compute_burn_rate_gph(
            conn,
            tail_number=tail_number,
            hobbs_time=hobbs_time,
            tach_time=tach_time,
            gallons_added=gallons_added,
        )
        cur = conn.execute(
            """
            INSERT INTO fuel_logs (
                tail_number, timestamp, hobbs_time, tach_time,
                gallons_added, fuel_after_gal, burn_rate_gph, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tail_number,
                timestamp,
                hobbs_time,
                tach_time,
                gallons_added,
                fuel_after_gal,
                burn_rate_gph,
                notes,
            ),
        )
        conn.commit()
        row_id = cur.lastrowid
    finally:
        conn.close()

    latest = _query_fuel_logs(tail_number=tail_number, limit=1, tenant_id=tenant_id)
    if latest:
        return latest[0]
    return {
        "id": row_id,
        "tail_number": tail_number,
        "timestamp": timestamp,
        "hobbs_time": hobbs_time,
        "tach_time": tach_time,
        "gallons_added": gallons_added,
        "fuel_after_gal": fuel_after_gal,
        "burn_rate_gph": None,
        "notes": notes,
    }


def _safe_float(value) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_utc_timestamp(value: object) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    normal = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normal)
    except ValueError:
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        else:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _collect_transport_flight_candidates(limit: int = 250, tenant_id: object | None = None) -> list[dict]:
    db_path = _aviation_db_path(tenant_id)
    if not db_path.exists():
        return []

    candidates: list[dict] = []
    try:
        conn = sqlite3.connect(str(db_path))
        try:
            _ensure_fuel_logs_table(conn)
            fuel_rows = conn.execute(
                """
                SELECT id, tail_number, timestamp, hobbs_time, tach_time, gallons_added
                FROM fuel_logs
                ORDER BY timestamp DESC, id DESC
                LIMIT ?
                """,
                (max(1, min(limit, 1000)),),
            ).fetchall()

            for row in fuel_rows:
                event_dt = _parse_utc_timestamp(row[2])
                if event_dt is None:
                    continue
                candidates.append(
                    {
                        "flight_id": f"FUEL-{(row[1] or 'N6424P').upper()}-{row[0]}",
                        "tail_number": (row[1] or "N6424P").upper(),
                        "source": "fuel_log",
                        "event_timestamp": row[2],
                        "event_dt": event_dt,
                        "label": f"{(row[1] or 'N6424P').upper()} fuel top-off ({float(row[5] or 0.0):.1f} gal)",
                    }
                )

            oil_cols = {info[1] for info in conn.execute("PRAGMA table_info(oil_sentinel_reports)").fetchall()}
            if "analyzed_at" in oil_cols:
                tail_expr = "tail_number" if "tail_number" in oil_cols else "'N6424P'"
                oil_rows = conn.execute(
                    f"""
                    SELECT id, {tail_expr}, report_name, analyzed_at
                    FROM oil_sentinel_reports
                    ORDER BY analyzed_at DESC
                    LIMIT ?
                    """,
                    (max(1, min(limit, 1000)),),
                ).fetchall()
                for row in oil_rows:
                    event_dt = _parse_utc_timestamp(row[3])
                    if event_dt is None:
                        continue
                    tail = (row[1] or "N6424P").upper()
                    title = (row[2] or "Oil report").strip()
                    candidates.append(
                        {
                            "flight_id": f"OIL-{tail}-{row[0]}",
                            "tail_number": tail,
                            "source": "oil_sentinel_report",
                            "event_timestamp": row[3],
                            "event_dt": event_dt,
                            "label": f"{tail} oil log: {title}",
                        }
                    )
        finally:
            conn.close()
    except Exception:
        return []

    return candidates


def _build_transport_flight_suggestion(
    find_timestamp: object,
    candidates: list[dict] | None = None,
    tenant_id: object | None = None,
) -> dict | None:
    find_dt = _parse_utc_timestamp(find_timestamp)
    if find_dt is None:
        return None
    if candidates is None:
        candidates = _collect_transport_flight_candidates(limit=250, tenant_id=tenant_id)
    if not candidates:
        return None

    winner: dict | None = None
    winner_delta_min: float | None = None
    winner_signed_delta: float = 0.0
    for candidate in candidates:
        event_dt = candidate.get("event_dt")
        if not isinstance(event_dt, datetime):
            continue
        signed_delta = (event_dt - find_dt).total_seconds() / 60.0
        delta_min = abs(signed_delta)
        if winner is None or winner_delta_min is None or delta_min < winner_delta_min:
            winner = candidate
            winner_delta_min = delta_min
            winner_signed_delta = signed_delta

    if winner is None or winner_delta_min is None:
        return None

    if winner_delta_min <= 90:
        confidence = "HIGH"
    elif winner_delta_min <= 360:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    return {
        "flight_id": winner.get("flight_id"),
        "tail_number": winner.get("tail_number"),
        "source": winner.get("source"),
        "label": winner.get("label"),
        "event_timestamp": winner.get("event_timestamp"),
        "time_delta_min": round(winner_delta_min, 1),
        "timing": "after" if winner_signed_delta >= 0 else "before",
        "confidence": confidence,
    }


def _query_recent_high_yield_specimen_alert(window_hours: int = 72, tenant_id: object | None = None) -> dict | None:
    db_path = _aviation_db_path(tenant_id)
    if not db_path.exists():
        return None

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=max(1, window_hours))).strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        conn = sqlite3.connect(str(db_path))
        try:
            _ensure_expeditions_table(conn)
            _ensure_specimen_inventory_table(conn)
            row = conn.execute(
                """
                SELECT s.id, s.timestamp, s.yield_stars, s.image_path,
                       s.color, s.hardness, s.mineral_class,
                       s.transport_suggestion_json, e.location_name
                FROM specimen_inventory s
                LEFT JOIN rockhounding_expeditions e ON e.id = s.expedition_id
                WHERE s.yield_stars >= 5
                  AND s.timestamp >= ?
                ORDER BY s.timestamp DESC, s.id DESC
                LIMIT 1
                """,
                (cutoff,),
            ).fetchone()
        finally:
            conn.close()
    except Exception:
        return None

    if row is None:
        return None

    suggestion = None
    if row[7]:
        try:
            suggestion = json.loads(row[7])
        except (TypeError, ValueError, json.JSONDecodeError):
            suggestion = None

    return {
        "id": row[0],
        "timestamp": row[1],
        "yield_stars": row[2],
        "image_path": row[3],
        "color": row[4],
        "hardness": row[5],
        "mineral_class": row[6],
        "transport_flight_suggestion": suggestion,
        "location_name": row[8],
    }


def _load_vault_health_status() -> dict:
    if not _VAULT_HEALTH_STATUS_PATH.exists():
        return {
            "status": "UNKNOWN",
            "label": "Vault Health: UNKNOWN",
            "emoji": "⚪",
            "source": "sentinel-not-run",
            "checked_at": None,
            "drive": "E:\\",
            "internet": None,
            "warnings": [],
            "is_warning": False,
        }
    try:
        with _VAULT_HEALTH_STATUS_PATH.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception:
        return {
            "status": "UNKNOWN",
            "label": "Vault Health: UNKNOWN",
            "emoji": "⚪",
            "source": "sentinel-read-error",
            "checked_at": None,
            "drive": "E:\\",
            "internet": None,
            "warnings": [],
            "is_warning": False,
        }

    if not isinstance(payload, dict):
        return {
            "status": "UNKNOWN",
            "label": "Vault Health: UNKNOWN",
            "emoji": "⚪",
            "source": "sentinel-invalid-payload",
            "checked_at": None,
            "drive": "E:\\",
            "internet": None,
            "warnings": [],
            "is_warning": False,
        }

    status = str(payload.get("status") or "UNKNOWN").upper()
    payload["status"] = status
    payload.setdefault("emoji", "🟠" if status == "WARNING" else "🟢")
    payload.setdefault("label", f"Vault Health: {status}")
    payload.setdefault("warnings", [])
    payload.setdefault("is_warning", status == "WARNING")
    return payload


def _extract_airport_code(*values: object) -> str | None:
    for value in values:
        if not value:
            continue
        text = str(value).upper()
        for match in _AIRPORT_CODE_PATTERN.findall(text):
            if match in _AIRPORT_REFERENCE:
                return match
    return None


def _nearest_airport_from_coords(latitude: float, longitude: float) -> dict:
    nearest_code = None
    nearest_distance = None
    for code, airport in _AIRPORT_REFERENCE.items():
        dist = _distance_km(latitude, longitude, airport["latitude"], airport["longitude"])
        if nearest_distance is None or dist < nearest_distance:
            nearest_distance = dist
            nearest_code = code

    if nearest_code is None:
        return dict(_HOME_AIRPORT)

    return {
        "code": nearest_code,
        "name": _AIRPORT_REFERENCE[nearest_code]["name"],
        "latitude": _AIRPORT_REFERENCE[nearest_code]["latitude"],
        "longitude": _AIRPORT_REFERENCE[nearest_code]["longitude"],
        "distance_km": nearest_distance,
    }


def _resolve_airport_for_report(report: dict, expeditions: list[dict]) -> dict:
    direct_code = _extract_airport_code(report.get("report_name"), report.get("source_pdf"))
    if direct_code:
        airport = _AIRPORT_REFERENCE[direct_code]
        return {
            "code": direct_code,
            "name": airport["name"],
            "latitude": airport["latitude"],
            "longitude": airport["longitude"],
            "distance_km": 0.0,
        }

    for exp in expeditions:
        lat = _safe_float(exp.get("latitude"))
        lon = _safe_float(exp.get("longitude"))
        if lat is None or lon is None:
            continue
        return _nearest_airport_from_coords(lat, lon)

    return dict(_HOME_AIRPORT)


def _build_fungal_mesh_branches(mesh_signals: list[dict] | None) -> list[dict]:
    raw_nodes = mesh_signals or []
    nodes: list[dict] = []
    for signal in raw_nodes:
        lat = _safe_float(signal.get("latitude"))
        lon = _safe_float(signal.get("longitude"))
        if lat is None or lon is None:
            continue
        nodes.append(
            {
                "id": int(signal.get("id") or 0),
                "latitude": float(lat),
                "longitude": float(lon),
                "confidence_pct": int(signal.get("confidence_pct") or 0),
            }
        )

    if len(nodes) < 2:
        return []

    root = max(nodes, key=lambda node: int(node.get("confidence_pct") or 0))
    connected: list[dict] = [root]
    remaining: list[dict] = [node for node in nodes if node is not root]
    branches: list[dict] = []

    while remaining:
        child = remaining.pop(0)
        parent = min(
            connected,
            key=lambda node: _distance_km(
                float(node.get("latitude") or 0.0),
                float(node.get("longitude") or 0.0),
                float(child.get("latitude") or 0.0),
                float(child.get("longitude") or 0.0),
            ),
        )
        branches.append(
            {
                "from_id": int(parent.get("id") or 0),
                "to_id": int(child.get("id") or 0),
                "from_latitude": float(parent.get("latitude") or 0.0),
                "from_longitude": float(parent.get("longitude") or 0.0),
                "to_latitude": float(child.get("latitude") or 0.0),
                "to_longitude": float(child.get("longitude") or 0.0),
            }
        )
        connected.append(child)

    return branches


def _build_navigator_mission_map(
    expeditions: list[dict],
    reports: list[dict],
    predicted_hotspots: list[dict] | None = None,
    mesh_signals: list[dict] | None = None,
) -> dict:
    expedition_points = []
    for exp in expeditions:
        lat = _safe_float(exp.get("latitude"))
        lon = _safe_float(exp.get("longitude"))
        if lat is None or lon is None:
            continue
        expedition_points.append(
            {
                "type": "expedition",
                "id": exp.get("id"),
                "timestamp": exp.get("timestamp"),
                "title": exp.get("location_name") or "Unknown Site",
                "subtitle": exp.get("specimen_types") or "Specimen not logged",
                "yield_rating": _safe_float(exp.get("yield_rating")),
                "globally_significant": bool(exp.get("globally_significant")),
                "mesh_citations": exp.get("mesh_citations") or [],
                "latitude": lat,
                "longitude": lon,
            }
        )

    aviation_points = []
    for report in reports:
        airport = _resolve_airport_for_report(report, expeditions)
        aviation_points.append(
            {
                "type": "aviation",
                "id": report.get("id"),
                "timestamp": report.get("analyzed_at"),
                "title": report.get("report_name") or "Oil Report",
                "subtitle": f"Nearest airport: {airport.get('code', 'N/A')} - {airport.get('name', 'Unknown')}",
                "flagged": bool(report.get("flagged")),
                "latitude": airport.get("latitude"),
                "longitude": airport.get("longitude"),
                "airport_code": airport.get("code"),
                "airport_name": airport.get("name"),
                "airport_distance_km": airport.get("distance_km"),
            }
        )

    fungal_mesh_branches = _build_fungal_mesh_branches(mesh_signals)

    return {
        "expeditions": expedition_points,
        "aviation_reports": aviation_points,
        "all_points": expedition_points + aviation_points,
        "predicted_hotspots": predicted_hotspots or [],
        "mesh_signals": mesh_signals or [],
        "mesh_network_mode": "MYCELIAL_BRANCHING",
        "fungal_mesh_branches": fungal_mesh_branches,
    }


def _query_expedition_by_id(location_id: int, user_id: int | None = None, tenant_id: object | None = None) -> dict | None:
    db_path = _aviation_db_path(tenant_id)
    if location_id <= 0 or not db_path.exists():
        return None
    uid = _normalise_user_id(user_id, default=1) if user_id is not None else None
    try:
        conn = sqlite3.connect(str(db_path))
        try:
            _ensure_expeditions_table(conn)
            if uid is None:
                row = conn.execute(
                    "SELECT id, user_id, timestamp, location_name, latitude, longitude, specimen_types, yield_rating "
                    "FROM rockhounding_expeditions WHERE id = ?",
                    (location_id,),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT id, user_id, timestamp, location_name, latitude, longitude, specimen_types, yield_rating "
                    "FROM rockhounding_expeditions WHERE id = ? AND user_id = ?",
                    (location_id, uid),
                ).fetchone()
        finally:
            conn.close()
    except Exception:
        return None

    if row is None:
        return None

    cols = ["id", "user_id", "timestamp", "location_name", "latitude", "longitude", "specimen_types", "yield_rating"]
    return dict(zip(cols, row))


def _resolve_airport_for_expedition(expedition: dict) -> dict:
    code = _extract_airport_code(expedition.get("location_name"), expedition.get("specimen_types"))
    if code:
        airport = _AIRPORT_REFERENCE[code]
        return {
            "code": code,
            "name": airport["name"],
            "latitude": airport["latitude"],
            "longitude": airport["longitude"],
            "distance_km": 0.0,
        }

    lat = _safe_float(expedition.get("latitude"))
    lon = _safe_float(expedition.get("longitude"))
    if lat is not None and lon is not None:
        return _nearest_airport_from_coords(lat, lon)
    return dict(_HOME_AIRPORT)


def _fetch_weather_bundle(airport_code: str) -> dict:
    """Fetch METAR/TAF for the airport; use deterministic fallback on network errors."""
    code = airport_code.upper().strip()
    if not code:
        code = _HOME_AIRPORT["code"]

    def _fetch(path: str) -> list[dict]:
        query = urlparse.urlencode({"ids": code, "format": "json"})
        url = f"https://aviationweather.gov/api/data/{path}?{query}"
        req = urlrequest.Request(url, headers={"User-Agent": "HutchSolves-Cortex/1.1"})
        with urlrequest.urlopen(req, timeout=2.5) as res:
            raw = res.read().decode("utf-8")
        data = json.loads(raw)
        return data if isinstance(data, list) else []

    try:
        metar_rows = _fetch("metar")
        taf_rows = _fetch("taf")
        metar = metar_rows[0].get("rawOb") if metar_rows else None
        taf = taf_rows[0].get("rawOb") if taf_rows else None
        return {
            "airport_code": code,
            "metar": metar,
            "taf": taf,
            "source": "aviationweather.gov",
            "is_fallback": False,
        }
    except (urlerror.URLError, TimeoutError, ValueError, OSError, json.JSONDecodeError):
        now = datetime.now(timezone.utc).strftime("%d%H%MZ")
        return {
            "airport_code": code,
            "metar": f"{code} {now} AUTO 18010KT 10SM FEW030 18/11 A2992",
            "taf": f"TAF {code} {now} {now[:2]}12/{now[:2]}24 18010KT P6SM SCT035",
            "source": "fallback-sentinel",
            "is_fallback": True,
        }


def _weather_risk_from_metar(metar: str | None) -> tuple[str, list[str]]:
    if not metar:
        return "MARGINAL", ["No live METAR available"]

    raw = metar.upper()
    reasons: list[str] = []
    risk = "GOOD"

    if any(token in raw for token in [" TS", " +TS", "SQ", "FC"]):
        risk = "POOR"
        reasons.append("convective activity detected")
    if any(token in raw for token in [" 1/2SM", " 1SM", " 2SM", "FG", "FZFG"]):
        risk = "POOR"
        reasons.append("reduced visibility")
    elif any(token in raw for token in [" 3SM", " 4SM", " 5SM", "BR"]):
        if risk != "POOR":
            risk = "MARGINAL"
        reasons.append("marginal visibility")

    if any(token in raw for token in ["OVC00", "OVC01", "BKN00", "BKN01"]):
        risk = "POOR"
        reasons.append("very low ceiling")
    elif any(token in raw for token in ["OVC02", "BKN02", "OVC03", "BKN03"]):
        if risk != "POOR":
            risk = "MARGINAL"
        reasons.append("low ceiling")

    if not reasons:
        reasons.append("no immediate weather hazard signals")

    return risk, reasons


def _compute_load_profile(load_profile: str, specimen_weight_lbs: float | None) -> dict:
    profile = (load_profile or "standard").strip().lower()
    if profile not in _LOAD_PROFILE_SPECIMEN_LBS:
        profile = "standard"

    planned_specimens = _LOAD_PROFILE_SPECIMEN_LBS[profile]
    if profile == "custom" and specimen_weight_lbs is not None:
        planned_specimens = max(0.0, float(specimen_weight_lbs))

    baseline_total = (
        _N6424P_EMPTY_WEIGHT_LBS
        + _N6424P_BASE_CREW_LBS
        + _N6424P_BASE_MISC_LBS
        + (_N6424P_BASE_FUEL_GAL * _AVGAS_LBS_PER_GAL)
    )
    dry_weight = (
        _N6424P_EMPTY_WEIGHT_LBS
        + _N6424P_BASE_CREW_LBS
        + _N6424P_BASE_MISC_LBS
        + planned_specimens
    )

    max_safe_fuel_gal = max(0.0, min(_N6424P_MAX_FUEL_GAL, (_N6424P_MAX_GROSS_LBS - dry_weight) / _AVGAS_LBS_PER_GAL))
    planned_fuel_gal = max(0.0, min(_N6424P_BASE_FUEL_GAL, max_safe_fuel_gal))
    loaded_total = dry_weight + (planned_fuel_gal * _AVGAS_LBS_PER_GAL)
    remaining_payload = _N6424P_MAX_GROSS_LBS - loaded_total

    takeoff_roll_delta_pct = round((planned_specimens / _N6424P_MAX_GROSS_LBS) * 100 * 1.8, 1)
    climb_rate_delta_fpm = round(planned_specimens * 0.9, 0)

    return {
        "profile": profile,
        "specimen_weight_lbs": round(planned_specimens, 1),
        "baseline_takeoff_weight_lbs": round(baseline_total, 1),
        "estimated_takeoff_weight_lbs": round(loaded_total, 1),
        "planned_fuel_gal": round(planned_fuel_gal, 1),
        "max_gross_lbs": _N6424P_MAX_GROSS_LBS,
        "remaining_payload_lbs": round(remaining_payload, 1),
        "is_within_limits": loaded_total <= _N6424P_MAX_GROSS_LBS,
        "takeoff_roll_delta_pct": takeoff_roll_delta_pct,
        "climb_rate_delta_fpm": climb_rate_delta_fpm,
    }


def _build_fuel_status(load_profile: dict) -> dict:
    available_weight_for_fuel = max(
        0.0,
        _N6424P_MAX_GROSS_LBS
        - (
            _N6424P_EMPTY_WEIGHT_LBS
            + _N6424P_BASE_CREW_LBS
            + _N6424P_BASE_MISC_LBS
            + load_profile["specimen_weight_lbs"]
        ),
    )
    max_safe_fuel_gal = min(_N6424P_MAX_FUEL_GAL, round(available_weight_for_fuel / _AVGAS_LBS_PER_GAL, 1))
    recommended_gal = min(max_safe_fuel_gal, _N6424P_BASE_FUEL_GAL)
    endurance_hr = round(recommended_gal / _N6424P_FUEL_BURN_GPH, 2) if recommended_gal > 0 else 0.0

    if recommended_gal >= 30:
        status = "GREEN"
        note = "Fuel margin supports standard mission profile."
    elif recommended_gal >= 24:
        status = "AMBER"
        note = "Fuel margin reduced; validate alternates and reserve."
    else:
        status = "RED"
        note = "Fuel margin insufficient for normal mission confidence."

    return {
        "status": status,
        "recommended_fuel_gal": round(recommended_gal, 1),
        "max_safe_fuel_gal": max_safe_fuel_gal,
        "estimated_endurance_hr": endurance_hr,
        "reserve_target_min": 45,
        "note": note,
    }


def _build_go_no_go(sentinel_status: str, fuel_status: dict, weather_risk: str, load_profile: dict) -> dict:
    status = (sentinel_status or "UNKNOWN").upper()
    reasons: list[str] = []
    decision = "GO"

    if status in {"OVERDUE", "UNKNOWN"}:
        decision = "NO-GO"
        reasons.append(f"Sentinel status is {status}")
    elif status == "WARNING":
        decision = "CAUTION"
        reasons.append("Sentinel warning window is active")

    if fuel_status.get("status") == "RED":
        decision = "NO-GO"
        reasons.append("Fuel margin is red")
    elif fuel_status.get("status") == "AMBER" and decision == "GO":
        decision = "CAUTION"
        reasons.append("Fuel margin is amber")

    if weather_risk == "POOR":
        decision = "NO-GO"
        reasons.append("Destination weather risk is poor")
    elif weather_risk == "MARGINAL" and decision == "GO":
        decision = "CAUTION"
        reasons.append("Destination weather is marginal")

    if not load_profile.get("is_within_limits", True):
        decision = "NO-GO"
        reasons.append("Estimated takeoff weight exceeds max gross")

    if not reasons:
        reasons.append("Sentinel, fuel, and weather checks are all acceptable")

    return {"decision": decision, "reasons": reasons}


def _query_oil_sentinel_reports(limit: int = 20, tenant_id: object | None = None) -> list[dict]:
    """Read the last *limit* rows from oil_sentinel_reports, newest-first."""
    db_path = _aviation_db_path(tenant_id)
    if not db_path.exists():
        return []
    try:
        with open_sqlite(db_path) as conn:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(oil_sentinel_reports)").fetchall()}
            if not cols:
                return []

            has_aluminium = "aluminium" in cols
            rows = conn.execute(
                (
                    """
                    SELECT id, report_name, source_pdf, iron, copper, aluminium,
                           iron_delta_pct, copper_delta_pct, iron_flagged,
                           copper_flagged, flagged, analyzed_at
                    FROM oil_sentinel_reports
                    ORDER BY analyzed_at DESC
                    LIMIT ?
                    """
                    if has_aluminium else
                    """
                    SELECT id, report_name, source_pdf, iron, copper, NULL as aluminium,
                           iron_delta_pct, copper_delta_pct, iron_flagged,
                           copper_flagged, flagged, analyzed_at
                    FROM oil_sentinel_reports
                    ORDER BY analyzed_at DESC
                    LIMIT ?
                    """
                ),
                (max(1, min(limit, 10000)),),
            ).fetchall()
    except Exception:
        return []
    return [
        {
            "id":               row[0],
            "report_name":      row[1],
            "source_pdf":       row[2],
            "iron":             row[3],
            "copper":           row[4],
            "aluminium":        row[5],
            "iron_delta_pct":   row[6],
            "copper_delta_pct": row[7],
            "iron_flagged":     bool(row[8]),
            "copper_flagged":   bool(row[9]),
            "flagged":          bool(row[10]),
            "analyzed_at":      row[11],
        }
        for row in rows
    ]


def _summarise_session(events: list[dict]) -> dict:
    """
    Build a session dict from a group of cortex_telemetry events (newest-first).
    A session is a run of events with no gap > SESSION_GAP_MIN between them.
    """
    pulse_count = sum(1 for e in events if e["event"] == "engagement_pulse")
    activities  = sorted({event_label(e["event"]) for e in events})
    return {
        "start":        events[-1]["timestamp"],
        "end":          events[0]["timestamp"],
        "pulse_count":  pulse_count,
        "duration_min": pulse_count * PULSE_INTERVAL_MIN,
        "activities":   activities,
        "event_count":  len(events),
    }


def _marine_db_path() -> Path:
    return Path(app.config.get("MARINE_DB_PATH", _ROOT / "data" / "marine.sqlite"))


def _reef_reference_path() -> Path:
    return Path(app.config.get("REEF_REFERENCE_PATH", _ROOT / "data" / "reef_reference.json"))


def _marine_snapshot_dir() -> Path:
    return Path(app.config.get("MARINE_SNAPSHOT_DIR", _ROOT / "outputs" / "marine_snapshots"))


def _load_reef_reference() -> list[dict]:
    path = _reef_reference_path()
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return [item for item in data if isinstance(item, dict)]


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_km = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return round(radius_km * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)), 2)


def _ensure_manifest_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS marine_investigations (
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
        """
    )
    conn.commit()


def _query_recent_investigations(limit: int = 5) -> list[dict]:
    db_path = _marine_db_path()
    if not db_path.exists():
        return []
    with open_sqlite(db_path) as conn:
        _ensure_manifest_table(conn)
        rows = conn.execute(
            """
            SELECT id, name, created_at, updated_at, scope_type, dataset, station_id, limit_value, path, query_string
            FROM marine_investigations
            ORDER BY id DESC
            LIMIT ?
            """,
            (max(1, min(limit, 20)),),
        ).fetchall()
    return [
        {
            "id": row[0],
            "name": row[1],
            "created_at": row[2],
            "updated_at": row[3],
            "scope_type": row[4],
            "dataset": row[5],
            "station_id": row[6],
            "limit": row[7],
            "path": row[8],
            "query_string": row[9],
            "open_url": f"{row[8]}{f'?{row[9]}' if row[9] else ''}",
        }
        for row in rows
    ]


def _load_latest_snapshot() -> dict | None:
    snapshot_dir = _marine_snapshot_dir()
    latest_path = snapshot_dir / "latest.json"
    if not latest_path.exists():
        return None
    with latest_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _load_latest_alert_event() -> dict | None:
    snapshot_dir = _marine_snapshot_dir()
    alert_path = snapshot_dir / "latest_alert_event.json"
    if not alert_path.exists():
        return None
    with alert_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _get_investigation(manifest_id: int) -> dict | None:
    db_path = _marine_db_path()
    if not db_path.exists():
        return None
    with open_sqlite(db_path) as conn:
        _ensure_manifest_table(conn)
        row = conn.execute(
            """
            SELECT id, name, created_at, updated_at, scope_type, dataset, station_id, limit_value, path, query_string
            FROM marine_investigations
            WHERE id = ?
            """,
            (manifest_id,),
        ).fetchone()
    if row is None:
        return None
    return {
        "id": row[0],
        "name": row[1],
        "created_at": row[2],
        "updated_at": row[3],
        "scope_type": row[4],
        "dataset": row[5],
        "station_id": row[6],
        "limit": row[7],
        "path": row[8],
        "query_string": row[9],
        "open_url": f"{row[8]}{f'?{row[9]}' if row[9] else ''}",
    }


def _create_investigation_manifest(
    *,
    name: str,
    scope_type: str,
    dataset: str = "",
    station_id: str = "",
    limit: int = 100,
    path: str,
    query_string: str,
) -> dict:
    db_path = _marine_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    with open_sqlite(db_path) as conn:
        _ensure_manifest_table(conn)
        cursor = conn.execute(
            """
            INSERT INTO marine_investigations (
                name, created_at, updated_at, scope_type, dataset, station_id, limit_value, path, query_string
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name.strip(),
                now,
                now,
                scope_type,
                dataset or None,
                station_id or None,
                max(1, min(limit, 250)),
                path,
                query_string,
            ),
        )
        conn.commit()
        row_id = cursor.lastrowid
        row = conn.execute(
            """
            SELECT id, name, created_at, updated_at, scope_type, dataset, station_id, limit_value, path, query_string
            FROM marine_investigations
            WHERE id = ?
            """,
            (row_id,),
        ).fetchone()
    if row is None:
        raise RuntimeError("Unable to reload saved manifest after insert.")
    return {
        "id": row[0],
        "name": row[1],
        "created_at": row[2],
        "updated_at": row[3],
        "scope_type": row[4],
        "dataset": row[5],
        "station_id": row[6],
        "limit": row[7],
        "path": row[8],
        "query_string": row[9],
        "open_url": f"{row[8]}{f'?{row[9]}' if row[9] else ''}",
    }


def _query_marine_observations(
    dataset: str = "",
    station_id: str = "",
    limit: int = 25,
    ascending: bool = False,
) -> list[dict]:
    db_path = _marine_db_path()
    if not db_path.exists():
        return []

    filters = []
    params: list[object] = []

    if dataset:
        dataset_map = {
            "sst": "noaa_erddap_sst",
            "buoy": "noaa_erddap_buoy_observations",
        }
        normalized_dataset = dataset_map.get(dataset, dataset)
        filters.append("dataset_name = ?")
        params.append(normalized_dataset)

    if station_id:
        filters.append("station_id = ?")
        params.append(station_id)

    where = f"WHERE {' AND '.join(filters)}" if filters else ""
    order_clause = "ORDER BY timestamp ASC, id ASC" if ascending else "ORDER BY timestamp DESC, id DESC"
    query = f"""
        SELECT dataset_name, timestamp, latitude, longitude, metric_name, metric_value,
               source, station_id, baseline, deviation, anomaly_status
        FROM marine_observations
        {where}
        {order_clause}
        LIMIT ?
    """
    params.append(max(1, min(limit, 250)))

    with open_sqlite(db_path) as conn:
        rows = conn.execute(query, params).fetchall()

    observations = []
    for row in rows:
        observation = {
            "dataset_name": row[0],
            "timestamp": row[1],
            "latitude": row[2],
            "longitude": row[3],
            "metric_name": row[4],
            "metric_value": row[5],
            "source": row[6],
            "station_id": row[7],
            "baseline": row[8],
            "deviation": row[9],
            "anomaly_status": row[10],
        }
        observation.update(_derive_reef_stress_fields(observation))
        observations.append(observation)
    return observations


def _summarize_anomaly_scope(observations: list[dict]) -> dict:
    summary = {
        "total": len(observations),
        "normal": 0,
        "watch": 0,
        "anomaly": 0,
    }
    for row in observations:
        status = row.get("anomaly_status", "normal")
        if status in summary:
            summary[status] += 1
    return summary


def _derive_reef_stress_fields(observation: dict) -> dict:
    is_sst = (
        observation.get("dataset_name") == "noaa_erddap_sst"
        or observation.get("metric_name") == "sea_surface_temperature"
    )
    if not is_sst:
        return {"reef_stress_status": None, "reef_stress_reason": None}

    baseline = observation.get("baseline")
    deviation = observation.get("deviation")
    observed = observation.get("metric_value")

    if baseline is None or deviation is None:
        status = "normal"
        threshold_exceeded = None
    elif deviation >= 2.0:
        status = "stress"
        threshold_exceeded = "sst_deviation_ge_2.0C"
    elif deviation >= 1.0:
        status = "watch"
        threshold_exceeded = "sst_deviation_ge_1.0C"
    else:
        status = "normal"
        threshold_exceeded = None

    return {
        "reef_stress_status": status,
        "reef_stress_reason": {
            "baseline_used": baseline,
            "observed_sst": observed,
            "deviation": deviation,
            "threshold_exceeded": threshold_exceeded,
            "resulting_reef_stress_status": status,
            "rule_basis": "deterministic_sst_deviation_threshold",
        },
    }


def _summarize_reef_stress_scope(observations: list[dict]) -> dict:
    summary = {"sst_rows": 0, "normal": 0, "watch": 0, "stress": 0}
    for row in observations:
        status = row.get("reef_stress_status")
        if status is None:
            continue
        summary["sst_rows"] += 1
        if status in summary:
            summary[status] += 1
    return summary


def _build_station_context(observations: list[dict]) -> list[dict]:
    stations: dict[str, dict] = {}
    for row in observations:
        station_id = row.get("station_id") or ""
        if not station_id:
            continue

        current = stations.get(station_id)
        if current is None:
            current = {
                "station_id": station_id,
                "latitude": row.get("latitude"),
                "longitude": row.get("longitude"),
                "datasets_present": set(),
                "latest_timestamp": row.get("timestamp"),
                "latest_reef_stress_status": None,
                "latest_anomaly_status": row.get("anomaly_status"),
            }
            stations[station_id] = current

        current["datasets_present"].add(row.get("dataset_name"))

        row_timestamp = row.get("timestamp") or ""
        current_timestamp = current.get("latest_timestamp") or ""
        if row_timestamp >= current_timestamp:
            current["latest_timestamp"] = row_timestamp
            current["latest_anomaly_status"] = row.get("anomaly_status")

        if row.get("reef_stress_status") is not None:
            current_reef_timestamp = current.get("_latest_reef_timestamp", "")
            if row_timestamp >= current_reef_timestamp:
                current["_latest_reef_timestamp"] = row_timestamp
                current["latest_reef_stress_status"] = row.get("reef_stress_status")

    result = []
    for station in stations.values():
        station.pop("_latest_reef_timestamp", None)
        station["datasets_present"] = sorted(item for item in station["datasets_present"] if item)
        result.append(station)
    result.sort(key=lambda item: (item["latest_timestamp"] or "", item["station_id"]), reverse=True)
    return result


def _summarize_station_context(station_context: list[dict]) -> dict:
    summary = {
        "total_stations": len(station_context),
        "stations_with_sst": 0,
        "reef_watch": 0,
        "reef_stress": 0,
    }
    for station in station_context:
        has_sst = "noaa_erddap_sst" in station.get("datasets_present", [])
        if has_sst:
            summary["stations_with_sst"] += 1
        if station.get("latest_reef_stress_status") == "watch":
            summary["reef_watch"] += 1
        if station.get("latest_reef_stress_status") == "stress":
            summary["reef_stress"] += 1
    return summary


def _build_reef_context(station_context: list[dict], reef_reference: list[dict], threshold_km: float = 150.0) -> list[dict]:
    result = []
    for station in station_context:
        nearest = None
        nearest_distance = None
        for reef in reef_reference:
            distance = _distance_km(
                station["latitude"],
                station["longitude"],
                float(reef["latitude"]),
                float(reef["longitude"]),
            )
            if nearest_distance is None or distance < nearest_distance:
                nearest_distance = distance
                nearest = reef

        near_reef = nearest is not None and nearest_distance is not None and nearest_distance <= threshold_km
        result.append(
            {
                "station_id": station["station_id"],
                "latitude": station["latitude"],
                "longitude": station["longitude"],
                "latest_timestamp": station["latest_timestamp"],
                "latest_anomaly_status": station["latest_anomaly_status"],
                "latest_reef_stress_status": station["latest_reef_stress_status"],
                "nearest_reef_id": nearest["reef_id"] if near_reef and nearest else None,
                "nearest_reef_name": nearest["reef_name"] if near_reef and nearest else None,
                "nearest_reef_latitude": float(nearest["latitude"]) if near_reef and nearest else None,
                "nearest_reef_longitude": float(nearest["longitude"]) if near_reef and nearest else None,
                "nearest_reef_distance_km": nearest_distance if near_reef else None,
                "reef_proximity_status": "near_reef" if near_reef else "none",
            }
        )
    return result


def _summarize_reef_context(reef_context: list[dict], reef_reference: list[dict]) -> dict:
    summary = {
        "total_reefs": len(reef_reference),
        "stations_near_reef": 0,
        "near_reef_watch": 0,
        "near_reef_stress": 0,
    }
    for row in reef_context:
        if row["reef_proximity_status"] != "near_reef":
            continue
        summary["stations_near_reef"] += 1
        if row.get("latest_reef_stress_status") == "watch":
            summary["near_reef_watch"] += 1
        if row.get("latest_reef_stress_status") == "stress":
            summary["near_reef_stress"] += 1
    return summary


def _derive_reef_alerts(reef_context: list[dict]) -> list[dict]:
    alerts = []
    for row in reef_context:
        reef_stress = row.get("latest_reef_stress_status")
        proximity = row.get("reef_proximity_status")
        if proximity == "near_reef" and reef_stress == "stress":
            priority_status = "priority"
            priority_reason = "near_reef + reef_stress=stress"
        elif proximity == "near_reef" and reef_stress == "watch":
            priority_status = "attention"
            priority_reason = "near_reef + reef_stress=watch"
        else:
            priority_status = "normal"
            priority_reason = "no_near_reef_stress_trigger"

        alerts.append(
            {
                **row,
                "priority_status": priority_status,
                "priority_reason": priority_reason,
            }
        )

    priority_order = {"priority": 0, "attention": 1, "normal": 2}
    alerts.sort(
        key=lambda item: (
            priority_order.get(item["priority_status"], 3),
            item.get("nearest_reef_distance_km") if item.get("nearest_reef_distance_km") is not None else 999999,
            item.get("station_id", ""),
        )
    )
    return alerts


def _summarize_reef_alerts(reef_alerts: list[dict]) -> dict:
    summary = {
        "near_reef_total": 0,
        "attention": 0,
        "priority": 0,
    }
    for row in reef_alerts:
        if row.get("reef_proximity_status") == "near_reef":
            summary["near_reef_total"] += 1
        if row.get("priority_status") == "attention":
            summary["attention"] += 1
        if row.get("priority_status") == "priority":
            summary["priority"] += 1
    return summary


def _query_station_context(dataset: str = "", station_id: str = "", limit: int = 100) -> list[dict]:
    observations = _query_marine_observations(dataset=dataset, station_id=station_id, limit=max(1, min(limit, 250)))
    context = _build_station_context(observations)
    return context[: max(1, min(limit, 250))]


def _query_reef_context(dataset: str = "", station_id: str = "", limit: int = 100) -> list[dict]:
    station_context = _query_station_context(dataset=dataset, station_id=station_id, limit=limit)
    reef_reference = _load_reef_reference()
    return _build_reef_context(station_context, reef_reference)[: max(1, min(limit, 250))]


def _query_reef_alerts(
    dataset: str = "",
    station_id: str = "",
    limit: int = 100,
    minimum_priority: str = "",
) -> list[dict]:
    reef_alerts = _derive_reef_alerts(_query_reef_context(dataset=dataset, station_id=station_id, limit=limit))
    if minimum_priority == "priority":
        reef_alerts = [row for row in reef_alerts if row["priority_status"] == "priority"]
    elif minimum_priority == "attention":
        reef_alerts = [row for row in reef_alerts if row["priority_status"] in {"attention", "priority"}]
    return reef_alerts[: max(1, min(limit, 250))]


def _query_station_series(station_id: str, dataset: str = "", limit: int = 100) -> list[dict]:
    if not station_id.strip():
        return []
    return _query_marine_observations(
        dataset=dataset,
        station_id=station_id.strip(),
        limit=max(1, min(limit, 250)),
        ascending=True,
    )


def _build_marine_export(dataset: str = "", station_id: str = "", limit: int = 100, minimum_priority: str = "") -> dict:
    bounded_limit = max(1, min(limit, 250))
    observations = _query_marine_observations(dataset=dataset, station_id=station_id, limit=bounded_limit)
    station_series = _query_station_series(station_id=station_id, dataset=dataset, limit=bounded_limit) if station_id else []
    latest_telemetry = _query_marine_telemetry(limit=1)
    station_context = _build_station_context(observations)
    reef_reference = _load_reef_reference()
    reef_context = _build_reef_context(station_context, reef_reference)
    reef_alerts = _query_reef_alerts(
        dataset=dataset,
        station_id=station_id,
        limit=bounded_limit,
        minimum_priority=minimum_priority,
    )
    return {
        "meta": {
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "filters_applied": {
                "dataset": dataset or None,
                "station_id": station_id or None,
                "minimum_priority": minimum_priority or None,
            },
            "limit": bounded_limit,
            "note": "Anomaly fields are deterministic threshold-rule outputs and do not imply ecological causation.",
        },
        "telemetry": latest_telemetry[0] if latest_telemetry else None,
        "summary": _summarize_anomaly_scope(observations),
        "reef_stress_summary": _summarize_reef_stress_scope(observations),
        "station_context_summary": _summarize_station_context(station_context),
        "reef_context_summary": _summarize_reef_context(reef_context, reef_reference),
        "reef_alert_summary": _summarize_reef_alerts(reef_alerts),
        "observations": observations,
        "map_points": observations,
        "station_context": station_context,
        "reef_context": reef_context,
        "reef_alerts": reef_alerts,
        "station_series": station_series if station_id else [],
    }


def _query_marine_telemetry(limit: int = 10) -> list[dict]:
    db_path = _marine_db_path()
    if not db_path.exists():
        return []

    with open_sqlite(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, timestamp, event, payload
            FROM telemetry
            WHERE event = 'dataset_ingest'
            ORDER BY id DESC
            LIMIT ?
            """,
            (max(1, min(limit, 50)),),
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


# ── Routes ─────────────────────────────────────────────────────────────────

def _root_access_permitted() -> bool:
    role = _normalise_user_role(request.args.get("user_role") or "Admin")
    tenant_id = _normalise_tenant_id(request.args.get("tenant_id") or request.args.get("tenant_slug") or _request_tenant_id())
    return role == "Admin" and tenant_id in {_DEFAULT_TENANT_ID, "default"}


def _sovereign_ledger_write_permitted(data: dict | None = None) -> bool:
    payload = data or {}
    role = _normalise_user_role(
        payload.get("user_role")
        or request.args.get("user_role")
        or "Admin"
    )
    tenant_id = _normalise_tenant_id(
        payload.get("tenant_id")
        or payload.get("tenant_slug")
        or request.args.get("tenant_id")
        or request.args.get("tenant_slug")
        or _request_tenant_id()
    )
    if role == "Admin" and tenant_id in {_DEFAULT_TENANT_ID, "default"}:
        return True
    return role == "Operations Director"


def _resolve_operations_director_hourly_rate(
    *,
    tenant_id: str,
    user_id: int,
    tenant_slug: str,
) -> float:
    """Resolve hourly rate from Operations Director profile, with billing fallback."""
    def _extract_rate(profile: dict | None) -> float | None:
        if not profile:
            return None
        permissions = profile.get("permissions") or {}
        for key in ("hourly_rate_usd", "hourly_rate", "operations_hourly_rate_usd"):
            value = _safe_float(permissions.get(key))
            if value is not None and value > 0:
                return round(float(value), 2)
        return None

    profile = _query_user_profile(user_id=user_id, tenant_id=tenant_id)
    if profile and _normalise_user_role(profile.get("role")) == "Operations Director":
        resolved = _extract_rate(profile)
        if resolved is not None:
            return resolved

    db_path = _aviation_db_path(tenant_id)
    if db_path.exists():
        conn = sqlite3.connect(str(db_path))
        try:
            _ensure_identity_tables(conn)
            _ensure_user_profile_columns(conn)
            row = conn.execute(
                "SELECT id FROM user_profiles WHERE LOWER(TRIM(role)) = 'operations director' ORDER BY id ASC LIMIT 1"
            ).fetchone()
        finally:
            conn.close()
        if row:
            od_profile = _query_user_profile(user_id=_normalise_user_id(row[0], default=1), tenant_id=tenant_id)
            resolved = _extract_rate(od_profile)
            if resolved is not None:
                return resolved

    fallback = _safe_float(get_hourly_rate(tenant_slug))
    if fallback is None or fallback <= 0:
        fallback = 250.0
    return round(float(fallback), 2)


def _calculate_digital_guardian_roi(averted_drift_hours: object, hourly_rate_usd: float) -> dict:
    hours = _safe_float(averted_drift_hours)
    resolved_hours = max(0.0, float(hours if hours is not None else 0.0))
    resolved_rate = max(0.0, float(hourly_rate_usd or 0.0))
    roi_value = round(resolved_hours * resolved_rate, 2)
    return {
        "averted_drift_hours": round(resolved_hours, 2),
        "hourly_rate_usd": round(resolved_rate, 2),
        "roi_usd": roi_value,
        "formula": "ROI = Averted Drift Hours x Hourly Rate",
    }


def _classify_observatory_command(command_text: str) -> str:
    command = re.sub(r"\s+", " ", str(command_text or "").strip().lower())
    if not command:
        return "unknown"
    expedition_patterns = (
        r"\b(log|record|add|create)\b.*\b(expedition|field observation|observation)\b",
        r"\bexpedition\b.*\b(current location|here|now)\b",
    )
    if any(re.search(pattern, command) for pattern in expedition_patterns):
        return "log_expedition"
    return "unknown"


def _build_mobile_pulse_payload(*, tenant_id: str, user_id: int) -> dict:
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    role = (_query_user_profile(user_id=user_id, tenant_id=tenant_id) or {}).get("role") or "Admin"
    pulse_notifications = [
        {
            "id": "system-status",
            "severity": "ok",
            "label": "System Status: Digital Guardian Active. Ready for the Mass Market.",
        },
        {
            "id": "lighthouse-governance",
            "severity": "ok",
            "label": "Lighthouse Governance: Absolute. Audit Ready.",
        },
        {
            "id": "mesh-radar",
            "severity": "info",
            "label": "Mesh Radar: Active.",
        },
    ]
    latest_pulse = _load_digital_guardian_pulse()
    if latest_pulse:
        pulse_notifications.insert(
            0,
            {
                "id": str(latest_pulse.get("id") or "digital-guardian-ingest"),
                "severity": str(latest_pulse.get("severity") or "info"),
                "label": str(latest_pulse.get("label") or "Digital Guardian Pulse: External ingest completed."),
                "rationale_hash": str(latest_pulse.get("rationale_hash") or ""),
                "external_philosophy_version": str(latest_pulse.get("external_philosophy_version") or ""),
            },
        )
    return {
        "generated_at": generated_at,
        "tenant_id": tenant_id,
        "role": _normalise_user_role(role),
        "pulse_notifications": pulse_notifications,
        "one_tap_actions": [
            {
                "action": "ack_pulse",
                "label": "Acknowledge",
                "endpoint": "/api/mobile/pulse-notifications/ack",
                "method": "POST",
            },
            {
                "action": "log_expedition_current_location",
                "label": "Log Expedition",
                "endpoint": "/api/observatory/chat-action",
                "method": "POST",
            },
            {
                "action": "open_navigator",
                "label": "Open Navigator",
                "endpoint": "/navigator",
                "method": "GET",
            },
        ],
    }


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/workflow")
def workflow():
    """Business Workflow view — home of the Drift Optimizer and Report Generator."""
    return render_template("workflow.html")


@app.route("/sovereign")
def sovereign_dashboard():
    if not _root_access_permitted():
        abort(403)
    snapshot = _metered_usage_fleet_snapshot()
    franchise_stats = _build_franchise_stats_payload()
    risk_score = _build_mesh_risk_score_payload()
    return render_template("sovereign.html", snapshot=snapshot, franchise_stats=franchise_stats, risk_score=risk_score)


@app.route("/compliance")
def compliance_portal():
    role = request.args.get("user_role") or "Operations Director"
    if not _compliance_access_permitted(role):
        abort(403)
    org_id = _request_organization_id(default=_DEFAULT_ORGANIZATION_ID)
    return render_template(
        "compliance.html",
        active_org_id=org_id,
        active_role=_normalise_user_role(role),
    )


@app.route("/api/sovereign/fleet")
def api_sovereign_fleet():
    if not _root_access_permitted():
        return jsonify({"error": "forbidden"}), 403
    period = (request.args.get("period") or "").strip() or None
    return jsonify(_metered_usage_fleet_snapshot(period=period))


@app.route("/api/sovereign/franchise-stats")
def api_sovereign_franchise_stats():
    period = (request.args.get("period") or "").strip() or None
    requested_org_id = _request_organization_id(default=None)
    role = _normalise_user_role(request.args.get("user_role") or "Admin")

    if _root_access_permitted():
        return jsonify(_build_franchise_stats_payload(period=period))

    if role != "Operations Director" or not requested_org_id:
        return jsonify({"error": "forbidden"}), 403

    return jsonify(_build_franchise_stats_payload(scope_org_id=requested_org_id, period=period))


@app.route("/api/sovereign/risk-score")
def api_sovereign_risk_score():
    if not _root_access_permitted():
        return jsonify({"error": "forbidden"}), 403
    period_days = request.args.get("period_days", default=30, type=int) or 30
    return jsonify(_build_mesh_risk_score_payload(period_days=period_days))


@app.route("/api/mobile/pulse-notifications", methods=["GET"])
def api_mobile_pulse_notifications():
    tenant_id = _normalise_tenant_id(request.args.get("tenant_id") or request.args.get("tenant_slug") or _request_tenant_id())
    user_id = _normalise_user_id(request.args.get("user_id", default=1, type=int), default=1)
    return jsonify(_build_mobile_pulse_payload(tenant_id=tenant_id, user_id=user_id))


@app.route("/api/mobile/pulse-notifications/ack", methods=["POST"])
def api_mobile_pulse_notifications_ack():
    data = request.get_json(silent=True) or {}
    latest_pulse = _load_digital_guardian_pulse() or {}
    tenant_id = _normalise_tenant_id(data.get("tenant_id") or data.get("tenant_slug") or latest_pulse.get("tenant_id") or _request_tenant_id())
    organization_id = _normalise_organization_id(
        data.get("organization_id") or latest_pulse.get("organization_id") or _request_organization_id(default=_DEFAULT_ORGANIZATION_ID) or _DEFAULT_ORGANIZATION_ID
    )
    pulse_id = str(data.get("pulse_id") or latest_pulse.get("id") or "latest-pulse")
    rationale_hash = str(data.get("rationale_hash") or latest_pulse.get("rationale_hash") or "")
    acknowledged_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ledger_record = _govern_log(
        org_id=organization_id,
        actor="mobile_operator",
        action_type=_AI_PULSE_ACK_ACTION_TYPE,
        payload={
            "tenant_id": tenant_id,
            "pulse_id": pulse_id,
            "rationale_hash": rationale_hash,
            "acknowledged_at": acknowledged_at,
        },
    )
    return jsonify(
        {
            "status": "acknowledged",
            "acknowledged_at": acknowledged_at,
            "tenant_id": tenant_id,
            "pulse_id": pulse_id,
            "rationale_hash": rationale_hash,
            "ledger_record": ledger_record,
        }
    ), 200


@app.route("/api/ingestor/flight-log", methods=["POST"])
def api_ingestor_flight_log():
    """Mock external ingestor for flight-log data; triggers a Digital Guardian pulse."""
    data = request.get_json(silent=True) or {}
    tenant_id = _normalise_tenant_id(data.get("tenant_id") or data.get("tenant_slug") or _request_tenant_id())
    organization_id = _request_organization_id(default=_DEFAULT_ORGANIZATION_ID) or _DEFAULT_ORGANIZATION_ID
    user_id = _normalise_user_id(data.get("user_id"), default=1)
    ingested_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    tail_number = str(data.get("tail_number") or data.get("aircraft") or "UNKNOWN").strip().upper() or "UNKNOWN"
    provider = str(data.get("provider") or "external-flight-log").strip() or "external-flight-log"

    payload = {
        "provider": provider,
        "tail_number": tail_number,
        "flight_hours": _safe_float(data.get("flight_hours")),
        "logged_at": str(data.get("logged_at") or ingested_at),
        "source_reference": str(data.get("source_reference") or "mock-ingestor"),
    }

    ingest_dir = _ROOT / "outputs" / "ingestor"
    ingest_dir.mkdir(parents=True, exist_ok=True)
    ingest_path = ingest_dir / f"flight_log_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    ingest_path.write_text(json.dumps({"tenant_id": tenant_id, "organization_id": organization_id, **payload}, indent=2), encoding="utf-8")

    record = _govern_log(
        org_id=_normalise_organization_id(organization_id),
        actor="ingestor",
        action_type="shadow_ingest_flight_log",
        payload={
            "tenant_id": tenant_id,
            "user_id": user_id,
            **payload,
            "ingested_at": ingested_at,
            "file": ingest_path.name,
        },
    )
    pulse = _persist_digital_guardian_pulse(
        {
            "severity": "info",
            "label": f"Digital Guardian Pulse: Flight log ingested for {tail_number}.",
            "source": provider,
            "tenant_id": tenant_id,
            "organization_id": organization_id,
            "ingested_at": ingested_at,
            "summary": f"External flight log received from {provider}.",
        }
    )
    try:
        socketio.emit("digital_guardian_pulse", pulse)
    except Exception:
        pass

    return jsonify(
        {
            "status": "ingested",
            "tenant_id": tenant_id,
            "organization_id": _normalise_organization_id(organization_id),
            "record": record,
            "pulse": pulse,
            "ingest_file": str(ingest_path),
        }
    ), 201


@app.route("/api/sovereign/ledger/success-pdf", methods=["POST"])
def api_sovereign_ledger_success_pdf():
    """Generate a Digital Guardian ROI success PDF and log the action to governance ledger."""
    data = request.get_json(silent=True) or {}
    if not _sovereign_ledger_write_permitted(data):
        return jsonify({"error": "forbidden"}), 403

    tenant_slug = str(data.get("tenant_slug") or "default").strip() or "default"
    tenant_id = _normalise_tenant_id(data.get("tenant_id") or tenant_slug)
    org_id = _normalise_organization_id(data.get("org_id") or _request_organization_id(default=_DEFAULT_ORGANIZATION_ID) or _DEFAULT_ORGANIZATION_ID)
    user_id = _normalise_user_id(data.get("user_id"), default=1)
    actor = str(data.get("actor") or "operations_director").strip().lower() or "operations_director"

    hourly_rate_usd = _resolve_operations_director_hourly_rate(
        tenant_id=tenant_id,
        user_id=user_id,
        tenant_slug=tenant_slug,
    )
    roi = _calculate_digital_guardian_roi(
        averted_drift_hours=data.get("averted_drift_hours"),
        hourly_rate_usd=hourly_rate_usd,
    )

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    pdf_name = f"HutchSolves_Digital_Guardian_Success_{org_id}_{stamp}.pdf"
    pdf_path = _ROOT / "outputs" / pdf_name
    pdf_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.lib.colors import HexColor
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer, Table, TableStyle

        NAVY = HexColor("#102A43")
        AQUA = HexColor("#0E9F9A")
        WHITE = HexColor("#FFFFFF")
        GREY = HexColor("#334E68")
        LIGHT = HexColor("#F0F4F8")

        page_w, page_h = A4
        margin = 20 * mm

        def _draw_banner(canvas, doc):
            canvas.saveState()
            canvas.setFillColor(NAVY)
            canvas.rect(0, page_h - 16 * mm, page_w, 16 * mm, fill=1, stroke=0)
            canvas.setFillColor(WHITE)
            canvas.setFont("Helvetica-Bold", 11)
            canvas.drawString(margin, page_h - 10 * mm, "HutchSolves — Digital Guardian Success Report")
            canvas.setFont("Helvetica", 8)
            canvas.drawRightString(page_w - margin, page_h - 10 * mm, generated_at[:10])
            canvas.restoreState()

        doc = BaseDocTemplate(
            str(pdf_path),
            pagesize=A4,
            leftMargin=margin,
            rightMargin=margin,
            topMargin=22 * mm,
            bottomMargin=16 * mm,
        )
        frame = Frame(margin, 16 * mm, page_w - 2 * margin, page_h - 38 * mm, id="main")
        doc.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=_draw_banner)])

        h1 = ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=20, textColor=NAVY, leading=24, spaceAfter=6)
        h2 = ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=12, textColor=AQUA, leading=16, spaceBefore=10, spaceAfter=4)
        body = ParagraphStyle("body", fontName="Helvetica", fontSize=10, textColor=GREY, leading=14)

        rows = [
            ["Metric", "Value"],
            ["Organization", org_id],
            ["Tenant", tenant_id],
            ["Averted Drift Hours", f"{roi['averted_drift_hours']:.2f}"],
            ["Operations Director Rate (USD)", f"${roi['hourly_rate_usd']:.2f}"],
            ["ROI (USD)", f"${roi['roi_usd']:.2f}"],
            ["Formula", "ROI = Averted Drift Hours x Hourly Rate"],
        ]
        table = Table(rows, colWidths=[72 * mm, 98 * mm])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), NAVY),
            ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("BACKGROUND", (0, 1), (-1, -1), LIGHT),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT]),
            ("GRID", (0, 0), (-1, -1), 0.4, GREY),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))

        story = [
            Paragraph("Digital Guardian Success", h1),
            Paragraph("Mass-market readiness ROI confirmation for the Morning Card program.", body),
            Spacer(1, 4 * mm),
            Paragraph("ROI Snapshot", h2),
            table,
            Spacer(1, 8 * mm),
            Paragraph("System Status: Digital Guardian Active. Ready for the Mass Market.", body),
            Paragraph(f"Generated at: {generated_at}", body),
        ]
        doc.build(story)
    except Exception as exc:  # pragma: no cover
        return jsonify({"error": "pdf_generation_failed", "detail": str(exc)}), 500

    ledger_record = _govern_log(
        org_id=org_id,
        actor=actor,
        action_type="digital_guardian_success_pdf",
        payload={
            "tenant_id": tenant_id,
            "tenant_slug": tenant_slug,
            "user_id": user_id,
            "generated_at": generated_at,
            "pdf_name": pdf_name,
            **roi,
        },
    )

    return jsonify(
        {
            "status": "generated",
            "pdf": {
                "path": str(pdf_path),
                "filename": pdf_name,
                "generated_at": generated_at,
            },
            "roi": roi,
            "ledger_record": ledger_record,
        }
    ), 201


@app.route("/api/sovereign/generate-prospectus", methods=["POST"])
def api_sovereign_generate_prospectus():
    """POST — Generate the HutchSolves Investor Due Diligence Brief as a PDF."""
    if not _root_access_permitted():
        return jsonify({"error": "forbidden"}), 403

    snapshot = _metered_usage_fleet_snapshot()
    hub_cfg = _load_hub_config()
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    pdf_path = _ROOT / "outputs" / "HutchSolves_Investor_Brief_2026.pdf"
    pdf_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.lib.colors import HexColor
        from reportlab.platypus import (
            BaseDocTemplate, Frame, PageTemplate,
            Paragraph, Spacer, HRFlowable, Table, TableStyle,
        )
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.enums import TA_CENTER, TA_LEFT

        NAVY = HexColor("#0D1B2A")
        TEAL = HexColor("#1A8A7A")
        LIGHT = HexColor("#F4F7FB")
        WHITE = HexColor("#FFFFFF")
        GREY  = HexColor("#4A5568")

        PAGE_W, PAGE_H = A4
        MARG = 22 * mm

        def _header_footer(canvas, doc):
            canvas.saveState()
            canvas.setFillColor(NAVY)
            canvas.rect(0, PAGE_H - 18 * mm, PAGE_W, 18 * mm, fill=1, stroke=0)
            canvas.setFillColor(WHITE)
            canvas.setFont("Helvetica-Bold", 11)
            canvas.drawString(MARG, PAGE_H - 11 * mm, "HutchSolves — Investor Due Diligence Brief 2026")
            canvas.setFont("Helvetica", 8)
            canvas.drawRightString(PAGE_W - MARG, PAGE_H - 11 * mm, f"CONFIDENTIAL  ·  {generated_at[:10]}")
            canvas.setFillColor(TEAL)
            canvas.rect(0, 0, PAGE_W, 10 * mm, fill=1, stroke=0)
            canvas.setFillColor(WHITE)
            canvas.setFont("Helvetica", 8)
            canvas.drawCentredString(PAGE_W / 2, 3.5 * mm, f"© 2026 HutchSolves  ·  Page {doc.page}")
            canvas.restoreState()

        doc = BaseDocTemplate(
            str(pdf_path),
            pagesize=A4,
            leftMargin=MARG, rightMargin=MARG,
            topMargin=22 * mm, bottomMargin=18 * mm,
        )
        frame = Frame(MARG, 18 * mm, PAGE_W - 2 * MARG, PAGE_H - 40 * mm, id="main")
        doc.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=_header_footer)])

        H1 = ParagraphStyle("H1", fontName="Helvetica-Bold", fontSize=22, textColor=NAVY,
                             spaceAfter=6, leading=26)
        H2 = ParagraphStyle("H2", fontName="Helvetica-Bold", fontSize=14, textColor=TEAL,
                             spaceBefore=14, spaceAfter=4, leading=18)
        BODY = ParagraphStyle("BODY", fontName="Helvetica", fontSize=10, textColor=GREY,
                               leading=14, spaceAfter=4)
        SMALL = ParagraphStyle("SMALL", fontName="Helvetica", fontSize=8, textColor=GREY, leading=11)
        BADGE = ParagraphStyle("BADGE", fontName="Helvetica-Bold", fontSize=9, textColor=WHITE,
                               backColor=TEAL, alignment=TA_CENTER, leading=12)

        org_count   = int(snapshot.get("totals", {}).get("organization_count", 0))
        oracle_total = int(snapshot.get("totals", {}).get("oracle_api_calls", 0))
        nav_total    = int(snapshot.get("totals", {}).get("navigator_logs", 0))
        period       = str(snapshot.get("period", generated_at[:7]))

        story = [
            Paragraph("HutchSolves", H1),
            Paragraph("Due Diligence &amp; Investor Prospectus — 2026", H2),
            Spacer(1, 4 * mm),
            HRFlowable(width="100%", thickness=1.5, color=TEAL, spaceAfter=6),
            Paragraph(
                "This document summarises the operational, financial, and governance posture "
                "of the HutchSolves Cortex platform for the reporting period ending "
                f"<b>{period}</b>. Prepared exclusively for qualified investors.",
                BODY,
            ),
            Spacer(1, 6 * mm),
            Paragraph("Fleet Metrics Snapshot", H2),
        ]

        kpi_data = [
            ["Metric", "Value"],
            ["Active Organizations", str(org_count)],
            ["Systems Oracle API Calls", str(oracle_total)],
            ["Navigator Expedition Logs", str(nav_total)],
            ["Reporting Period", period],
            ["Autonomous Pulse", "ACTIVE" if hub_cfg.get("REAL_TIME_PULSE") else "STANDBY"],
            ["Auto-Prune", "ENABLED" if hub_cfg.get("AUTO_PRUNE") else "DISABLED"],
            ["Legacy Switch", str(hub_cfg.get("LEGACY_SWITCH", "—")).upper()],
        ]
        kpi_table = Table(kpi_data, colWidths=[90 * mm, 80 * mm])
        kpi_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), NAVY),
            ("TEXTCOLOR",  (0, 0), (-1, 0), WHITE),
            ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",   (0, 0), (-1, -1), 10),
            ("BACKGROUND", (0, 1), (-1, -1), LIGHT),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT]),
            ("GRID",       (0, 0), (-1, -1), 0.5, GREY),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(kpi_table)
        story.append(Spacer(1, 8 * mm))

        orgs = snapshot.get("organizations") or []
        if orgs:
            story.append(Paragraph("Per-Organization Breakdown", H2))
            org_rows = [["Organization ID", "Oracle API Calls", "Navigator Logs"]]
            for o in orgs:
                org_rows.append([
                    str(o.get("organization_id", "—")),
                    str(o.get("oracle_api_calls", 0)),
                    str(o.get("navigator_logs", 0)),
                ])
            org_table = Table(org_rows, colWidths=[90 * mm, 50 * mm, 30 * mm])
            org_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), TEAL),
                ("TEXTCOLOR",  (0, 0), (-1, 0), WHITE),
                ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE",   (0, 0), (-1, -1), 9),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT]),
                ("GRID",       (0, 0), (-1, -1), 0.4, GREY),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]))
            story.append(org_table)
            story.append(Spacer(1, 8 * mm))

        story += [
            Paragraph("Governance &amp; Architect Certification", H2),
            Paragraph(
                "This brief is certified by the HutchSolves Board Architect under "
                "autonomous lighthouse protocol v11.5.0-FINAL.",
                BODY,
            ),
            Spacer(1, 4 * mm),
            Paragraph("Lighthouse Status: Market Standard. The Mesh is the Industry. Joshua R Hutchison: Founder &amp; Architect.", BODY),
            Spacer(1, 10 * mm),
            HRFlowable(width="100%", thickness=0.8, color=GREY, spaceAfter=4),
            Paragraph(f"Generated: {generated_at}  ·  Classification: CONFIDENTIAL", SMALL),
        ]

        doc.build(story)
    except Exception as exc:  # pragma: no cover
        return jsonify({"error": "pdf_generation_failed", "detail": str(exc)}), 500

    return jsonify({
        "status": "generated",
        "path": str(pdf_path),
        "filename": pdf_path.name,
        "period": snapshot.get("period"),
        "generated_at": generated_at,
        "totals": snapshot.get("totals"),
        "autonomous_pulse": {
            "AUTO_PRUNE": hub_cfg.get("AUTO_PRUNE"),
            "REAL_TIME_PULSE": hub_cfg.get("REAL_TIME_PULSE"),
            "LEGACY_SWITCH": hub_cfg.get("LEGACY_SWITCH"),
        },
    }), 201



@app.route("/aviation")
def aviation():
    """Aero-Cortex View — Fe/Cu/Al trend sparklines from oil_sentinel_reports."""
    from nerves.aviation.ocr_worker import _build_fleet_health_summary, OilExtraction
    tenant_id = _request_tenant_id()
    reports = _query_oil_sentinel_reports(limit=20, tenant_id=tenant_id)
    # Build fleet overview stats from the page-level report list so the template
    # can display min/max/avg without a separate DB query.
    fleet_extractions = [
        OilExtraction(
            source_pdf=r["source_pdf"] or "",
            report_name=r["report_name"],
            iron=r["iron"],
            copper=r["copper"],
            aluminium=r["aluminium"],
            analyzed_at=r["analyzed_at"],
            extraction_method="stored",
        )
        for r in reports
    ]
    fleet_overview = _build_fleet_health_summary(fleet_extractions)
    maintenance_forecast = predict_component_failure(tenant_id=tenant_id, tail_number="N6424P")
    return render_template(
        "aviation.html",
        reports=reports,
        baseline_fe=38.0,
        fleet_overview=fleet_overview,
        maintenance_forecast=maintenance_forecast,
    )


@app.route("/navigator")
def navigator():
    """The Navigator — rockhounding expedition log."""
    tenant_id = _request_tenant_id()
    user_id = _normalise_user_id(request.args.get("user_id", default=1, type=int), default=1)
    expeditions = _query_expeditions(limit=100, user_id=user_id, tenant_id=tenant_id)
    specimens = _query_specimen_inventory(limit=20, tenant_id=tenant_id)
    correlation = correlate_global_signals(
        tenant_id=tenant_id,
        user_id=user_id,
        expedition_records=expeditions,
        specimen_records=specimens,
    )
    _apply_global_correlation_annotations(
        expeditions=expeditions,
        specimens=specimens,
        correlation=correlation,
    )
    specimen_portfolio = _build_specimen_portfolio_summary(specimens)
    reports = _query_oil_sentinel_reports(limit=100, tenant_id=tenant_id)
    hotspots = predict_hotspots(months=12, horizon_days=30, limit=5)
    mission_map = _build_navigator_mission_map(
        expeditions,
        reports,
        predicted_hotspots=hotspots,
        mesh_signals=correlation.get("mesh_signals") or [],
    )
    return render_template(
        "navigator.html",
        expeditions=expeditions,
        specimens=specimens,
        specimen_portfolio=specimen_portfolio,
        active_user_id=user_id,
        active_tenant_id=tenant_id,
        mission_map=mission_map,
    )


@app.route("/navigator/mobile")
def navigator_mobile():
    tenant_id = _request_tenant_id()
    user_id = _normalise_user_id(request.args.get("user_id", default=1, type=int), default=1)
    return render_template(
        "navigator_mobile.html",
        active_tenant_id=tenant_id,
        active_user_id=user_id,
    )


@app.route("/api/navigator/expeditions/invite", methods=["POST"])
def api_navigator_expeditions_invite():
    data = request.get_json(silent=True) or {}
    tenant_id = _normalise_tenant_id(data.get("tenant_id") or data.get("tenant_slug") or _request_tenant_id())
    user_id = _normalise_user_id(data.get("user_id"), default=1)
    if _is_associate_user(tenant_id=tenant_id, user_id=user_id):
        return jsonify({"error": "associate role is read-only for expedition invites"}), 403

    expedition_id = _normalise_user_id(data.get("expedition_id"), default=0)
    external_email = str(data.get("external_email") or "").strip().lower()
    if expedition_id <= 0:
        return jsonify({"error": "expedition_id is required"}), 400
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", external_email):
        return jsonify({"error": "valid external_email is required"}), 400

    actor = str(data.get("actor") or "operations_director").strip().lower() or "operations_director"
    invite = _create_expedition_guest_invite(
        tenant_id=tenant_id,
        expedition_id=expedition_id,
        external_email=external_email,
        actor=actor,
    )
    if invite is None:
        return jsonify({"error": "expedition_not_found"}), 404

    org_id = _normalise_organization_id(
        _request_organization_id(default=_DEFAULT_ORGANIZATION_ID) or _DEFAULT_ORGANIZATION_ID
    )
    ledger_record = _govern_log(
        org_id=org_id,
        actor=actor,
        action_type="navigator_expedition_guest_invite",
        payload={
            "tenant_id": tenant_id,
            "expedition_id": expedition_id,
            "invite_id": invite.get("invite_id"),
            "external_email": external_email,
            "expires_at": invite.get("expires_at"),
        },
    )
    share_url = f"{request.url_root.rstrip('/')}/api/navigator/expeditions/shared/{invite['token']}?tenant_id={tenant_id}"
    return jsonify(
        {
            "status": "invited",
            "invite": {
                "invite_id": invite.get("invite_id"),
                "expedition_id": invite.get("expedition_id"),
                "external_email": external_email,
                "external_email_hint": invite.get("external_email_hint"),
                "created_at": invite.get("created_at"),
                "expires_at": invite.get("expires_at"),
                "one_time_access_token": invite.get("token"),
                "share_url": share_url,
            },
            "ledger_record": ledger_record,
        }
    ), 201


@app.route("/api/navigator/expeditions/shared/<token>", methods=["GET"])
def api_navigator_expeditions_shared(token: str):
    tenant_id = _normalise_tenant_id(request.args.get("tenant_id") or _request_tenant_id())
    access = _redeem_expedition_guest_invite(tenant_id=tenant_id, token=token)
    if access is None:
        return jsonify({"error": "invite_not_found"}), 404
    if access.get("status") == "expired":
        return jsonify({"error": "invite_expired", **access}), 410
    if access.get("status") == "already_redeemed":
        return jsonify({"error": "invite_already_redeemed", **access}), 410
    if not access.get("expedition"):
        return jsonify({"error": "expedition_not_found"}), 404

    org_id = _normalise_organization_id(
        _request_organization_id(default=_DEFAULT_ORGANIZATION_ID) or _DEFAULT_ORGANIZATION_ID
    )
    ledger_record = _govern_log(
        org_id=org_id,
        actor="guest_token",
        action_type="navigator_expedition_guest_redeem",
        payload={
            "tenant_id": tenant_id,
            "invite_id": access.get("invite_id"),
            "expedition_id": access.get("expedition_id"),
            "external_email_hint": access.get("external_email_hint"),
            "redeemed_at": access.get("redeemed_at"),
        },
    )
    return jsonify({"status": "granted", "access": access, "ledger_record": ledger_record}), 200


@app.route("/api/compliance/control-points", methods=["GET"])
def api_compliance_control_points():
    role = request.args.get("user_role") or "Operations Director"
    if not _compliance_access_permitted(role):
        return jsonify({"error": "forbidden"}), 403

    org_id = _request_organization_id(default=None)
    if _normalise_user_role(role) == "Operations Director" and not org_id:
        org_id = _DEFAULT_ORGANIZATION_ID
    limit = min(max(request.args.get("limit", default=100, type=int) or 100, 1), 500)
    return jsonify(_build_soc2_control_points(org_id=org_id, limit=limit))


@app.route("/marine")
def marine():
    dataset = request.args.get("dataset", "").strip()
    station_id = request.args.get("station_id", "").strip()
    limit = request.args.get("limit", default=25, type=int) or 25
    observations = _query_marine_observations(dataset=dataset, station_id=station_id, limit=limit)
    anomaly_summary = _summarize_anomaly_scope(observations)
    reef_stress_summary = _summarize_reef_stress_scope(observations)
    telemetry = _query_marine_telemetry(limit=5)
    latest_ingest = telemetry[0] if telemetry else None
    reef_alerts = _query_reef_alerts(dataset=dataset, station_id=station_id, limit=limit)
    latest_snapshot = _load_latest_snapshot()
    latest_alert_event = _load_latest_alert_event()
    return render_template(
        "marine.html",
        observations=observations,
        anomaly_summary=anomaly_summary,
        reef_stress_summary=reef_stress_summary,
        reef_alert_summary=_summarize_reef_alerts(reef_alerts),
        reef_alerts=reef_alerts[:5],
        telemetry=telemetry,
        latest_ingest=latest_ingest,
        latest_snapshot=latest_snapshot,
        latest_alert_event=latest_alert_event,
        saved_investigations=_query_recent_investigations(limit=5),
        dataset_filter=dataset,
        station_id_filter=station_id,
        limit_value=max(1, min(limit, 100)),
    )


@app.route("/marine/alerts")
def marine_alerts():
    dataset = request.args.get("dataset", "").strip()
    minimum_priority = request.args.get("minimum_priority", "").strip()
    limit = request.args.get("limit", default=25, type=int) or 25
    reef_alerts = _query_reef_alerts(
        dataset=dataset,
        limit=limit,
        minimum_priority=minimum_priority,
    )
    telemetry = _query_marine_telemetry(limit=1)
    latest_ingest = telemetry[0] if telemetry else None
    latest_snapshot = _load_latest_snapshot()
    latest_alert_event = _load_latest_alert_event()
    return render_template(
        "marine_alerts.html",
        reef_alerts=reef_alerts,
        reef_alert_summary=_summarize_reef_alerts(reef_alerts),
        latest_ingest=latest_ingest,
        latest_snapshot=latest_snapshot,
        latest_alert_event=latest_alert_event,
        dataset_filter=dataset,
        minimum_priority_filter=minimum_priority,
        limit_value=max(1, min(limit, 250)),
    )


@app.route("/marine/briefing")
def marine_briefing():
    latest_snapshot = _load_latest_snapshot()
    latest_alert_event = _load_latest_alert_event()
    reef_alerts = _query_reef_alerts(limit=10, minimum_priority="attention")
    return render_template(
        "marine_briefing.html",
        latest_snapshot=latest_snapshot,
        latest_alert_event=latest_alert_event,
        reef_alerts=reef_alerts,
    )


@app.route("/marine/snapshots")
def marine_snapshots():
    latest_snapshot = _load_latest_snapshot()
    return render_template("marine_snapshots.html", latest_snapshot=latest_snapshot)


@app.route("/ocean-map")
def ocean_map():
    dataset = request.args.get("dataset", "").strip()
    station_id = request.args.get("station_id", "").strip()
    limit = request.args.get("limit", default=100, type=int) or 100
    station_context = _query_station_context(dataset=dataset, station_id=station_id, limit=limit)
    reef_reference = _load_reef_reference()
    reef_context = _build_reef_context(station_context, reef_reference)
    reef_alerts = _derive_reef_alerts(reef_context)
    return render_template(
        "ocean_map.html",
        saved_investigations=_query_recent_investigations(limit=5),
        station_context_summary=_summarize_station_context(station_context),
        reef_context_summary=_summarize_reef_context(reef_context, reef_reference),
        reef_alert_summary=_summarize_reef_alerts(reef_alerts),
        reef_alerts=reef_alerts[:5],
        dataset_filter=dataset,
        station_id_filter=station_id,
        limit_value=max(1, min(limit, 250)),
    )


@app.route("/marine/station/<station_id>")
def marine_station(station_id: str):
    dataset = request.args.get("dataset", "").strip()
    limit = request.args.get("limit", default=100, type=int) or 100
    series = _query_station_series(station_id=station_id, dataset=dataset, limit=limit)
    latest_observations = list(reversed(series))[:10]
    available_datasets = sorted({row["dataset_name"] for row in series})
    return render_template(
        "marine_station.html",
        station_id=station_id,
        dataset_filter=dataset,
        limit_value=max(1, min(limit, 250)),
        series=series,
        latest_observations=latest_observations,
        available_datasets=available_datasets,
        saved_investigations=_query_recent_investigations(limit=5),
    )


@app.route("/api/drift/analyse", methods=["POST"])
def api_drift_analyse():
    """
    POST JSON:
    {
        "client_name":    "Acme Corp",
        "revenue_trend":  -0.03,
        "process_score":  62,
        "team_alignment": 48,
        "market_response": 55,
        "custom_signals": {"Customer NPS": 38}   // optional
    }
    Returns the DriftReport as JSON.
    """
    data = request.get_json(force=True, silent=True) or {}

    client_name = data.get("client_name", "").strip()
    if not client_name:
        return jsonify({"error": "client_name is required"}), 400

    try:
        optimizer = DriftOptimizer(
            client_name    = client_name,
            revenue_trend  = float(data.get("revenue_trend",  0.0)),
            process_score  = float(data.get("process_score",  50.0)),
            team_alignment = float(data.get("team_alignment", 50.0)),
            market_response= float(data.get("market_response",50.0)),
            custom_signals = data.get("custom_signals") or {},
        )
        report = optimizer.analyse()
        return jsonify({"ok": True, "report": report.to_dict()})

    except (ValueError, TypeError) as exc:
        return jsonify({"error": str(exc)}), 422


@app.route("/api/report/generate", methods=["POST"])
def api_report_generate():
    """
    POST JSON (same shape as /api/drift/analyse).
    Runs the Drift Optimizer, generates a PDF, and returns the file.
    """
    data = request.get_json(force=True, silent=True) or {}

    client_name = data.get("client_name", "").strip()
    if not client_name:
        return jsonify({"error": "client_name is required"}), 400

    tenant_slug = data.get("tenant_slug", "default").strip() or "default"

    try:
        optimizer = DriftOptimizer(
            client_name    = client_name,
            revenue_trend  = float(data.get("revenue_trend",  0.0)),
            process_score  = float(data.get("process_score",  50.0)),
            team_alignment = float(data.get("team_alignment", 50.0)),
            market_response= float(data.get("market_response",50.0)),
            custom_signals = data.get("custom_signals") or {},
        )
        drift_report = optimizer.analyse()
        gen  = ReportGenerator(drift_report, tenant_slug=tenant_slug)
        path = gen.generate()

        return send_file(
            path,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=Path(path).name,
        )

    except (ValueError, TypeError) as exc:
        return jsonify({"error": str(exc)}), 422
    except Exception as exc:
        app.logger.exception("Report generation failed")
        return jsonify({"error": "Report generation failed", "detail": str(exc)}), 500


@app.route("/api/reports/list")
def api_reports_list():
    """Return a list of previously generated report files."""
    reports_dir = _ROOT / "outputs" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    files = sorted(reports_dir.glob("*.pdf"), key=lambda f: f.stat().st_mtime, reverse=True)
    return jsonify([
        {"name": f.name, "size_kb": round(f.stat().st_size / 1024, 1)}
        for f in files
    ])


# ── Telemetry / Billing routes ───────────────────────────────────────────────

@app.route("/api/telemetry/pulse", methods=["POST"])
def api_telemetry_pulse():
    """
    Called by the JS timer every PULSE_INTERVAL_MIN of active UI time.
    POST JSON: { "tenant_slug": "lakeside-legal" }
    Returns the updated billable summary for the tenant.

    Shadow-snapshot logic: after every 3 pulses (= 30 minutes of active time)
    a ``shadow:snapshot`` summary event is also written to cortex_telemetry so
    that the Recent Sessions panel can report session milestones.
    """
    _SHADOW_SNAPSHOT_PULSE_INTERVAL = 3   # pulses between shadow snapshots (3 × 10 min = 30 min)

    data        = request.get_json(force=True, silent=True) or {}
    tenant_slug = data.get("tenant_slug", "default").strip() or "default"
    write_event(tenant_slug, "engagement_pulse", {"duration_min": 10})
    pulses      = total_pulse_count(tenant_slug)
    rate        = get_hourly_rate(tenant_slug)
    total_min   = pulses * 10
    total_hours = total_min / 60
    investment  = round(total_hours * rate, 2)

    # Emit a shadow:snapshot milestone every 30 minutes of cumulative active time.
    shadow_emitted = False
    if pulses > 0 and pulses % _SHADOW_SNAPSHOT_PULSE_INTERVAL == 0:
        write_event(
            tenant_slug,
            "shadow:snapshot",
            {
                "pulse_count":   pulses,
                "total_minutes": total_min,
                "total_hours":   round(total_hours, 2),
                "investment":    investment,
                "hourly_rate":   rate,
            },
        )
        shadow_emitted = True

    return jsonify({
        "ok":            True,
        "tenant_slug":   tenant_slug,
        "total_minutes": total_min,
        "total_hours":   round(total_hours, 2),
        "hourly_rate":   rate,
        "investment":    investment,
        "shadow_snapshot_emitted": shadow_emitted,
    })


@app.route("/api/telemetry/billable")
def api_telemetry_billable():
    """
    GET ?tenant_slug=X
    Returns current billable summary without writing a new event.
    Used by the Hub header timer on page load.
    """
    tenant_slug = request.args.get("tenant_slug", "default").strip() or "default"
    pulses      = total_pulse_count(tenant_slug)
    rate        = get_hourly_rate(tenant_slug)
    total_min   = pulses * 10
    total_hours = total_min / 60
    return jsonify({
        "tenant_slug":   tenant_slug,
        "tenant_name":   get_tenant_name(tenant_slug),
        "total_minutes": total_min,
        "total_hours":   round(total_hours, 2),
        "hourly_rate":   rate,
        "investment":    round(total_hours * rate, 2),
        "display":       format_duration(total_min),
    })


@app.route("/api/telemetry/engagement")
def api_telemetry_engagement():
    """
    GET ?tenant_slug=X
    Full engagement summary including event history (for report preview / admin).
    """
    tenant_slug = request.args.get("tenant_slug", "default").strip() or "default"
    return jsonify(calculate_engagement(tenant_slug))


@app.route("/api/telemetry/sessions")
def api_telemetry_sessions():
    """
    GET ?tenant_slug=X&limit=5
    Returns recent session groupings for the tenant (newest first).
    A session is a consecutive run of cortex_telemetry events with no gap
    larger than 30 minutes between them.
    """
    _SESSION_GAP_MIN = 30
    tenant_slug  = request.args.get("tenant_slug", "default").strip() or "default"
    max_sessions = min(max(request.args.get("limit", default=5, type=int) or 5, 1), 20)

    events = query_events(tenant_slug, limit=200)
    if not events:
        return jsonify({
            "sessions":    [],
            "tenant_slug": tenant_slug,
            "tenant_name": get_tenant_name(tenant_slug),
            "hourly_rate": get_hourly_rate(tenant_slug),
        })

    sessions: list[dict] = []
    current: list[dict]  = []

    for ev in events:          # events arrive newest-first from query_events
        if not current:
            current.append(ev)
            continue
        try:
            t_new  = datetime.fromisoformat(ev["timestamp"].replace("Z", "+00:00"))
            t_prev = datetime.fromisoformat(current[-1]["timestamp"].replace("Z", "+00:00"))
            gap_min = abs((t_prev - t_new).total_seconds()) / 60
        except (ValueError, KeyError):
            gap_min = 0

        if gap_min <= _SESSION_GAP_MIN:
            current.append(ev)
        else:
            sessions.append(_summarise_session(current))
            current = [ev]
            if len(sessions) >= max_sessions:
                break

    if current and len(sessions) < max_sessions:
        sessions.append(_summarise_session(current))

    rate     = get_hourly_rate(tenant_slug)
    currency = get_currency(tenant_slug)
    for s in sessions:
        s["investment"] = format_currency(s["duration_min"] / 60 * rate, currency)

    # Surface shadow:snapshot milestones separately — the UI can show them as
    # "Session Checkpoint" entries in the timeline.
    shadow_events = query_events(tenant_slug, event_filter=["shadow:snapshot"], limit=5)
    shadow_milestones = [
        {
            "timestamp":     ev["timestamp"],
            "total_minutes": ev["payload"].get("total_minutes"),
            "investment":    format_currency(
                (ev["payload"].get("total_minutes", 0) / 60) * rate, currency
            ),
        }
        for ev in shadow_events
    ]

    return jsonify({
        "sessions":          sessions[:max_sessions],
        "shadow_milestones": shadow_milestones,
        "tenant_slug":       tenant_slug,
        "tenant_name":       get_tenant_name(tenant_slug),
        "hourly_rate":       rate,
    })


@app.route("/api/aviation/oil-reports")
def api_aviation_oil_reports():
    """
    GET ?limit=N
    Returns oil sentinel report rows (chronological, oldest-first) for sparkline
    rendering plus the Fe baseline constant.
    """
    tenant_id = _request_tenant_id()
    limit   = min(max(request.args.get("limit", default=2000, type=int) or 2000, 1), 10000)
    reports = list(reversed(_query_oil_sentinel_reports(limit=limit, tenant_id=tenant_id)))
    return jsonify({"tenant_id": tenant_id, "reports": reports, "baseline_fe": 38.0})


@app.route("/api/aviation/predictive-maintenance")
def api_aviation_predictive_maintenance():
    tenant_id = _request_tenant_id()
    tail_number = (request.args.get("tail_number", default="N6424P", type=str) or "N6424P").strip().upper()
    return jsonify(
        {
            "tenant_id": tenant_id,
            **predict_component_failure(tenant_id=tenant_id, tail_number=tail_number),
        }
    )


# ── Navigator API ─────────────────────────────────────────────────────────────

@app.route("/api/navigator/expeditions", methods=["GET", "POST"])
@app.route("/api/navigator/field-observations", methods=["GET", "POST"])
@app.route("/api/navigator/observations", methods=["GET", "POST"])
def api_navigator_expeditions():
    """
    GET  ?limit=N  — list expedition records, newest-first.
    POST           — record a new find from the field.
    """
    if request.method == "GET":
        tenant_id = _request_tenant_id()
        limit = min(max(request.args.get("limit", default=100, type=int) or 100, 1), 500)
        user_id = _normalise_user_id(request.args.get("user_id", default=1, type=int), default=1)
        expeditions = _query_expeditions(limit=limit, user_id=user_id, tenant_id=tenant_id)
        specimens = _query_specimen_inventory(limit=250, tenant_id=tenant_id)
        correlation = correlate_global_signals(
            tenant_id=tenant_id,
            user_id=user_id,
            expedition_records=expeditions,
            specimen_records=specimens,
        )
        _apply_global_correlation_annotations(
            expeditions=expeditions,
            specimens=specimens,
            correlation=correlation,
        )
        return jsonify(expeditions)

    # POST — record a new find
    data      = request.get_json(silent=True) or {}
    tenant_id = _normalise_tenant_id(data.get("tenant_id") or data.get("tenant_slug") or _request_tenant_id())
    user_id   = _normalise_user_id(data.get("user_id"), default=1)
    if _is_associate_user(tenant_id=tenant_id, user_id=user_id):
        return jsonify({"error": "associate role is read-only for expedition posting"}), 403
    ts        = (data.get("timestamp") or
                 datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    loc       = data.get("location_name", "").strip() or None
    lat       = data.get("latitude")
    lng       = data.get("longitude")
    specimens = data.get("specimen_types", "").strip() or None
    try:
        yield_r = float(data["yield_rating"]) if data.get("yield_rating") is not None else None
    except (ValueError, TypeError):
        yield_r = None

    created = _insert_expedition(
        tenant_id=tenant_id,
        user_id=user_id,
        timestamp=ts,
        location_name=loc,
        latitude=lat,
        longitude=lng,
        specimen_types=specimens,
        yield_rating=yield_r,
    )
    # Track Navigator Expedition usage for billing preview
    _metered_usage_increment(
        _normalise_organization_id(_request_organization_id(default=_DEFAULT_ORGANIZATION_ID) or _DEFAULT_ORGANIZATION_ID),
        "navigator_expeditions",
    )
    return jsonify(created), 201


@app.route("/api/navigator/specimens", methods=["GET", "POST"])
def api_navigator_specimens():
    """
    GET  ?limit=N
    POST JSON specimen record (photo path + characteristics + yield stars).
    """
    if request.method == "GET":
        tenant_id = _request_tenant_id()
        limit = min(max(request.args.get("limit", default=100, type=int) or 100, 1), 500)
        user_id = _normalise_user_id(request.args.get("user_id", default=1, type=int), default=1)
        specimens = _query_specimen_inventory(limit=limit, tenant_id=tenant_id)
        expeditions = _query_expeditions(limit=250, user_id=user_id, tenant_id=tenant_id)
        correlation = correlate_global_signals(
            tenant_id=tenant_id,
            user_id=user_id,
            expedition_records=expeditions,
            specimen_records=specimens,
        )
        _apply_global_correlation_annotations(
            expeditions=expeditions,
            specimens=specimens,
            correlation=correlation,
        )
        return jsonify(specimens)

    data = request.get_json(silent=True) or {}
    tenant_id = _normalise_tenant_id(data.get("tenant_id") or data.get("tenant_slug") or _request_tenant_id())
    user_id = _normalise_user_id(data.get("user_id"), default=1)

    expedition_id = None
    expedition = None
    raw_expedition_id = data.get("expedition_id")
    if raw_expedition_id not in (None, ""):
        try:
            expedition_id = int(raw_expedition_id)
        except (TypeError, ValueError):
            return jsonify({"error": "expedition_id must be an integer"}), 400
        if expedition_id <= 0:
            return jsonify({"error": "expedition_id must be > 0"}), 400

    try:
        yield_stars = int(data.get("yield_stars"))
    except (TypeError, ValueError):
        return jsonify({"error": "yield_stars must be an integer from 1 to 5"}), 400
    if yield_stars < 1 or yield_stars > 5:
        return jsonify({"error": "yield_stars must be in the range 1..5"}), 400

    def _to_float_or_none(name: str) -> float | None:
        value = data.get(name)
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            raise ValueError(name)

    try:
        hardness = _to_float_or_none("hardness")
        specific_gravity = _to_float_or_none("specific_gravity")
        estimated_weight_lbs = _to_float_or_none("estimated_weight_lbs")
        market_value_usd = _to_float_or_none("market_value_usd")
        latitude = _to_float_or_none("latitude")
        longitude = _to_float_or_none("longitude")
    except ValueError as bad_field:
        return jsonify({"error": f"{bad_field.args[0]} must be numeric"}), 400

    if estimated_weight_lbs is not None and estimated_weight_lbs < 0:
        return jsonify({"error": "estimated_weight_lbs must be >= 0"}), 400
    if specific_gravity is not None and specific_gravity < 0:
        return jsonify({"error": "specific_gravity must be >= 0"}), 400
    if market_value_usd is not None and market_value_usd < 0:
        return jsonify({"error": "market_value_usd must be >= 0"}), 400

    ts = data.get("timestamp") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    image_path = (data.get("image_path") or "").strip() or None
    color = (data.get("color") or "").strip() or None
    mineral_class = (data.get("mineral_class") or "").strip() or None
    notes = (data.get("notes") or "").strip() or None

    if expedition_id and (latitude is None or longitude is None):
        expedition = _query_expedition_by_id(expedition_id, tenant_id=tenant_id)
        if expedition:
            if latitude is None:
                latitude = _safe_float(expedition.get("latitude"))
            if longitude is None:
                longitude = _safe_float(expedition.get("longitude"))
            if data.get("user_id") in (None, ""):
                user_id = _normalise_user_id(expedition.get("user_id"), default=user_id)

    expedition_location_name = (expedition or {}).get("location_name") if expedition else None

    specimen = _insert_specimen_inventory(
        expedition_id=expedition_id,
        timestamp=ts,
        image_path=image_path,
        yield_stars=yield_stars,
        estimated_weight_lbs=estimated_weight_lbs,
        market_value_usd=market_value_usd,
        color=color,
        hardness=hardness,
        specific_gravity=specific_gravity,
        mineral_class=mineral_class,
        notes=notes,
        latitude=latitude,
        longitude=longitude,
        tenant_id=tenant_id,
    )

    signal_result = None
    if yield_stars >= 5:
        signal_result = _emit_observatory_signal(
            tenant_id=tenant_id,
            user_id=user_id,
            user_role=None,
            signal_type=mineral_class or color or "Specimen",
            location_name=expedition_location_name,
            latitude=latitude,
            longitude=longitude,
            source="specimen_inventory",
        )

    return jsonify({"status": "created", "tenant_id": tenant_id, "specimen": specimen, "signal": signal_result}), 201


@app.route("/api/observatory/chat-action", methods=["POST"])
def api_observatory_chat_action():
    data = request.get_json(silent=True) or {}
    command_text = str(data.get("command") or data.get("message") or "").strip()
    if not command_text:
        return jsonify({"error": "command is required"}), 400

    intent = _classify_observatory_command(command_text)
    tenant_id = _normalise_tenant_id(data.get("tenant_id") or data.get("tenant_slug") or _request_tenant_id())
    user_id = _normalise_user_id(data.get("user_id"), default=1)

    if intent == "log_expedition":
        if _is_associate_user(tenant_id=tenant_id, user_id=user_id):
            return jsonify({"error": "associate role is read-only for expedition posting"}), 403

        current_location = data.get("current_location") if isinstance(data.get("current_location"), dict) else {}
        lat = _safe_float(current_location.get("latitude") if current_location else data.get("latitude"))
        lon = _safe_float(current_location.get("longitude") if current_location else data.get("longitude"))
        location_name = (
            str((current_location or {}).get("label") or data.get("location_name") or "Current Location").strip()
            or "Current Location"
        )
        yield_rating = _safe_float(data.get("yield_rating"))
        if yield_rating is None:
            parsed_yield = re.search(r"\byield\s*(\d+(?:\.\d+)?)\b", command_text.lower())
            if parsed_yield:
                yield_rating = _safe_float(parsed_yield.group(1))

        created = _insert_expedition(
            tenant_id=tenant_id,
            user_id=user_id,
            timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            location_name=location_name,
            latitude=lat,
            longitude=lon,
            specimen_types=str(data.get("specimen_types") or "").strip() or None,
            yield_rating=yield_rating,
        )
        _metered_usage_increment(
            _normalise_organization_id(_request_organization_id(default=_DEFAULT_ORGANIZATION_ID) or _DEFAULT_ORGANIZATION_ID),
            "navigator_expeditions",
        )

        return jsonify(
            {
                "status": "executed",
                "intent": intent,
                "command": command_text,
                "result": "Expedition logged at current location.",
                "expedition": created,
            }
        ), 201

    return jsonify(
        {
            "status": "ignored",
            "intent": intent,
            "command": command_text,
            "supported_examples": [
                "Log Expedition at current location.",
            ],
        }
    ), 400


@app.route("/api/observatory/signals", methods=["POST"])
def api_observatory_signals():
    data = request.get_json(silent=True) or {}
    tenant_id = _normalise_tenant_id(data.get("tenant_id") or data.get("tenant_slug") or _request_tenant_id())
    user_id = _normalise_user_id(data.get("user_id"), default=1)
    if _is_associate_user(tenant_id=tenant_id, user_id=user_id):
        return jsonify({"error": "associate role is read-only for observatory signal posting"}), 403

    signal_type = (data.get("signal_type") or data.get("specimen_type") or data.get("mineral_class") or "Specimen")
    location_name = (data.get("location_name") or "").strip() or None
    latitude = _safe_float(data.get("latitude"))
    longitude = _safe_float(data.get("longitude"))
    general_region = (data.get("general_region") or "").strip() or None
    user_role = (data.get("role") or "").strip() or None

    result = _emit_observatory_signal(
        tenant_id=tenant_id,
        user_id=user_id,
        signal_type=signal_type,
        location_name=location_name,
        latitude=latitude,
        longitude=longitude,
        user_role=user_role,
        general_region=general_region,
        source="api",
    )

    status_code = 201 if result.get("status") == "created" else 200
    return jsonify({"tenant_id": tenant_id, **result}), status_code


@app.route("/api/observatory/signals/<int:signal_id>/vouch", methods=["POST"])
def api_observatory_signal_vouch(signal_id: int):
    data = request.get_json(silent=True) or {}
    tenant_id = _normalise_tenant_id(data.get("tenant_id") or data.get("tenant_slug") or _request_tenant_id())

    signal = _query_observatory_signal(signal_id)
    if signal is None:
        return jsonify({"error": "signal not found"}), 404

    if str(signal.get("tenant_token") or "") == _tenant_token(tenant_id):
        return jsonify({"error": "cannot vouch your own signal"}), 400

    evidence_count = _count_local_signal_evidence(
        tenant_id=tenant_id,
        signal_type=str(signal.get("signal_type") or ""),
        general_region=str(signal.get("general_region") or ""),
    )
    if evidence_count <= 0:
        return jsonify({"error": "no similar local finds in this region to support vouch"}), 403

    already_vouched = _has_vouched_signal(signal_id, tenant_id=tenant_id)
    if not already_vouched:
        _record_signal_vouch(signal_id=signal_id, tenant_id=tenant_id, evidence_count=evidence_count)

    refreshed_signal = _query_observatory_signal(signal_id) or signal
    probability = signal_probability(refreshed_signal, tenant_id=tenant_id)
    card = _build_global_node_card(tenant_id=tenant_id, limit=3)

    return jsonify(
        {
            "status": "vouched" if not already_vouched else "already-vouched",
            "tenant_id": tenant_id,
            "signal": {
                **refreshed_signal,
                "probability_status": probability.get("status"),
                "confidence_pct": probability.get("confidence_pct"),
                "evidence_count": evidence_count,
                "already_vouched": True,
            },
            "global_node": card,
        }
    ), 200


@app.route("/api/navigator/observations/bulk-sync", methods=["POST"])
def api_navigator_observations_bulk_sync():
    data = request.get_json(silent=True) or {}
    tenant_id = _normalise_tenant_id(data.get("tenant_id") or data.get("tenant_slug") or _request_tenant_id())
    fallback_user_id = _normalise_user_id(data.get("user_id"), default=1)
    items = data.get("items") or []
    if not isinstance(items, list) or not items:
        return jsonify({"error": "items list is required"}), 400

    created: list[dict] = []
    for raw_item in items:
        if not isinstance(raw_item, dict):
            continue

        user_id = _normalise_user_id(raw_item.get("user_id"), default=fallback_user_id)
        timestamp = str(raw_item.get("timestamp") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        location_name = (raw_item.get("location_name") or "").strip() or None
        specimen_types = (raw_item.get("specimen_types") or "").strip() or None

        latitude = _safe_float(raw_item.get("latitude"))
        longitude = _safe_float(raw_item.get("longitude"))
        yield_rating = _safe_float(raw_item.get("yield_rating"))

        created.append(
            _insert_expedition(
                tenant_id=tenant_id,
                user_id=user_id,
                timestamp=timestamp,
                location_name=location_name,
                latitude=latitude,
                longitude=longitude,
                specimen_types=specimen_types,
                yield_rating=yield_rating,
            )
        )

    return jsonify(
        {
            "status": "synced",
            "tenant_id": tenant_id,
            "synced_count": len(created),
            "items": created,
        }
    ), 200


@app.route("/api/navigator/profile/share-signals", methods=["GET", "POST"])
def api_navigator_profile_share_signals():
    if request.method == "GET":
        tenant_id = _request_tenant_id()
        user_id = _normalise_user_id(request.args.get("user_id", default=1, type=int), default=1)
        profile = _query_user_profile(user_id=user_id, tenant_id=tenant_id)
        if profile is None:
            return jsonify({"error": "user profile not found"}), 404
        return jsonify(
            {
                "tenant_id": tenant_id,
                "user_id": user_id,
                "username": profile.get("username"),
                "role": profile.get("role"),
                "share_signals": bool(profile.get("share_signals")),
            }
        )

    data = request.get_json(silent=True) or {}
    tenant_id = _normalise_tenant_id(data.get("tenant_id") or data.get("tenant_slug") or _request_tenant_id())
    user_id = _normalise_user_id(data.get("user_id"), default=1)
    raw_share = data.get("share_signals")
    if raw_share in (None, ""):
        return jsonify({"error": "share_signals is required"}), 400
    share_signals = _coerce_bool(raw_share, default=False)
    profile = _upsert_user_share_signals(user_id=user_id, tenant_id=tenant_id, share_signals=share_signals)
    return jsonify(
        {
            "status": "updated",
            "tenant_id": tenant_id,
            "user_id": user_id,
            "username": profile.get("username"),
            "role": profile.get("role"),
            "share_signals": bool(profile.get("share_signals")),
        }
    )


@app.route("/api/mentorship/onboarding", methods=["POST"])
def api_mentorship_onboarding():
    data = request.get_json(silent=True) or {}
    tenant_id = _normalise_tenant_id(data.get("tenant_id") or data.get("tenant_slug") or _request_tenant_id())
    username = str(data.get("username") or "").strip()
    if not username:
        return jsonify({"error": "username is required"}), 400

    role = _normalise_user_role(data.get("role") or "Lead Analyst")
    home_base = str(data.get("home_base_icao") or _PRIMARY_ICAO_CODES[0]).strip().upper() or _PRIMARY_ICAO_CODES[0]
    share_signals = _coerce_bool(data.get("share_signals"), default=False)
    mentor_mesh = data.get("mentor_mesh")

    raw_scopes = data.get("scopes")
    scopes: list[str] = []
    if isinstance(raw_scopes, list):
        scopes = [str(scope).strip() for scope in raw_scopes if str(scope).strip()]
    elif isinstance(raw_scopes, str):
        scopes = [token.strip() for token in raw_scopes.split(",") if token.strip()]

    raw_user_id = data.get("user_id")
    user_id = None
    if raw_user_id not in (None, ""):
        try:
            user_id = _normalise_user_id(raw_user_id)
        except (TypeError, ValueError):
            return jsonify({"error": "user_id must be an integer"}), 400

    db_path = _aviation_db_path(tenant_id)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        profile = mentorship_onboarding(
            conn=conn,
            username=username,
            role=role,
            home_base_icao=home_base,
            scopes=scopes,
            user_id=user_id,
            share_signals=share_signals,
            mentor_mesh=mentor_mesh,
        )
    finally:
        conn.close()

    return jsonify({"status": "onboarded", "tenant_id": tenant_id, "profile": profile}), 200


@app.route("/api/mentorship/guest-audit", methods=["GET", "POST"])
def api_guest_oracle_audit():
    if request.method == "GET":
        tenant_id = _request_tenant_id()
        user_id = _normalise_user_id(request.args.get("user_id", default=1, type=int), default=1)
        profile = _query_user_profile(user_id=user_id, tenant_id=tenant_id)
        if profile is None:
            return jsonify({"error": "user profile not found"}), 404

        rows = _query_guest_oracle_submissions_for_user(
            tenant_id=tenant_id,
            user_id=user_id,
            limit=request.args.get("limit", default=25, type=int) or 25,
        )
        return jsonify(
            {
                "tenant_id": tenant_id,
                "user_id": user_id,
                "role": profile.get("role"),
                "submissions": rows,
            }
        )

    data = request.get_json(silent=True) or {}
    tenant_id = _normalise_tenant_id(data.get("tenant_id") or data.get("tenant_slug") or _request_tenant_id())
    user_id = _normalise_user_id(data.get("user_id"), default=1)
    profile = _query_user_profile(user_id=user_id, tenant_id=tenant_id)
    if profile is None:
        return jsonify({"error": "user profile not found"}), 404

    permissions = profile.get("permissions") or {}
    if profile.get("role") != "Guest Scientist":
        return jsonify({"error": "guest_oracle_audit is only available to Guest Scientist users"}), 403

    drift_pct = _safe_float(data.get("drift_pct"))
    discovery_note = str(data.get("discovery_note") or "").strip() or None
    if drift_pct is None and not discovery_note:
        return jsonify({"error": "drift_pct or discovery_note is required"}), 400

    can_submit_drift = bool(permissions.get("can_submit_drift"))
    can_submit_discovery = bool(permissions.get("can_submit_discovery"))
    if drift_pct is not None and not can_submit_drift:
        return jsonify({"error": "user permission denied for drift submissions"}), 403
    if discovery_note and not can_submit_discovery:
        return jsonify({"error": "user permission denied for discovery submissions"}), 403

    if drift_pct is not None:
        drift_pct = max(0.0, min(100.0, float(drift_pct)))

    private_label = str(data.get("private_location_label") or "").strip() or None
    private_lat = _safe_float(data.get("private_latitude"))
    private_lon = _safe_float(data.get("private_longitude"))

    if drift_pct is not None and discovery_note:
        submission_type = "DRIFT_DISCOVERY"
    elif drift_pct is not None:
        submission_type = "DRIFT"
    else:
        submission_type = "DISCOVERY"

    created = _insert_guest_oracle_submission(
        tenant_id=tenant_id,
        user_id=user_id,
        submission_type=submission_type,
        drift_pct=drift_pct,
        discovery_note=discovery_note,
        private_location_label=private_label,
        private_latitude=private_lat,
        private_longitude=private_lon,
        source="guest_oracle_api",
    )

    response_payload = {
        "id": created.get("id"),
        "user_id": created.get("user_id"),
        "submission_type": created.get("submission_type"),
        "drift_pct": created.get("drift_pct"),
        "discovery_note": created.get("discovery_note"),
        "submitted_at": created.get("submitted_at"),
        "source": created.get("source"),
    }
    if "DRIFT" in str(created.get("submission_type") or "").upper():
        _emit_realtime(
            "drift_update",
            {
                "tenant_id": tenant_id,
                "user_id": user_id,
                "submission_type": created.get("submission_type"),
                "drift_pct": created.get("drift_pct"),
                "submitted_at": created.get("submitted_at"),
                "source": created.get("source") or "guest_oracle_api",
                "message": f"Drift update received: {created.get('drift_pct')}%",
            },
        )
    network_health = _query_network_health(tenant_id=tenant_id, mentor_mesh=profile.get("mentor_mesh"))
    return jsonify({"status": "submitted", "tenant_id": tenant_id, "submission": response_payload, "network_health": network_health}), 201


@app.route("/api/mentorship/guest-inbox")
def api_guest_signal_inbox():
    tenant_id = _request_tenant_id()
    user_id = _normalise_user_id(request.args.get("user_id", default=1, type=int), default=1)
    profile = _query_user_profile(user_id=user_id, tenant_id=tenant_id)
    if profile is None:
        return jsonify({"error": "user profile not found"}), 404

    db_path = _aviation_db_path(tenant_id)
    conn = sqlite3.connect(str(db_path))
    try:
        _ensure_guest_signal_inbox_table(conn)
        rows = conn.execute(
            """
            SELECT id, signal_kind, message, emitted_at, source, is_read
            FROM guest_signal_inbox
            WHERE user_id = ?
            ORDER BY emitted_at DESC, id DESC
            LIMIT ?
            """,
            (user_id, max(1, min(request.args.get("limit", default=25, type=int) or 25, 250))),
        ).fetchall()
    finally:
        conn.close()

    return jsonify(
        {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "messages": [
                {
                    "id": int(row[0]),
                    "signal_kind": row[1],
                    "message": row[2],
                    "emitted_at": row[3],
                    "source": row[4],
                    "is_read": bool(int(row[5] or 0)),
                }
                for row in rows
            ],
        }
    )


@app.route("/api/global-node/philosophical-signal", methods=["POST"])
def api_global_node_philosophical_signal():
    data = request.get_json(silent=True) or {}
    tenant_id = _normalise_tenant_id(data.get("tenant_id") or data.get("tenant_slug") or _request_tenant_id())
    user_id = _normalise_user_id(data.get("user_id"), default=1)
    quote_text = str(data.get("quote") or data.get("quote_text") or "").strip()
    if not quote_text:
        return jsonify({"error": "quote is required"}), 400

    profile = _query_user_profile(user_id=user_id, tenant_id=tenant_id)
    if profile is None:
        return jsonify({"error": "user profile not found"}), 404

    permissions = profile.get("permissions") or {}
    if not bool(permissions.get("can_broadcast_philosophical_signal")):
        return jsonify({"error": "user does not have permission to broadcast philosophical signals"}), 403

    mentor_mesh = data.get("mentor_mesh") or profile.get("mentor_mesh") or _GUEST_DEFAULT_MENTOR_MESH
    try:
        signal = _broadcast_philosophical_signal(
            tenant_id=tenant_id,
            mentor_mesh=mentor_mesh,
            quote_text=quote_text,
            source="global_node_api",
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify({"status": "broadcast", "tenant_id": tenant_id, "signal": signal}), 201


@app.route("/api/architect/automation/deploy", methods=["POST"])
def api_architect_automation_deploy():
    data = request.get_json(silent=True) or {}
    tenant_id = _normalise_tenant_id(data.get("tenant_id") or data.get("tenant_slug") or _request_tenant_id())
    user_id = _normalise_user_id(data.get("user_id"), default=1)
    requested_key = str(data.get("suggestion_key") or "").strip()

    architect = suggest_workflow_automation(
        tenant_id=tenant_id,
        user_id=user_id,
        horizon_days=30,
        mentor_mesh=(_query_user_profile(user_id, tenant_id=tenant_id) or {}).get("mentor_mesh"),
    )
    suggestions = architect.get("suggestions") or []
    if not suggestions:
        return jsonify({"error": "no deployable automation suggestion available", "automation_architect": architect}), 409

    if requested_key:
        target = next((row for row in suggestions if str(row.get("key") or "") == requested_key), None)
        if target is None:
            return jsonify({"error": "suggestion_key not found in deployable suggestions"}), 404
    else:
        target = suggestions[0]

    writable_scopes = set(str(scope) for scope in (architect.get("writable_scopes") or []))
    required_scope = str(target.get("required_scope") or "")
    if required_scope not in writable_scopes:
        return jsonify({"error": "write permission denied for suggested automation scope"}), 403

    deployment = _deploy_suggested_pruner(tenant_id=tenant_id, user_id=user_id, suggestion=target)
    return jsonify(
        {
            "status": "deployed",
            "tenant_id": tenant_id,
            "user_id": user_id,
            "suggestion": target,
            "deployment": deployment,
            "automation_architect": architect,
        }
    ), 201


@app.route("/api/architect/automation/dry-run", methods=["POST"])
def api_architect_automation_dry_run():
    data = request.get_json(silent=True) or {}
    tenant_id = _normalise_tenant_id(data.get("tenant_id") or data.get("tenant_slug") or _request_tenant_id())
    user_id = _normalise_user_id(data.get("user_id"), default=1)
    requested_key = str(data.get("suggestion_key") or "").strip()

    architect = suggest_workflow_automation(
        tenant_id=tenant_id,
        user_id=user_id,
        horizon_days=30,
        mentor_mesh=(_query_user_profile(user_id, tenant_id=tenant_id) or {}).get("mentor_mesh"),
    )
    suggestions = architect.get("suggestions") or []
    if not suggestions:
        return jsonify({"error": "no dry-runnable automation suggestion available", "automation_architect": architect}), 409

    if requested_key:
        target = next((row for row in suggestions if str(row.get("key") or "") == requested_key), None)
        if target is None:
            return jsonify({"error": "suggestion_key not found in deployable suggestions"}), 404
    else:
        target = suggestions[0]

    writable_scopes = set(str(scope) for scope in (architect.get("writable_scopes") or []))
    required_scope = str(target.get("required_scope") or "")
    if required_scope not in writable_scopes:
        return jsonify({"error": "write permission denied for suggested automation scope"}), 403

    dry_run = _dry_run_suggested_pruner(
        tenant_id=tenant_id,
        user_id=user_id,
        suggestion=target,
    )
    status_code = 200 if dry_run.get("status") == "dry_run_complete" else 500
    return jsonify(
        {
            "status": dry_run.get("status"),
            "tenant_id": tenant_id,
            "user_id": user_id,
            "suggestion": target,
            "dry_run": dry_run,
            "automation_architect": architect,
        }
    ), status_code


@app.route("/api/navigator/consumables", methods=["GET", "POST"])
def api_navigator_consumables():
    """
    GET  ?limit=N
    POST JSON update for a consumable entry.
    """
    if request.method == "GET":
        tenant_id = _request_tenant_id()
        user_id = _normalise_user_id(request.args.get("user_id", default=1, type=int), default=1)
        limit = min(max(request.args.get("limit", default=25, type=int) or 25, 1), 250)
        rows = _query_mission_consumables(limit=limit, user_id=user_id, tenant_id=tenant_id)
        return jsonify({"tenant_id": tenant_id, "items": rows, "restock_alert": _build_restock_alert(rows)})

    data = request.get_json(silent=True) or {}
    tenant_id = _normalise_tenant_id(data.get("tenant_id") or data.get("tenant_slug") or _request_tenant_id())
    user_id = _normalise_user_id(data.get("user_id"), default=1)
    item_key = (data.get("item_key") or "").strip().lower()
    if not item_key:
        return jsonify({"error": "item_key is required"}), 400

    display_name = (data.get("display_name") or item_key.replace("_", " ").title()).strip()
    unit = (data.get("unit") or "units").strip() or "units"
    notes = (data.get("notes") or "").strip() or None

    try:
        quantity = float(data.get("quantity"))
    except (TypeError, ValueError):
        return jsonify({"error": "quantity must be numeric"}), 400
    if quantity < 0:
        return jsonify({"error": "quantity must be >= 0"}), 400

    threshold_raw = data.get("restock_threshold")
    if threshold_raw in (None, ""):
        defaults = {row["item_key"]: row for row in _MISSION_CONSUMABLE_DEFAULTS}
        threshold = float(defaults.get(item_key, {}).get("restock_threshold", 0.0))
    else:
        try:
            threshold = float(threshold_raw)
        except (TypeError, ValueError):
            return jsonify({"error": "restock_threshold must be numeric"}), 400
        if threshold < 0:
            return jsonify({"error": "restock_threshold must be >= 0"}), 400

    ts = data.get("updated_at") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    row = _upsert_mission_consumable(
        user_id=user_id,
        item_key=item_key,
        display_name=display_name,
        quantity=quantity,
        unit=unit,
        restock_threshold=threshold,
        notes=notes,
        updated_at=ts,
        source=(data.get("source") or "api").strip() or "api",
        tenant_id=tenant_id,
    )
    all_rows = _query_mission_consumables(limit=250, user_id=user_id, tenant_id=tenant_id)
    return jsonify({"status": "updated", "tenant_id": tenant_id, "item": row, "restock_alert": _build_restock_alert(all_rows)}), 200


@app.route("/api/navigator/mission-costs")
def api_navigator_mission_costs():
    """
    GET ?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD
    Returns mission ROI aggregate: fuel + consumable depletion vs specimen yield.
    """
    tenant_id = _request_tenant_id()
    start_date = request.args.get("start_date", type=str)
    end_date = request.args.get("end_date", type=str)
    payload = _query_mission_roi(start_date=start_date, end_date=end_date, tenant_id=tenant_id)
    payload["tenant_id"] = tenant_id
    return jsonify(payload)


@app.route("/api/navigator/mission-forecast")
def api_navigator_mission_forecast():
    """
    Suggest the top mission window for the upcoming week by blending
    5-day TAF weather signals, local fuel-market trend, and consulting drift load.
    """
    return jsonify(_build_mission_forecast(horizon_days=5))


@app.route("/api/navigator/mission-map")
def api_navigator_mission_map():
    """Combined map points for Aviation reports (airport proxy) + rockhounding finds."""
    expedition_limit = min(max(request.args.get("expedition_limit", default=200, type=int) or 200, 1), 500)
    aviation_limit = min(max(request.args.get("aviation_limit", default=200, type=int) or 200, 1), 500)
    tenant_id = _request_tenant_id()
    user_id = _normalise_user_id(request.args.get("user_id", default=1, type=int), default=1)
    expeditions = _query_expeditions(limit=expedition_limit, user_id=user_id, tenant_id=tenant_id)
    specimens = _query_specimen_inventory(limit=250, tenant_id=tenant_id)
    correlation = correlate_global_signals(
        tenant_id=tenant_id,
        user_id=user_id,
        expedition_records=expeditions,
        specimen_records=specimens,
    )
    _apply_global_correlation_annotations(
        expeditions=expeditions,
        specimens=specimens,
        correlation=correlation,
    )
    reports = _query_oil_sentinel_reports(limit=aviation_limit, tenant_id=tenant_id)
    hotspots = predict_hotspots(months=12, horizon_days=30, limit=5)
    payload = _build_navigator_mission_map(
        expeditions,
        reports,
        predicted_hotspots=hotspots,
        mesh_signals=correlation.get("mesh_signals") or [],
    )
    payload["tenant_id"] = tenant_id
    return jsonify(payload)


@app.route("/api/navigator/fuel-logs", methods=["GET", "POST"])
def api_navigator_fuel_logs():
    """
    GET  ?tail_number=<tail>&limit=N
    POST JSON fuel top-off event with Hobbs/Tach entries.
    """
    if request.method == "GET":
        tenant_id = _request_tenant_id()
        tail_number = request.args.get("tail_number", default="", type=str) or ""
        limit = min(max(request.args.get("limit", default=100, type=int) or 100, 1), 500)
        return jsonify(_query_fuel_logs(tail_number=tail_number, limit=limit, tenant_id=tenant_id))

    data = request.get_json(silent=True) or {}
    tenant_id = _normalise_tenant_id(data.get("tenant_id") or data.get("tenant_slug") or _request_tenant_id())
    tail_number = (data.get("tail_number") or "N6424P").strip().upper()
    if not tail_number:
        return jsonify({"error": "tail_number is required"}), 400

    try:
        gallons_added = float(data.get("gallons_added"))
    except (TypeError, ValueError):
        return jsonify({"error": "gallons_added must be numeric"}), 400
    if gallons_added <= 0:
        return jsonify({"error": "gallons_added must be > 0"}), 400

    def _to_float(name: str) -> float | None:
        value = data.get(name)
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            raise ValueError(name)

    try:
        hobbs_time = _to_float("hobbs_time")
        tach_time = _to_float("tach_time")
        fuel_after = _to_float("fuel_after_gal")
    except ValueError as bad_field:
        return jsonify({"error": f"{bad_field.args[0]} must be numeric"}), 400

    if hobbs_time is None and tach_time is None:
        return jsonify({"error": "either hobbs_time or tach_time is required"}), 400

    ts = data.get("timestamp") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    notes = (data.get("notes") or "").strip() or None

    row = _insert_fuel_log(
        tail_number=tail_number,
        timestamp=ts,
        hobbs_time=hobbs_time,
        tach_time=tach_time,
        gallons_added=gallons_added,
        fuel_after_gal=fuel_after,
        notes=notes,
        tenant_id=tenant_id,
    )
    return jsonify({"status": "created", "tenant_id": tenant_id, "fuel_log": row}), 201


@app.route("/api/navigator/preflight")
def api_navigator_preflight():
    """
    GET ?location_id=<expedition_id>&load_profile=standard|high-yield|custom&specimen_weight_lbs=<float>
    Returns pre-flight summary with Sentinel, fuel, destination weather, and go/no-go.
    """
    from nerves.aviation.recency_check import RecencyChecker, PRIMARY_TAIL_NUMBER

    location_id = request.args.get("location_id", type=int)
    tenant_id = _request_tenant_id()
    user_id = _normalise_user_id(request.args.get("user_id", default=1, type=int), default=1)
    if not location_id:
        return jsonify({"error": "location_id is required"}), 400

    expedition = _query_expedition_by_id(location_id, user_id=user_id, tenant_id=tenant_id)
    if expedition is None:
        return jsonify({"error": f"location_id {location_id} not found"}), 404

    profile = _query_user_profile(user_id, tenant_id=tenant_id) or {}
    mission_region = _resolve_general_region(
        location_name=expedition.get("location_name"),
        latitude=_safe_float(expedition.get("latitude")),
        longitude=_safe_float(expedition.get("longitude")),
        home_base_icao=profile.get("home_base_icao"),
    )
    high_risk_signals = _query_regional_high_risk_signals(
        tenant_id=tenant_id,
        general_region=mission_region,
        limit=5,
    )

    load_profile = request.args.get("load_profile", default="standard", type=str) or "standard"
    specimen_weight_lbs = request.args.get("specimen_weight_lbs", default=None, type=float)

    airport = _resolve_airport_for_expedition(expedition)
    weather = _fetch_weather_bundle(airport.get("code") or _HOME_AIRPORT["code"])
    weather_risk, weather_reasons = _weather_risk_from_metar(weather.get("metar"))

    load = _compute_load_profile(load_profile=load_profile, specimen_weight_lbs=specimen_weight_lbs)
    fuel = _build_fuel_status(load)

    sentinel = RecencyChecker().check(tail_number=PRIMARY_TAIL_NUMBER)
    sentinel_iron_delta = sentinel.latest_reading.iron_delta_ppm if sentinel.latest_reading else None
    sentinel_card = {
        "tail_number": sentinel.tail_number,
        "status": sentinel.status,
        "colour": sentinel.colour,
        "days_remaining": sentinel.days_remaining,
        "last_analysis_date": sentinel.last_analysis_date,
        "iron_delta_ppm": sentinel_iron_delta,
    }

    go_no_go = _build_go_no_go(
        sentinel_status=sentinel.status,
        fuel_status=fuel,
        weather_risk=weather_risk,
        load_profile=load,
    )

    return jsonify(
        {
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "tenant_id": tenant_id,
            "location_id": expedition["id"],
            "location_name": expedition.get("location_name") or "Unknown Site",
            "destination": {
                "latitude": _safe_float(expedition.get("latitude")),
                "longitude": _safe_float(expedition.get("longitude")),
            },
            "nearest_airport": airport,
            "sentinel": sentinel_card,
            "fuel_status": fuel,
            "weather": {
                **weather,
                "risk": weather_risk,
                "reasons": weather_reasons,
            },
            "mission_region": mission_region,
            "high_risk_signals": high_risk_signals,
            "load_profile": load,
            "go_no_go": go_no_go,
        }
    )


# ── Briefing response cache (short-lived TTL to absorb rapid-fire stress calls) ──
_BRIEFING_CACHE: dict[str, tuple[float, dict]] = {}
_BRIEFING_CACHE_TTL_S = 5.0


def _briefing_cache_key(tenant_id: str, user_id: int, user_role: str, organization_id: str | None) -> str:
    return f"{tenant_id}|{user_id}|{user_role}|{organization_id or ''}"


@app.route("/api/briefing/daily")
def api_briefing_daily():
    """
    GET ?tenant_slug=<slug>
    Aggregate morning card: Sentinel aviation status + last-24 h billable pulse.
    Returns a single JSON object ready for a mobile briefing card.
    """
    from nerves.aviation.recency_check import (
        RecencyChecker,
        WARNING_DAYS_REMAINING,
        PRIMARY_TAIL_NUMBER,
    )

    tenant_slug = request.args.get("tenant_slug", "default").strip() or "default"
    tenant_id = _request_tenant_id()
    organization_id = _request_organization_id(default=None)
    user_role = _normalise_user_role(request.args.get("user_role", "Admin"))
    user_id = _normalise_user_id(request.args.get("user_id", default=1, type=int), default=1)
    role_label = _ROLE_DISPLAY_LABEL.get(user_role, _ROLE_DISPLAY_LABEL["Admin"])

    # Short-lived cache: only for root/default briefing context.
    # Tenant-scoped contexts are intentionally uncached so write-after-read checks
    # (e.g., readiness-drop sentinel tests) always observe fresh state.
    _cache_requested = str(request.args.get("cache") or "").strip() in {"1", "true", "yes", "on"}
    _cache_allowed = (
        _cache_requested
        and tenant_id in {_DEFAULT_TENANT_ID, "default"}
        and user_id == 1
        and user_role == "Admin"
        and not organization_id
    )
    _cache_key = _briefing_cache_key(tenant_id, user_id, user_role, organization_id)
    _now_ts = time.monotonic()
    if _cache_allowed:
        _cached = _BRIEFING_CACHE.get(_cache_key)
        if _cached is not None and (_now_ts - _cached[0]) < _BRIEFING_CACHE_TTL_S:
            return jsonify(_cached[1])

    checker = RecencyChecker()
    sentinel = checker.check(tail_number=PRIMARY_TAIL_NUMBER)
    fleet = checker.check_fleet()
    iron_delta = sentinel.latest_reading.iron_delta_ppm if sentinel.latest_reading else None

    aviation_card = {
        "tail_number":         sentinel.tail_number,
        "status":              sentinel.status,
        "colour":              sentinel.colour,
        "days_since_analysis": sentinel.days_since_analysis,
        "days_remaining":      sentinel.days_remaining,
        "warning_threshold":   WARNING_DAYS_REMAINING,
        "iron_delta_ppm":      iron_delta,
        "delta_flag":          sentinel.latest_reading.delta_flag if sentinel.latest_reading else None,
        "last_analysis_date":  sentinel.last_analysis_date,
        "is_warning":          sentinel.is_warning(),
        "is_overdue":          sentinel.is_overdue(),
    }

    fleet_tails = []
    for item in fleet.tails:
        fleet_tails.append(
            {
                "tail_number": item.tail_number,
                "status": item.status,
                "colour": item.colour,
                "days_remaining": item.days_remaining,
                "last_analysis_date": item.last_analysis_date,
                "iron_delta_ppm": item.latest_reading.iron_delta_ppm if item.latest_reading else None,
                "has_data": item.latest_reading is not None,
            }
        )
    active_tail_count = sum(1 for row in fleet_tails if row["has_data"])
    fleet_card = {
        "primary_tail": fleet.primary_tail,
        "configured_tail_count": len(fleet_tails),
        "active_tail_count": active_tail_count,
        "fleet_alert": fleet.fleet_alert,
        "fleet_colour": fleet.fleet_colour,
        "tails": fleet_tails,
    }

    cutoff_24h = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S")
    events_24h = [
        e for e in query_events(tenant_slug, limit=200)
        if e.get("timestamp", "") >= cutoff_24h
    ]
    pulse_count_24h = sum(1 for e in events_24h if e.get("event") == "engagement_pulse")
    shadow_count_24h = sum(1 for e in events_24h if e.get("event") == "shadow:snapshot")
    rate = get_hourly_rate(tenant_slug)
    currency = get_currency(tenant_slug)
    billable_min = pulse_count_24h * PULSE_INTERVAL_MIN
    investment_24h = format_currency(billable_min / 60 * rate, currency)

    billing_card = {
        "tenant_slug": tenant_slug,
        "tenant_name": get_tenant_name(tenant_slug),
        "hourly_rate": rate,
        "currency": currency,
        "pulse_count_24h": pulse_count_24h,
        "shadow_snapshots": shadow_count_24h,
        "shadow_snapshot_today": shadow_count_24h > 0,
        "billable_min_24h": billable_min,
        "investment_24h": investment_24h,
    }

    consumables = _query_mission_consumables(limit=50, user_id=user_id, tenant_id=tenant_id)
    restock_alert = _build_restock_alert(consumables)
    fuel_market = _build_fuel_market_alert()
    mission_forecast = _build_mission_forecast(fuel_market=fuel_market, horizon_days=5)
    pac_pruning = _query_pac_pruning_metrics()
    edge_sync = {
        "status": "ACTIVE",
        "label": "Edge Sync: Active.",
        "is_active": True,
    }
    global_node = _build_global_node_card(tenant_id=tenant_id, limit=3)
    discovery_forecast = _build_discovery_forecast(tenant_id=tenant_id, user_id=user_id, fleet_card=fleet_card)
    briefing_expeditions = _query_expeditions(limit=250, user_id=user_id, tenant_id=tenant_id)
    briefing_specimens = _query_specimen_inventory(limit=250, tenant_id=tenant_id)
    mesh_radar = correlate_global_signals(
        tenant_id=tenant_id,
        user_id=user_id,
        expedition_records=briefing_expeditions,
        specimen_records=briefing_specimens,
    )
    _apply_global_correlation_annotations(
        expeditions=briefing_expeditions,
        specimens=briefing_specimens,
        correlation=mesh_radar,
    )
    auto_restock = auto_restock_check(consumables=consumables, discovery_forecast=discovery_forecast)
    fleet_readiness = _build_fleet_readiness_gauge(
        fuel_market=fuel_market,
        fleet_card=fleet_card,
        aviation_card=aviation_card,
        discovery_forecast=discovery_forecast,
        auto_restock=auto_restock,
    )
    _record_fleet_readiness_snapshot(tenant_id=tenant_id, user_id=user_id, fleet_readiness=fleet_readiness)
    pivot = optimization_pivot(tenant_id=tenant_id, user_id=user_id, fleet_readiness=fleet_readiness)
    intelligence_synthesis = summarize_global_trends(
        tenant_id=tenant_id,
        user_id=user_id,
        signal_limit=10,
    )
    systems_oracle = systems_thinking_overlay(
        tenant_id=tenant_id,
        user_id=user_id,
        discovery_forecast=discovery_forecast,
        fleet_readiness=fleet_readiness,
        optimization_pivot=pivot,
        restock_alert=restock_alert,
        mesh_radar=mesh_radar,
        global_node=global_node,
        organization_id=organization_id,
    )
    maintenance_forecast = predict_component_failure(tenant_id=tenant_id, tail_number=PRIMARY_TAIL_NUMBER)
    fleet_status_badge = maintenance_forecast.get("fleet_status_label") or "Fleet Status: Gold Master."
    profile = _query_user_profile(user_id, tenant_id=tenant_id) or {}
    legacy_state = legacy_heartbeat_check(
        tenant_id=tenant_id,
        tenant_slug=tenant_slug,
        inactivity_days=_LEGACY_INACTIVITY_DAYS,
        mentor_mesh=profile.get("mentor_mesh"),
    )
    network_health = _query_network_health(tenant_id=tenant_id, mentor_mesh=profile.get("mentor_mesh"))
    automation_architect = suggest_workflow_automation(
        tenant_id=tenant_id,
        user_id=user_id,
        horizon_days=30,
        mentor_mesh=profile.get("mentor_mesh"),
    )
    systems_oracle["collective_mesh_bottlenecks"] = automation_architect.get("collective_intelligence") or {}
    home_region = _resolve_general_region(
        location_name=None,
        latitude=None,
        longitude=None,
        home_base_icao=profile.get("home_base_icao"),
    )
    regional_high_risk_signals = _query_regional_high_risk_signals(
        tenant_id=tenant_id,
        general_region=home_region,
        limit=3,
    )
    intelligence_synthesis["home_region"] = home_region
    intelligence_synthesis["regional_high_risk_count"] = len(regional_high_risk_signals)
    intelligence_synthesis["local_action_recommendation"] = _recommend_local_action(
        regional_high_risk_signals=regional_high_risk_signals,
        discovery_forecast=discovery_forecast,
        fleet_readiness=fleet_readiness,
    )

    vault_health = _load_vault_health_status()
    system_status = {
        "status": "DIGITAL_GUARDIAN",
        "label": "System Status: Digital Guardian Active. Ready for the Mass Market.",
    }
    lighthouse_governance = {
        "status": "ABSOLUTE",
        "label": "Lighthouse Governance: Absolute. Audit Ready.",
    }
    _org_id_for_briefing = _normalise_organization_id(organization_id or _DEFAULT_ORGANIZATION_ID)
    billing_preview = _generate_billing_preview(_org_id_for_briefing)
    org_theme = _load_org_theme(_org_id_for_briefing)

    if active_tail_count > 1:
        overall_alert = fleet.fleet_alert
    elif sentinel.is_overdue() or sentinel.status == "UNKNOWN":
        overall_alert = "CRITICAL"
    elif sentinel.is_warning():
        overall_alert = "WARNING"
    else:
        overall_alert = "OK"

    if restock_alert.get("is_active") and overall_alert == "OK":
        overall_alert = "WARNING"
    if fuel_market.get("is_refuel_alert") and overall_alert == "OK":
        overall_alert = "WARNING"
    if discovery_forecast.get("detected") and not auto_restock.get("is_ready_for_mission") and overall_alert == "OK":
        overall_alert = "WARNING"

    narrative_parts: list[str] = []
    if iron_delta is not None:
        direction = "spike" if iron_delta > 0 else "drop"
        fe_current = round(38.0 + iron_delta, 1)
        narrative_parts.append(
            f"{PRIMARY_TAIL_NUMBER} shows a {iron_delta:+.1f} ppm Fe {direction} "
            f"(current: {fe_current} ppm vs 38 ppm baseline)."
        )
    dr = aviation_card["days_remaining"]
    if dr is not None and dr < WARNING_DAYS_REMAINING:
        narrative_parts.append(
            f"Only {dr} days remaining before the 120-day overdue threshold; schedule analysis soon."
        )
    if active_tail_count > 1:
        narrative_parts.append(
            f"Fleet Health is {fleet.fleet_alert} across {active_tail_count} active tails."
        )
    if billing_card["billable_min_24h"] > 0:
        narrative_parts.append(
            f"{billing_card['tenant_name']} logged {billing_card['billable_min_24h']} min "
            f"({billing_card['investment_24h']}) in the last 24 h."
        )
    if restock_alert.get("is_active"):
        low_names = ", ".join(restock_alert.get("low_item_labels") or [])
        narrative_parts.append(f"Restock needed: {low_names}.")
    if fuel_market.get("is_refuel_alert"):
        narrative_parts.append(str(fuel_market.get("label") or "Refuel alert active."))
    if mission_forecast.get("suggested_date"):
        narrative_parts.append(
            f"Suggested launch window: {mission_forecast.get('suggested_date')} "
            f"({mission_forecast.get('breakdown_summary')})."
        )
    narrative_parts.append(
        f"Pruned Today: {int(pac_pruning.get('pruned_today_count') or 0)} item(s), "
        f"Billable Pulse ${float(pac_pruning.get('pruned_today_billable_pulse') or 0.0):.2f}, "
        f"Drift {float(pac_pruning.get('recorded_drift_pct') or 0.0):.1f}%."
    )
    narrative_parts.append(str(pac_pruning.get("professional_ecology_label") or "Professional Ecology: Monitoring."))
    narrative_parts.append(str(edge_sync.get("label") or "Edge Sync: Active."))
    narrative_parts.append(str(global_node.get("label") or "Global Pulse: Connected."))
    narrative_parts.append(str(global_node.get("mesh_integrity_label") or "Mesh Integrity: 100%."))
    narrative_parts.append(str(mesh_radar.get("label") or "Mesh Radar: Active."))
    narrative_parts.append(str(network_health.get("network_health_label") or "Network Health: 100%."))
    narrative_parts.append(str(network_health.get("status_label") or "Network Status: Dormant."))
    narrative_parts.append(str(legacy_state.get("label") or "Lighthouse Status: Primary Active. Legacy Protocol Standing By."))
    narrative_parts.append(str(system_status.get("label") or "System Status: Digital Guardian Active. Ready for the Mass Market."))
    narrative_parts.append(str(lighthouse_governance.get("label") or "Lighthouse Governance: Absolute. Audit Ready."))
    narrative_parts.append(str(billing_preview.get("label") or "Billing Preview: —"))
    narrative_parts.append(str(automation_architect.get("architect_mode_label") or "Architect Mode: Enabled. Suggestions Pending."))
    narrative_parts.append(str(automation_architect.get("proposed_automation_label") or "Proposed Automation: Awaiting recurring drift signatures."))
    narrative_parts.append(str(automation_architect.get("proposal_message") or "Collecting 30-day drift cadence before recommending a targeted pruner."))
    narrative_parts.append(
        str(
            ((automation_architect.get("collective_intelligence") or {}).get("label"))
            or "Mesh Bottlenecks: Insufficient mesh drift signatures."
        )
    )
    narrative_parts.append(str(intelligence_synthesis.get("label") or "Intelligence Synthesis: Nominal."))
    narrative_parts.append(str(intelligence_synthesis.get("global_pulse_summary") or "Global Pulse synthesis unavailable."))
    narrative_parts.append(str(intelligence_synthesis.get("local_action_recommendation") or "Local Action: continue mission monitoring."))
    narrative_parts.append(str(systems_oracle.get("label") or "Systems Oracle: Standby."))
    narrative_parts.append(str(systems_oracle.get("philosophical_synthesis") or "Philosophical Synthesis unavailable."))
    narrative_parts.append(str(maintenance_forecast.get("label") or "Predictive Maintenance: Active."))
    narrative_parts.append(str(fleet_status_badge))
    if maintenance_forecast.get("schedule_service_required"):
        due_components = ", ".join(maintenance_forecast.get("schedule_service_components") or []) or "critical components"
        narrative_parts.append(f"Schedule Service: immediate booking required for {due_components}.")
    narrative_parts.append(str(discovery_forecast.get("label") or "Discovery Forecast: Monitoring."))
    if discovery_forecast.get("route"):
        narrative_parts.append(str((discovery_forecast.get("route") or {}).get("route_label") or "Mission Route ready."))
    if auto_restock.get("detected_hotspot"):
        if auto_restock.get("is_ready_for_mission"):
            narrative_parts.append("Ready for Mission: consumables meet predicted high-yield route needs.")
        else:
            shortfalls = ", ".join(auto_restock.get("shortfall_items") or []) or "consumables"
            narrative_parts.append(f"Resupply Required: {shortfalls} below predicted mission needs.")
    narrative_parts.append(str(fleet_readiness.get("label") or "Fleet Readiness: 0% (Prep Required)."))
    narrative_parts.append(str(pivot.get("label") or "Strategy: Monitoring."))
    narrative_parts.append(str(pivot.get("rationale") or "Yield Velocity > Operational Cost."))
    if global_node.get("signals"):
        narrative_parts.append(str((global_node.get("signals") or [])[0].get("message") or "Global discovery feed updated."))
    if vault_health.get("status") == "WARNING":
        warning_text = "; ".join(str(x) for x in (vault_health.get("warnings") or [])[:2])
        warning_msg = warning_text if warning_text else "external backup drive requires attention"
        narrative_parts.append(f"Vault health warning: {warning_msg}.")

    cutoff_7d = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S")
    recent_expeditions_count = 0
    tenant_db_path = _aviation_db_path(tenant_id)
    if tenant_db_path.exists():
        try:
            _ec = sqlite3.connect(str(tenant_db_path))
            try:
                _ensure_expeditions_table(_ec)
                recent_expeditions_count = _ec.execute(
                    "SELECT COUNT(*) FROM rockhounding_expeditions WHERE timestamp >= ? AND user_id = ?",
                    (cutoff_7d, user_id),
                ).fetchone()[0]
            finally:
                _ec.close()
        except Exception:
            pass

    specimen_alert = _query_recent_high_yield_specimen_alert(window_hours=72, tenant_id=tenant_id)
    high_yield_specimen_alert = {
        "is_active": bool(specimen_alert),
        "window_hours": 72,
    }
    if specimen_alert:
        high_yield_specimen_alert.update(specimen_alert)
        specimen_site = specimen_alert.get("location_name") or "field site"
        specimen_flight = (specimen_alert.get("transport_flight_suggestion") or {}).get("flight_id")
        flight_note = f" via {specimen_flight}" if specimen_flight else ""
        narrative_parts.append(
            f"High-yield specimen alert: 5-star find logged at {specimen_site}{flight_note}."
        )

    lead_analyst_payload = None
    operations_director_payload = None
    associate_payload = None
    if user_role == "Lead Analyst":
        lead_analyst_payload = {
            "raw_telemetry": _query_marine_telemetry(limit=25),
            "raw_drift_logs": query_events(tenant_slug, limit=200),
        }
    elif user_role == "Operations Director":
        org_observations = _query_expeditions(limit=25, user_id=user_id, tenant_id=tenant_id)
        operations_director_payload = {
            "title": "Org Telemetry",
            "organization_id": organization_id or "legacy",
            "tenant_id": tenant_id,
            "observations_count": len(org_observations),
            "telemetry": org_observations,
        }
        narrative_parts.append(
            f"Org telemetry scope: {len(org_observations)} observation(s) within organization {organization_id or 'legacy'}."
        )
    elif user_role == "Associate":
        associate_payload = {
            "title": "Expedition Discovery",
            "recent_field_observations": recent_expeditions_count,
            "highlight": (
                f"Recent 5-star find near {high_yield_specimen_alert.get('location_name') or 'the field route'}."
                if high_yield_specimen_alert.get("is_active")
                else "No major discoveries recorded in the last 72 hours."
            ),
        }
        narrative_parts = [
            "Expedition Discovery summary ready.",
            f"{recent_expeditions_count} field observations logged this week.",
            str(associate_payload["highlight"]),
            str(global_node.get("label") or "Global Pulse: Connected."),
            str(global_node.get("mesh_integrity_label") or "Mesh Integrity: 100%."),
            str(mesh_radar.get("label") or "Mesh Radar: Active."),
            str(network_health.get("network_health_label") or "Network Health: 100%."),
            str(network_health.get("status_label") or "Network Status: Dormant."),
            str(legacy_state.get("label") or "Lighthouse Status: Primary Active. Legacy Protocol Standing By."),
            str(system_status.get("label") or "System Status: Digital Guardian Active. Ready for the Mass Market."),
            str(lighthouse_governance.get("label") or "Lighthouse Governance: Absolute. Audit Ready."),
            str(billing_preview.get("label") or "Billing Preview: —"),
            str(automation_architect.get("architect_mode_label") or "Architect Mode: Enabled. Suggestions Pending."),
            str(automation_architect.get("proposed_automation_label") or "Proposed Automation: Awaiting recurring drift signatures."),
            str(intelligence_synthesis.get("label") or "Intelligence Synthesis: Nominal."),
            str(intelligence_synthesis.get("global_pulse_summary") or "Global Pulse synthesis unavailable."),
            str(intelligence_synthesis.get("local_action_recommendation") or "Local Action: continue mission monitoring."),
            str(systems_oracle.get("label") or "Systems Oracle: Standby."),
            str(systems_oracle.get("systems_reflection") or "Systems-Thinking Reflection unavailable."),
            str(maintenance_forecast.get("label") or "Predictive Maintenance: Active."),
            str(fleet_status_badge),
            str(discovery_forecast.get("label") or "Discovery Forecast: Monitoring."),
            str(fleet_readiness.get("label") or "Fleet Readiness: 0% (Prep Required)."),
            str(pivot.get("label") or "Strategy: Monitoring."),
        ]

    narrative = "  ".join(narrative_parts) if narrative_parts else "All systems nominal."

    _briefing_payload = {
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "overall_alert": overall_alert,
            "aviation": aviation_card,
            "role": {
                "value": user_role,
                "label": role_label,
                "user_id": user_id,
            },
            "tenant": {
                "id": tenant_id,
                "label": f"Tenant ID: {tenant_id}",
            },
            "organization": {
                "id": organization_id or "legacy",
                "label": f"Organization ID: {organization_id or 'legacy'}",
            },
            "fleet": fleet_card,
            "billing": billing_card,
            "consumables": consumables,
            "restock_alert": restock_alert,
            "auto_restock": auto_restock,
            "fuel_market": fuel_market,
            "fleet_readiness": fleet_readiness,
            "optimization_pivot": pivot,
            "edge_sync": edge_sync,
            "global_node": global_node,
            "mesh_radar": {
                "status": mesh_radar.get("status") or "ACTIVE",
                "label": mesh_radar.get("label") or "Mesh Radar: Active.",
                "signal_count": len(mesh_radar.get("mesh_signals") or []),
            },
            "system_longevity": legacy_state,
            "system_status": system_status,
            "lighthouse_governance": lighthouse_governance,
            "billing_preview": billing_preview,
            "org_theme": org_theme,
            "network_health": network_health,
            "automation_architect": automation_architect,
            "intelligence_synthesis": intelligence_synthesis,
            "systems_thinking_overlay": systems_oracle,
            "regional_high_risk_signals": regional_high_risk_signals,
            "maintenance_forecast": maintenance_forecast,
            "fleet_status_badge": fleet_status_badge,
            "global_feed": global_node.get("signals", []),
            "discovery_forecast": discovery_forecast,
            "mission_forecast": mission_forecast,
            "pac_pruning": pac_pruning,
            "lead_analyst_payload": lead_analyst_payload,
            "operations_director_payload": operations_director_payload,
            "associate_summary": associate_payload,
            "scientist_payload": lead_analyst_payload,
            "org_admin_payload": operations_director_payload,
            "tourist_summary": associate_payload,
            "vault_health": vault_health,
            "narrative": narrative,
            "recent_expeditions_count": recent_expeditions_count,
            "high_yield_specimen_alert": high_yield_specimen_alert,
        }
    if _cache_allowed:
        _BRIEFING_CACHE[_cache_key] = (time.monotonic(), _briefing_payload)
    return jsonify(_briefing_payload)


@app.route("/api/systems-oracle/external-philosophy", methods=["GET", "POST"])
def api_systems_oracle_external_philosophy():
    tenant_id = _request_tenant_id()
    organization_id = _request_organization_id(default=None)

    if request.method == "GET":
        payload = _load_external_philosophy(
            tenant_id=tenant_id,
            organization_id=organization_id,
        )
        return jsonify(
            {
                "tenant_id": tenant_id,
                "organization_id": organization_id or "legacy",
                "external_philosophy": payload,
            }
        )

    data = request.get_json(silent=True) or {}
    title = str(data.get("title") or "Corporate Values").strip() or "Corporate Values"

    values: list[str] = []
    raw_values = data.get("values")
    if isinstance(raw_values, list):
        values = [str(item or "").strip()[:220] for item in raw_values if str(item or "").strip()]
    else:
        values_text = str(data.get("values_text") or "").strip()
        if values_text:
            values = [line.strip()[:220] for line in values_text.splitlines() if line.strip()]

    if not values:
        return jsonify({"error": "values or values_text is required"}), 400

    weight = _safe_float(data.get("weight"))
    if weight is None:
        weight = 0.35
    weight = max(0.05, min(float(weight), 0.95))

    doc = {
        "title": title[:120],
        "values": values[:20],
        "weight": round(weight, 2),
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": str(data.get("source") or "api").strip() or "api",
    }

    output_path = _external_philosophy_path(tenant_id=tenant_id, organization_id=organization_id)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(doc, indent=2), encoding="utf-8")

    # Log philosophy update to immutable governance ledger
    actor = str(request.args.get("actor") or (request.get_json(silent=True) or {}).get("actor") or "system").strip()[:64] or "system"
    _govern_log(
        org_id=organization_id or "legacy",
        actor=actor,
        action_type="philosophy_update",
        payload={"tenant_id": tenant_id, "title": doc["title"], "values_count": len(doc["values"]), "weight": doc["weight"]},
    )

    payload = _load_external_philosophy(
        tenant_id=tenant_id,
        organization_id=organization_id,
    )
    return jsonify(
        {
            "status": "saved",
            "tenant_id": tenant_id,
            "organization_id": organization_id or "legacy",
            "external_philosophy": payload,
        }
    ), 201


@app.route("/api/admin/governance/log", methods=["POST"])
def api_admin_governance_log():
    """
    Write an explicit governance record.  Restricted to System-Admin (Joshua/Hutch).
    POST JSON: { actor, org_id, action_type, payload }
    """
    data = request.get_json(silent=True) or {}
    actor = str(data.get("actor") or "").strip().lower()
    if actor not in _GOVERNANCE_SYSTEM_ADMIN_USERNAMES:
        return jsonify({"error": "forbidden", "detail": "Governance write requires System-Admin authority."}), 403

    org_id = _normalise_organization_id(str(data.get("org_id") or _DEFAULT_ORGANIZATION_ID))
    action_type = str(data.get("action_type") or "manual_entry").strip()[:64] or "manual_entry"
    payload = data.get("payload") or {}
    if not isinstance(payload, dict):
        payload = {"raw": str(payload)}

    record = _govern_log(org_id=org_id, actor=actor, action_type=action_type, payload=payload)
    return jsonify({"status": "logged", "record": record}), 201


@app.route("/api/admin/governance/audit", methods=["GET"])
def api_admin_governance_audit():
    """
    Read governance ledger entries (read-only for all callers).
    GET ?org_id=<id>&limit=50
    """
    org_id_filter = request.args.get("org_id", "").strip()
    limit = min(max(request.args.get("limit", default=50, type=int) or 50, 1), 500)
    try:
        entries = [
            {
                "event_id": entry.get("event_id"),
                "timestamp": entry.get("timestamp"),
                "org_id": entry.get("org_id"),
                "actor": entry.get("actor"),
                "action_type": entry.get("action_type"),
                "checksum": entry.get("checksum"),
                "rationale_hash": (entry.get("payload") or {}).get("rationale_hash"),
                "external_philosophy_version": (entry.get("payload") or {}).get("external_philosophy_version"),
                "telemetry_window": (entry.get("payload") or {}).get("telemetry_window"),
            }
            for entry in _query_governance_entries(org_id=org_id_filter or None, limit=limit)
        ]
        return jsonify({"entries": entries, "count": len(entries)})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/admin/theme", methods=["GET", "POST"])
def api_admin_theme():
    """
    GET  ?org_id=<id>   — retrieve current theme for an org.
    POST JSON { org_id, primary_color, secondary_color, logo_url, actor } — save theme.
    """
    if request.method == "GET":
        org_id = _normalise_organization_id(
            request.args.get("org_id") or _request_organization_id(default=_DEFAULT_ORGANIZATION_ID) or _DEFAULT_ORGANIZATION_ID
        )
        theme = _load_org_theme(org_id)
        return jsonify({"org_id": org_id, "theme": theme})

    data = request.get_json(silent=True) or {}
    org_id = _normalise_organization_id(
        str(data.get("org_id") or _request_organization_id(default=_DEFAULT_ORGANIZATION_ID) or _DEFAULT_ORGANIZATION_ID)
    )
    primary_color = str(data.get("primary_color") or "#0f766e").strip()[:32]
    secondary_color = str(data.get("secondary_color") or "#065F46").strip()[:32]
    logo_url = str(data.get("logo_url") or "").strip()[:512] or None
    actor = str(data.get("actor") or "system").strip()[:64] or "system"

    # Validate hex-colour format (allow #RGB and #RRGGBB)
    _hex_re = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
    if not _hex_re.match(primary_color):
        return jsonify({"error": "primary_color must be a valid hex colour (e.g. #0f766e)"}), 400
    if not _hex_re.match(secondary_color):
        return jsonify({"error": "secondary_color must be a valid hex colour"}), 400

    saved = _save_org_theme(
        org_id,
        {"primary_color": primary_color, "secondary_color": secondary_color, "logo_url": logo_url},
        actor=actor,
    )
    return jsonify({"status": "saved", "org_id": org_id, "theme": saved}), 201


@app.route("/api/marine/observations")
def api_marine_observations():
    dataset = request.args.get("dataset", "").strip()
    station_id = request.args.get("station_id", "").strip()
    limit = request.args.get("limit", default=25, type=int) or 25
    return jsonify(
        _query_marine_observations(
            dataset=dataset,
            station_id=station_id,
            limit=limit,
        )
    )


@app.route("/api/marine/telemetry")
def api_marine_telemetry():
    limit = request.args.get("limit", default=10, type=int) or 10
    return jsonify(_query_marine_telemetry(limit=limit))


@app.route("/api/marine/map-points")
def api_marine_map_points():
    dataset = request.args.get("dataset", "").strip()
    station_id = request.args.get("station_id", "").strip()
    limit = request.args.get("limit", default=100, type=int) or 100
    return jsonify(
        _query_marine_observations(
            dataset=dataset,
            station_id=station_id,
            limit=max(1, min(limit, 250)),
        )
    )


@app.route("/api/marine/station-series")
def api_marine_station_series():
    station_id = request.args.get("station_id", "").strip()
    if not station_id:
        return jsonify({"error": "station_id is required"}), 400

    dataset = request.args.get("dataset", "").strip()
    limit = request.args.get("limit", default=100, type=int) or 100
    return jsonify(
        _query_station_series(
            station_id=station_id,
            dataset=dataset,
            limit=limit,
        )
    )


@app.route("/api/marine/station-context")
def api_marine_station_context():
    dataset = request.args.get("dataset", "").strip()
    station_id = request.args.get("station_id", "").strip()
    limit = request.args.get("limit", default=100, type=int) or 100
    return jsonify(_query_station_context(dataset=dataset, station_id=station_id, limit=limit))


@app.route("/api/marine/reef-context")
def api_marine_reef_context():
    dataset = request.args.get("dataset", "").strip()
    station_id = request.args.get("station_id", "").strip()
    limit = request.args.get("limit", default=100, type=int) or 100
    return jsonify(_query_reef_context(dataset=dataset, station_id=station_id, limit=limit))


@app.route("/api/marine/reef-alerts")
def api_marine_reef_alerts():
    dataset = request.args.get("dataset", "").strip()
    station_id = request.args.get("station_id", "").strip()
    limit = request.args.get("limit", default=100, type=int) or 100
    minimum_priority = request.args.get("minimum_priority", "").strip()
    return jsonify(
        _query_reef_alerts(
            dataset=dataset,
            station_id=station_id,
            limit=limit,
            minimum_priority=minimum_priority,
        )
    )


@app.route("/api/marine/export")
def api_marine_export():
    dataset = request.args.get("dataset", "").strip()
    station_id = request.args.get("station_id", "").strip()
    limit = request.args.get("limit", default=100, type=int) or 100
    minimum_priority = request.args.get("minimum_priority", "").strip()
    return jsonify(
        _build_marine_export(
            dataset=dataset,
            station_id=station_id,
            limit=limit,
            minimum_priority=minimum_priority,
        )
    )


@app.route("/api/marine/snapshots/latest")
def api_marine_snapshot_latest():
    latest_snapshot = _load_latest_snapshot()
    if latest_snapshot is None:
        return jsonify(
            {
                "ok": True,
                "snapshot": None,
                "note": "No marine snapshot has been generated yet.",
            }
        )
    return jsonify({"ok": True, "snapshot": latest_snapshot})


@app.route("/api/marine/alerts/latest-event")
def api_marine_alert_latest_event():
    latest_alert_event = _load_latest_alert_event()
    if latest_alert_event is None:
        return jsonify(
            {
                "ok": True,
                "event": None,
                "note": "No marine alert event has been generated yet.",
            }
        )
    return jsonify({"ok": True, "event": latest_alert_event})


@app.route("/api/marine/investigations", methods=["GET", "POST"])
def api_marine_investigations():
    if request.method == "GET":
        limit = request.args.get("limit", default=10, type=int) or 10
        return jsonify(_query_recent_investigations(limit=limit))

    data = request.get_json(force=True, silent=True) or request.form.to_dict()
    name = str(data.get("name", "")).strip()
    path = str(data.get("path", "")).strip()
    if not name:
        return jsonify({"error": "name is required"}), 400
    if not path:
        return jsonify({"error": "path is required"}), 400

    manifest = _create_investigation_manifest(
        name=name,
        scope_type=str(data.get("scope_type", "marine")).strip() or "marine",
        dataset=str(data.get("dataset", "")).strip(),
        station_id=str(data.get("station_id", "")).strip(),
        limit=int(data.get("limit", 100) or 100),
        path=path,
        query_string=str(data.get("query_string", "")).strip(),
    )
    return jsonify(manifest), 201


@app.route("/api/marine/investigations/<int:manifest_id>")
def api_marine_investigation_detail(manifest_id: int):
    manifest = _get_investigation(manifest_id)
    if manifest is None:
        return jsonify({"error": "manifest not found"}), 404
    return jsonify(manifest)


@app.route("/marine/investigations/<int:manifest_id>/open")
def marine_investigation_open(manifest_id: int):
    manifest = _get_investigation(manifest_id)
    if manifest is None:
        abort(404)
    return redirect(manifest["open_url"])


# ── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    socketio.run(app, debug=True, port=5050)
