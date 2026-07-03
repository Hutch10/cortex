"""
provision_new_org.py — HutchSolves v8.0.0-ORCHESTRATOR org provisioning utility.

Spins up an isolated cluster of users for a new organization under the
multi-tenant ORGANIZATIONS_ROOT layout introduced in v8.0.0.

Usage:
    python scripts/provision_new_org.py <org_id> [--admin <username>] [--dry-run]

Layout created:
    <ORGANIZATIONS_ROOT>/
        <org_id>/
            tenants/
                default/
                    marine.sqlite        ← tenant DB with seeded user profiles
                    external_philosophy.json  ← corporate-values template

Exit code: 0 on success, 1 on failure.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── Repo root one level above this script ─────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent

_TENANT_ID_SANITIZER = re.compile(r"[^a-z0-9_-]+")

_DATA_HUB_ROOT = Path.home() / "AppData" / "Roaming" / "Aero Cortex Hub" / "data"
_ORGANIZATIONS_ROOT = _DATA_HUB_ROOT / "organizations"
_ORG_METADATA_FILENAME = "org_metadata.json"

# Default user cluster: Admin, Operations Director, Lead Analyst, Associate
_DEFAULT_USERS: list[dict] = [
    {"username": "admin",       "role": "Admin",     "home_base_icao": "KIXD"},
    {"username": "operations_director", "role": "Operations Director", "home_base_icao": "KIXD"},
    {"username": "lead_analyst_1",      "role": "Lead Analyst", "home_base_icao": "KIXD"},
    {"username": "associate_1",         "role": "Associate",   "home_base_icao": "KIXD"},
]

_PHILOSOPHY_TEMPLATE: dict = {
    "title": "Corporate Values",
    "values": [
        "Integrity first: decisions reflect our principles.",
        "Continuous improvement: every cycle is a learning cycle.",
        "Collaboration over isolation: shared knowledge multiplies impact.",
        "Sustainability: long-term health preferred over short-term gain.",
        "Transparency: clear signals, no hidden telemetry.",
    ],
    "weight": 0.35,
}

_CREATE_USER_PROFILES = """
CREATE TABLE IF NOT EXISTS user_profiles (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    username       TEXT UNIQUE NOT NULL,
    role           TEXT NOT NULL DEFAULT 'Lead Analyst',
    home_base_icao TEXT,
    share_signals  INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL
)
"""


def _normalise_org_id(value: str) -> str:
    token = value.strip().lower()
    cleaned = _TENANT_ID_SANITIZER.sub("-", token).strip("-")
    if not cleaned:
        raise ValueError(f"Invalid organization ID: {value!r}")
    return cleaned[:64]


def _org_metadata_path(org_id: str) -> Path:
    return _ORGANIZATIONS_ROOT / org_id / _ORG_METADATA_FILENAME


def _ok(msg: str) -> None:
    print(f"  [OK]  {msg}")


def _info(msg: str) -> None:
    print(f"  [--]  {msg}")


def _fail(msg: str) -> None:
    print(f"  [FAIL] {msg}", file=sys.stderr)


def provision(org_id: str, admin_username: str | None, dry_run: bool, parent_org_id: str | None = None) -> bool:
    try:
        org_id = _normalise_org_id(org_id)
    except ValueError as exc:
        _fail(str(exc))
        return False

    resolved_parent_org_id = None
    if parent_org_id not in (None, ""):
        try:
            resolved_parent_org_id = _normalise_org_id(parent_org_id)
        except ValueError as exc:
            _fail(str(exc))
            return False

    org_root = _ORGANIZATIONS_ROOT / org_id
    tenant_dir = org_root / "tenants" / "default"
    db_path = tenant_dir / "marine.sqlite"
    philosophy_path = tenant_dir / "external_philosophy.json"
    metadata_path = _org_metadata_path(org_id)

    print()
    print("=" * 66)
    print(f"  HutchSolves v8.0.0-ORCHESTRATOR — Provision New Org")
    print("=" * 66)
    print(f"  Organization ID : {org_id}")
    if resolved_parent_org_id:
        print(f"  Parent Org      : {resolved_parent_org_id}")
    print(f"  Database        : {db_path}")
    print(f"  Philosophy      : {philosophy_path}")
    print(f"  Metadata        : {metadata_path}")
    if dry_run:
        print("  Mode            : DRY RUN (no files will be written)")
    print()

    if db_path.exists():
        _info(f"Organization '{org_id}' already has a tenant DB at {db_path}; skipping creation.")
    elif not dry_run:
        tenant_dir.mkdir(parents=True, exist_ok=True)

        # Seed the database with the default user cluster.
        users = [dict(u) for u in _DEFAULT_USERS]
        if admin_username:
            # Replace the default 'admin' username with the caller's choice.
            for i, u in enumerate(users):
                if u["role"] == "Admin":
                    users[i] = dict(u, username=admin_username)
                    break

        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute(_CREATE_USER_PROFILES)
            now = datetime.now(timezone.utc).isoformat()
            for user in users:
                conn.execute(
                    "INSERT OR IGNORE INTO user_profiles (username, role, home_base_icao, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    (user["username"], user["role"], user["home_base_icao"], now),
                )
            conn.commit()

            seeded = conn.execute("SELECT id, username, role FROM user_profiles").fetchall()
        finally:
            conn.close()

        _ok(f"Tenant DB created: {db_path}")
        for row in seeded:
            _ok(f"  User seeded — id={row[0]}, username={row[1]!r}, role={row[2]!r}")
    else:
        _info(f"[DRY RUN] Would create tenant DB at {db_path}")
        for user in _DEFAULT_USERS:
            _info(f"  [DRY RUN] Would seed user: username={user['username']!r}, role={user['role']!r}")

    # Write the external philosophy template.
    if philosophy_path.exists():
        _info(f"external_philosophy.json already exists at {philosophy_path}; skipping.")
    elif not dry_run:
        philosophy_path.write_text(
            json.dumps(_PHILOSOPHY_TEMPLATE, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        _ok(f"Corporate Values template written: {philosophy_path}")
    else:
        _info(f"[DRY RUN] Would write external_philosophy.json at {philosophy_path}")

    metadata_doc = {
        "org_id": org_id,
        "parent_org_id": resolved_parent_org_id,
        "relationship_type": "child" if resolved_parent_org_id else "root",
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if metadata_path.exists():
        _info(f"Organization metadata already exists at {metadata_path}; skipping overwrite.")
    elif not dry_run:
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        metadata_path.write_text(json.dumps(metadata_doc, indent=2), encoding="utf-8")
        _ok(f"Organization metadata written: {metadata_path}")
    else:
        _info(f"[DRY RUN] Would write organization metadata at {metadata_path}")

    print()
    print("=" * 66)
    if dry_run:
        print(f"  [DRY RUN] Organization '{org_id}' provisioning plan complete.")
    else:
        print(f"  Organization '{org_id}' provisioned successfully.")
        print(f"  Operations Director isolation is enforced via separate database paths.")
        if resolved_parent_org_id:
            print(f"  Parent-child franchise relationship registered under '{resolved_parent_org_id}'.")
        print(f"  Upload a custom external_philosophy.json to override corporate values.")
    print("=" * 66)
    print()
    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Provision a new isolated HutchSolves organization.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("org_id", help="Organization identifier (e.g. 'acme-corp', 'internal')")
    parser.add_argument("--admin", metavar="USERNAME", default=None, help="Override the default 'admin' username.")
    parser.add_argument("--parent-org", metavar="ORG_ID", default=None, help="Optional parent organization identifier for franchise hierarchies.")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be done without writing any files.")
    args = parser.parse_args()

    success = provision(
        org_id=args.org_id,
        admin_username=args.admin,
        dry_run=args.dry_run,
        parent_org_id=args.parent_org,
    )
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
