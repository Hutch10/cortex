"""CLI onboarding for HutchSolves multi-tenant users.

Creates/updates:
- tenant SQLite database folder under AppData/.../tenants/<tenant_id>/marine.sqlite
- user_profiles row for the onboarded user
- mission_scopes rows for requested scopes
- baseline mission consumables for the user
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

TENANTS_ROOT = Path.home() / "AppData" / "Roaming" / "Aero Cortex Hub" / "data" / "tenants"
TENANT_ID_SANITIZER = re.compile(r"[^a-z0-9_-]+")

CREATE_EXPEDITIONS = """
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

CREATE_FUEL_LOGS = """
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

CREATE_SPECIMEN_INVENTORY = """
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
    estimated_weight_lbs REAL,
    market_value_usd REAL,
    notes TEXT,
    latitude REAL,
    longitude REAL,
    transport_suggestion_json TEXT,
    FOREIGN KEY(expedition_id) REFERENCES rockhounding_expeditions(id) ON DELETE SET NULL
)
"""

CREATE_MISSION_CONSUMABLES = """
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

CREATE_MISSION_CONSUMABLE_EVENTS = """
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

CREATE_FUEL_MARKET_LOGS = """
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

CREATE_USER_PROFILES = """
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

CREATE_MISSION_SCOPES = """
CREATE TABLE IF NOT EXISTS mission_scopes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    scope_type TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY(user_id) REFERENCES user_profiles(id) ON DELETE CASCADE,
    UNIQUE(user_id, scope_type)
)
"""

MISSION_DEFAULTS = [
    {"item_key": "oil_quarts", "display_name": "Oil Quarts", "quantity": 12.0, "unit": "qt", "restock_threshold": 4.0},
    {"item_key": "sample_kits", "display_name": "Sample Kits", "quantity": 10.0, "unit": "kits", "restock_threshold": 3.0},
    {"item_key": "field_bags", "display_name": "Field Bags", "quantity": 8.0, "unit": "bags", "restock_threshold": 2.0},
]

GUEST_AUDIT_SCOPES = ["Discovery", "Systems Oracle Audit"]
GUEST_DEFAULT_MENTOR_MESH = "fungal-outreach"


def _default_permissions(role: str) -> dict:
    if role == "Guest Scientist":
        return {
            "can_submit_drift": True,
            "can_submit_discovery": True,
            "can_view_honey_hole": False,
            "can_broadcast_philosophical_signal": False,
            "permissions_profile": "guest_scientist_restricted",
            "systems_oracle_audit_enabled": True,
            "allowed_scopes": list(GUEST_AUDIT_SCOPES),
        }
    if role == "Tourist":
        return {
            "can_submit_drift": False,
            "can_submit_discovery": False,
            "can_view_honey_hole": False,
            "can_broadcast_philosophical_signal": False,
            "permissions_profile": "tourist",
        }
    if role == "Scientist":
        return {
            "can_submit_drift": True,
            "can_submit_discovery": True,
            "can_view_honey_hole": True,
            "can_broadcast_philosophical_signal": False,
            "permissions_profile": "scientist",
        }
    return {
        "can_submit_drift": True,
        "can_submit_discovery": True,
        "can_view_honey_hole": True,
        "can_broadcast_philosophical_signal": True,
        "permissions_profile": "admin",
    }


def normalise_tenant_id(raw: object, default: str = "internal") -> str:
    token = str(raw or "").strip().lower()
    cleaned = TENANT_ID_SANITIZER.sub("-", token).strip("-")
    if not cleaned:
        fallback = TENANT_ID_SANITIZER.sub("-", default.strip().lower()).strip("-")
        cleaned = fallback or "internal"
    return cleaned[:64]


def scoped_item_key(user_id: int, item_key: str) -> str:
    return f"u{int(user_id)}:{item_key.strip().lower()}"


def parse_scopes(raw: str) -> list[str]:
    scopes = []
    for token in (raw or "").split(","):
        value = token.strip()
        if value:
            scopes.append(value)
    return scopes or ["Marine", "Aviation", "Mineral"]


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(CREATE_USER_PROFILES)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(user_profiles)").fetchall()}
    if "share_signals" not in cols:
        conn.execute("ALTER TABLE user_profiles ADD COLUMN share_signals INTEGER NOT NULL DEFAULT 0")
    if "mentor_mesh" not in cols:
        conn.execute("ALTER TABLE user_profiles ADD COLUMN mentor_mesh TEXT")
    if "permissions_json" not in cols:
        conn.execute("ALTER TABLE user_profiles ADD COLUMN permissions_json TEXT")
    conn.execute(CREATE_MISSION_SCOPES)
    conn.execute(CREATE_EXPEDITIONS)
    conn.execute(CREATE_FUEL_LOGS)
    conn.execute(CREATE_SPECIMEN_INVENTORY)
    conn.execute(CREATE_MISSION_CONSUMABLES)
    conn.execute(CREATE_MISSION_CONSUMABLE_EVENTS)
    conn.execute(CREATE_FUEL_MARKET_LOGS)


def upsert_user(
    conn: sqlite3.Connection,
    username: str,
    role: str,
    home_base_icao: str,
    user_id: int | None,
    share_signals: bool,
    mentor_mesh: str | None,
    permissions_json: str,
) -> int:
    share_value = 1 if share_signals else 0
    if user_id is not None:
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
            (user_id, username, role, home_base_icao, share_value, mentor_mesh, permissions_json),
        )
        row = conn.execute("SELECT id FROM user_profiles WHERE id = ?", (user_id,)).fetchone()
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
            (username, role, home_base_icao, share_value, mentor_mesh, permissions_json),
        )
        row = conn.execute("SELECT id FROM user_profiles WHERE username = ?", (username,)).fetchone()

    if row is None:
        raise RuntimeError("Unable to resolve onboarded user id")
    return int(row[0])


def upsert_scopes(conn: sqlite3.Connection, user_id: int, scopes: list[str]) -> None:
    for scope in scopes:
        conn.execute(
            """
            INSERT INTO mission_scopes (user_id, scope_type, is_active)
            VALUES (?, ?, 1)
            ON CONFLICT(user_id, scope_type) DO UPDATE SET
                is_active = 1
            """,
            (user_id, scope),
        )


def seed_consumables(conn: sqlite3.Connection, user_id: int) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for item in MISSION_DEFAULTS:
        conn.execute(
            """
            INSERT INTO mission_consumables (
                item_key, display_name, quantity, unit, restock_threshold, updated_at, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(item_key) DO NOTHING
            """,
            (
                scoped_item_key(user_id, item["item_key"]),
                item["display_name"],
                item["quantity"],
                item["unit"],
                item["restock_threshold"],
                now,
                None,
            ),
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Onboard a user into a tenant-isolated HutchSolves database")
    parser.add_argument("--tenant-id", required=True, help="Tenant identifier (e.g. research-team-a)")
    parser.add_argument("--username", required=True, help="Username to create or update")
    parser.add_argument("--role", default="Scientist", choices=["Admin", "Scientist", "Guest Scientist", "Tourist"], help="Role for the user")
    parser.add_argument("--home-base-icao", default="KIXD", help="Home base ICAO code")
    parser.add_argument("--scopes", default="Marine,Aviation,Mineral", help="Comma-separated mission scopes")
    parser.add_argument("--mentor-mesh", default=GUEST_DEFAULT_MENTOR_MESH, help="Mentor mesh label for guest onboarding")
    parser.add_argument("--user-id", type=int, default=None, help="Optional explicit user id")
    parser.add_argument(
        "--share-signals",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Opt user into anonymized Global Node signal sharing",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()

    tenant_id = normalise_tenant_id(args.tenant_id)
    tenant_dir = TENANTS_ROOT / tenant_id
    db_path = tenant_dir / "marine.sqlite"

    role = args.role.strip()
    is_guest_scientist = role == "Guest Scientist"
    scopes = GUEST_AUDIT_SCOPES if is_guest_scientist else parse_scopes(args.scopes)
    share_signals = True if is_guest_scientist else bool(args.share_signals)
    mentor_mesh = args.mentor_mesh.strip().lower() if is_guest_scientist else None
    permissions_json = json.dumps(_default_permissions(role), sort_keys=True)

    tenant_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        ensure_schema(conn)
        user_id = upsert_user(
            conn,
            username=args.username.strip(),
            role=role,
            home_base_icao=args.home_base_icao.strip().upper() or "KIXD",
            user_id=args.user_id,
            share_signals=share_signals,
            mentor_mesh=mentor_mesh,
            permissions_json=permissions_json,
        )
        upsert_scopes(conn, user_id=user_id, scopes=scopes)
        seed_consumables(conn, user_id=user_id)
        conn.commit()
    finally:
        conn.close()

    print(f"Onboarding complete for tenant '{tenant_id}'.")
    print(f"Database: {db_path}")
    print(f"User: {args.username} (id={user_id}, role={role})")
    print(f"Signal Sharing Opt-In: {'enabled' if share_signals else 'disabled'}")
    if mentor_mesh:
        print(f"Mentor Mesh: {mentor_mesh}")
    print(f"Scopes: {', '.join(scopes)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
