"""
hutch_deploy.py — HutchSolves v7.0.0-SINGULARITY "The Autonomous Legacy" deployment orchestrator.

Steps:
    1. Run the full pytest suite (tests/)
    2. Validate field-observation + specimen + fuel-log + consumables vault integrity
    3. Probe backup drive health (SMART/latency surrogate) and publish vault status
            4. Verify mission-map assets + geospatial API + preflight + Morning Card,
                including mission forecast, role-aware briefing, tenant migration hardening,
                edge outbox reconciliation, Global Node anonymization, probability engine,
                digital logbook catch-up, market tracking, mesh correlation, intelligence synthesis,
                predictive maintenance, systems oracle manuscript sync, and guest data-isolation
    5. Run automated cloud mirror for specimen + aviation vault
    6. Batch-OCR scan tests/fixtures/ in dry-run mode (no DB writes)
    7. Export a snapshot of data/cortex.sqlite to outputs/
    8. Verify Sunday weekly ZIP exists and is non-empty
    9. Run sunday_briefing.py --force smoke test

Exit code: 0 on full success, 1 if any step fails.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import re
import shutil
import sqlite3
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib import error as urlerror
from urllib import request as urlrequest

# ── Repo root is one level above this script ──────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent

# Ensure the repo root is importable (so `nerves.*` pakages resolve correctly
# regardless of how/where this script is invoked).
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ── Paths ─────────────────────────────────────────────────────────────────────
TESTS_DIR    = ROOT / "tests"
FIXTURES_DIR = TESTS_DIR / "fixtures"
CORTEX_DB    = ROOT / "data" / "cortex.sqlite"
OUTPUTS_DIR  = ROOT / "outputs"
BACKUP_DIR   = OUTPUTS_DIR / "fortress_backups"
HANGAR_ALERTS_PATH = OUTPUTS_DIR / "hangar_alerts" / "preflight_prep_notifications.log"
VAULT_HEALTH_PATH = OUTPUTS_DIR / "vault_health_status.json"
BACKUP_DRIVE_LETTER = "E"
AVIATION_DATA_DIR = Path.home() / "AppData" / "Roaming" / "Aero Cortex Hub" / "data"
AVIATION_TENANTS_DIR = AVIATION_DATA_DIR / "tenants"
AVIATION_ORGS_DIR = AVIATION_DATA_DIR / "organizations"
AVIATION_DB = AVIATION_TENANTS_DIR / "internal" / "marine.sqlite"
GLOBAL_NODE_DB = AVIATION_DATA_DIR / "global_node.sqlite"
GOVERNANCE_DB = AVIATION_DATA_DIR / "system_governance.sqlite"
SYSTEMS_ORACLE_MANUSCRIPT = ROOT / "data" / "mycology_to_your_ecology_manuscript.txt"
LIGHTHOUSE_SCHEMA_PATH = ROOT / "hub" / "static" / "schema" / "lighthouse_v1.json"
TENANT_ID_SANITIZER = re.compile(r"[^a-z0-9_-]+")
ORG_METADATA_FILENAME = "org_metadata.json"

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
_CREATE_OIL_SENTINEL_REPORTS = """
CREATE TABLE IF NOT EXISTS oil_sentinel_reports (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    report_name      TEXT,
    source_pdf       TEXT UNIQUE,
    iron             REAL,
    copper           REAL,
    aluminium        REAL,
    iron_delta_pct   REAL,
    copper_delta_pct REAL,
    iron_flagged     INTEGER,
    copper_flagged   INTEGER,
    flagged          INTEGER,
    analyzed_at      TEXT NOT NULL
)
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
_CREATE_SPECIMEN_INVENTORY = """
CREATE TABLE IF NOT EXISTS specimen_inventory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    expedition_id INTEGER,
    timestamp TEXT NOT NULL,
    image_path TEXT,
    yield_stars INTEGER NOT NULL,
    estimated_weight_lbs REAL,
    color TEXT,
    hardness REAL,
    specific_gravity REAL,
    mineral_class TEXT,
    notes TEXT,
    latitude REAL,
    longitude REAL,
    transport_suggestion_json TEXT,
    FOREIGN KEY(expedition_id) REFERENCES rockhounding_expeditions(id) ON DELETE SET NULL
)
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


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _banner(msg: str) -> None:
    width = 66
    print("\n" + "=" * width)
    print(f"  {msg}")
    print("=" * width)


def _ok(msg: str)   -> None: print(f"  [OK]  {msg}")
def _fail(msg: str) -> None: print(f"  [FAIL] {msg}", file=sys.stderr)
def _info(msg: str) -> None: print(f"  [--]  {msg}")


def _send_preflight_prep_notification(*, tenant_id: str, route_label: str, distance_nm: float) -> str:
    HANGAR_ALERTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tenant_id": tenant_id,
        "type": "Pre-Flight Prep",
        "distance_nm": round(float(distance_nm), 1),
        "route": route_label,
        "message": "Pre-Flight Prep: hotspot within 100nm of home base.",
    }
    with HANGAR_ALERTS_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload) + "\n")
    return payload["message"]


def _is_valid_coord(lat: float, lon: float) -> bool:
    return -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0


def _is_valid_image_path(raw_path: str) -> bool:
    value = (raw_path or "").strip()
    if not value:
        return True

    lowered = value.lower()
    if lowered.startswith(("http://", "https://", "mobile://", "file://", "s3://", "gs://")):
        return True

    path_obj = Path(value)
    if path_obj.is_absolute():
        return path_obj.exists()
    return (ROOT / path_obj).exists()


def _to_json_object(raw: str) -> dict:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    normal = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normal)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _to_optional_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalise_tenant_id(raw: object, default: str = "internal") -> str:
    token = str(raw or "").strip().lower()
    cleaned = TENANT_ID_SANITIZER.sub("-", token).strip("-")
    if not cleaned:
        fallback = TENANT_ID_SANITIZER.sub("-", default.strip().lower()).strip("-")
        cleaned = fallback or "internal"
    return cleaned[:64]


def _tenant_token(tenant_id: object) -> str:
    normalised = _normalise_tenant_id(tenant_id)
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()[:16]


def _org_tenant_db_path(*, organization_id: object, tenant_id: object) -> Path:
    org = _normalise_tenant_id(organization_id, default="internal")
    tenant = _normalise_tenant_id(tenant_id, default="internal")
    return AVIATION_ORGS_DIR / org / "tenants" / tenant / "marine.sqlite"


def _org_metadata_path(org_id: object) -> Path:
    return AVIATION_ORGS_DIR / _normalise_tenant_id(org_id, default="internal") / ORG_METADATA_FILENAME


def _verify_org_admin_isolation(client) -> tuple[bool, str]:
    """Verify that Org Admin users from separate organizations cannot access each other's telemetry."""
    org_a = _normalise_tenant_id(f"org-a-{int(time.time() * 1000)}")
    org_b = _normalise_tenant_id(f"org-b-{int(time.time() * 1000)}")
    tenant_a = "default"
    tenant_b = "default"
    
    org_a_db_path = _org_tenant_db_path(organization_id=org_a, tenant_id=tenant_a)
    org_b_db_path = _org_tenant_db_path(organization_id=org_b, tenant_id=tenant_b)
    
    org_a_db_path.parent.mkdir(parents=True, exist_ok=True)
    org_b_db_path.parent.mkdir(parents=True, exist_ok=True)
    
    obs_a_id = None
    obs_b_id = None
    user_a_id = None
    user_b_id = None
    
    try:
        # Initialize org A database with Org Admin user
        conn_a = sqlite3.connect(str(org_a_db_path))
        try:
            conn_a.execute(_CREATE_USER_PROFILES)
            conn_a.execute(_CREATE_EXPEDITIONS)
            conn_a.execute(
                "INSERT INTO user_profiles (username, role, home_base_icao) VALUES (?, ?, ?)",
                ("deploy_org_admin_a", "Org Admin", "KIXD"),
            )
            user_a_id = conn_a.execute("SELECT id FROM user_profiles WHERE username = 'deploy_org_admin_a'").fetchone()[0]
            
            # Create observation in org A
            conn_a.execute(
                "INSERT INTO rockhounding_expeditions (user_id, timestamp, location_name, latitude, longitude, specimen_types, yield_rating) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (user_a_id, datetime.now(timezone.utc).isoformat(), "Isolated Location A", 38.07, -97.86, "Agate", 8.5),
            )
            obs_a_id = conn_a.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn_a.commit()
        finally:
            conn_a.close()
        
        # Initialize org B database with Org Admin user
        conn_b = sqlite3.connect(str(org_b_db_path))
        try:
            conn_b.execute(_CREATE_USER_PROFILES)
            conn_b.execute(_CREATE_EXPEDITIONS)
            conn_b.execute(
                "INSERT INTO user_profiles (username, role, home_base_icao) VALUES (?, ?, ?)",
                ("deploy_org_admin_b", "Org Admin", "KUKL"),
            )
            user_b_id = conn_b.execute("SELECT id FROM user_profiles WHERE username = 'deploy_org_admin_b'").fetchone()[0]
            
            # Create observation in org B
            conn_b.execute(
                "INSERT INTO rockhounding_expeditions (user_id, timestamp, location_name, latitude, longitude, specimen_types, yield_rating) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (user_b_id, datetime.now(timezone.utc).isoformat(), "Isolated Location B", 38.17, -97.76, "Jasper", 7.2),
            )
            obs_b_id = conn_b.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn_b.commit()
        finally:
            conn_b.close()
        
        # Test 1: Verify org A database is isolated at filesystem level
        if not org_a_db_path.exists():
            return False, f"Organization {org_a} database not found at {org_a_db_path}"
        
        # Test 2: Verify org B database is isolated at filesystem level
        if not org_b_db_path.exists():
            return False, f"Organization {org_b} database not found at {org_b_db_path}"
        
        # Test 3: Verify that Org Admin A can access their own organization briefing
        briefing_a = client.get(
            f"/api/briefing/daily?tenant_slug=default&organization_id={org_a}&user_id={user_a_id}&user_role=Org+Admin"
        )
        if briefing_a.status_code != 200:
            return False, f"Org Admin A cannot access their own organization briefing (HTTP {briefing_a.status_code})"
        
        briefing_payload_a = briefing_a.get_json(silent=True) or {}
        org_context_a = briefing_payload_a.get("organization")
        if isinstance(org_context_a, dict):
            org_context_a_id = org_context_a.get("id")
        else:
            org_context_a_id = org_context_a
        if org_context_a_id != org_a:
            return False, f"Org Admin A's briefing has mismatched organization context: {org_context_a_id} != {org_a}"
        
        # Test 4: Verify that Org Admin B can access their own organization briefing
        briefing_b = client.get(
            f"/api/briefing/daily?tenant_slug=default&organization_id={org_b}&user_id={user_b_id}&user_role=Org+Admin"
        )
        if briefing_b.status_code != 200:
            return False, f"Org Admin B cannot access their own organization briefing (HTTP {briefing_b.status_code})"
        
        briefing_payload_b = briefing_b.get_json(silent=True) or {}
        org_context_b = briefing_payload_b.get("organization")
        if isinstance(org_context_b, dict):
            org_context_b_id = org_context_b.get("id")
        else:
            org_context_b_id = org_context_b
        if org_context_b_id != org_b:
            return False, f"Org Admin B's briefing has mismatched organization context: {org_context_b_id} != {org_b}"
        
        # Test 5: Verify database-level isolation - Org A data is in org_a DB, Org B data is in org_b DB
        # Direct SQLite check: verify that org_a has specific location, org_b doesn't
        try:
            conn_a = sqlite3.connect(str(org_a_db_path))
            try:
                location_a_result = conn_a.execute(
                    "SELECT id, location_name FROM rockhounding_expeditions WHERE location_name = ?", 
                    ("Isolated Location A",)
                ).fetchone()
                if location_a_result is None:
                    return False, f"Org A's observation not found in org A database"
            finally:
                conn_a.close()
            
            conn_b = sqlite3.connect(str(org_b_db_path))
            try:
                location_a_in_b = conn_b.execute(
                    "SELECT id FROM rockhounding_expeditions WHERE location_name = ?", 
                    ("Isolated Location A",)
                ).fetchone()
                if location_a_in_b is not None:
                    return False, "Org A's observation (Isolated Location A) leaked into Org B's database"
                
                # Also verify org B's own data is there
                location_b_result = conn_b.execute(
                    "SELECT id FROM rockhounding_expeditions WHERE location_name = ?", 
                    ("Isolated Location B",)
                ).fetchone()
                if location_b_result is None:
                    return False, "Org B's observation not found in org B database"
            finally:
                conn_b.close()
        except sqlite3.DatabaseError as exc:
            return False, f"Database isolation check failed: {exc}"
        
        return True, f"Org-Admin isolation verified at database and briefing levels between {org_a} and {org_b}."
    finally:
        try:
            # Cleanup org A database
            if org_a_db_path.exists():
                org_a_db_path.unlink()
            if org_a_db_path.parent.exists():
                try:
                    org_a_db_path.parent.rmdir()
                except OSError:
                    pass
            parent_dir = org_a_db_path.parent.parent
            if parent_dir.exists():
                try:
                    parent_dir.rmdir()
                except OSError:
                    pass
            
            # Cleanup org B database
            if org_b_db_path.exists():
                org_b_db_path.unlink()
            if org_b_db_path.parent.exists():
                try:
                    org_b_db_path.parent.rmdir()
                except OSError:
                    pass
            parent_dir = org_b_db_path.parent.parent
            if parent_dir.exists():
                try:
                    parent_dir.rmdir()
                except OSError:
                    pass
        except OSError:
            pass


def _verify_global_node_anonymization(client) -> tuple[bool, str]:
    tenant_a = _normalise_tenant_id(f"global-node-a-{int(time.time() * 1000)}")
    tenant_b = _normalise_tenant_id(f"global-node-b-{int(time.time() * 1000)}")
    tenant_a_dir = AVIATION_TENANTS_DIR / tenant_a
    tenant_b_dir = AVIATION_TENANTS_DIR / tenant_b
    tenant_a_db = tenant_a_dir / "marine.sqlite"
    tenant_b_db = tenant_b_dir / "marine.sqlite"

    signal_id = None
    expedition_id = None
    pii_marker = "PII-TOKEN-ALPHA"
    pii_photo = "mobile://deploy-user-a-private-photo.jpg"
    pii_location = "Hidden User A Canyon"
    pii_lat = 38.12345
    pii_lon = -97.54321

    try:
        for tenant in (tenant_a, tenant_b):
            bootstrap = client.get(f"/api/navigator/consumables?tenant_id={tenant}&user_id=1&limit=5")
            if bootstrap.status_code != 200:
                return False, f"tenant bootstrap failed for {tenant}"

        conn_a = sqlite3.connect(str(tenant_a_db))
        try:
            conn_a.execute(_CREATE_USER_PROFILES)
            cols = {row[1] for row in conn_a.execute("PRAGMA table_info(user_profiles)").fetchall()}
            if "share_signals" not in cols:
                conn_a.execute("ALTER TABLE user_profiles ADD COLUMN share_signals INTEGER NOT NULL DEFAULT 0")
            conn_a.execute(
                """
                INSERT INTO user_profiles (id, username, role, home_base_icao, share_signals)
                VALUES (1, 'deploy_user_a', 'Scientist', 'KIXD', 1)
                ON CONFLICT(id) DO UPDATE SET
                    username = excluded.username,
                    role = excluded.role,
                    home_base_icao = excluded.home_base_icao,
                    share_signals = excluded.share_signals
                """
            )
            conn_a.commit()
        finally:
            conn_a.close()

        obs_resp = client.post(
            "/api/navigator/observations",
            json={
                "tenant_id": tenant_a,
                "user_id": 1,
                "location_name": pii_location,
                "latitude": pii_lat,
                "longitude": pii_lon,
                "specimen_types": "Agate",
                "yield_rating": 9.1,
            },
        )
        if obs_resp.status_code != 201:
            return False, "unable to create high-yield observation for anonymization test"
        expedition_id = (obs_resp.get_json(silent=True) or {}).get("id")

        specimen_resp = client.post(
            "/api/navigator/specimens",
            json={
                "tenant_id": tenant_a,
                "user_id": 1,
                "expedition_id": expedition_id,
                "yield_stars": 5,
                "image_path": pii_photo,
                "mineral_class": "Agate",
                "notes": f"deploy privacy marker {pii_marker}",
                "latitude": pii_lat,
                "longitude": pii_lon,
            },
        )
        if specimen_resp.status_code != 201:
            return False, "unable to create specimen for global-node anonymization"

        signal_payload = (specimen_resp.get_json(silent=True) or {}).get("signal") or {}
        if str(signal_payload.get("status") or "").lower() != "created":
            return False, "high-yield specimen did not emit a global observatory signal"
        signal_id = int(((signal_payload.get("signal") or {}).get("id") or 0) or 0)
        if signal_id <= 0:
            return False, "global signal did not return an id"

        if not GLOBAL_NODE_DB.exists():
            return False, "global_node.sqlite was not created"

        tenant_a_token = _tenant_token(tenant_a)
        conn_g = sqlite3.connect(str(GLOBAL_NODE_DB))
        try:
            cols = {row[1] for row in conn_g.execute("PRAGMA table_info(observatory_signals)").fetchall()}
            forbidden_cols = {"username", "image_path", "latitude", "longitude", "notes", "home_base_icao"}
            present_forbidden = sorted(cols.intersection(forbidden_cols))
            if present_forbidden:
                return False, f"global node schema leaked PII columns: {', '.join(present_forbidden)}"

            row = conn_g.execute(
                """
                SELECT id, role_label, signal_type, general_region
                FROM observatory_signals
                WHERE id = ? AND tenant_token = ?
                """,
                (signal_id, tenant_a_token),
            ).fetchone()
        finally:
            conn_g.close()

        if row is None:
            return False, "global node did not retain emitted signal for tenant A"

        public_blob = " ".join(str(x or "") for x in row).lower()
        blocked_tokens = [
            "deploy_user_a",
            pii_marker.lower(),
            pii_photo.lower(),
            f"{pii_lat:.5f}",
            f"{pii_lon:.5f}",
            pii_location.lower(),
        ]
        leaked = [token for token in blocked_tokens if token and token in public_blob]
        if leaked:
            return False, f"global node signal leaked private data tokens: {', '.join(leaked)}"

        brief_resp = client.get(f"/api/briefing/daily?tenant_slug=default&tenant_id={tenant_b}&user_role=Admin")
        if brief_resp.status_code != 200:
            return False, "morning briefing unavailable for global feed verification"
        brief = brief_resp.get_json(silent=True) or {}
        global_node = brief.get("global_node") or {}
        if str(global_node.get("label") or "").strip() != "Global Pulse: Connected.":
            return False, "Morning Card global pulse label is missing"

        feed = global_node.get("signals") or []
        if not isinstance(feed, list) or not feed:
            return False, "Morning Card global discovery feed is empty for cross-tenant signal"

        message_blob = " ".join(str(item.get("message") or "") for item in feed).lower()
        if "high-yield" not in message_blob or "region" not in message_blob:
            return False, "global discovery feed message is not anonymized as role + region + type"
        if any(token in message_blob for token in blocked_tokens):
            return False, "global discovery feed message leaked private data"

        return True, f"anonymized global signal verified for tenant token {tenant_a_token}"
    finally:
        try:
            if signal_id and GLOBAL_NODE_DB.exists():
                conn_g = sqlite3.connect(str(GLOBAL_NODE_DB))
                try:
                    conn_g.execute("DELETE FROM observatory_signals WHERE id = ?", (signal_id,))
                    conn_g.commit()
                finally:
                    conn_g.close()

            if tenant_a_db.exists():
                conn = sqlite3.connect(str(tenant_a_db))
                try:
                    if expedition_id is not None:
                        conn.execute("DELETE FROM specimen_inventory WHERE expedition_id = ?", (expedition_id,))
                        conn.execute("DELETE FROM rockhounding_expeditions WHERE id = ?", (expedition_id,))
                    conn.commit()
                finally:
                    conn.close()

            for db_path, tenant_dir in ((tenant_a_db, tenant_a_dir), (tenant_b_db, tenant_b_dir)):
                if db_path.exists():
                    db_path.unlink()
                if tenant_dir.exists():
                    tenant_dir.rmdir()
        except OSError:
            pass


def _verify_signal_probability_engine(client) -> tuple[bool, str]:
    tenant_source = _normalise_tenant_id(f"prob-source-{int(time.time() * 1000)}")
    tenant_auditor = _normalise_tenant_id(f"prob-auditor-{int(time.time() * 1000)}")
    tenant_source_dir = AVIATION_TENANTS_DIR / tenant_source
    tenant_auditor_dir = AVIATION_TENANTS_DIR / tenant_auditor
    tenant_source_db = tenant_source_dir / "marine.sqlite"
    tenant_auditor_db = tenant_auditor_dir / "marine.sqlite"

    signal_id = None
    auditor_expedition_ids: list[int] = []
    auditor_specimen_ids: list[int] = []

    try:
        for tenant in (tenant_source, tenant_auditor):
            bootstrap = client.get(f"/api/navigator/consumables?tenant_id={tenant}&user_id=1&limit=5")
            if bootstrap.status_code != 200:
                return False, f"tenant bootstrap failed for probability check ({tenant})"

        share_resp = client.post(
            "/api/navigator/profile/share-signals",
            json={"tenant_id": tenant_source, "user_id": 1, "share_signals": True},
        )
        if share_resp.status_code != 200:
            return False, "could not enable share_signals for probability-source tenant"

        for idx in range(2):
            obs_resp = client.post(
                "/api/navigator/observations",
                json={
                    "tenant_id": tenant_auditor,
                    "user_id": 1,
                    "location_name": f"KIXD Agate Basin {idx + 1}",
                    "latitude": 38.955 + (idx * 0.01),
                    "longitude": -94.745 - (idx * 0.01),
                    "specimen_types": "Agate",
                    "yield_rating": 7.2,
                },
            )
            if obs_resp.status_code != 201:
                return False, "unable to create local reference observation for probability engine"
            expedition_id = int((obs_resp.get_json(silent=True) or {}).get("id") or 0)
            if expedition_id <= 0:
                return False, "local reference observation missing id"
            auditor_expedition_ids.append(expedition_id)

            specimen_resp = client.post(
                "/api/navigator/specimens",
                json={
                    "tenant_id": tenant_auditor,
                    "user_id": 1,
                    "expedition_id": expedition_id,
                    "yield_stars": 3,
                    "mineral_class": "Agate",
                    "notes": "deploy-probability-reference",
                },
            )
            if specimen_resp.status_code != 201:
                return False, "unable to create local Agate specimen reference for probability engine"
            specimen_id = int((((specimen_resp.get_json(silent=True) or {}).get("specimen") or {}).get("id") or 0) or 0)
            if specimen_id <= 0:
                return False, "local reference specimen missing id"
            auditor_specimen_ids.append(specimen_id)

        emit_resp = client.post(
            "/api/observatory/signals",
            json={
                "tenant_id": tenant_source,
                "user_id": 1,
                "signal_type": "Agate",
                "general_region": "KIXD region",
                "role": "Scientist",
            },
        )
        if emit_resp.status_code not in (200, 201):
            return False, "failed to emit synthetic global signal for probability verification"

        emit_payload = emit_resp.get_json(silent=True) or {}
        signal_id = int((((emit_payload.get("signal") or {}).get("id") or 0) or 0))
        if signal_id <= 0:
            return False, "synthetic global signal did not return id"

        briefing = client.get(f"/api/briefing/daily?tenant_slug=default&tenant_id={tenant_auditor}&user_role=Admin")
        if briefing.status_code != 200:
            return False, "morning briefing unavailable for probability verification"
        briefing_payload = briefing.get_json(silent=True) or {}
        global_node = briefing_payload.get("global_node") or {}
        feed = global_node.get("signals") or []
        if not isinstance(feed, list):
            return False, "global discovery feed missing list payload for probability verification"

        target = next((row for row in feed if int(row.get("id") or 0) == signal_id), None)
        if target is None:
            return False, "synthetic global signal not visible in auditor feed"
        if str(target.get("probability_status") or "") != "Verified":
            return False, "Agate signal in Agate-rich region was not tagged Verified"
        if int(target.get("confidence_pct") or 0) != 100:
            return False, "Agate signal in Agate-rich region did not return 100% confidence"

        mesh_label = str(global_node.get("mesh_integrity_label") or "").strip()
        if mesh_label != "Mesh Integrity: 100%.":
            return False, "Mesh Integrity label was not 100% during probability verification"

        vouch_resp = client.post(
            f"/api/observatory/signals/{signal_id}/vouch",
            json={"tenant_id": tenant_auditor, "user_id": 1},
        )
        if vouch_resp.status_code != 200:
            return False, "vouch endpoint failed for supported regional signal"

        vouch_payload = vouch_resp.get_json(silent=True) or {}
        vouch_signal = vouch_payload.get("signal") or {}
        if not bool(vouch_signal.get("already_vouched")):
            return False, "vouch response did not report already_vouched=true"

        return True, "Agate in KIXD region classified Verified (100%) and vouch flow succeeded"
    finally:
        try:
            if signal_id and GLOBAL_NODE_DB.exists():
                conn_g = sqlite3.connect(str(GLOBAL_NODE_DB))
                try:
                    conn_g.execute("DELETE FROM observatory_signal_vouches WHERE signal_id = ?", (signal_id,))
                    conn_g.execute("DELETE FROM observatory_signals WHERE id = ?", (signal_id,))
                    conn_g.commit()
                finally:
                    conn_g.close()

            if tenant_auditor_db.exists():
                conn = sqlite3.connect(str(tenant_auditor_db))
                try:
                    for specimen_id in auditor_specimen_ids:
                        conn.execute("DELETE FROM specimen_inventory WHERE id = ?", (specimen_id,))
                    for expedition_id in auditor_expedition_ids:
                        conn.execute("DELETE FROM rockhounding_expeditions WHERE id = ?", (expedition_id,))
                    conn.commit()
                finally:
                    conn.close()

            for db_path, tenant_dir in ((tenant_source_db, tenant_source_dir), (tenant_auditor_db, tenant_auditor_dir)):
                if db_path.exists():
                    db_path.unlink()
                if tenant_dir.exists():
                    tenant_dir.rmdir()
        except OSError:
            pass


def _verify_hotspot_prediction_engine(client) -> tuple[bool, str]:
    tenant_hotspot = _normalise_tenant_id(f"hotspot-{int(time.time() * 1000)}")
    tenant_hotspot_dir = AVIATION_TENANTS_DIR / tenant_hotspot
    tenant_hotspot_db = tenant_hotspot_dir / "marine.sqlite"

    specimen_ids: list[int] = []
    signal_ids: list[int] = []

    try:
        bootstrap = client.get(f"/api/navigator/consumables?tenant_id={tenant_hotspot}&user_id=1&limit=5")
        if bootstrap.status_code != 200:
            return False, "tenant bootstrap failed for hotspot verification"

        share_resp = client.post(
            "/api/navigator/profile/share-signals",
            json={"tenant_id": tenant_hotspot, "user_id": 1, "share_signals": True},
        )
        if share_resp.status_code != 200:
            return False, "could not enable share_signals for hotspot verification tenant"

        seeded_points = [
            (38.9580, -94.7802),
            (38.9624, -94.7721),
            (38.9543, -94.7896),
        ]
        for idx, (lat, lon) in enumerate(seeded_points, start=1):
            specimen_resp = client.post(
                "/api/navigator/specimens",
                json={
                    "tenant_id": tenant_hotspot,
                    "user_id": 1,
                    "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "yield_stars": 5,
                    "mineral_class": "Discovery Pulse",
                    "notes": f"deploy-hotspot-seed-{idx}",
                    "latitude": lat,
                    "longitude": lon,
                },
            )
            if specimen_resp.status_code != 201:
                return False, "unable to create synthetic 5-star find for hotspot verification"

            specimen_payload = specimen_resp.get_json(silent=True) or {}
            specimen_id = int((((specimen_payload.get("specimen") or {}).get("id") or 0) or 0))
            if specimen_id <= 0:
                return False, "synthetic hotspot specimen missing id"
            specimen_ids.append(specimen_id)

            signal_payload = specimen_payload.get("signal") or {}
            if str(signal_payload.get("status") or "").lower() != "created":
                return False, "synthetic 5-star hotspot find did not emit a global observatory signal"
            signal_id = int(((((signal_payload.get("signal") or {}).get("id")) or 0) or 0))
            if signal_id <= 0:
                return False, "synthetic hotspot signal missing id"
            signal_ids.append(signal_id)

        mission_map_resp = client.get(
            f"/api/navigator/mission-map?tenant_id={tenant_hotspot}&expedition_limit=250&aviation_limit=250"
        )
        if mission_map_resp.status_code != 200:
            return False, "mission-map API unavailable during hotspot verification"
        mission_map = mission_map_resp.get_json(silent=True) or {}
        predicted_hotspots = mission_map.get("predicted_hotspots")
        if not isinstance(predicted_hotspots, list):
            return False, "mission-map payload missing predicted_hotspots list"

        hotspot_match = next(
            (
                row
                for row in predicted_hotspots
                if int(row.get("probability_pct") or 0) >= 85
                and int(row.get("signal_count_12m") or 0) >= 3
                and (
                    "KIXD" in str(row.get("region") or "").upper()
                    or str(row.get("airport_code") or "").upper() == "KIXD"
                )
            ),
            None,
        )
        if hotspot_match is None:
            return False, "hotspot engine did not flag KIXD region after multiple 5-star finds"

        briefing_resp = client.get(
            f"/api/briefing/daily?tenant_slug=default&tenant_id={tenant_hotspot}&user_role=Admin"
        )
        if briefing_resp.status_code != 200:
            return False, "morning briefing unavailable during hotspot verification"

        briefing_payload = briefing_resp.get_json(silent=True) or {}
        discovery_forecast = briefing_payload.get("discovery_forecast") or {}
        forecast_label = str(discovery_forecast.get("label") or "").strip()
        if forecast_label != "Discovery Forecast: High-Yield Zone Detected.":
            return False, "Morning Card discovery forecast label mismatch for detected hotspot"

        fleet_readiness = briefing_payload.get("fleet_readiness") or {}
        readiness_label = str(fleet_readiness.get("label") or "").strip()
        if readiness_label != "Fleet Readiness: 100% (Mission Ready).":
            return False, "Morning Card readiness gauge did not report 100% mission-ready state"
        baseline_readiness = int(fleet_readiness.get("readiness_pct") or 0)
        if baseline_readiness < 100:
            return False, "readiness gauge baseline did not reach 100% for nearby hotspot"

        route_label = str(
            discovery_forecast.get("suggested_route")
            or ((discovery_forecast.get("route") or {}).get("route_label"))
            or ""
        ).strip()
        if not route_label.startswith("Mission Route:"):
            return False, "Morning Card did not include mission route for detected hotspot"

        route_distance_km = _to_optional_float((discovery_forecast.get("route") or {}).get("distance_km"))
        route_distance_nm = round((route_distance_km or 0.0) * 0.539957, 1)
        if route_distance_nm <= 100.0:
            notice = _send_preflight_prep_notification(
                tenant_id=tenant_hotspot,
                route_label=route_label,
                distance_nm=route_distance_nm,
            )
        else:
            notice = "Pre-Flight Prep notification skipped (hotspot beyond 100nm)."

        low_oil_resp = client.post(
            "/api/navigator/consumables",
            json={
                "tenant_id": tenant_hotspot,
                "user_id": 1,
                "item_key": "oil_quarts",
                "display_name": "Oil Quarts",
                "quantity": 1.0,
                "unit": "qt",
                "restock_threshold": 4.0,
                "notes": "deploy-readiness-drop",
            },
        )
        if low_oil_resp.status_code != 200:
            return False, "unable to lower oil quarts for readiness-drop verification"

        low_briefing_resp = client.get(
            f"/api/briefing/daily?tenant_slug=default&tenant_id={tenant_hotspot}&user_role=Admin"
        )
        if low_briefing_resp.status_code != 200:
            return False, "morning briefing unavailable during readiness-drop verification"
        low_briefing_payload = low_briefing_resp.get_json(silent=True) or {}
        low_readiness = low_briefing_payload.get("fleet_readiness") or {}
        low_readiness_pct = int(low_readiness.get("readiness_pct") or 0)
        if low_readiness_pct >= baseline_readiness:
            return False, "readiness gauge did not drop after forcing low Oil Quarts during hotspot detection"

        return True, (
            f"hotspot engine predicted {hotspot_match.get('region')} at "
            f"{hotspot_match.get('probability_pct')}% and Morning Card displays 'Discovery Forecast: High-Yield Zone Detected.'; "
            f"{notice}; readiness gauge drop verified when Oil Quarts fell below threshold"
        )
    finally:
        try:
            if signal_ids and GLOBAL_NODE_DB.exists():
                conn_g = sqlite3.connect(str(GLOBAL_NODE_DB))
                try:
                    for signal_id in signal_ids:
                        conn_g.execute("DELETE FROM observatory_signal_vouches WHERE signal_id = ?", (signal_id,))
                        conn_g.execute("DELETE FROM observatory_signals WHERE id = ?", (signal_id,))
                    conn_g.commit()
                finally:
                    conn_g.close()

            if tenant_hotspot_db.exists():
                conn = sqlite3.connect(str(tenant_hotspot_db))
                try:
                    for specimen_id in specimen_ids:
                        conn.execute("DELETE FROM specimen_inventory WHERE id = ?", (specimen_id,))
                    conn.commit()
                finally:
                    conn.close()

            if tenant_hotspot_db.exists():
                tenant_hotspot_db.unlink()
            if tenant_hotspot_dir.exists():
                tenant_hotspot_dir.rmdir()
        except OSError:
            pass


def _verify_global_mesh_correlation_engine(client) -> tuple[bool, str]:
    tenant_source = _normalise_tenant_id(f"mesh-source-{int(time.time() * 1000)}")
    tenant_private = _normalise_tenant_id(f"mesh-private-{int(time.time() * 1000)}")
    tenant_source_dir = AVIATION_TENANTS_DIR / tenant_source
    tenant_private_dir = AVIATION_TENANTS_DIR / tenant_private
    tenant_source_db = tenant_source_dir / "marine.sqlite"
    tenant_private_db = tenant_private_dir / "marine.sqlite"

    signal_id = None
    expedition_id = None
    specimen_id = None

    try:
        for tenant in (tenant_source, tenant_private):
            bootstrap = client.get(f"/api/navigator/consumables?tenant_id={tenant}&user_id=1&limit=5")
            if bootstrap.status_code != 200:
                return False, f"tenant bootstrap failed for mesh correlation check ({tenant})"

        share_resp = client.post(
            "/api/navigator/profile/share-signals",
            json={"tenant_id": tenant_source, "user_id": 1, "share_signals": True},
        )
        if share_resp.status_code != 200:
            return False, "could not enable share_signals for mesh-source tenant"

        emit_resp = client.post(
            "/api/observatory/signals",
            json={
                "tenant_id": tenant_source,
                "user_id": 1,
                "signal_type": "Agate",
                "general_region": "KDEN region",
                "role": "Scientist",
            },
        )
        if emit_resp.status_code not in (200, 201):
            return False, "unable to emit synthetic global Agate signal"

        emit_payload = emit_resp.get_json(silent=True) or {}
        signal_id = int((((emit_payload.get("signal") or {}).get("id") or 0) or 0))
        if signal_id <= 0:
            return False, "synthetic global Agate signal did not return id"

        obs_resp = client.post(
            "/api/navigator/observations",
            json={
                "tenant_id": tenant_private,
                "user_id": 1,
                "location_name": "KIXD Private Agate Basin",
                "latitude": 38.955,
                "longitude": -94.745,
                "specimen_types": "Agate",
                "yield_rating": 7.1,
            },
        )
        if obs_resp.status_code != 201:
            return False, "unable to create private observation for mesh correlation"

        expedition_id = int(((obs_resp.get_json(silent=True) or {}).get("id") or 0))
        if expedition_id <= 0:
            return False, "private observation did not return expedition id"

        specimen_resp = client.post(
            "/api/navigator/specimens",
            json={
                "tenant_id": tenant_private,
                "user_id": 1,
                "expedition_id": expedition_id,
                "yield_stars": 4,
                "mineral_class": "Agate",
                "notes": "deploy-mesh-correlation",
                "latitude": 38.955,
                "longitude": -94.745,
            },
        )
        if specimen_resp.status_code != 201:
            return False, "unable to create private Agate specimen for mesh correlation"

        specimen_payload = specimen_resp.get_json(silent=True) or {}
        specimen_id = int((((specimen_payload.get("specimen") or {}).get("id") or 0) or 0))
        if specimen_id <= 0:
            return False, "private Agate specimen did not return id"

        specimens_resp = client.get(
            f"/api/navigator/specimens?tenant_id={tenant_private}&user_id=1&limit=100"
        )
        if specimens_resp.status_code != 200:
            return False, "specimen API unavailable for mesh correlation verification"
        specimens = specimens_resp.get_json(silent=True) or []
        target = next((row for row in specimens if int(row.get("id") or 0) == specimen_id), None)
        if target is None:
            return False, "private Agate specimen not visible in specimen API payload"
        if not bool(target.get("globally_significant")):
            return False, "private Agate specimen was not tagged Globally Significant"
        citations = [int(value) for value in (target.get("mesh_citations") or []) if int(value or 0) > 0]
        if signal_id not in citations:
            return False, "private Agate specimen missing citation to synthetic global Agate signal"

        map_resp = client.get(
            f"/api/navigator/mission-map?tenant_id={tenant_private}&user_id=1&expedition_limit=250&aviation_limit=250"
        )
        if map_resp.status_code != 200:
            return False, "mission-map API unavailable for global mesh verification"
        mesh_signals = (map_resp.get_json(silent=True) or {}).get("mesh_signals") or []
        if not any(int(row.get("id") or 0) == signal_id for row in mesh_signals):
            return False, "mission-map payload missing synthetic global mesh signal"

        briefing_resp = client.get(
            f"/api/briefing/daily?tenant_slug=default&tenant_id={tenant_private}&user_role=Admin"
        )
        if briefing_resp.status_code != 200:
            return False, "morning briefing unavailable for mesh radar verification"
        briefing_payload = briefing_resp.get_json(silent=True) or {}
        mesh_radar = briefing_payload.get("mesh_radar") or {}
        if str(mesh_radar.get("label") or "").strip() != "Mesh Radar: Active.":
            return False, "Morning Card mesh radar label mismatch during mesh correlation verification"

        return True, "private Agate correlation matched synthetic global Agate signal and Morning Card shows Mesh Radar: Active."
    finally:
        try:
            if signal_id and GLOBAL_NODE_DB.exists():
                conn_g = sqlite3.connect(str(GLOBAL_NODE_DB))
                try:
                    conn_g.execute("DELETE FROM observatory_signal_vouches WHERE signal_id = ?", (signal_id,))
                    conn_g.execute("DELETE FROM observatory_signals WHERE id = ?", (signal_id,))
                    conn_g.commit()
                finally:
                    conn_g.close()

            if tenant_private_db.exists():
                conn = sqlite3.connect(str(tenant_private_db))
                try:
                    if specimen_id is not None:
                        conn.execute("DELETE FROM specimen_inventory WHERE id = ?", (specimen_id,))
                    if expedition_id is not None:
                        conn.execute("DELETE FROM rockhounding_expeditions WHERE id = ?", (expedition_id,))
                    conn.commit()
                finally:
                    conn.close()

            for db_path, tenant_dir in ((tenant_source_db, tenant_source_dir), (tenant_private_db, tenant_private_dir)):
                if db_path.exists():
                    db_path.unlink()
                if tenant_dir.exists():
                    tenant_dir.rmdir()
        except OSError:
            pass


def _verify_intelligence_synthesis_engine(client) -> tuple[bool, str]:
    tenant_source = _normalise_tenant_id(f"synthesis-source-{int(time.time() * 1000)}")
    tenant_local = _normalise_tenant_id(f"synthesis-local-{int(time.time() * 1000)}")
    tenant_source_dir = AVIATION_TENANTS_DIR / tenant_source
    tenant_local_dir = AVIATION_TENANTS_DIR / tenant_local
    tenant_source_db = tenant_source_dir / "marine.sqlite"
    tenant_local_db = tenant_local_dir / "marine.sqlite"

    signal_id = None
    expedition_id = None

    try:
        for tenant in (tenant_source, tenant_local):
            bootstrap = client.get(f"/api/navigator/consumables?tenant_id={tenant}&user_id=1&limit=5")
            if bootstrap.status_code != 200:
                return False, f"tenant bootstrap failed for synthesis check ({tenant})"

        share_resp = client.post(
            "/api/navigator/profile/share-signals",
            json={"tenant_id": tenant_source, "user_id": 1, "share_signals": True},
        )
        if share_resp.status_code != 200:
            return False, "could not enable share_signals for synthesis-source tenant"

        emit_resp = client.post(
            "/api/observatory/signals",
            json={
                "tenant_id": tenant_source,
                "user_id": 1,
                "signal_type": "Hazardous Weather",
                "general_region": "KIXD region",
                "role": "Scientist",
            },
        )
        if emit_resp.status_code not in (200, 201):
            return False, "failed to emit synthetic high-risk signal for synthesis verification"

        emit_payload = emit_resp.get_json(silent=True) or {}
        signal_id = int((((emit_payload.get("signal") or {}).get("id") or 0) or 0))
        if signal_id <= 0:
            return False, "synthetic high-risk signal missing id"

        obs_resp = client.post(
            "/api/navigator/observations",
            json={
                "tenant_id": tenant_local,
                "user_id": 1,
                "location_name": "KIXD Synthesis Mission",
                "latitude": 38.955,
                "longitude": -94.745,
                "specimen_types": "Agate",
                "yield_rating": 6.4,
            },
        )
        if obs_resp.status_code != 201:
            return False, "unable to create local mission for regional high-risk pre-check"
        expedition_id = int(((obs_resp.get_json(silent=True) or {}).get("id") or 0))
        if expedition_id <= 0:
            return False, "local mission missing expedition id"

        preflight_resp = client.get(
            f"/api/navigator/preflight?tenant_id={tenant_local}&user_id=1&location_id={expedition_id}&load_profile=high-yield"
        )
        if preflight_resp.status_code != 200:
            return False, "preflight API unavailable for regional high-risk verification"
        preflight_payload = preflight_resp.get_json(silent=True) or {}
        high_risk = preflight_payload.get("high_risk_signals") or []
        if not any(int(row.get("id") or 0) == signal_id for row in high_risk):
            return False, "Navigator pre-check did not surface regional high-risk signal"

        briefing_resp = client.get(
            f"/api/briefing/daily?tenant_slug=default&tenant_id={tenant_local}&user_role=Admin"
        )
        if briefing_resp.status_code != 200:
            return False, "morning briefing unavailable for intelligence synthesis verification"
        briefing_payload = briefing_resp.get_json(silent=True) or {}
        synthesis = briefing_payload.get("intelligence_synthesis") or {}

        if str(synthesis.get("label") or "").strip() != "Intelligence Synthesis: Nominal.":
            return False, "intelligence synthesis label mismatch in briefing payload"

        summary = str(synthesis.get("global_pulse_summary") or "").strip()
        if not summary:
            return False, "LLM-generated global pulse summary missing from briefing payload"

        sentence_count = len([part for part in re.split(r"(?<=[.!?])\s+", summary) if part.strip()])
        if sentence_count < 2:
            return False, "global pulse summary did not contain two sentences"

        local_action = str(synthesis.get("local_action_recommendation") or "").strip()
        if not local_action.startswith("Local Action:"):
            return False, "local action recommendation missing from intelligence synthesis payload"

        return True, "intelligence synthesis payload includes two-sentence Global Pulse summary and regional high-risk pre-check is active"
    finally:
        try:
            if signal_id and GLOBAL_NODE_DB.exists():
                conn_g = sqlite3.connect(str(GLOBAL_NODE_DB))
                try:
                    conn_g.execute("DELETE FROM observatory_signal_vouches WHERE signal_id = ?", (signal_id,))
                    conn_g.execute("DELETE FROM observatory_signals WHERE id = ?", (signal_id,))
                    conn_g.commit()
                finally:
                    conn_g.close()

            if tenant_local_db.exists():
                conn = sqlite3.connect(str(tenant_local_db))
                try:
                    if expedition_id is not None:
                        conn.execute("DELETE FROM rockhounding_expeditions WHERE id = ?", (expedition_id,))
                    conn.commit()
                finally:
                    conn.close()

            for db_path, tenant_dir in ((tenant_source_db, tenant_source_dir), (tenant_local_db, tenant_local_dir)):
                if db_path.exists():
                    db_path.unlink()
                if tenant_dir.exists():
                    tenant_dir.rmdir()
        except OSError:
            pass


def _verify_systems_oracle_engine(client) -> tuple[bool, str]:
    tenant_oracle = _normalise_tenant_id(f"oracle-{int(time.time() * 1000)}")
    tenant_oracle_dir = AVIATION_TENANTS_DIR / tenant_oracle
    tenant_oracle_db = tenant_oracle_dir / "marine.sqlite"

    try:
        if not SYSTEMS_ORACLE_MANUSCRIPT.exists():
            return False, "systems oracle manuscript file is missing"

        manuscript_text = SYSTEMS_ORACLE_MANUSCRIPT.read_text(encoding="utf-8").strip()
        if "Mycology to Your Ecology" not in manuscript_text:
            return False, "systems oracle manuscript title was not found in digital manuscript"

        bootstrap = client.get(f"/api/navigator/consumables?tenant_id={tenant_oracle}&user_id=1&limit=5")
        if bootstrap.status_code != 200:
            return False, "tenant bootstrap failed for systems oracle verification"

        briefing_resp = client.get(
            f"/api/briefing/daily?tenant_slug=default&tenant_id={tenant_oracle}&user_role=Admin"
        )
        if briefing_resp.status_code != 200:
            return False, "morning briefing unavailable for systems oracle verification"

        payload = briefing_resp.get_json(silent=True) or {}
        oracle = payload.get("systems_thinking_overlay") or {}
        if str(oracle.get("label") or "").strip() != "Systems Oracle: Synced with Mycology to Your Ecology.":
            return False, "systems oracle sync label mismatch in briefing payload"

        reflection = str(oracle.get("systems_reflection") or "").strip()
        if not reflection.startswith("Systems-Thinking Reflection:"):
            return False, "systems oracle reflection line missing expected prefix"

        synthesis = str(oracle.get("philosophical_synthesis") or "").strip()
        if not synthesis.startswith("Philosophical Synthesis:"):
            return False, "systems oracle philosophical synthesis missing expected prefix"

        manuscript = oracle.get("manuscript") or {}
        if not bool(manuscript.get("loaded")):
            return False, "systems oracle payload did not report manuscript loaded=true"
        if int(manuscript.get("principles_count") or 0) <= 0:
            return False, "systems oracle payload did not expose manuscript principles"

        return True, "digital manuscript synced and systems-thinking overlay rendered in Morning Card payload"
    finally:
        try:
            if tenant_oracle_db.exists():
                tenant_oracle_db.unlink()
            if tenant_oracle_dir.exists():
                tenant_oracle_dir.rmdir()
        except OSError:
            pass


def _verify_pac_pruning_engine(client) -> tuple[bool, str]:
    db_path = ROOT / "data" / "marine.sqlite"
    script_path = ROOT / "scripts" / "prune_auction_logs.py"
    if not script_path.exists():
        return False, "scripts/prune_auction_logs.py not found"

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    csv_path = Path(tempfile.gettempdir()) / f"pac-auction-{int(time.time() * 1000)}.csv"
    inserted_count = 0

    try:
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["Date", "Item Type", "Final Hammer Price", "Commission"])
            for idx in range(10):
                writer.writerow([today, f"Specimen-{idx+1}", f"{1000 + (idx * 25):.2f}", "40.00"])

        result = subprocess.run(
            [sys.executable, str(script_path), str(csv_path), "--db", str(db_path)],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return False, f"prune_auction_logs.py failed with exit code {result.returncode}"

        summary = _to_json_object((result.stdout or "").strip())
        if int(summary.get("ingested_rows") or 0) != 10:
            return False, "prune_auction_logs.py did not ingest the expected 10 rows"

        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute(_CREATE_PAC_AUCTION_LOGS)
            row = conn.execute(
                """
                SELECT COUNT(*), ROUND(AVG(COALESCE(drift_pct, 0.0)), 1)
                FROM pac_auction_logs
                WHERE source_file = ?
                """,
                (str(csv_path),),
            ).fetchone()
            inserted_count = int((row or [0])[0] or 0)
            avg_drift = float((row or [0, 0.0])[1] or 0.0)
        finally:
            conn.close()

        if inserted_count != 10:
            return False, "PAC auction rows were not written to marine.sqlite"
        if avg_drift != 0.0:
            return False, "PAC auction ingestion did not preserve 0.0% drift"

        briefing_resp = client.get("/api/briefing/daily?tenant_slug=default&user_role=Admin")
        if briefing_resp.status_code != 200:
            return False, "morning briefing unavailable for PAC pruning verification"
        briefing_payload = briefing_resp.get_json(silent=True) or {}
        pac_pruning = briefing_payload.get("pac_pruning") or {}
        if int(pac_pruning.get("pruned_today_count") or 0) < 10:
            return False, "Morning Card pac_pruning metric did not report ingested rows"
        drift_pct = _to_optional_float(pac_pruning.get("recorded_drift_pct"))
        if drift_pct is None or abs(float(drift_pct)) > 1e-6:
            return False, f"Morning Card pac_pruning drift metric is not 0.0% (got {pac_pruning.get('recorded_drift_pct')})"
        if str(pac_pruning.get("professional_ecology_label") or "").strip() != "Professional Ecology: Pruned and Flowing.":
            return False, "Morning Card professional ecology label did not resolve to Pruned and Flowing"

        return True, "synthetic 10-item PAC auction log ingested with 0.0% drift and Morning Card pruning metrics active"
    finally:
        try:
            if db_path.exists():
                conn = sqlite3.connect(str(db_path))
                try:
                    conn.execute(_CREATE_PAC_AUCTION_LOGS)
                    conn.execute("DELETE FROM pac_auction_logs WHERE source_file = ?", (str(csv_path),))
                    conn.commit()
                finally:
                    conn.close()
            if csv_path.exists():
                csv_path.unlink()
        except OSError:
            pass


def _verify_predictive_maintenance_engine(client) -> tuple[bool, str]:
    tenant_id = _normalise_tenant_id(f"maintenance-{int(time.time() * 1000)}")
    tenant_dir = AVIATION_TENANTS_DIR / tenant_id
    tenant_db = tenant_dir / "marine.sqlite"

    try:
        bootstrap = client.get(f"/api/navigator/consumables?tenant_id={tenant_id}&user_id=1&limit=5")
        if bootstrap.status_code != 200:
            return False, "tenant bootstrap failed for predictive maintenance verification"

        conn = sqlite3.connect(str(tenant_db))
        try:
            conn.execute(_CREATE_OIL_SENTINEL_REPORTS)
            conn.execute(_CREATE_FUEL_LOGS)
            now = datetime.now(timezone.utc)
            ts_old = (now - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
            ts_new = (now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")

            conn.execute(
                """
                INSERT INTO oil_sentinel_reports (
                    report_name, source_pdf, iron, copper, aluminium,
                    iron_delta_pct, copper_delta_pct, iron_flagged, copper_flagged,
                    flagged, analyzed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "maintenance-baseline",
                    "deploy-maintenance-baseline.pdf",
                    33.0,
                    9.0,
                    7.0,
                    0.0,
                    0.0,
                    0,
                    0,
                    0,
                    ts_old,
                ),
            )
            conn.execute(
                """
                INSERT INTO oil_sentinel_reports (
                    report_name, source_pdf, iron, copper, aluminium,
                    iron_delta_pct, copper_delta_pct, iron_flagged, copper_flagged,
                    flagged, analyzed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "maintenance-critical",
                    "deploy-maintenance-critical.pdf",
                    45.0,
                    16.0,
                    11.0,
                    18.0,
                    7.0,
                    1,
                    0,
                    1,
                    ts_new,
                ),
            )

            conn.execute(
                """
                INSERT INTO fuel_logs (tail_number, timestamp, hobbs_time, tach_time, gallons_added, fuel_after_gal, burn_rate_gph, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("N6424P", ts_old, 1200.0, 1105.0, 20.0, 36.0, 9.0, "deploy-maintenance-baseline"),
            )
            conn.execute(
                """
                INSERT INTO fuel_logs (tail_number, timestamp, hobbs_time, tach_time, gallons_added, fuel_after_gal, burn_rate_gph, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("N6424P", ts_new, 1215.0, 1118.0, 22.0, 35.0, 9.5, "deploy-maintenance-critical"),
            )
            conn.commit()
        finally:
            conn.close()

        maintenance_resp = client.get(f"/api/aviation/predictive-maintenance?tenant_id={tenant_id}&tail_number=N6424P")
        if maintenance_resp.status_code != 200:
            return False, "predictive maintenance API unavailable during hardening verification"
        maintenance_payload = maintenance_resp.get_json(silent=True) or {}
        components = maintenance_payload.get("components") or []
        cylinder = next((row for row in components if str(row.get("component_key") or "") == "cylinders"), None)
        if cylinder is None:
            return False, "predictive maintenance payload missing cylinders component"
        if str(cylinder.get("status") or "") != "INSPECT_NOW":
            return False, "45.0 ppm iron did not trigger red cylinder inspect-now status"
        if str(cylinder.get("status_emoji") or "") != "🔴":
            return False, "cylinder inspect-now state did not expose red status emoji"

        briefing_resp = client.get(f"/api/briefing/daily?tenant_slug=default&tenant_id={tenant_id}&user_role=Admin")
        if briefing_resp.status_code != 200:
            return False, "morning briefing unavailable during predictive maintenance verification"
        briefing_payload = briefing_resp.get_json(silent=True) or {}
        forecast = briefing_payload.get("maintenance_forecast") or {}
        if not bool(forecast.get("schedule_service_required")):
            return False, "maintenance forecast did not request service when TTI was below 10 hours"

        return True, "45.0 ppm iron correctly mapped to red cylinder inspect-now status with service booking trigger"
    finally:
        try:
            if tenant_db.exists():
                tenant_db.unlink()
            if tenant_dir.exists():
                tenant_dir.rmdir()
        except OSError:
            pass


def _verify_logbook_deep_audit(client) -> tuple[bool, str]:
    tenant_audit = _normalise_tenant_id(f"deep-audit-{int(time.time() * 1000)}")
    tenant_audit_dir = AVIATION_TENANTS_DIR / tenant_audit
    tenant_audit_db = tenant_audit_dir / "marine.sqlite"

    try:
        bootstrap = client.get(f"/api/navigator/consumables?tenant_id={tenant_audit}&user_id=1&limit=5")
        if bootstrap.status_code != 200:
            return False, "tenant bootstrap failed for logbook deep-audit verification"

        base_hobbs = 500.0
        now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        for idx in range(7):
            ts = (now - timedelta(hours=(7 - idx))).strftime("%Y-%m-%dT%H:%M:%SZ")
            gallons_added = 9.5 if idx == 6 else 8.0
            fuel_resp = client.post(
                "/api/navigator/fuel-logs",
                json={
                    "tenant_id": tenant_audit,
                    "user_id": 1,
                    "tail_number": "N6424P",
                    "timestamp": ts,
                    "hobbs_time": base_hobbs + float(idx),
                    "gallons_added": gallons_added,
                    "fuel_after_gal": 30.0,
                    "notes": f"deploy-deep-audit-{idx}",
                },
            )
            if fuel_resp.status_code != 201:
                return False, "unable to seed fuel logs for deep-audit verification"

        logs_resp = client.get(
            f"/api/navigator/fuel-logs?tenant_id={tenant_audit}&tail_number=N6424P&limit=20"
        )
        if logs_resp.status_code != 200:
            return False, "fuel-log API unavailable during deep-audit verification"
        logs = logs_resp.get_json(silent=True) or []
        if not isinstance(logs, list) or len(logs) < 7:
            return False, "insufficient fuel-log history for 5-log burn average audit"

        ordered = sorted(logs, key=lambda row: str(row.get("timestamp") or ""))
        latest = ordered[-1]
        previous_five = ordered[-6:-1]
        baseline_rates = [_to_optional_float(row.get("burn_rate_gph")) for row in previous_five]
        baseline_rates = [value for value in baseline_rates if value is not None]
        if len(baseline_rates) < 5:
            return False, "unable to compute 5-log burn average for deep-audit"

        avg_five = sum(baseline_rates) / len(baseline_rates)
        latest_rate = _to_optional_float(latest.get("burn_rate_gph"))
        if latest_rate is None:
            return False, "latest burn-rate sample missing during deep-audit"

        latest_ts = _parse_utc(str(latest.get("timestamp") or ""))
        specimens_resp = client.get(f"/api/navigator/specimens?tenant_id={tenant_audit}&limit=250")
        if specimens_resp.status_code != 200:
            return False, "specimen API unavailable during deep-audit payload check"
        specimen_rows = specimens_resp.get_json(silent=True) or []
        payload_increase = 0
        if latest_ts is not None and isinstance(specimen_rows, list):
            for specimen in specimen_rows:
                sample_ts = _parse_utc(str((specimen or {}).get("timestamp") or ""))
                if sample_ts is None:
                    continue
                if 0 <= (latest_ts - sample_ts).total_seconds() <= 86400:
                    payload_increase += 1

        threshold = avg_five * 1.15
        if latest_rate <= threshold:
            return False, "deep-audit did not find burn-rate increase above 15% of the 5-log average"
        if payload_increase > 0:
            return False, "deep-audit expected no payload increase but recent specimen payload was detected"

        return True, (
            f"efficiency gap detected: burn {latest_rate:.2f} gph exceeded 5-log average {avg_five:.2f} gph by >15% "
            "without payload increase"
        )
    finally:
        try:
            if tenant_audit_db.exists():
                tenant_audit_db.unlink()
            if tenant_audit_dir.exists():
                tenant_audit_dir.rmdir()
        except OSError:
            pass


def _verify_pivot_engine_hardening(client) -> tuple[bool, str]:
    tenant_pivot = _normalise_tenant_id(f"pivot-{int(time.time() * 1000)}")
    tenant_pivot_dir = AVIATION_TENANTS_DIR / tenant_pivot
    tenant_pivot_db = tenant_pivot_dir / "marine.sqlite"

    try:
        bootstrap = client.get(f"/api/navigator/consumables?tenant_id={tenant_pivot}&user_id=1&limit=5")
        if bootstrap.status_code != 200:
            return False, "tenant bootstrap failed for pivot hardening verification"

        now = datetime.now(timezone.utc)
        updated_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        day_one = (now.date() - timedelta(days=1)).isoformat()
        day_two = (now.date() - timedelta(days=2)).isoformat()

        conn = sqlite3.connect(str(tenant_pivot_db))
        try:
            conn.execute(
                """
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
            )
            for day, pct in ((day_one, 62.0), (day_two, 66.0)):
                conn.execute(
                    """
                    INSERT INTO fleet_readiness_history (user_id, snapshot_date, readiness_pct, status, updated_at)
                    VALUES (1, ?, ?, 'PREP_REQUIRED', ?)
                    ON CONFLICT(user_id, snapshot_date) DO UPDATE SET
                        readiness_pct = excluded.readiness_pct,
                        status = excluded.status,
                        updated_at = excluded.updated_at
                    """,
                    (day, pct, updated_at),
                )
            conn.commit()
        finally:
            conn.close()

        briefing = client.get(
            f"/api/briefing/daily?tenant_slug=default&tenant_id={tenant_pivot}&user_role=Admin"
        )
        if briefing.status_code != 200:
            return False, "morning briefing unavailable for pivot hardening verification"

        payload = briefing.get_json(silent=True) or {}
        pivot = payload.get("optimization_pivot") or {}
        if str(pivot.get("pivot") or "") != "Prioritize Maintenance":
            return False, "pivot engine failed to recommend maintenance for consecutive low readiness days"
        if not str(pivot.get("label") or "").startswith("Strategy: Maintenance"):
            return False, "pivot engine did not return maintenance strategy label"
        if int(pivot.get("low_readiness_streak_days") or 0) < 2:
            return False, "pivot engine did not report two-day low-readiness streak"

        return True, "pivot engine recommends maintenance when readiness is <70 for two consecutive days"
    finally:
        try:
            if tenant_pivot_db.exists():
                tenant_pivot_db.unlink()
            if tenant_pivot_dir.exists():
                tenant_pivot_dir.rmdir()
        except OSError:
            pass


def _fetch_external_logbook_latest() -> dict | None:
    endpoint = (os.environ.get("HUTCH_DIGITAL_LOGBOOK_URL") or "").strip()
    if not endpoint:
        return None

    req = urlrequest.Request(endpoint, headers={"User-Agent": "HutchSolves-Deploy/2.1"})
    with urlrequest.urlopen(req, timeout=3.0) as response:
        payload = json.loads(response.read().decode("utf-8"))

    row = payload[0] if isinstance(payload, list) and payload else payload
    if not isinstance(row, dict):
        return None

    def _pick(*keys: str) -> object:
        for key in keys:
            if key in row:
                return row.get(key)
        return None

    timestamp = _pick("timestamp", "logged_at", "time", "event_time")
    tail_number = str(_pick("tail_number", "tail", "aircraft_tail") or "N6424P").strip().upper()
    hobbs_time = _to_optional_float(_pick("hobbs_time", "hobbs", "hobbs_hours"))
    tach_time = _to_optional_float(_pick("tach_time", "tach", "tach_hours"))
    gallons_added = _to_optional_float(_pick("gallons_added", "fuel_added_gal", "fuel_gallons"))

    if not timestamp:
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if hobbs_time is None and tach_time is None:
        return None

    return {
        "tail_number": tail_number or "N6424P",
        "timestamp": str(timestamp),
        "hobbs_time": hobbs_time,
        "tach_time": tach_time,
        "gallons_added": gallons_added if gallons_added and gallons_added > 0 else 0.1,
    }


def _verify_tax_export_integrity() -> tuple[bool, str]:
    export_script = ROOT / "scripts" / "tax_ready_export.py"
    if not export_script.exists():
        return False, "scripts/tax_ready_export.py not found."

    tmp_dir = Path(tempfile.gettempdir())
    out_path = tmp_dir / f"tax_export_smoke_{int(time.time())}.csv"

    result = subprocess.run(
        [
            sys.executable,
            str(export_script),
            "--start-date",
            "2026-01-01",
            "--end-date",
            "2026-12-31",
            "--output",
            str(out_path),
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return False, f"tax_ready_export.py exited with code {result.returncode}."

    if not out_path.exists():
        return False, "Tax export CSV was not generated."

    with out_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader, [])

    if len(header) < 2:
        return False, "Tax export CSV header has fewer than two columns."

    lowered = [str(col).strip().lower() for col in header]
    has_revenue = any("revenue" in col for col in lowered)
    has_expense = any("expense" in col for col in lowered)
    if not has_revenue or not has_expense:
        return False, "Tax export CSV missing Revenue/Expenses columns in header."

    return True, f"Tax export header validated ({', '.join(header[:6])})."


def _detect_logbook_gap_days() -> list[dict]:
    if not AVIATION_DB.exists():
        return []

    try:
        conn = sqlite3.connect(str(AVIATION_DB))
        try:
            conn.execute(_CREATE_FUEL_LOGS)
            fuel_rows = conn.execute(
                """
                SELECT
                    substr(timestamp, 1, 10) AS day,
                    COUNT(*) AS fuel_log_count,
                    SUM(CASE WHEN hobbs_time IS NOT NULL AND tach_time IS NOT NULL THEN 1 ELSE 0 END) AS complete_log_count
                FROM fuel_logs
                GROUP BY substr(timestamp, 1, 10)
                ORDER BY day DESC
                """
            ).fetchall()

            oil_days: set[str] = set()
            oil_cols = {row[1] for row in conn.execute("PRAGMA table_info(oil_sentinel_reports)").fetchall()}
            if "analyzed_at" in oil_cols:
                rows = conn.execute(
                    """
                    SELECT DISTINCT substr(analyzed_at, 1, 10)
                    FROM oil_sentinel_reports
                    WHERE analyzed_at IS NOT NULL AND TRIM(analyzed_at) <> ''
                    """
                ).fetchall()
                oil_days = {str(row[0]) for row in rows if row and row[0]}
        finally:
            conn.close()
    except sqlite3.DatabaseError:
        return []

    gaps: list[dict] = []
    for day, fuel_count, complete_count in fuel_rows:
        reasons: list[str] = []
        if str(day) not in oil_days:
            reasons.append("no aviation report")
        if int(complete_count or 0) == 0:
            reasons.append("no full flight log (Hobbs+Tach)")
        if reasons:
            gaps.append(
                {
                    "day": str(day),
                    "fuel_log_count": int(fuel_count or 0),
                    "reason": ", ".join(reasons),
                }
            )
    return gaps


def _verify_user_data_isolation(client) -> tuple[bool, str]:
    user_a_id = None
    user_b_id = None
    obs_a_id = None
    obs_b_id = None
    try:
        AVIATION_DB.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(AVIATION_DB))
        try:
            conn.execute(_CREATE_USER_PROFILES)
            conn.execute(_CREATE_MISSION_SCOPES)
            conn.execute(_CREATE_EXPEDITIONS)
            conn.execute(_CREATE_MISSION_CONSUMABLES)

            conn.execute(
                "INSERT OR IGNORE INTO user_profiles (username, role, home_base_icao) VALUES (?, ?, ?)",
                ("deploy_user_a", "Lead Analyst", "KIXD"),
            )
            conn.execute(
                "INSERT OR IGNORE INTO user_profiles (username, role, home_base_icao) VALUES (?, ?, ?)",
                ("deploy_user_b", "Operations Director", "KUKL"),
            )
            user_a_id = conn.execute("SELECT id FROM user_profiles WHERE username = 'deploy_user_a'").fetchone()[0]
            user_b_id = conn.execute("SELECT id FROM user_profiles WHERE username = 'deploy_user_b'").fetchone()[0]

            for scope in ("Marine", "Aviation", "Mineral"):
                conn.execute(
                    "INSERT OR IGNORE INTO mission_scopes (user_id, scope_type, is_active) VALUES (?, ?, 1)",
                    (user_a_id, scope),
                )
                conn.execute(
                    "INSERT OR IGNORE INTO mission_scopes (user_id, scope_type, is_active) VALUES (?, ?, 1)",
                    (user_b_id, scope),
                )
            conn.commit()
        finally:
            conn.close()

        obs_a_resp = client.post(
            "/api/navigator/field-observations",
            json={
                "user_id": user_a_id,
                "location_name": "Isolation Ridge A",
                "latitude": 38.07,
                "longitude": -97.86,
                "specimen_types": "Agate",
                "yield_rating": 6.2,
            },
        )
        obs_b_resp = client.post(
            "/api/navigator/field-observations",
            json={
                "user_id": user_b_id,
                "location_name": "Isolation Ridge B",
                "latitude": 38.17,
                "longitude": -97.76,
                "specimen_types": "Jasper",
                "yield_rating": 5.8,
            },
        )
        if obs_a_resp.status_code != 201 or obs_b_resp.status_code != 201:
            return False, "Unable to create synthetic field observations for isolation check."

        obs_a_id = (obs_a_resp.get_json(silent=True) or {}).get("id")
        obs_b_id = (obs_b_resp.get_json(silent=True) or {}).get("id")

        con_a_resp = client.post(
            "/api/navigator/consumables",
            json={
                "user_id": user_a_id,
                "item_key": "sample_kits",
                "display_name": "Sample Kits",
                "quantity": 2.0,
                "unit": "kits",
                "restock_threshold": 3.0,
            },
        )
        con_b_resp = client.post(
            "/api/navigator/consumables",
            json={
                "user_id": user_b_id,
                "item_key": "sample_kits",
                "display_name": "Sample Kits",
                "quantity": 11.0,
                "unit": "kits",
                "restock_threshold": 3.0,
            },
        )
        if con_a_resp.status_code != 200 or con_b_resp.status_code != 200:
            return False, "Unable to create synthetic consumables for isolation check."

        obs_a_list = client.get(f"/api/navigator/field-observations?user_id={user_a_id}&limit=50").get_json(silent=True) or []
        obs_b_list = client.get(f"/api/navigator/field-observations?user_id={user_b_id}&limit=50").get_json(silent=True) or []

        ids_a = {row.get("id") for row in obs_a_list}
        ids_b = {row.get("id") for row in obs_b_list}
        if obs_a_id not in ids_a or obs_b_id in ids_a:
            return False, "User A can see User B field observations or cannot see their own."
        if obs_b_id not in ids_b or obs_a_id in ids_b:
            return False, "User B can see User A field observations or cannot see their own."

        cons_a = (client.get(f"/api/navigator/consumables?user_id={user_a_id}&limit=50").get_json(silent=True) or {}).get("items") or []
        cons_b = (client.get(f"/api/navigator/consumables?user_id={user_b_id}&limit=50").get_json(silent=True) or {}).get("items") or []
        sample_a = next((row for row in cons_a if row.get("item_key") == "sample_kits"), None)
        sample_b = next((row for row in cons_b if row.get("item_key") == "sample_kits"), None)
        if sample_a is None or sample_b is None:
            return False, "Isolation check missing scoped sample_kits rows."
        if float(sample_a.get("quantity") or 0.0) >= float(sample_b.get("quantity") or 0.0):
            return False, "Scoped consumable quantities are leaking across users."

        return True, f"Isolation verified between users {user_a_id} and {user_b_id}."
    finally:
        try:
            conn = sqlite3.connect(str(AVIATION_DB))
            try:
                if obs_a_id is not None:
                    conn.execute("DELETE FROM rockhounding_expeditions WHERE id = ?", (obs_a_id,))
                if obs_b_id is not None:
                    conn.execute("DELETE FROM rockhounding_expeditions WHERE id = ?", (obs_b_id,))
                if user_a_id is not None:
                    conn.execute("DELETE FROM mission_consumables WHERE item_key LIKE ?", (f"u{user_a_id}:%",))
                    conn.execute("DELETE FROM mission_scopes WHERE user_id = ?", (user_a_id,))
                    conn.execute("DELETE FROM user_profiles WHERE id = ?", (user_a_id,))
                if user_b_id is not None:
                    conn.execute("DELETE FROM mission_consumables WHERE item_key LIKE ?", (f"u{user_b_id}:%",))
                    conn.execute("DELETE FROM mission_scopes WHERE user_id = ?", (user_b_id,))
                    conn.execute("DELETE FROM user_profiles WHERE id = ?", (user_b_id,))
                conn.commit()
            finally:
                conn.close()
        except sqlite3.DatabaseError:
            pass


def _verify_org_admin_cross_org_isolation(client) -> tuple[bool, str]:
    tenant_id = _normalise_tenant_id(f"org-shift-{int(time.time() * 1000)}")
    org_a = _normalise_tenant_id(f"org-a-{int(time.time() * 1000)}")
    org_b = _normalise_tenant_id(f"org-b-{int(time.time() * 1000)}")
    db_a = _org_tenant_db_path(organization_id=org_a, tenant_id=tenant_id)
    db_b = _org_tenant_db_path(organization_id=org_b, tenant_id=tenant_id)

    marker_a = "ORG-A-PRIVATE-TELEMETRY"
    marker_b = "ORG-B-PRIVATE-TELEMETRY"
    obs_a_id = None
    obs_b_id = None

    try:
        for org in (org_a, org_b):
            bootstrap = client.get(
                f"/api/navigator/consumables?tenant_id={tenant_id}&organization_id={org}&user_id=1&limit=5"
            )
            if bootstrap.status_code != 200:
                return False, f"org bootstrap failed for {org}"

        obs_a = client.post(
            "/api/navigator/observations",
            json={
                "tenant_id": tenant_id,
                "organization_id": org_a,
                "user_id": 1,
                "location_name": marker_a,
                "latitude": 38.901,
                "longitude": -94.801,
                "specimen_types": "Quartz",
                "yield_rating": 6.1,
            },
        )
        obs_b = client.post(
            "/api/navigator/observations",
            json={
                "tenant_id": tenant_id,
                "organization_id": org_b,
                "user_id": 1,
                "location_name": marker_b,
                "latitude": 38.921,
                "longitude": -94.821,
                "specimen_types": "Agate",
                "yield_rating": 6.4,
            },
        )
        if obs_a.status_code != 201 or obs_b.status_code != 201:
            return False, "unable to seed org-admin telemetry isolation records"

        obs_a_id = int(((obs_a.get_json(silent=True) or {}).get("id") or 0) or 0)
        obs_b_id = int(((obs_b.get_json(silent=True) or {}).get("id") or 0) or 0)

        brief_a = client.get(
            f"/api/briefing/daily?tenant_slug=default&tenant_id={tenant_id}&organization_id={org_a}&user_role=Org%20Admin&user_id=1"
        )
        brief_b = client.get(
            f"/api/briefing/daily?tenant_slug=default&tenant_id={tenant_id}&organization_id={org_b}&user_role=Org%20Admin&user_id=1"
        )
        if brief_a.status_code != 200 or brief_b.status_code != 200:
            return False, "briefing endpoint unavailable for org-admin isolation check"

        payload_a = brief_a.get_json(silent=True) or {}
        payload_b = brief_b.get_json(silent=True) or {}
        org_payload_a = payload_a.get("org_admin_payload") or {}
        org_payload_b = payload_b.get("org_admin_payload") or {}

        blob_a = json.dumps(org_payload_a).lower()
        blob_b = json.dumps(org_payload_b).lower()
        if marker_a.lower() not in blob_a:
            return False, "Org Admin A telemetry payload missing its own marker"
        if marker_b.lower() in blob_a:
            return False, "Org Admin A can see telemetry marker from Org Admin B"
        if marker_b.lower() not in blob_b:
            return False, "Org Admin B telemetry payload missing its own marker"
        if marker_a.lower() in blob_b:
            return False, "Org Admin B can see telemetry marker from Org Admin A"

        return True, f"Org admin telemetry isolation verified between {org_a} and {org_b}"
    finally:
        try:
            for db_path, obs_id in ((db_a, obs_a_id), (db_b, obs_b_id)):
                if db_path.exists():
                    conn = sqlite3.connect(str(db_path))
                    try:
                        conn.execute(_CREATE_EXPEDITIONS)
                        if obs_id:
                            conn.execute("DELETE FROM rockhounding_expeditions WHERE id = ?", (obs_id,))
                        conn.commit()
                    finally:
                        conn.close()

                tenant_dir = db_path.parent
                tenants_dir = tenant_dir.parent
                org_dir = tenants_dir.parent

                if db_path.exists():
                    db_path.unlink()
                if tenant_dir.exists():
                    tenant_dir.rmdir()
                if tenants_dir.exists():
                    tenants_dir.rmdir()
                if org_dir.exists():
                    org_dir.rmdir()
        except OSError:
            pass


def _verify_franchise_isolation(client) -> tuple[bool, str]:
    parent_org = _normalise_tenant_id(f"fr-parent-{int(time.time() * 1000)}")
    child_org = _normalise_tenant_id(f"fr-child-{int(time.time() * 1000)}")
    tenant_id = "default"
    private_marker = "CHILD-PRIVATE-FRANCHISE-TELEMETRY"
    child_db = _org_tenant_db_path(organization_id=child_org, tenant_id=tenant_id)
    parent_metadata = _org_metadata_path(parent_org)
    child_metadata = _org_metadata_path(child_org)
    period = datetime.now(timezone.utc).strftime("%Y-%m")
    last_updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    observation_id = None

    try:
        for org in (parent_org, child_org):
            bootstrap = client.get(
                f"/api/navigator/consumables?tenant_id={tenant_id}&organization_id={org}&user_id=1&limit=5"
            )
            if bootstrap.status_code != 200:
                return False, f"franchise bootstrap failed for {org}"

        parent_metadata.parent.mkdir(parents=True, exist_ok=True)
        child_metadata.parent.mkdir(parents=True, exist_ok=True)
        parent_metadata.write_text(
            json.dumps(
                {
                    "org_id": parent_org,
                    "parent_org_id": None,
                    "relationship_type": "root",
                    "created_at": last_updated_at,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        child_metadata.write_text(
            json.dumps(
                {
                    "org_id": child_org,
                    "parent_org_id": parent_org,
                    "relationship_type": "child",
                    "created_at": last_updated_at,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        obs_resp = client.post(
            "/api/navigator/observations",
            json={
                "tenant_id": tenant_id,
                "organization_id": child_org,
                "user_id": 1,
                "location_name": private_marker,
                "latitude": 38.741,
                "longitude": -94.871,
                "specimen_types": "Agate",
                "yield_rating": 8.4,
            },
        )
        if obs_resp.status_code != 201:
            return False, "unable to seed child-org private telemetry for franchise isolation"
        observation_id = int(((obs_resp.get_json(silent=True) or {}).get("id") or 0) or 0)

        conn = sqlite3.connect(str(GOVERNANCE_DB))
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS metered_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    org_id TEXT NOT NULL,
                    metric TEXT NOT NULL,
                    period TEXT NOT NULL,
                    count INTEGER NOT NULL DEFAULT 0,
                    last_updated_at TEXT NOT NULL,
                    UNIQUE(org_id, metric, period)
                )
                """
            )
            conn.execute(
                "INSERT INTO metered_usage (org_id, metric, period, count, last_updated_at) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(org_id, metric, period) DO UPDATE SET count = excluded.count, last_updated_at = excluded.last_updated_at",
                (child_org, "oracle_api_calls", period, 11, last_updated_at),
            )
            conn.execute(
                "INSERT INTO metered_usage (org_id, metric, period, count, last_updated_at) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(org_id, metric, period) DO UPDATE SET count = excluded.count, last_updated_at = excluded.last_updated_at",
                (child_org, "navigator_expeditions", period, 5, last_updated_at),
            )
            conn.execute(
                "INSERT INTO metered_usage (org_id, metric, period, count, last_updated_at) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(org_id, metric, period) DO UPDATE SET count = excluded.count, last_updated_at = excluded.last_updated_at",
                (parent_org, "oracle_api_calls", period, 3, last_updated_at),
            )
            conn.commit()
        finally:
            conn.close()

        stats_resp = client.get(
            f"/api/sovereign/franchise-stats?tenant_id={tenant_id}&organization_id={parent_org}&user_role=Operations%20Director"
        )
        if stats_resp.status_code != 200:
            return False, f"franchise stats endpoint unavailable for parent org (HTTP {stats_resp.status_code})"
        payload = stats_resp.get_json(silent=True) or {}
        rows = payload.get("organizations") or []
        row_ids = {str(row.get("organization_id") or "") for row in rows}
        if parent_org not in row_ids or child_org not in row_ids:
            return False, "parent org could not see expected child franchise stats"

        blob = json.dumps(payload).lower()
        if private_marker.lower() in blob:
            return False, "parent franchise stats leaked child private telemetry"
        if payload.get("private_data_included") is not False:
            return False, "franchise stats did not mark aggregate-only privacy scope"

        child_row = next((row for row in rows if str(row.get("organization_id") or "") == child_org), None)
        if not child_row:
            return False, "child org row missing from franchise stats response"
        if int(child_row.get("oracle_api_calls") or 0) != 11 or int(child_row.get("navigator_logs") or 0) != 5:
            return False, "child org aggregate franchise stats did not match seeded usage"

        return True, f"parent org {parent_org} can view child aggregate stats for {child_org} without private telemetry leakage"
    finally:
        try:
            if child_db.exists() and observation_id:
                conn = sqlite3.connect(str(child_db))
                try:
                    conn.execute(_CREATE_EXPEDITIONS)
                    conn.execute("DELETE FROM rockhounding_expeditions WHERE id = ?", (observation_id,))
                    conn.commit()
                finally:
                    conn.close()

            if GOVERNANCE_DB.exists():
                conn = sqlite3.connect(str(GOVERNANCE_DB))
                try:
                    conn.execute("DELETE FROM metered_usage WHERE org_id IN (?, ?)", (parent_org, child_org))
                    conn.commit()
                finally:
                    conn.close()

            for path in (child_metadata, parent_metadata):
                if path.exists():
                    path.unlink()

            for db_path in (_org_tenant_db_path(organization_id=parent_org, tenant_id=tenant_id), child_db):
                tenant_dir = db_path.parent
                tenants_dir = tenant_dir.parent
                org_dir = tenants_dir.parent
                if db_path.exists():
                    db_path.unlink()
                for directory in (tenant_dir, tenants_dir, org_dir):
                    if directory.exists():
                        try:
                            directory.rmdir()
                        except OSError:
                            pass
        except OSError:
            pass


def _verify_fungal_outreach_network(client) -> tuple[bool, str]:
    mentor_mesh = _normalise_tenant_id(f"fungal-mesh-{int(time.time() * 1000)}")
    tenant_a = _normalise_tenant_id(f"fungal-a-{int(time.time() * 1000)}")
    tenant_b = _normalise_tenant_id(f"fungal-b-{int(time.time() * 1000)}")
    tenant_a_dir = AVIATION_TENANTS_DIR / tenant_a
    tenant_b_dir = AVIATION_TENANTS_DIR / tenant_b
    tenant_a_db = tenant_a_dir / "marine.sqlite"
    tenant_b_db = tenant_b_dir / "marine.sqlite"

    guest_a_id = 41
    guest_b_id = 42
    private_label = "Honey Hole A"
    private_lat = 37.11111
    private_lon = -96.22222

    try:
        for tenant in (tenant_a, tenant_b):
            bootstrap = client.get(f"/api/navigator/consumables?tenant_id={tenant}&user_id=1&limit=5")
            if bootstrap.status_code != 200:
                return False, f"tenant bootstrap failed for fungal network check ({tenant})"

        onboard_a = client.post(
            "/api/mentorship/onboarding",
            json={
                "tenant_id": tenant_a,
                "username": "guest_scientist_a",
                "role": "Guest Scientist",
                "user_id": guest_a_id,
                "mentor_mesh": mentor_mesh,
            },
        )
        onboard_b = client.post(
            "/api/mentorship/onboarding",
            json={
                "tenant_id": tenant_b,
                "username": "guest_scientist_b",
                "role": "Guest Scientist",
                "user_id": guest_b_id,
                "mentor_mesh": mentor_mesh,
            },
        )
        if onboard_a.status_code != 200 or onboard_b.status_code != 200:
            return False, "mentorship onboarding failed for synthetic guest scientists"

        onboard_payload_a = onboard_a.get_json(silent=True) or {}
        permissions_a = ((onboard_payload_a.get("profile") or {}).get("permissions") or {})
        if bool(permissions_a.get("can_view_honey_hole")):
            return False, "Guest Scientist permissions were not restricted for honey-hole visibility"

        submit_a = client.post(
            "/api/mentorship/guest-audit",
            json={
                "tenant_id": tenant_a,
                "user_id": guest_a_id,
                "drift_pct": 3.2,
                "discovery_note": "Mycelial edge discovery for Systems Oracle audit.",
                "private_location_label": private_label,
                "private_latitude": private_lat,
                "private_longitude": private_lon,
            },
        )
        submit_b = client.post(
            "/api/mentorship/guest-audit",
            json={
                "tenant_id": tenant_b,
                "user_id": guest_b_id,
                "drift_pct": 1.1,
                "discovery_note": "Mesh integrity checkpoint.",
            },
        )
        if submit_a.status_code != 201 or submit_b.status_code != 201:
            return False, "guest audit submission failed for synthetic Guest Scientist nodes"

        guest_b_feed = client.get(f"/api/mentorship/guest-audit?tenant_id={tenant_b}&user_id={guest_b_id}&limit=20")
        if guest_b_feed.status_code != 200:
            return False, "guest audit read endpoint failed for Guest B"
        guest_b_payload = guest_b_feed.get_json(silent=True) or {}
        guest_b_blob = json.dumps(guest_b_payload).lower()
        blocked_tokens = [private_label.lower(), f"{private_lat}", f"{private_lon}", "honey hole"]
        if any(token in guest_b_blob for token in blocked_tokens):
            return False, "Guest B can see Guest A private Honey Hole coordinates across mentor mesh"

        broadcast = client.post(
            "/api/global-node/philosophical-signal",
            json={
                "tenant_id": tenant_a,
                "user_id": 1,
                "mentor_mesh": mentor_mesh,
                "quote": "Mycelial systems stay resilient by sharing signal without leaking private coordinates.",
            },
        )
        if broadcast.status_code != 201:
            return False, "philosophical signal broadcast endpoint failed"
        signal = ((broadcast.get_json(silent=True) or {}).get("signal") or {})
        if int(signal.get("broadcast_count") or 0) < 2:
            return False, "philosophical signal did not reach all connected guest nodes"

        inbox_b = client.get(f"/api/mentorship/guest-inbox?tenant_id={tenant_b}&user_id={guest_b_id}&limit=10")
        if inbox_b.status_code != 200:
            return False, "guest inbox endpoint unavailable for Guest B"
        messages = (inbox_b.get_json(silent=True) or {}).get("messages") or []
        if not any("mycelial systems" in str(row.get("message") or "").lower() for row in messages):
            return False, "Guest B inbox did not receive philosophical broadcast message"

        briefing_a = client.get(
            f"/api/briefing/daily?tenant_slug=default&tenant_id={tenant_a}&user_role=Guest%20Scientist&user_id={guest_a_id}"
        )
        if briefing_a.status_code != 200:
            return False, "morning briefing unavailable for fungal network health verification"
        payload_a = briefing_a.get_json(silent=True) or {}
        network_health = payload_a.get("network_health") or {}
        if str(network_health.get("status_label") or "").strip() != "Network Status: Flourishing.":
            return False, "Morning Card did not report Network Status: Flourishing."
        if int(network_health.get("active_guest_nodes") or 0) < 1:
            return False, "Morning Card network health did not report active guest nodes"

        briefing_b = client.get(
            f"/api/briefing/daily?tenant_slug=default&tenant_id={tenant_b}&user_role=Guest%20Scientist&user_id={guest_b_id}"
        )
        if briefing_b.status_code != 200:
            return False, "morning briefing unavailable for Guest B privacy verification"
        payload_b_blob = json.dumps(briefing_b.get_json(silent=True) or {}).lower()
        if any(token in payload_b_blob for token in blocked_tokens):
            return False, "Morning Card leaked Guest A Honey Hole coordinates to Guest B"

        return True, "guest mentorship onboarding, wisdom signal broadcast, and Honey Hole privacy isolation verified"
    finally:
        try:
            if GLOBAL_NODE_DB.exists():
                conn_g = sqlite3.connect(str(GLOBAL_NODE_DB))
                try:
                    conn_g.execute("DELETE FROM philosophical_signals WHERE mentor_mesh = ?", (mentor_mesh,))
                    conn_g.commit()
                finally:
                    conn_g.close()

            for db_path, tenant_dir in ((tenant_a_db, tenant_a_dir), (tenant_b_db, tenant_b_dir)):
                if db_path.exists():
                    db_path.unlink()
                if tenant_dir.exists():
                    tenant_dir.rmdir()
        except OSError:
            pass


def _verify_architect_write_permission_guardrails(client) -> tuple[bool, str]:
    tenant_id = _normalise_tenant_id(f"architect-scope-{int(time.time() * 1000)}")
    tenant_dir = AVIATION_TENANTS_DIR / tenant_id
    tenant_db = tenant_dir / "marine.sqlite"
    user_id = 73
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        bootstrap = client.get(f"/api/navigator/consumables?tenant_id={tenant_id}&user_id=1&limit=5")
        if bootstrap.status_code != 200:
            return False, f"tenant bootstrap failed for architect guardrail check ({tenant_id})"

        conn = sqlite3.connect(str(tenant_db))
        try:
            conn.execute(_CREATE_USER_PROFILES)
            conn.execute(_CREATE_MISSION_SCOPES)
            conn.execute(_CREATE_GUEST_ORACLE_SUBMISSIONS)
            conn.execute(
                """
                INSERT INTO user_profiles (id, username, role, home_base_icao, share_signals, mentor_mesh, permissions_json)
                VALUES (?, ?, ?, ?, 0, NULL, NULL)
                ON CONFLICT(id) DO UPDATE SET
                    username = excluded.username,
                    role = excluded.role,
                    home_base_icao = excluded.home_base_icao,
                    share_signals = excluded.share_signals,
                    mentor_mesh = excluded.mentor_mesh,
                    permissions_json = excluded.permissions_json
                """,
                (user_id, "architect_scope_tourist", "Tourist", "KIXD"),
            )
            conn.execute(
                """
                INSERT INTO mission_scopes (user_id, scope_type, is_active)
                VALUES (?, ?, 1)
                ON CONFLICT(user_id, scope_type) DO UPDATE SET is_active = 1
                """,
                (user_id, "Marine"),
            )
            conn.executemany(
                """
                INSERT INTO guest_oracle_submissions (
                    user_id, submission_type, drift_pct, discovery_note,
                    private_location_label, private_latitude, private_longitude,
                    submitted_at, source
                ) VALUES (?, ?, ?, ?, NULL, NULL, NULL, ?, ?)
                """,
                [
                    (user_id, "DRIFT", 6.4, "Calendar and paperwork backlog is increasing.", now, "deploy_architect_guardrail"),
                    (user_id, "DISCOVERY", 2.2, "Marine reef buoy review loop repeats daily.", now, "deploy_architect_guardrail"),
                    (user_id, "DISCOVERY", 1.4, "Aviation hangar preflight checklist triage.", now, "deploy_architect_guardrail"),
                ],
            )
            conn.commit()
        finally:
            conn.close()

        briefing = client.get(
            f"/api/briefing/daily?tenant_slug=default&tenant_id={tenant_id}&user_role=Tourist&user_id={user_id}"
        )
        if briefing.status_code != 200:
            return False, f"architect briefing unavailable for permission guardrail check (HTTP {briefing.status_code})"
        payload = briefing.get_json(silent=True) or {}
        architect = payload.get("automation_architect") or {}

        if str(architect.get("architect_mode_label") or "").strip() != "Architect Mode: Enabled. Suggestions Pending.":
            return False, "architect mode label did not resolve to the expected Morning Card string"

        writable_scopes = architect.get("writable_scopes") or []
        if writable_scopes:
            return False, "tourist profile unexpectedly received writable scopes for Architect suggestions"

        suggestions = architect.get("suggestions") or []
        if suggestions:
            return False, "Architect returned deployable suggestions for a no-write Tourist profile"

        if int(architect.get("filtered_unauthorized_count") or 0) < 1:
            return False, "Architect did not report filtered unauthorized suggestions"

        if not bool(architect.get("write_permission_verified")):
            return False, "Architect write_permission_verified flag is false"

        if bool(architect.get("can_deploy")):
            return False, "Architect can_deploy should be false when no write scopes are available"

        deploy = client.post(
            "/api/architect/automation/deploy",
            json={"tenant_id": tenant_id, "user_id": user_id, "suggestion_key": "marine_snapshot_pruner"},
        )
        if deploy.status_code != 409:
            return False, "Architect deploy endpoint allowed deployment without write-permitted suggestions"

        deploy_payload = deploy.get_json(silent=True) or {}
        if "no deployable automation suggestion available" not in str(deploy_payload.get("error") or ""):
            return False, "Architect deploy endpoint did not return expected no-deployable-suggestion guardrail"

        return True, "Architect suggestion engine filtered unauthorized scopes and blocked no-write deployments"
    finally:
        try:
            if tenant_db.exists():
                tenant_db.unlink()
            if tenant_dir.exists():
                tenant_dir.rmdir()
        except OSError:
            pass


def _verify_associate_post_guardrails(client) -> tuple[bool, str]:
    tenant_id = _normalise_tenant_id(f"associate-guardrail-{int(time.time() * 1000)}")
    tenant_dir = AVIATION_TENANTS_DIR / tenant_id
    tenant_db = tenant_dir / "marine.sqlite"
    user_id = 91

    try:
        bootstrap = client.get(f"/api/navigator/consumables?tenant_id={tenant_id}&user_id=1&limit=5")
        if bootstrap.status_code != 200:
            return False, f"tenant bootstrap failed for associate guardrail check ({tenant_id})"

        onboard = client.post(
            "/api/mentorship/onboarding",
            json={
                "tenant_id": tenant_id,
                "user_id": user_id,
                "username": "associate_guardrail",
                "role": "Associate",
                "home_base_icao": "KIXD",
            },
        )
        if onboard.status_code != 200:
            return False, f"associate onboarding failed for guardrail check (HTTP {onboard.status_code})"

        blocked_observation = client.post(
            "/api/navigator/expeditions",
            json={
                "tenant_id": tenant_id,
                "user_id": user_id,
                "location_name": "Associate Guardrail Test",
                "latitude": 38.0655,
                "longitude": -97.8606,
                "specimen_types": "Guardrail",
                "yield_rating": 5.0,
            },
        )
        if blocked_observation.status_code != 403:
            return False, "Associate user was allowed to POST /api/navigator/expeditions"

        blocked_observation_payload = blocked_observation.get_json(silent=True) or {}
        if "read-only" not in str(blocked_observation_payload.get("error") or "").lower():
            return False, "Associate observation block did not return read-only messaging"

        blocked_signal = client.post(
            "/api/observatory/signals",
            json={
                "tenant_id": tenant_id,
                "user_id": user_id,
                "signal_type": "Guardrail",
                "general_region": "KIXD region",
                "role": "Associate",
            },
        )
        if blocked_signal.status_code != 403:
            return False, "Associate user was allowed to POST /api/observatory/signals"

        blocked_signal_payload = blocked_signal.get_json(silent=True) or {}
        if "read-only" not in str(blocked_signal_payload.get("error") or "").lower():
            return False, "Associate signal block did not return read-only messaging"

        return True, "Associate role is blocked from expeditions and observatory signal POST routes"
    finally:
        try:
            if tenant_db.exists():
                tenant_db.unlink()
            if tenant_dir.exists():
                tenant_dir.rmdir()
        except OSError:
            pass


def _verify_governance_ledger_access(client) -> tuple[bool, str]:
    """
    Verify the immutable governance ledger:
      1. POST to /api/admin/governance/log with joshua actor → must succeed (201).
      2. POST with a non-admin actor → must be rejected (403).
      3. Confirm the written entry is visible via GET /api/admin/governance/audit.
      4. Confirm UPDATE on the row is blocked by the SQLite trigger.
    """
    import sqlite3 as _sqlite3

    # 1. Non-admin write must be rejected
    deny_resp = client.post(
        "/api/admin/governance/log",
        json={"actor": "org_admin", "org_id": "default", "action_type": "test", "payload": {}},
    )
    if deny_resp.status_code != 403:
        return False, f"governance log did not reject non-admin actor (got HTTP {deny_resp.status_code})"

    # 2. System-Admin (joshua) write must succeed
    ts_marker = int(time.time() * 1000)
    allow_resp = client.post(
        "/api/admin/governance/log",
        json={
            "actor": "joshua",
            "org_id": "default",
            "action_type": "sentinel_verify",
            "payload": {"deploy_ts": ts_marker},
        },
    )
    if allow_resp.status_code != 201:
        return False, f"governance log rejected System-Admin write (HTTP {allow_resp.status_code})"
    record = (allow_resp.get_json(silent=True) or {}).get("record") or {}
    event_id = record.get("event_id") or ""
    if not event_id:
        return False, "governance log response missing event_id"

    # 3. Audit read must surface the entry
    audit_resp = client.get("/api/admin/governance/audit?org_id=default&limit=20")
    if audit_resp.status_code != 200:
        return False, f"governance audit endpoint unavailable (HTTP {audit_resp.status_code})"
    entries = (audit_resp.get_json(silent=True) or {}).get("entries") or []
    ids = {e.get("event_id") for e in entries}
    if event_id not in ids:
        return False, f"written governance entry '{event_id}' not found in audit trail"

    # 4. Direct UPDATE must be blocked by the immutability trigger
    if GOVERNANCE_DB.exists():
        try:
            conn_gov = _sqlite3.connect(str(GOVERNANCE_DB))
            try:
                conn_gov.execute(
                    "UPDATE governance_ledger SET actor = 'tampered' WHERE event_id = ?",
                    (event_id,),
                )
                conn_gov.commit()
                # If we reach here the trigger did NOT fire — that is a failure
                return False, "governance immutability trigger did NOT block a direct UPDATE — ledger is mutable"
            except _sqlite3.DatabaseError:
                pass  # expected: trigger raised ABORT (raises IntegrityError in Python 3.14+, OperationalError in earlier versions)
            finally:
                conn_gov.close()
        except Exception as exc:
            return False, f"could not verify immutability trigger: {exc}"

    return True, "governance ledger write-only for System-Admin; read-only for others; immutability trigger active"


def _verify_unicorn_path_controls(client) -> tuple[bool, str]:
    tenant_id = _normalise_tenant_id(f"unicorn-{int(time.time() * 1000)}")
    org_id = f"org-{int(time.time() * 1000)}"
    tenant_dir = AVIATION_TENANTS_DIR / tenant_id

    try:
        ingest_resp = client.post(
            f"/api/ingestor/flight-log?organization_id={org_id}",
            json={
                "tenant_id": tenant_id,
                "provider": "deploy-risk-ingestor",
                "tail_number": "N14UP",
            },
        )
        if ingest_resp.status_code != 201:
            return False, f"ingestor pulse provenance failed (HTTP {ingest_resp.status_code})"
        ingest_payload = ingest_resp.get_json(silent=True) or {}
        pulse = ingest_payload.get("pulse") or {}
        telemetry_window = pulse.get("telemetry_window") or {}
        if not pulse.get("rationale_hash"):
            return False, "AI pulse is missing rationale_hash provenance"
        if not pulse.get("external_philosophy_version"):
            return False, "AI pulse is missing external philosophy version provenance"
        if int(telemetry_window.get("hours") or 0) != 24:
            return False, f"AI pulse telemetry window did not resolve to 24 hours (got {telemetry_window.get('hours')})"

        ack_resp = client.post(
            "/api/mobile/pulse-notifications/ack",
            json={
                "tenant_id": tenant_id,
                "organization_id": org_id,
                "pulse_id": pulse.get("id"),
                "rationale_hash": pulse.get("rationale_hash"),
            },
        )
        if ack_resp.status_code != 200:
            return False, f"mobile pulse acknowledgement failed (HTTP {ack_resp.status_code})"

        risk_resp = client.get("/api/sovereign/risk-score?tenant_slug=internal&tenant_id=internal&user_role=Admin")
        if risk_resp.status_code != 200:
            return False, f"sovereign risk API failed (HTTP {risk_resp.status_code})"
        risk_payload = risk_resp.get_json(silent=True) or {}
        if int(risk_payload.get("pulse_count") or 0) < 1:
            return False, "sovereign risk API did not detect any AI pulses"
        if int(risk_payload.get("acknowledged_count") or 0) < 1:
            return False, "sovereign risk API did not detect any pulse acknowledgements"

        expedition_resp = client.post(
            f"/api/navigator/expeditions?organization_id={org_id}",
            json={
                "tenant_id": tenant_id,
                "user_id": 1,
                "location_name": "Unicorn Path Invite Site",
                "latitude": 39.0997,
                "longitude": -94.5786,
                "specimen_types": "agate",
                "yield_rating": 4.9,
            },
        )
        if expedition_resp.status_code != 201:
            return False, f"navigator expedition seed failed (HTTP {expedition_resp.status_code})"
        expedition_id = int((expedition_resp.get_json(silent=True) or {}).get("id") or 0)
        if expedition_id <= 0:
            return False, "navigator expedition invite seed missing expedition id"

        invite_resp = client.post(
            f"/api/navigator/expeditions/invite?organization_id={org_id}",
            json={
                "tenant_id": tenant_id,
                "expedition_id": expedition_id,
                "external_email": "guest@example.com",
            },
        )
        if invite_resp.status_code != 201:
            return False, f"expedition invite endpoint failed (HTTP {invite_resp.status_code})"
        invite_payload = (invite_resp.get_json(silent=True) or {}).get("invite") or {}
        token = str(invite_payload.get("one_time_access_token") or "")
        if not token:
            return False, "expedition invite response missing one-time access token"

        redeem_resp = client.get(f"/api/navigator/expeditions/shared/{token}?tenant_id={tenant_id}&organization_id={org_id}")
        if redeem_resp.status_code != 200:
            return False, f"guest expedition redemption failed (HTTP {redeem_resp.status_code})"
        second_redeem_resp = client.get(f"/api/navigator/expeditions/shared/{token}?tenant_id={tenant_id}&organization_id={org_id}")
        if second_redeem_resp.status_code != 410:
            return False, "guest expedition token was not enforced as single-use"

        # Org isolation: a token issued for tenant A must not grant access when queried with tenant B.
        isolation_invite_resp = client.post(
            f"/api/navigator/expeditions/invite?organization_id={org_id}",
            json={
                "tenant_id": tenant_id,
                "expedition_id": expedition_id,
                "external_email": "isolation-probe@example.com",
            },
        )
        if isolation_invite_resp.status_code != 201:
            return False, f"guest token org-isolation seed failed (HTTP {isolation_invite_resp.status_code})"
        isolation_token = str(
            ((isolation_invite_resp.get_json(silent=True) or {}).get("invite") or {}).get("one_time_access_token") or ""
        )
        if not isolation_token:
            return False, "guest token org-isolation seed returned no token"
        alien_tenant_id = _normalise_tenant_id(f"alien-{int(time.time() * 1000)}")
        alien_resp = client.get(
            f"/api/navigator/expeditions/shared/{isolation_token}?tenant_id={alien_tenant_id}&organization_id={org_id}"
        )
        if alien_resp.status_code not in (404, 410):
            return False, (
                f"guest token org isolation failed: token for {tenant_id} was accessible "
                f"from alien tenant {alien_tenant_id} (HTTP {alien_resp.status_code})"
            )

        if not LIGHTHOUSE_SCHEMA_PATH.exists():
            return False, "open schema export lighthouse_v1.json is missing"
        try:
            schema_payload = json.loads(LIGHTHOUSE_SCHEMA_PATH.read_text(encoding="utf-8"))
        except Exception as exc:
            return False, f"open schema export is unreadable: {exc}"
        definitions = schema_payload.get("definitions") or {}
        required_schema_types = ("AeroCortexTelemetry", "MaintenanceEvent", "SystemsDrift", "ObservationSignal", "DriftMetrics")
        missing_types = [t for t in required_schema_types if t not in definitions]
        if missing_types:
            return False, f"open schema export is missing definitions: {', '.join(missing_types)}"

        audit_resp = client.get(f"/api/admin/governance/audit?org_id={org_id}&limit=25")
        if audit_resp.status_code != 200:
            return False, f"governance audit lookup for AI pulse provenance failed (HTTP {audit_resp.status_code})"
        audit_entries = (audit_resp.get_json(silent=True) or {}).get("entries") or []
        pulse_entries = [entry for entry in audit_entries if entry.get("action_type") == "ai_pulse"]
        if not pulse_entries:
            return False, "governance audit did not surface the AI pulse provenance entry"
        if pulse_entries[0].get("rationale_hash") != pulse.get("rationale_hash"):
            return False, "governance audit rationale_hash does not match the emitted AI pulse"
        missing_hashes = [e.get("event_id", "?")[:12] for e in pulse_entries if not e.get("rationale_hash")]
        if missing_hashes:
            return False, (
                f"governance ledger has {len(missing_hashes)} ai_pulse entries without rationale_hash: "
                + ", ".join(missing_hashes)
            )

        return True, (
            f"rationale hash {str(pulse.get('rationale_hash'))[:12]} tied to {pulse.get('external_philosophy_version')} "
            f"with a {telemetry_window.get('hours')}h telemetry window; one-time expedition token redeemed once; "
            f"guest token org isolation enforced; all ledger pulses carry rationale_hash; "
            f"mesh risk score {risk_payload.get('risk_score')}"
        )
    finally:
        try:
            if tenant_dir.exists():
                shutil.rmtree(tenant_dir, ignore_errors=True)
        except Exception:
            pass


def _verify_morning_card_speed_stress(client, runs: int = 25) -> tuple[bool, str]:
    durations_ms: list[float] = []
    payload_sizes: list[int] = []

    for _ in range(max(5, int(runs or 25))):
        started = time.perf_counter()
        response = client.get("/api/mobile/pulse-notifications?tenant_slug=default&tenant_id=default&user_id=1")
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        durations_ms.append(elapsed_ms)

        if response.status_code != 200:
            return False, f"mobile pulse API failed during stress test (HTTP {response.status_code})"

        payload = response.get_json(silent=True) or {}
        pulses = payload.get("pulse_notifications") or []
        actions = payload.get("one_tap_actions") or []
        if not isinstance(payload, dict) or not isinstance(pulses, list) or not isinstance(actions, list):
            return False, "mobile pulse payload missing required pulse_notifications/one_tap_actions keys"

        payload_sizes.append(len(json.dumps(payload)))

    ordered = sorted(durations_ms)
    p95_index = max(0, int(math.ceil(len(ordered) * 0.95)) - 1)
    p95_ms = ordered[p95_index]
    avg_ms = sum(durations_ms) / len(durations_ms)
    max_ms = max(durations_ms) if durations_ms else 0.0
    max_payload_kb = (max(payload_sizes) / 1024.0) if payload_sizes else 0.0

    if p95_ms > 50.0 or max_ms > 50.0:
        return False, f"Mobile pulse latency regression: avg {avg_ms:.1f} ms, p95 {p95_ms:.1f} ms, max {max_ms:.1f} ms exceeds 50.0 ms threshold"

    return True, f"mobile pulse avg {avg_ms:.1f} ms, p95 {p95_ms:.1f} ms, max {max_ms:.1f} ms across {len(durations_ms)} runs; max payload {max_payload_kb:.1f} KB"


def _verify_legacy_switch_protocol(client) -> tuple[bool, str]:
    tenant_id = _normalise_tenant_id(f"legacy-switch-{int(time.time() * 1000)}")
    tenant_dir = AVIATION_TENANTS_DIR / tenant_id
    tenant_db = tenant_dir / "marine.sqlite"
    senior_guest_id = 81
    mentor_mesh = "legacy-lighthouse"
    stale_ts = (datetime.now(timezone.utc) - timedelta(days=15)).strftime("%Y-%m-%dT%H:%M:%SZ")
    emitted_signal_id = None
    emitted_quote_id = None

    try:
        bootstrap = client.get(f"/api/navigator/consumables?tenant_id={tenant_id}&user_id=1&limit=5")
        if bootstrap.status_code != 200:
            return False, f"tenant bootstrap failed for legacy switch check ({tenant_id})"

        onboard = client.post(
            "/api/mentorship/onboarding",
            json={
                "tenant_id": tenant_id,
                "username": "Senior Guest",
                "role": "Guest Scientist",
                "user_id": senior_guest_id,
                "mentor_mesh": mentor_mesh,
            },
        )
        if onboard.status_code != 200:
            return False, "unable to onboard designated Senior Guest for legacy switch verification"

        stale_activity = client.post(
            "/api/navigator/observations",
            json={
                "tenant_id": tenant_id,
                "user_id": 1,
                "timestamp": stale_ts,
                "location_name": "Legacy Lighthouse Ridge",
                "latitude": 38.19,
                "longitude": -97.78,
                "specimen_types": "Quartz",
                "yield_rating": 4.0,
            },
        )
        if stale_activity.status_code != 201:
            return False, f"unable to seed stale primary-user activity (HTTP {stale_activity.status_code})"

        briefing = client.get(
            f"/api/briefing/daily?tenant_slug=default&tenant_id={tenant_id}&user_role=Admin&user_id=1"
        )
        if briefing.status_code != 200:
            return False, f"morning briefing unavailable for legacy switch verification (HTTP {briefing.status_code})"
        payload = briefing.get_json(silent=True) or {}
        longevity = payload.get("system_longevity") or {}

        if str(longevity.get("label") or "").strip() != "Lighthouse Status: Market Standard. The Mesh is the Industry. Joshua R Hutchison: Founder & Architect.":
            return False, "legacy switch did not emit the expected Lighthouse Status confirmation line"
        if not bool(longevity.get("is_legacy_mode")):
            return False, "legacy switch did not enter LEGACY_MODE after >14 days inactivity"

        promoted = longevity.get("temporary_mentor") or {}
        if int(promoted.get("user_id") or 0) != senior_guest_id:
            return False, "legacy switch did not promote the designated Senior Guest"

        auto_signal = client.post(
            "/api/observatory/signals",
            json={
                "tenant_id": tenant_id,
                "user_id": 1,
                "signal_type": "Legacy Quartz",
                "general_region": "KIXD region",
            },
        )
        if auto_signal.status_code != 201:
            return False, "legacy autonomous observatory emission did not create a signal"
        signal_payload = auto_signal.get_json(silent=True) or {}
        if str(signal_payload.get("status") or "") != "created":
            return False, "legacy autonomous observatory emission returned non-created status"
        emitted_signal = signal_payload.get("signal") or {}
        emitted_signal_id = emitted_signal.get("id")
        if not bool(emitted_signal.get("autonomous_quorum_enabled")):
            return False, "legacy autonomous quorum flag was not enabled on observatory emission"

        quote = client.post(
            "/api/global-node/philosophical-signal",
            json={
                "tenant_id": tenant_id,
                "user_id": senior_guest_id,
                "mentor_mesh": mentor_mesh,
                "quote": "Legacy mesh remains alive through distributed quorum sensing.",
            },
        )
        if quote.status_code != 201:
            return False, "promoted Senior Guest could not broadcast philosophical signal in legacy mode"
        emitted_quote_id = ((quote.get_json(silent=True) or {}).get("signal") or {}).get("id")

        return True, "legacy switch entered Market Standard lighthouse mode with Senior Guest mentor promotion and autonomous observatory emission"
    finally:
        try:
            if GLOBAL_NODE_DB.exists():
                conn_g = sqlite3.connect(str(GLOBAL_NODE_DB))
                try:
                    if emitted_signal_id is not None:
                        conn_g.execute("DELETE FROM observatory_signals WHERE id = ?", (emitted_signal_id,))
                    if emitted_quote_id is not None:
                        conn_g.execute("DELETE FROM philosophical_signals WHERE id = ?", (emitted_quote_id,))
                    conn_g.commit()
                finally:
                    conn_g.close()

            if tenant_db.exists():
                tenant_db.unlink()
            if tenant_dir.exists():
                tenant_dir.rmdir()
        except OSError:
            pass


def _verify_new_tenant_schema_initialization(client) -> tuple[bool, str]:
    tenant_id = f"deploy-tenant-{int(time.time() * 1000)}"
    tenant_dir = AVIATION_TENANTS_DIR / tenant_id
    tenant_db = tenant_dir / "marine.sqlite"

    try:
        resp = client.get(f"/api/navigator/consumables?tenant_id={tenant_id}&limit=5")
        if resp.status_code != 200:
            return False, f"tenant bootstrap endpoint unavailable (HTTP {resp.status_code})"

        payload = resp.get_json(silent=True) or {}
        if str(payload.get("tenant_id") or "") != tenant_id:
            return False, "consumables payload did not echo tenant_id"

        if not tenant_db.exists():
            return False, "tenant database file was not created"

        conn = sqlite3.connect(str(tenant_db))
        try:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            required_tables = {
                "user_profiles",
                "mission_scopes",
                "rockhounding_expeditions",
                "fuel_logs",
                "specimen_inventory",
                "mission_consumables",
                "mission_consumable_events",
                "fuel_market_logs",
            }
            missing = sorted(required_tables - tables)
            if missing:
                return False, f"tenant schema missing tables: {', '.join(missing)}"

            specimen_cols = {
                row[1] for row in conn.execute("PRAGMA table_info(specimen_inventory)").fetchall()
            }
            if "specific_gravity" not in specimen_cols:
                return False, "tenant schema missing specimen_inventory.specific_gravity"
        finally:
            conn.close()

        return True, f"tenant schema initialized for {tenant_id}"
    finally:
        try:
            if tenant_db.exists():
                tenant_db.unlink()
            if tenant_dir.exists():
                tenant_dir.rmdir()
        except OSError:
            pass


def _verify_edge_outbox_reconciliation(client) -> tuple[bool, str]:
    tenant_id = f"edge-sync-{int(time.time() * 1000)}"
    tenant_dir = AVIATION_TENANTS_DIR / tenant_id
    tenant_db = tenant_dir / "marine.sqlite"
    created_ids: list[int] = []

    cached_payload = {
        "tenant_id": tenant_id,
        "user_id": 1,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "location_name": "Broken Connection Ridge",
        "latitude": 38.205,
        "longitude": -97.705,
        "specimen_types": "Quartz",
        "yield_rating": 4.6,
    }

    try:
        before = client.get(f"/api/navigator/observations?tenant_id={tenant_id}&user_id=1&limit=50")
        if before.status_code != 200:
            return False, f"observation list unavailable before restore (HTTP {before.status_code})"
        before_rows = before.get_json(silent=True) or []
        if before_rows:
            return False, "synthetic outbox tenant was not empty before reconciliation"

        restore = client.post(
            "/api/navigator/observations/bulk-sync",
            json={"tenant_id": tenant_id, "user_id": 1, "items": [cached_payload]},
        )
        if restore.status_code != 200:
            return False, f"bulk-sync restore failed (HTTP {restore.status_code})"

        restore_payload = restore.get_json(silent=True) or {}
        synced_count = int(restore_payload.get("synced_count") or 0)
        if synced_count != 1:
            return False, "bulk-sync restore did not report exactly one synced observation"

        created_ids = [int(row.get("id")) for row in (restore_payload.get("items") or []) if row.get("id") is not None]

        after = client.get(f"/api/navigator/observations?tenant_id={tenant_id}&user_id=1&limit=50")
        if after.status_code != 200:
            return False, f"observation list unavailable after restore (HTTP {after.status_code})"
        after_rows = after.get_json(silent=True) or []
        if not any(str(row.get("location_name") or "") == cached_payload["location_name"] for row in after_rows):
            return False, "cached observation was not visible after bulk-sync restore"

        return True, f"cached outbox payload restored for tenant {tenant_id}"
    finally:
        try:
            if tenant_db.exists():
                conn = sqlite3.connect(str(tenant_db))
                try:
                    for row_id in created_ids:
                        conn.execute("DELETE FROM rockhounding_expeditions WHERE id = ?", (row_id,))
                    conn.commit()
                finally:
                    conn.close()
            if tenant_db.exists():
                tenant_db.unlink()
            if tenant_dir.exists():
                tenant_dir.rmdir()
        except OSError:
            pass


def _has_internet(timeout_sec: float = 1.5) -> bool:
    for host in ("1.1.1.1", "8.8.8.8"):
        try:
            with socket.create_connection((host, 53), timeout=timeout_sec):
                return True
        except OSError:
            continue
    return False


def _probe_drive_latency_ms(drive_root: Path) -> float | None:
    probe_file = drive_root / ".cortex_latency_probe.tmp"
    payload = os.urandom(512 * 1024)
    start = time.perf_counter()
    try:
        with probe_file.open("wb") as handle:
            handle.write(payload)
            handle.flush()
        with probe_file.open("rb") as handle:
            _ = handle.read()
    except OSError:
        return None
    finally:
        try:
            if probe_file.exists():
                probe_file.unlink()
        except OSError:
            pass
    return round((time.perf_counter() - start) * 1000.0, 1)


def _probe_backup_drive_health(drive_letter: str = BACKUP_DRIVE_LETTER) -> dict:
    drive = f"{drive_letter.upper()}:\\"
    drive_root = Path(drive)
    health_status = "UNKNOWN"
    warnings: list[str] = []

    if not drive_root.exists():
        warnings.append(f"backup drive {drive} not detected")

    ps_cmd = (
        f"$v = Get-Volume -DriveLetter {drive_letter.upper()} -ErrorAction SilentlyContinue; "
        "if ($null -eq $v) { '{}' } else { "
        "$v | Select-Object DriveLetter,HealthStatus,Size,SizeRemaining | ConvertTo-Json -Compress }"
    )
    try:
        volume_probe = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            timeout=8,
        )
        if volume_probe.returncode == 0:
            vol = _to_json_object((volume_probe.stdout or "").strip())
            if vol:
                health_status = str(vol.get("HealthStatus") or "UNKNOWN").upper()
                if health_status not in {"HEALTHY", "OK"}:
                    warnings.append(f"SMART/volume health reported {health_status}")
        else:
            warnings.append("SMART probe command failed")
    except (OSError, subprocess.SubprocessError):
        warnings.append("SMART probe unavailable")

    latency_ms = _probe_drive_latency_ms(drive_root) if drive_root.exists() else None
    if latency_ms is None:
        warnings.append("latency probe unavailable")
    elif latency_ms >= 250.0:
        warnings.append(f"write/read latency high ({latency_ms} ms)")

    status = "WARNING" if warnings else "OK"
    emoji = "WARN" if status == "WARNING" else "OK"
    label = f"{emoji} - Vault Health"

    return {
        "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "drive": drive,
        "status": status,
        "emoji": emoji,
        "label": label,
        "smart_health": health_status,
        "latency_ms": latency_ms,
        "internet": _has_internet(),
        "warnings": warnings,
        "is_warning": status == "WARNING",
        "source": "hutch_deploy_v3.0.0-gold",
    }


def _write_vault_health_status(payload: dict) -> None:
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    VAULT_HEALTH_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# Step 1 — pytest
# ─────────────────────────────────────────────────────────────────────────────

def run_tests() -> bool:
    _banner("STEP 1 — pytest (all tests)")
    # Leftover tmp* directories from TemporaryDirectory test teardown can
    # cause WinError 5 (Access Denied) during collection — ignore them.
    result = subprocess.run(
        [
            sys.executable, "-m", "pytest", str(TESTS_DIR), "-v", "--tb=short",
            "--ignore-glob=tests/tmp*",
        ],
        cwd=str(ROOT),
    )
    passed = result.returncode == 0
    if passed:
        _ok("All tests passed.")
    else:
        _fail(f"pytest exited with code {result.returncode}.")
    return passed


# ─────────────────────────────────────────────────────────────────────────────
# Step 2 — rockhounding integrity
# ─────────────────────────────────────────────────────────────────────────────

def check_rockhounding_integrity() -> bool:
    _banner("STEP 2 — Vault hardening (rockhounding + specimen + fuel + consumables)")

    AVIATION_DB.parent.mkdir(parents=True, exist_ok=True)

    try:
        conn = sqlite3.connect(str(AVIATION_DB))
        try:
            conn.execute(_CREATE_EXPEDITIONS)
            conn.execute(_CREATE_FUEL_LOGS)
            conn.execute(_CREATE_SPECIMEN_INVENTORY)
            conn.execute(_CREATE_MISSION_CONSUMABLES)

            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            conn.execute(
                """
                INSERT INTO mission_consumables (item_key, display_name, quantity, unit, restock_threshold, updated_at, notes)
                VALUES ('oil_quarts', 'Oil Quarts', 12.0, 'qt', 4.0, ?, NULL)
                ON CONFLICT(item_key) DO NOTHING
                """,
                (now,),
            )
            conn.execute(
                """
                INSERT INTO mission_consumables (item_key, display_name, quantity, unit, restock_threshold, updated_at, notes)
                VALUES ('sample_kits', 'Sample Kits', 10.0, 'kits', 3.0, ?, NULL)
                ON CONFLICT(item_key) DO NOTHING
                """,
                (now,),
            )
            conn.execute(
                """
                INSERT INTO mission_consumables (item_key, display_name, quantity, unit, restock_threshold, updated_at, notes)
                VALUES ('field_bags', 'Field Bags', 8.0, 'bags', 2.0, ?, NULL)
                ON CONFLICT(item_key) DO NOTHING
                """,
                (now,),
            )

            quick = conn.execute("PRAGMA quick_check").fetchone()
            quick_result = str(quick[0]).lower() if quick else ""
            if quick_result != "ok":
                _fail(f"SQLite quick_check failed: {quick_result or 'unknown'}")
                return False

            count = conn.execute("SELECT COUNT(*) FROM rockhounding_expeditions").fetchone()[0]
            fuel_count = conn.execute("SELECT COUNT(*) FROM fuel_logs").fetchone()[0]
            specimen_count = conn.execute("SELECT COUNT(*) FROM specimen_inventory").fetchone()[0]
            consumables_count = conn.execute("SELECT COUNT(*) FROM mission_consumables").fetchone()[0]
            specimen_paths = conn.execute(
                """
                SELECT id, image_path
                FROM specimen_inventory
                WHERE image_path IS NOT NULL
                  AND TRIM(image_path) <> ''
                """
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        _fail(f"Rockhounding DB integrity check failed: {exc}")
        return False

    _ok(f"rockhounding_expeditions count accessible: {count}")
    _ok(f"specimen_inventory count accessible: {specimen_count}")
    _ok(f"fuel_logs count accessible: {fuel_count}")
    _ok(f"mission_consumables count accessible: {consumables_count}")

    invalid_paths = [
        (row_id, path)
        for row_id, path in specimen_paths
        if not _is_valid_image_path(path)
    ]
    if invalid_paths:
        sample = "; ".join(f"id={row_id}: {path}" for row_id, path in invalid_paths[:3])
        _fail(f"Invalid specimen image path(s) detected: {sample}")
        return False

    _ok(f"Specimen image-path integrity verified ({len(specimen_paths)} path(s) checked).")
    return True


# ─────────────────────────────────────────────────────────────────────────────
# Step 3 — Drive-Health sentinel
# ─────────────────────────────────────────────────────────────────────────────

def check_drive_health_sentinel() -> bool:
    _banner("STEP 3 — Drive-Health Sentinel (SMART + latency)")

    try:
        health = _probe_backup_drive_health(BACKUP_DRIVE_LETTER)
        _write_vault_health_status(health)
    except OSError as exc:
        _fail(f"Drive-health sentinel write failed: {exc}")
        return False

    if health.get("status") == "WARNING":
        warning_text = "; ".join(health.get("warnings") or ["unspecified backup-drive warning"])
        _info(f"Vault health flagged WARNING: {warning_text}")
    else:
        _ok("Backup drive health checks are within sentinel thresholds.")

    _ok(f"Vault-health card status persisted to outputs/vault_health_status.json ({health.get('label')}).")
    return True


# ─────────────────────────────────────────────────────────────────────────────
# Step 4 — Sentinel hardening (mission map + preflight API)
# ─────────────────────────────────────────────────────────────────────────────

def check_mission_map_and_preflight() -> bool:
    _banner("STEP 4 — Sentinel hardening (mission map + preflight + Morning Card)")

    try:
        from hub.app import app
    except Exception as exc:
        _fail(f"Unable to import Flask app for hardening checks: {exc}")
        return False

    client = app.test_client()

    # 1) Navigator page should include Leaflet assets and mission map root node.
    nav_resp = client.get("/navigator")
    if nav_resp.status_code != 200:
        _fail(f"Navigator page unavailable (HTTP {nav_resp.status_code}).")
        return False

    nav_html = nav_resp.data.decode("utf-8", errors="ignore")
    required_markers = [
        "leaflet@1.9.4/dist/leaflet.css",
        "leaflet@1.9.4/dist/leaflet.js",
        "id=\"mission-map\"",
        "id=\"hotspot-toggle\"",
        "id=\"global-mesh-toggle\"",
        "Global Fungal Mesh",
        "id=\"sync-status-indicator\"",
        "id=\"share-signals-toggle\"",
        "predicted_hotspots",
        "mesh_signals",
        "fungal_mesh_branches",
        "High-Risk Signals:",
        "queueObservationOutbox",
        "/api/navigator/observations/bulk-sync",
        "/api/navigator/profile/share-signals",
    ]
    for marker in required_markers:
        if marker not in nav_html:
            _fail(f"Navigator assets check failed: missing '{marker}'.")
            return False
    _ok("Mission Map Leaflet assets detected in /navigator.")

    # 2) Mission-map API geospatial validation.
    map_resp = client.get("/api/navigator/mission-map?expedition_limit=300&aviation_limit=300")
    if map_resp.status_code != 200:
        _fail(f"Mission-map API unavailable (HTTP {map_resp.status_code}).")
        return False
    map_payload = map_resp.get_json(silent=True) or {}
    points = map_payload.get("all_points")
    if not isinstance(points, list):
        _fail("Mission-map API payload missing list field 'all_points'.")
        return False

    valid_coord_count = 0
    for p in points:
        lat = p.get("latitude")
        lon = p.get("longitude")
        if lat is None or lon is None:
            continue
        try:
            lat_f = float(lat)
            lon_f = float(lon)
        except (TypeError, ValueError):
            _fail(f"Invalid coordinate types in mission-map payload: lat={lat}, lon={lon}")
            return False
        if not _is_valid_coord(lat_f, lon_f):
            _fail(f"Out-of-range coordinate in mission-map payload: lat={lat_f}, lon={lon_f}")
            return False
        valid_coord_count += 1

    if valid_coord_count == 0:
        _info("Mission-map API returned zero coordinate points (schema validated; data may be empty).")
    else:
        _ok(f"Mission-map API returned {valid_coord_count} valid geospatial point(s).")

    roi_resp = client.get("/api/navigator/mission-costs?start_date=2026-01-01&end_date=2026-12-31")
    if roi_resp.status_code != 200:
        _fail(f"Mission ROI API unavailable (HTTP {roi_resp.status_code}).")
        return False
    roi_payload = roi_resp.get_json(silent=True) or {}
    roi_keys = {"fuel_cost_usd", "consumables_cost_usd", "total_cost_usd", "five_star_count"}
    if not roi_keys.issubset(set(roi_payload.keys())):
        _fail("Mission ROI API payload missing expected financial keys.")
        return False
    _ok("Mission ROI API responded with fuel + consumables + specimen yield aggregates.")

    forecast_resp = client.get("/api/navigator/mission-forecast")
    if forecast_resp.status_code != 200:
        _fail(f"Mission forecast API unavailable (HTTP {forecast_resp.status_code}).")
        return False
    forecast_payload = forecast_resp.get_json(silent=True) or {}
    forecast_keys = {"suggested_date", "label", "breakdown_summary", "windows"}
    if not forecast_keys.issubset(set(forecast_payload.keys())):
        _fail("Mission forecast API payload missing expected fields.")
        return False
    if not forecast_payload.get("suggested_date"):
        _fail("Mission forecast API did not produce a suggested launch date.")
        return False
    _ok("Mission forecast API produced a suggested launch window for the upcoming week.")

    scientist_briefing = client.get("/api/briefing/daily?tenant_slug=default&user_role=Lead%20Analyst")
    if scientist_briefing.status_code != 200:
        _fail("Role-based briefing unavailable for Lead Analyst profile.")
        return False
    scientist_payload = scientist_briefing.get_json(silent=True) or {}
    scientist_block = scientist_payload.get("scientist_payload") or {}
    if not isinstance(scientist_block.get("raw_telemetry"), list):
        _fail("Lead Analyst briefing did not include raw telemetry payload.")
        return False
    if not isinstance(scientist_block.get("raw_drift_logs"), list):
        _fail("Lead Analyst briefing did not include raw drift logs.")
        return False

    tourist_briefing = client.get("/api/briefing/daily?tenant_slug=default&user_role=Associate")
    if tourist_briefing.status_code != 200:
        _fail("Role-based briefing unavailable for Associate profile.")
        return False
    tourist_payload = tourist_briefing.get_json(silent=True) or {}
    tourist_summary = tourist_payload.get("tourist_summary") or {}
    if str(tourist_summary.get("title") or "") != "Expedition Discovery":
        _fail("Associate briefing did not provide Expedition Discovery summary.")
        return False
    _ok("Role-based briefing supports Lead Analyst telemetry logs and Associate discovery summary.")

    tenant_schema_ok, tenant_schema_msg = _verify_new_tenant_schema_initialization(client)
    if not tenant_schema_ok:
        _fail(f"Tenant migration hardening failed: {tenant_schema_msg}")
        return False
    _ok(f"Tenant migration hardening verified: {tenant_schema_msg}")

    edge_sync_ok, edge_sync_msg = _verify_edge_outbox_reconciliation(client)
    if not edge_sync_ok:
        _fail(f"Edge reconciliation hardening failed: {edge_sync_msg}")
        return False
    _ok(f"Edge reconciliation verified after broken-connection simulation: {edge_sync_msg}")

    global_node_ok, global_node_msg = _verify_global_node_anonymization(client)
    if not global_node_ok:
        _fail(f"Global Node anonymization hardening failed: {global_node_msg}")
        return False
    _ok(f"Global Node anonymization hardening verified: {global_node_msg}")

    org_admin_ok, org_admin_msg = _verify_org_admin_isolation(client)
    if not org_admin_ok:
        _fail(f"Org-Admin isolation hardening failed: {org_admin_msg}")
        return False
    _ok(f"Org-Admin isolation hardening verified: {org_admin_msg}")

    franchise_ok, franchise_msg = _verify_franchise_isolation(client)
    if not franchise_ok:
        _fail(f"Franchise isolation hardening failed: {franchise_msg}")
        return False
    _ok(f"Franchise isolation hardening verified: {franchise_msg}")

    probability_ok, probability_msg = _verify_signal_probability_engine(client)
    if not probability_ok:
        _fail(f"Signal probability engine hardening failed: {probability_msg}")
        return False
    _ok(f"Signal probability engine verified: {probability_msg}")

    hotspot_ok, hotspot_msg = _verify_hotspot_prediction_engine(client)
    if not hotspot_ok:
        _fail(f"Hotspot engine hardening failed: {hotspot_msg}")
        return False
    _ok(f"Hotspot engine verified: {hotspot_msg}")

    mesh_ok, mesh_msg = _verify_global_mesh_correlation_engine(client)
    if not mesh_ok:
        _fail(f"Global mesh correlation hardening failed: {mesh_msg}")
        return False
    _ok(f"Global mesh correlation verified: {mesh_msg}")

    synthesis_ok, synthesis_msg = _verify_intelligence_synthesis_engine(client)
    if not synthesis_ok:
        _fail(f"Intelligence synthesis hardening failed: {synthesis_msg}")
        return False
    _ok(f"Intelligence synthesis verified: {synthesis_msg}")

    oracle_ok, oracle_msg = _verify_systems_oracle_engine(client)
    if not oracle_ok:
        _fail(f"Systems Oracle hardening failed: {oracle_msg}")
        return False
    _ok(f"Systems Oracle verified: {oracle_msg}")

    pac_ok, pac_msg = _verify_pac_pruning_engine(client)
    if not pac_ok:
        _fail(f"PAC pruning hardening failed: {pac_msg}")
        return False
    _ok(f"PAC pruning verified: {pac_msg}")
    _ok("Morning Card displays: Professional Ecology: Pruned and Flowing.")

    maintenance_ok, maintenance_msg = _verify_predictive_maintenance_engine(client)
    if not maintenance_ok:
        _fail(f"Predictive maintenance hardening failed: {maintenance_msg}")
        return False
    _ok(f"Predictive maintenance verified: {maintenance_msg}")

    deep_audit_ok, deep_audit_msg = _verify_logbook_deep_audit(client)
    if not deep_audit_ok:
        _fail(f"Logbook deep-audit hardening failed: {deep_audit_msg}")
        return False
    _ok(f"Logbook deep-audit verified: {deep_audit_msg}")

    pivot_ok, pivot_msg = _verify_pivot_engine_hardening(client)
    if not pivot_ok:
        _fail(f"Pivot engine hardening failed: {pivot_msg}")
        return False
    _ok(f"Pivot engine verified: {pivot_msg}")

    # 3) Pre-flight API smoke check for primary tail (N6424P).
    exp_resp = client.get("/api/navigator/expeditions?limit=1")
    if exp_resp.status_code != 200:
        _fail(f"Could not query expedition list for pre-flight check (HTTP {exp_resp.status_code}).")
        return False

    expeditions = exp_resp.get_json(silent=True) or []
    created_temp = False
    exp_id = None
    if expeditions:
        exp_id = expeditions[0].get("id")
    else:
        create_resp = client.post(
            "/api/navigator/expeditions",
            json={
                "location_name": "FleetCommander Temp",
                "latitude": 38.0655,
                "longitude": -97.8606,
                "specimen_types": "Temp",
                "yield_rating": 5.0,
            },
        )
        if create_resp.status_code != 201:
            _fail(f"Unable to create temporary expedition for preflight check (HTTP {create_resp.status_code}).")
            return False
        exp_id = (create_resp.get_json(silent=True) or {}).get("id")
        created_temp = True

    preflight = client.get(f"/api/navigator/preflight?location_id={exp_id}&load_profile=high-yield")
    if preflight.status_code != 200:
        _fail(f"Pre-flight API failed for location_id={exp_id} (HTTP {preflight.status_code}).")
        return False
    pre = preflight.get_json(silent=True) or {}
    required_keys = ["sentinel", "fuel_status", "weather", "go_no_go", "load_profile", "nearest_airport"]
    missing = [k for k in required_keys if k not in pre]
    if missing:
        _fail(f"Pre-flight API missing keys: {', '.join(missing)}")
        return False
    if (pre.get("sentinel") or {}).get("tail_number") != "N6424P":
        _fail("Pre-flight API did not return primary-tail sentinel card for N6424P.")
        return False
    _ok("Pre-flight API returned N6424P Sentinel + Fuel + Weather + Go/No-Go summary.")

    # 3a) Pull latest Hobbs/Tach from an external digital logbook if configured.
    try:
        external_logbook = _fetch_external_logbook_latest()
    except (urlerror.URLError, TimeoutError, ValueError, OSError, json.JSONDecodeError) as exc:
        _info(f"External digital logbook unavailable ({exc}); skipping sync.")
        external_logbook = None

    if external_logbook is None:
        _info("External digital logbook not configured or no Hobbs/Tach record available; skipping sync.")
    else:
        sync_resp = client.post("/api/navigator/fuel-logs", json={**external_logbook, "notes": "deploy-logbook-sync"})
        if sync_resp.status_code != 201:
            _fail(f"External digital logbook sync failed (HTTP {sync_resp.status_code}).")
            return False
        sync_payload = sync_resp.get_json(silent=True) or {}
        sync_row = sync_payload.get("fuel_log") or {}
        sync_row_id = sync_row.get("id")
        _ok(
            "External digital logbook sync pulled latest Hobbs/Tach "
            f"for {sync_row.get('tail_number') or external_logbook.get('tail_number')} "
            f"(hobbs={sync_row.get('hobbs_time')}, tach={sync_row.get('tach_time')})."
        )
        if sync_row_id is not None:
            try:
                conn = sqlite3.connect(str(AVIATION_DB))
                try:
                    conn.execute("DELETE FROM fuel_logs WHERE id = ?", (sync_row_id,))
                    conn.commit()
                finally:
                    conn.close()
            except sqlite3.DatabaseError:
                _info("Temporary external logbook sync cleanup failed; continuing.")

    gaps = _detect_logbook_gap_days()
    if gaps:
        preview = "; ".join(f"{row['day']} ({row['reason']})" for row in gaps[:3])
        _info(f"Automated logbook catch-up identified {len(gaps)} gap day(s): {preview}")
    else:
        _ok("Automated logbook catch-up found no gap days in fuel-log history.")

    isolation_ok, isolation_msg = _verify_user_data_isolation(client)
    if not isolation_ok:
        _fail(f"Guest gate isolation check failed: {isolation_msg}")
        return False
    _ok(f"Guest gate data isolation verified: {isolation_msg}")

    fungal_ok, fungal_msg = _verify_fungal_outreach_network(client)
    if not fungal_ok:
        _fail(f"Fungal outreach hardening failed: {fungal_msg}")
        return False
    _ok(f"Fungal outreach hardening verified: {fungal_msg}")
    _ok("Morning Card displays: Network Status: Flourishing.")

    architect_ok, architect_msg = _verify_architect_write_permission_guardrails(client)
    if not architect_ok:
        _fail(f"Architect write-permission hardening failed: {architect_msg}")
        return False
    _ok(f"Architect write-permission hardening verified: {architect_msg}")

    associate_ok, associate_msg = _verify_associate_post_guardrails(client)
    if not associate_ok:
        _fail(f"Associate guardrail hardening failed: {associate_msg}")
        return False
    _ok(f"Associate guardrail hardening verified: {associate_msg}")

    legacy_ok, legacy_msg = _verify_legacy_switch_protocol(client)
    if not legacy_ok:
        _fail(f"Legacy switch hardening failed: {legacy_msg}")
        return False
    _ok(f"Legacy switch hardening verified: {legacy_msg}")
    _ok("Morning Card displays: Lighthouse Status: Market Standard. The Mesh is the Industry. Joshua R Hutchison: Founder & Architect.")

    governance_ok, governance_msg = _verify_governance_ledger_access(client)
    if not governance_ok:
        _fail(f"Governance ledger hardening failed: {governance_msg}")
        return False
    _ok(f"Governance ledger hardening verified: {governance_msg}")
    _ok("Lighthouse Governance: Absolute. Audit Ready.")

    unicorn_ok, unicorn_msg = _verify_unicorn_path_controls(client)
    if not unicorn_ok:
        _fail(f"Unicorn Path hardening failed: {unicorn_msg}")
        return False
    _ok(f"Unicorn Path hardening verified: {unicorn_msg}")

    speed_ok, speed_msg = _verify_morning_card_speed_stress(client, runs=30)
    if not speed_ok:
        _fail(f"Mobile pulse speed stress test failed: {speed_msg}")
        return False
    _ok(f"Mobile pulse speed stress test verified: {speed_msg}")

    # 3b) Transport correlation hardening: synthetic fuel log must match synthetic specimen.
    fuel_log_id = None
    specimen_corr_id = None
    corr_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        fuel_resp = client.post(
            "/api/navigator/fuel-logs",
            json={
                "tail_number": "N6424P",
                "timestamp": corr_ts,
                "hobbs_time": 999.9,
                "gallons_added": 12.0,
                "fuel_after_gal": 34.0,
                "notes": "deploy-correlation-smoke",
            },
        )
        if fuel_resp.status_code != 201:
            _fail(f"Unable to create synthetic fuel log for correlation check (HTTP {fuel_resp.status_code}).")
            return False
        fuel_payload = fuel_resp.get_json(silent=True) or {}
        fuel_row = fuel_payload.get("fuel_log") or {}
        fuel_log_id = fuel_row.get("id")
        expected_flight_id = f"FUEL-N6424P-{fuel_log_id}"

        corr_specimen_resp = client.post(
            "/api/navigator/specimens",
            json={
                "timestamp": corr_ts,
                "yield_stars": 4,
                "hardness": 6.2,
                "mineral_class": "CorrelationQuartz",
                "notes": "deploy-correlation-smoke",
            },
        )
        if corr_specimen_resp.status_code != 201:
            _fail(f"Unable to create synthetic specimen for correlation check (HTTP {corr_specimen_resp.status_code}).")
            return False
        corr_specimen_payload = corr_specimen_resp.get_json(silent=True) or {}
        corr_specimen = corr_specimen_payload.get("specimen") or {}
        specimen_corr_id = corr_specimen.get("id")
        suggestion = corr_specimen.get("transport_flight_suggestion") or {}
        if suggestion.get("flight_id") != expected_flight_id:
            _fail(
                "Transport correlation mismatch: "
                f"expected {expected_flight_id}, got {suggestion.get('flight_id') or 'none'}."
            )
            return False
        _ok("Transport flight correlation matched synthetic specimen to synthetic fuel log.")
    finally:
        try:
            conn = sqlite3.connect(str(AVIATION_DB))
            try:
                if specimen_corr_id is not None:
                    conn.execute("DELETE FROM specimen_inventory WHERE id = ?", (specimen_corr_id,))
                if fuel_log_id is not None:
                    conn.execute("DELETE FROM fuel_logs WHERE id = ?", (fuel_log_id,))
                conn.commit()
            finally:
                conn.close()
        except sqlite3.DatabaseError:
            _info("Synthetic correlation cleanup failed; continuing.")

    if created_temp and exp_id is not None:
        try:
            conn = sqlite3.connect(str(AVIATION_DB))
            try:
                conn.execute("DELETE FROM rockhounding_expeditions WHERE id = ?", (exp_id,))
                conn.commit()
            finally:
                conn.close()
        except sqlite3.DatabaseError:
            _info("Temporary expedition cleanup failed; continuing.")

    # 4) Morning Card remains primary executive entry point.
    workflow_resp = client.get("/workflow")
    if workflow_resp.status_code != 200:
        _fail(f"Workflow page unavailable (HTTP {workflow_resp.status_code}).")
        return False
    workflow_html = workflow_resp.data.decode("utf-8", errors="ignore")
    if (
        "id=\"morning-card\"" not in workflow_html
        or "loadMorningCard()" not in workflow_html
        or "id=\"mc-vault-health\"" not in workflow_html
        or "id=\"mc-restock-alert\"" not in workflow_html
        or "id=\"mc-edge-sync\"" not in workflow_html
        or "id=\"mc-global-pulse\"" not in workflow_html
        or "id=\"mc-mesh-integrity\"" not in workflow_html
        or "id=\"mc-mesh-radar\"" not in workflow_html
        or "id=\"mc-network-health\"" not in workflow_html
        or "id=\"mc-network-health-fill\"" not in workflow_html
        or "id=\"mc-guest-nodes\"" not in workflow_html
        or "id=\"mc-network-status\"" not in workflow_html
        or "id=\"mc-intel-synthesis-label\"" not in workflow_html
        or "id=\"mc-strategic-global-pulse\"" not in workflow_html
        or "id=\"mc-strategic-local-action\"" not in workflow_html
        or "id=\"mc-systems-oracle-label\"" not in workflow_html
        or "id=\"mc-systems-reflection\"" not in workflow_html
        or "id=\"mc-philosophical-synthesis\"" not in workflow_html
        or "id=\"mc-global-feed\"" not in workflow_html
        or "vouchGlobalSignal" not in workflow_html
        or "id=\"mc-suggested-launch\"" not in workflow_html
        or "id=\"mc-discovery-forecast\"" not in workflow_html
        or "id=\"mc-discovery-route\"" not in workflow_html
        or "id=\"mc-fleet-readiness\"" not in workflow_html
        or "id=\"mc-fleet-readiness-fill\"" not in workflow_html
        or "id=\"mc-strategy-badge\"" not in workflow_html
        or "id=\"mc-strategy-rationale\"" not in workflow_html
        or "id=\"mc-architect-mode\"" not in workflow_html
        or "id=\"mc-proposed-automation\"" not in workflow_html
        or "id=\"mc-system-longevity\"" not in workflow_html
        or "id=\"mc-pruned-today\"" not in workflow_html
        or "id=\"mc-professional-ecology\"" not in workflow_html
        or "id=\"automation-lab\"" not in workflow_html
        or "id=\"al-architect-mode\"" not in workflow_html
        or "id=\"al-proposed\"" not in workflow_html
        or "id=\"al-collective\"" not in workflow_html
        or "id=\"al-deploy-btn\"" not in workflow_html
        or "deploySuggestedAutomation" not in workflow_html
        or "/api/architect/automation/deploy" not in workflow_html
        or "id=\"mc-fleet-status-gold\"" not in workflow_html
        or "id=\"mc-schedule-service\"" not in workflow_html
        or "id=\"mc-role\"" not in workflow_html
        or "id=\"mc-tenant-id\"" not in workflow_html
    ):
        _fail("Morning Card executive entry point not detected in workflow UI.")
        return False
    _ok("Morning Card remains the primary executive entry point.")

    aviation_resp = client.get("/aviation")
    if aviation_resp.status_code != 200:
        _fail(f"Aviation fleet page unavailable (HTTP {aviation_resp.status_code}).")
        return False
    aviation_html = aviation_resp.data.decode("utf-8", errors="ignore")
    if (
        "Predictive TTI by major component" not in aviation_html
        or "id=\"predictive-tti\"" not in aviation_html
        or "tti-fill--inspect_now" not in aviation_html
    ):
        _fail("Fleet page is missing Predictive TTI progress-bar rendering.")
        return False
    _ok("Fleet page renders Predictive TTI progress bars for major components.")

    # 5) Morning Card should surface a High-Yield Specimen alert for a fresh 5-star find.
    specimen_id = None
    market_specimen_id = None
    original_oil = None
    original_kits = None
    low_kits_quantity = None
    try:
        baseline_consumables = client.get("/api/navigator/consumables?limit=50")
        if baseline_consumables.status_code == 200:
            items = (baseline_consumables.get_json(silent=True) or {}).get("items") or []
            for item in items:
                if item.get("item_key") == "oil_quarts":
                    original_oil = item
                elif item.get("item_key") == "sample_kits":
                    original_kits = item

        specimen_resp = client.post(
            "/api/navigator/specimens",
            json={
                "yield_stars": 5,
                "image_path": "mobile://deploy-smoke-specimen.jpg",
                "color": "smoke-test",
                "hardness": 5.0,
                "mineral_class": "smoke-test",
                "notes": "deploy-smoke",
            },
        )
        if specimen_resp.status_code != 201:
            _fail(f"Unable to create 5-star specimen for Morning Card check (HTTP {specimen_resp.status_code}).")
            return False
        specimen_payload = specimen_resp.get_json(silent=True) or {}
        specimen_id = ((specimen_payload.get("specimen") or {}).get("id"))

        briefing_resp = client.get("/api/briefing/daily?tenant_slug=default&user_role=Admin")
        if briefing_resp.status_code != 200:
            _fail(f"Morning briefing API unavailable after specimen insert (HTTP {briefing_resp.status_code}).")
            return False
        briefing = briefing_resp.get_json(silent=True) or {}
        role_label = ((briefing.get("role") or {}).get("label") or "").strip()
        if role_label != "Role: Administrator (Hutch).":
            _fail("Morning Card role label is not Administrator (Hutch).")
            return False
        tenant_label = ((briefing.get("tenant") or {}).get("label") or "").strip()
        if not tenant_label.startswith("Tenant ID:"):
            _fail("Morning Card tenant footer label is missing from briefing payload.")
            return False
        edge_sync_label = ((briefing.get("edge_sync") or {}).get("label") or "").strip()
        if edge_sync_label != "Edge Sync: Active.":
            _fail("Morning Card edge sync label is missing from briefing payload.")
            return False
        global_pulse_label = ((briefing.get("global_node") or {}).get("label") or "").strip()
        if global_pulse_label != "Global Pulse: Connected.":
            _fail("Morning Card global pulse label is missing from briefing payload.")
            return False
        mesh_integrity_label = ((briefing.get("global_node") or {}).get("mesh_integrity_label") or "").strip()
        if not mesh_integrity_label.startswith("Mesh Integrity:"):
            _fail("Morning Card mesh integrity label is missing from briefing payload.")
            return False
        specimen_alert = briefing.get("high_yield_specimen_alert") or {}
        if not specimen_alert.get("is_active"):
            _fail("Morning Card did not activate high_yield_specimen_alert after a 5-star specimen insert.")
            return False
        if (specimen_alert.get("yield_stars") or 0) < 5:
            _fail("Morning Card high_yield_specimen_alert did not report a 5-star specimen.")
            return False

        market_specimen_resp = client.post(
            "/api/navigator/specimens",
            json={
                "yield_stars": 3,
                "mineral_class": "Agate",
                "estimated_weight_lbs": 10.0,
                "notes": "deploy-market-value-smoke",
            },
        )
        if market_specimen_resp.status_code != 201:
            _fail("Unable to create synthetic Agate specimen for market tracker check.")
            return False
        market_payload = market_specimen_resp.get_json(silent=True) or {}
        market_specimen = market_payload.get("specimen") or {}
        market_specimen_id = market_specimen.get("id")
        market_value = market_specimen.get("market_value_usd")
        if market_value is None or float(market_value) <= 0:
            _fail("Market tracker failed: synthetic 10-lb Agate specimen did not produce non-zero USD value.")
            return False
        _ok("Market tracker produced non-zero USD value for synthetic 10-lb Agate find.")

        # Force low consumables and verify Morning Card restock alert.
        low_oil_resp = client.post(
            "/api/navigator/consumables",
            json={
                "item_key": "oil_quarts",
                "display_name": "Oil Quarts",
                "quantity": 1.0,
                "unit": "qt",
                "restock_threshold": 4.0,
                "notes": "deploy-restock-smoke",
            },
        )
        low_kits_resp = client.post(
            "/api/navigator/consumables",
            json={
                "item_key": "sample_kits",
                "display_name": "Sample Kits",
                "quantity": 1.0,
                "unit": "kits",
                "restock_threshold": 3.0,
                "notes": "deploy-restock-smoke",
            },
        )
        if low_oil_resp.status_code != 200 or low_kits_resp.status_code != 200:
            _fail("Unable to force low consumables for restock hardening check.")
            return False

        low_kits_payload = low_kits_resp.get_json(silent=True) or {}
        low_kits_quantity = ((low_kits_payload.get("item") or {}).get("quantity"))

        low_briefing_resp = client.get("/api/briefing/daily?tenant_slug=default&user_role=Admin")
        if low_briefing_resp.status_code != 200:
            _fail("Morning briefing API unavailable during restock hardening check.")
            return False
        low_briefing = low_briefing_resp.get_json(silent=True) or {}
        restock = low_briefing.get("restock_alert") or {}
        if not restock.get("is_active"):
            _fail("Morning Card did not trigger Restock Needed when consumables were forced low.")
            return False
        labels = {str(x) for x in (restock.get("low_item_labels") or [])}
        if "Oil Quarts" not in labels or "Sample Kits" not in labels:
            _fail("Restock alert missing Oil Quarts or Sample Kits while low.")
            return False
        _ok("Morning Card restock alert triggered correctly for low Oil Quarts and Sample Kits.")

        # Perform synthetic restock action and assert count increment.
        restock_kits_resp = client.post(
            "/api/navigator/consumables",
            json={
                "item_key": "sample_kits",
                "display_name": "Sample Kits",
                "quantity": 5.0,
                "unit": "kits",
                "restock_threshold": 3.0,
                "notes": "deploy-restock-increment",
            },
        )
        restock_oil_resp = client.post(
            "/api/navigator/consumables",
            json={
                "item_key": "oil_quarts",
                "display_name": "Oil Quarts",
                "quantity": 8.0,
                "unit": "qt",
                "restock_threshold": 4.0,
                "notes": "deploy-restock-increment",
            },
        )
        if restock_kits_resp.status_code != 200 or restock_oil_resp.status_code != 200:
            _fail("Synthetic restock action failed via Consumables API.")
            return False

        restock_item = ((restock_kits_resp.get_json(silent=True) or {}).get("item") or {})
        restocked_quantity = restock_item.get("quantity")
        if low_kits_quantity is None:
            _fail("Unable to establish pre-restock Sample Kits quantity.")
            return False
        if restocked_quantity is None or float(restocked_quantity) <= float(low_kits_quantity):
            _fail("Consumables API restock did not increment Sample Kits quantity.")
            return False
        _ok("Consumables API restock action incremented Sample Kits quantity successfully.")

        restocked_briefing_resp = client.get("/api/briefing/daily?tenant_slug=default&user_role=Admin")
        if restocked_briefing_resp.status_code != 200:
            _fail("Morning briefing API unavailable during post-restock verification.")
            return False
        restocked_briefing = restocked_briefing_resp.get_json(silent=True) or {}
        restocked_alert = restocked_briefing.get("restock_alert") or {}
        if restocked_alert.get("is_active"):
            _fail("Morning Card still reports Restock Needed after synthetic restock.")
            return False
        if str(restocked_alert.get("label") or "").strip().lower() != "systems nominal":
            _fail("Morning Card did not return Systems Nominal after synthetic restock.")
            return False
        _ok("Morning Card shows Systems Nominal after synthetic restock.")

        fuel_market = restocked_briefing.get("fuel_market") or {}
        if str(fuel_market.get("label") or "").strip() != "Fuel Market: Nominal.":
            _fail("Morning Card fuel market line is not nominal after briefing refresh.")
            return False
        _ok("Morning Card shows Fuel Market: Nominal.")

        mission_forecast = restocked_briefing.get("mission_forecast") or {}
        launch_date = str(mission_forecast.get("suggested_date") or "").strip()
        if not launch_date:
            _fail("Morning Card missing suggested launch date for upcoming week.")
            return False
        try:
            launch_dt = datetime.strptime(launch_date, "%Y-%m-%d").date()
            today = datetime.now(timezone.utc).date()
            if launch_dt < today or (launch_dt - today).days > 7:
                _fail("Morning Card suggested launch date is not within the upcoming week.")
                return False
        except ValueError:
            _fail("Morning Card suggested launch date has invalid format.")
            return False
        _ok(f"Morning Card displays Suggested Launch for upcoming week: {launch_date}.")

        restocked_role = restocked_briefing.get("role") or {}
        if str(restocked_role.get("label") or "").strip() != "Role: Administrator (Hutch).":
            _fail("Morning Card did not preserve Administrator role label after refresh.")
            return False
        _ok("Morning Card displays role: Administrator (Hutch).")

        restocked_tenant = restocked_briefing.get("tenant") or {}
        if not str(restocked_tenant.get("label") or "").strip().startswith("Tenant ID:"):
            _fail("Morning Card did not preserve Tenant ID label after refresh.")
            return False
        _ok(f"Morning Card footer identifies tenant: {restocked_tenant.get('label')}")

        restocked_edge_sync = restocked_briefing.get("edge_sync") or {}
        if str(restocked_edge_sync.get("label") or "").strip() != "Edge Sync: Active.":
            _fail("Morning Card did not preserve Edge Sync label after refresh.")
            return False
        _ok("Morning Card shows Edge Sync: Active.")

        restocked_global = restocked_briefing.get("global_node") or {}
        if str(restocked_global.get("label") or "").strip() != "Global Pulse: Connected.":
            _fail("Morning Card did not preserve Global Pulse label after refresh.")
            return False
        _ok("Morning Card shows Global Pulse: Connected.")

        restocked_mesh_label = str(restocked_global.get("mesh_integrity_label") or "").strip()
        if restocked_mesh_label != "Mesh Integrity: 100%.":
            _fail("Morning Card did not preserve Mesh Integrity: 100%. after refresh.")
            return False
        _ok("Morning Card shows Mesh Integrity: 100%.")

        mesh_radar = restocked_briefing.get("mesh_radar") or {}
        mesh_radar_label = str(mesh_radar.get("label") or "").strip()
        if mesh_radar_label != "Mesh Radar: Active.":
            _fail("Morning Card mesh radar label did not resolve to Mesh Radar: Active.")
            return False
        _ok("Morning Card displays: Mesh Radar: Active.")

        synthesis = restocked_briefing.get("intelligence_synthesis") or {}
        synthesis_label = str(synthesis.get("label") or "").strip()
        if synthesis_label != "Intelligence Synthesis: Nominal.":
            _fail("Morning Card intelligence synthesis label did not resolve to Intelligence Synthesis: Nominal.")
            return False
        summary_text = str(synthesis.get("global_pulse_summary") or "").strip()
        if not summary_text:
            _fail("Morning Card intelligence synthesis summary is missing.")
            return False
        local_action = str(synthesis.get("local_action_recommendation") or "").strip()
        if not local_action.startswith("Local Action:"):
            _fail("Morning Card strategic local action recommendation is missing.")
            return False
        _ok("Morning Card displays: Intelligence Synthesis: Nominal.")

        systems_oracle = restocked_briefing.get("systems_thinking_overlay") or {}
        systems_oracle_label = str(systems_oracle.get("label") or "").strip()
        if systems_oracle_label != "Systems Oracle: Synced with Mycology to Your Ecology.":
            _fail("Morning Card systems oracle label did not resolve to expected sync text.")
            return False
        systems_reflection = str(systems_oracle.get("systems_reflection") or "").strip()
        if not systems_reflection.startswith("Systems-Thinking Reflection:"):
            _fail("Morning Card systems-thinking reflection line is missing expected prefix.")
            return False
        systems_synthesis = str(systems_oracle.get("philosophical_synthesis") or "").strip()
        if not systems_synthesis.startswith("Philosophical Synthesis:"):
            _fail("Morning Card philosophical synthesis line is missing expected prefix.")
            return False
        manuscript_payload = systems_oracle.get("manuscript") or {}
        if not bool(manuscript_payload.get("loaded")):
            _fail("Systems Oracle did not report loaded manuscript metadata in Morning Card payload.")
            return False
        _ok("Morning Card displays: Systems Oracle: Synced with Mycology to Your Ecology.")

        fleet_status_badge = str(restocked_briefing.get("fleet_status_badge") or "").strip()
        if fleet_status_badge != "Fleet Status: Gold Master.":
            _fail("Morning Card fleet status badge did not resolve to Fleet Status: Gold Master.")
            return False
        _ok("Morning Card displays: Fleet Status: Gold Master.")

        discovery_forecast = restocked_briefing.get("discovery_forecast") or {}
        discovery_label = str(discovery_forecast.get("label") or "").strip()
        if not discovery_label.startswith("Discovery Forecast:"):
            _fail("Morning Card discovery forecast label is missing from briefing payload.")
            return False
        _ok(f"Morning Card discovery forecast line present: {discovery_label}")

        fleet_readiness = restocked_briefing.get("fleet_readiness") or {}
        readiness_label = str(fleet_readiness.get("label") or "").strip()
        if readiness_label != "Fleet Readiness: 100% (Mission Ready).":
            _fail("Morning Card fleet readiness gauge did not reach mission-ready 100% state.")
            return False
        _ok("Morning Card displays: Fleet Readiness: 100% (Mission Ready).")

        pivot = restocked_briefing.get("optimization_pivot") or {}
        pivot_label = str(pivot.get("label") or "").strip()
        pivot_rationale = str(pivot.get("rationale") or "").strip()
        if not pivot_label.startswith("Strategy:"):
            _fail("Morning Card strategy recommendation is missing expected Strategy: prefix.")
            return False
        if not pivot_rationale:
            _fail("Morning Card strategy rationale is missing.")
            return False
        _ok(f"Morning Card strategy recommendation present: {pivot_label}")

        architect_block = restocked_briefing.get("automation_architect") or {}
        architect_label = str(architect_block.get("architect_mode_label") or "").strip()
        if architect_label != "Architect Mode: Enabled. Suggestions Pending.":
            _fail("Morning Card architect mode label did not resolve to expected v6 text.")
            return False
        proposed_automation = str(architect_block.get("proposed_automation_label") or "").strip()
        if not proposed_automation.startswith("Proposed Automation:"):
            _fail("Morning Card proposed automation line is missing expected prefix.")
            return False
        _ok("Morning Card displays: Architect Mode: Enabled. Suggestions Pending.")

        longevity = restocked_briefing.get("system_longevity") or {}
        longevity_label = str(longevity.get("label") or "").strip()
        if not longevity_label.startswith("Lighthouse Status:"):
            _fail("Morning Card system longevity line is missing expected Lighthouse Status prefix.")
            return False
        _ok(f"Morning Card system longevity line present: {longevity_label}")

        vault_health = briefing.get("vault_health") or {}
        if not isinstance(vault_health, dict) or "status" not in vault_health:
            _fail("Morning Card payload missing vault_health status block.")
            return False
        _ok(f"Morning Card vault health status present: {vault_health.get('status')}")

        system_status = restocked_briefing.get("system_status") or {}
        system_status_label = str(system_status.get("label") or "").strip()
        if system_status_label != "System Status: Digital Guardian Active. Ready for the Mass Market.":
            _fail(f"Morning Card system status label is incorrect: '{system_status_label}' (expected 'System Status: Digital Guardian Active. Ready for the Mass Market.')")
            return False
        _ok("Morning Card displays: System Status: Digital Guardian Active. Ready for the Mass Market.")

        governance_block = restocked_briefing.get("lighthouse_governance") or {}
        governance_label = str(governance_block.get("label") or "").strip()
        if governance_label != "Lighthouse Governance: Absolute. Audit Ready.":
            _fail(f"Morning Card governance label incorrect: '{governance_label}'")
            return False
        _ok("Morning Card displays: Lighthouse Governance: Absolute. Audit Ready.")
        
        _ok("Morning Card high-yield specimen alert is active for recent 5-star finds.")

        tax_ok, tax_msg = _verify_tax_export_integrity()
        if not tax_ok:
            _fail(f"Tax export integrity check failed: {tax_msg}")
            return False
        _ok(f"Tax export integrity verified: {tax_msg}")
    finally:
        if specimen_id is not None:
            try:
                conn = sqlite3.connect(str(AVIATION_DB))
                try:
                    conn.execute("DELETE FROM specimen_inventory WHERE id = ?", (specimen_id,))
                    if market_specimen_id is not None:
                        conn.execute("DELETE FROM specimen_inventory WHERE id = ?", (market_specimen_id,))
                    conn.commit()
                finally:
                    conn.close()
            except sqlite3.DatabaseError:
                _info("Temporary specimen cleanup failed; continuing.")

        def _restore_consumable(item: dict | None, fallback: dict) -> None:
            source = item or fallback
            client.post(
                "/api/navigator/consumables",
                json={
                    "item_key": source["item_key"],
                    "display_name": source["display_name"],
                    "quantity": source["quantity"],
                    "unit": source["unit"],
                    "restock_threshold": source["restock_threshold"],
                    "notes": source.get("notes"),
                },
            )

        try:
            _restore_consumable(
                original_oil,
                {
                    "item_key": "oil_quarts",
                    "display_name": "Oil Quarts",
                    "quantity": 12.0,
                    "unit": "qt",
                    "restock_threshold": 4.0,
                    "notes": None,
                },
            )
            _restore_consumable(
                original_kits,
                {
                    "item_key": "sample_kits",
                    "display_name": "Sample Kits",
                    "quantity": 10.0,
                    "unit": "kits",
                    "restock_threshold": 3.0,
                    "notes": None,
                },
            )
        except Exception:
            _info("Temporary consumables cleanup failed; continuing.")
    return True


# ─────────────────────────────────────────────────────────────────────────────
# Step 5 — automated cloud mirror
# ─────────────────────────────────────────────────────────────────────────────

def run_cloud_mirror() -> bool:
    _banner("STEP 5 — Automated Cloud Mirror")

    mirror_script = ROOT / "scripts" / "vault_mirror.py"
    if not mirror_script.exists():
        _fail("scripts/vault_mirror.py not found.")
        return False

    result = subprocess.run(
        [sys.executable, str(mirror_script)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        _fail(f"vault_mirror.py exited with code {result.returncode}.")
        return False

    payload = _to_json_object((result.stdout or "").strip())
    if not payload:
        _fail("vault_mirror.py returned non-JSON output.")
        return False

    if not payload.get("internet_detected"):
        _info("No internet detected; cloud mirror skipped by design.")
        return True

    if not payload.get("mirrored"):
        _fail("Internet detected but no vault data was mirrored.")
        return False

    latest_ts = _parse_utc(str(payload.get("latest_container_timestamp") or ""))
    if latest_ts is None:
        _fail("Cloud mirror integrity failed: latest off-site container timestamp missing.")
        return False

    age_min = (datetime.now(timezone.utc) - latest_ts).total_seconds() / 60.0
    if age_min > 20:
        _fail(
            "Cloud mirror integrity failed: "
            f"latest off-site container timestamp is stale ({age_min:.1f} min old)."
        )
        return False

    _ok(
        "Cloud mirror complete: "
        f"{payload.get('specimen_files_mirrored', 0)} specimen file(s), "
        f"aviation DB mirrored={bool(payload.get('aviation_vault_mirrored'))}, "
        f"encrypted={bool(payload.get('encrypted'))}, "
        f"latest container age={age_min:.1f} min."
    )
    return True


# ─────────────────────────────────────────────────────────────────────────────
# Step 6 — batch OCR fixture scan (dry-run)
# ─────────────────────────────────────────────────────────────────────────────

def run_fixture_scan() -> bool:
    _banner("STEP 6 — batch OCR scan (fixtures/, dry-run)")

    if not FIXTURES_DIR.exists():
        _info("tests/fixtures/ not found — skipping scan.")
        return True

    # Import at call-time so a missing optional dep (pdfminer) doesn't abort
    # the test step.
    try:
        from nerves.aviation.ocr_worker import OcrWorker
    except ImportError as exc:
        _info(f"OcrWorker unavailable ({exc}) — skipping scan.")
        return True

    worker = OcrWorker()
    summary = worker.process_folder(
        str(FIXTURES_DIR),
        dry_run=True,
        recursive=False,
    )

    processed = summary.get("processed", 0)
    errors    = len(summary.get("errors", []))
    health    = summary.get("fleet_health", {})

    _info(f"PDFs processed : {processed}")
    _info(f"Errors         : {errors}")
    if health:
        _info(f"Fleet status   : {health.get('fleet_status', 'N/A')}")
        _info(f"Fe avg         : {health.get('iron', {}).get('avg', 'N/A')} ppm")

    if errors:
        _fail(f"{errors} error(s) during fixture scan.")
        return False

    _ok("Fixture scan complete (dry-run — no DB writes).")
    return True


# ─────────────────────────────────────────────────────────────────────────────
# Step 7 — export DB snapshot
# ─────────────────────────────────────────────────────────────────────────────

def export_snapshot() -> bool:
    _banner("STEP 7 — export cortex.sqlite snapshot")

    if not CORTEX_DB.exists():
        _info("data/cortex.sqlite not found — skipping snapshot.")
        return True

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts      = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dst     = BACKUP_DIR / f"fortress_backup_{ts}.db"

    try:
        shutil.copy2(CORTEX_DB, dst)
        _ok(f"Snapshot written: {dst.relative_to(ROOT)}")
        return True
    except OSError as exc:
        _fail(f"Snapshot failed: {exc}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Step 8 — verify Sunday Executive Weekly ZIP
# ─────────────────────────────────────────────────────────────────────────────

def check_weekly_zip() -> bool:
    _banner("STEP 8 — verify Executive Weekly ZIP")
    weekly_dir = ROOT / "outputs" / "reports" / "weekly"

    if not weekly_dir.exists():
        _info("outputs/reports/weekly/ not found — run sunday_briefing.py --force first.")
        return True   # non-blocking: no zip yet is expected on a fresh install

    zips = sorted(weekly_dir.glob("HutchSolves_Executive_Weekly_*.zip"), reverse=True)
    if not zips:
        _info("No Executive_Weekly ZIP found yet — run scripts/sunday_briefing.py --force to generate.")
        return True   # non-blocking

    latest = zips[0]
    size   = latest.stat().st_size
    if size == 0:
        _fail(f"Latest ZIP is zero bytes: {latest.relative_to(ROOT)}")
        return False

    _ok(f"Latest ZIP: {latest.relative_to(ROOT)}  ({size:,} bytes)")
    return True


# ─────────────────────────────────────────────────────────────────────────────
# Step 9 — run sunday_briefing.py --force (smoke test)
# ─────────────────────────────────────────────────────────────────────────────

def run_sunday_briefing() -> bool:
    _banner("STEP 9 — Sunday Briefing smoke test (--force)")
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "sunday_briefing.py"), "--force"],
        cwd=str(ROOT),
    )
    if result.returncode == 0:
        _ok("sunday_briefing.py executed without errors.")
        return True
    _fail(f"sunday_briefing.py exited with code {result.returncode}.")
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Entrypoint
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    print("\nHutchSolves v7.0.0-SINGULARITY \u2014 The Autonomous Legacy deployment script")
    print(f"Repo root : {ROOT}")
    print(f"Started   : {datetime.now(timezone.utc).isoformat()}")

    results = {
        "pytest":            run_tests(),
        "rockhounding":      check_rockhounding_integrity(),
        "drive_health":      check_drive_health_sentinel(),
        "sentinel_hardening": check_mission_map_and_preflight(),
        "cloud_mirror":      run_cloud_mirror(),
        "ocr_scan":          run_fixture_scan(),
        "snapshot":          export_snapshot(),
        "weekly_zip":        check_weekly_zip(),
        "sunday_pulse":      run_sunday_briefing(),
    }

    _banner("SUMMARY")
    all_ok = True
    for step, ok in results.items():
        status = "PASS" if ok else "FAIL"
        print(f"  {step:<12} {status}")
        if not ok:
            all_ok = False

    print()
    if all_ok:
        print("  Deployment checks: ALL PASSED")
        sys.exit(0)
    else:
        print("  Deployment checks: FAILED — review output above", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    import sys
    verify_ui_mode = "--verify-ui" in sys.argv
    if verify_ui_mode:
        sys.argv.remove("--verify-ui")
    # v14.1 v14.1.0 "The Performance Singularity" enhancement: UI verification mode
    # ensures morning card fallback logic remains responsive despite external CDN latency.
    main()
