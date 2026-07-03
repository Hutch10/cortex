from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

try:
    from supabase import Client, create_client
except ImportError as exc:  # pragma: no cover - dependency guard for local setup
    raise RuntimeError(
        "Missing dependency 'supabase'. Install with: pip install supabase"
    ) from exc


TENANTS_TABLE = "tenants"
ASSET_HEALTH_TABLE = "asset_health"


@dataclass(frozen=True)
class AssetSample:
    tenant_id: str
    tail_number: str
    iron_ppm: float
    flight_hours: float
    report_date: str
    status: str
    wear_rate_ppm_hr: float | None


def _env(name: str) -> str | None:
    value = os.getenv(name)
    return value.strip() if value else None


def get_supabase_client() -> Client:
    url = _env("SUPABASE_URL")
    key = _env("SUPABASE_SERVICE_ROLE_KEY") or _env("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError(
            "Missing Supabase credentials. Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY "
            "(or SUPABASE_KEY for environments where inserts are allowed)."
        )
    return create_client(url, key)


def compute_status(wear_rate_ppm_hr: float | None) -> str:
    if wear_rate_ppm_hr is None:
        return "STABLE"
    if wear_rate_ppm_hr >= 1.0:
        return "CRITICAL"
    if wear_rate_ppm_hr > 0.5:
        return "CAUTION"
    return "STABLE"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create or reuse a HutchSolves Cortex tenant and insert an asset_health sample into Supabase."
    )
    parser.add_argument("name", help="Tenant name, e.g. NorthStar Aviation")
    parser.add_argument("tail", help="Aircraft tail number, e.g. N1234P")
    parser.add_argument("hours", type=float, help="Current flight hours, e.g. 1025")
    parser.add_argument("iron", type=float, help="Current iron PPM sample, e.g. 55")
    parser.add_argument("--home-base", default=None, help="Optional home base ICAO code")
    parser.add_argument(
        "--report-date",
        default=date.today().isoformat(),
        help="Sample report date in YYYY-MM-DD format (defaults to today)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON output instead of a human summary.",
    )
    return parser.parse_args()


def normalise_tail_number(raw: str) -> str:
    return str(raw or "").strip().upper()


def ensure_report_date(raw: str) -> str:
    try:
        return date.fromisoformat(str(raw)).isoformat()
    except ValueError as exc:
        raise ValueError("report-date must be YYYY-MM-DD") from exc


def find_tenant(client: Client, tenant_name: str) -> dict[str, Any] | None:
    response = (
        client.table(TENANTS_TABLE)
        .select("id, tenant_name, home_base_icao, created_at")
        .eq("tenant_name", tenant_name)
        .limit(1)
        .execute()
    )
    rows = list(response.data or [])
    return rows[0] if rows else None


def create_tenant(client: Client, tenant_name: str, home_base_icao: str | None) -> dict[str, Any]:
    tenant_id = str(uuid.uuid4())
    payload = {
        "id": tenant_id,
        "tenant_name": tenant_name,
        "home_base_icao": home_base_icao,
    }
    response = client.table(TENANTS_TABLE).insert(payload).execute()
    rows = list(response.data or [])
    if not rows:
        raise RuntimeError("Supabase did not return the created tenant row.")
    return rows[0]


def find_or_create_tenant(client: Client, tenant_name: str, home_base_icao: str | None) -> dict[str, Any]:
    existing = find_tenant(client, tenant_name)
    if existing:
        return existing
    return create_tenant(client, tenant_name, home_base_icao)


def previous_asset_sample(client: Client, tenant_id: str, tail_number: str) -> dict[str, Any] | None:
    response = (
        client.table(ASSET_HEALTH_TABLE)
        .select("iron_ppm, flight_hours, report_date, status")
        .eq("tenant_id", tenant_id)
        .eq("tail_number", tail_number)
        .order("flight_hours", desc=True)
        .limit(1)
        .execute()
    )
    rows = list(response.data or [])
    return rows[0] if rows else None


def build_asset_sample(
    *,
    tenant_id: str,
    tail_number: str,
    iron_ppm: float,
    flight_hours: float,
    report_date: str,
    previous: dict[str, Any] | None,
) -> AssetSample:
    wear_rate_ppm_hr: float | None = None
    if previous:
        prev_iron = float(previous.get("iron_ppm") or 0.0)
        prev_hours = float(previous.get("flight_hours") or 0.0)
        hours_delta = flight_hours - prev_hours
        if hours_delta > 0:
            wear_rate_ppm_hr = (iron_ppm - prev_iron) / hours_delta

    status = compute_status(wear_rate_ppm_hr)
    return AssetSample(
        tenant_id=tenant_id,
        tail_number=tail_number,
        iron_ppm=iron_ppm,
        flight_hours=flight_hours,
        report_date=report_date,
        status=status,
        wear_rate_ppm_hr=wear_rate_ppm_hr,
    )


def insert_asset_sample(client: Client, sample: AssetSample) -> dict[str, Any]:
    payload = {
        "tenant_id": sample.tenant_id,
        "tail_number": sample.tail_number,
        "iron_ppm": sample.iron_ppm,
        "flight_hours": sample.flight_hours,
        "report_date": sample.report_date,
        "status": sample.status,
    }
    response = client.table(ASSET_HEALTH_TABLE).insert(payload).execute()
    rows = list(response.data or [])
    if not rows:
        raise RuntimeError("Supabase did not return the inserted asset_health row.")
    return rows[0]


def main() -> int:
    args = parse_args()
    tenant_name = str(args.name).strip()
    tail_number = normalise_tail_number(args.tail)
    report_date = ensure_report_date(args.report_date)

    if not tenant_name:
        raise ValueError("name must not be empty")
    if not tail_number:
        raise ValueError("tail must not be empty")
    if args.hours < 0:
        raise ValueError("hours must be non-negative")
    if args.iron < 0:
        raise ValueError("iron must be non-negative")

    client = get_supabase_client()
    tenant = find_or_create_tenant(client, tenant_name, args.home_base)
    tenant_id = str(tenant.get("id"))

    previous = previous_asset_sample(client, tenant_id, tail_number)
    sample = build_asset_sample(
        tenant_id=tenant_id,
        tail_number=tail_number,
        iron_ppm=float(args.iron),
        flight_hours=float(args.hours),
        report_date=report_date,
        previous=previous,
    )
    inserted = insert_asset_sample(client, sample)

    summary = {
        "tenant": {
            "id": tenant_id,
            "tenant_name": tenant.get("tenant_name"),
            "home_base_icao": tenant.get("home_base_icao"),
        },
        "asset_health": inserted,
        "computed": {
            "wear_rate_ppm_hr": round(sample.wear_rate_ppm_hr, 4) if sample.wear_rate_ppm_hr is not None else None,
            "status": sample.status,
        },
    }

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"Tenant      : {tenant.get('tenant_name')} ({tenant_id})")
        print(f"Tail Number : {tail_number}")
        print(f"Report Date : {report_date}")
        print(f"Iron PPM    : {sample.iron_ppm:.2f}")
        print(f"Flight Hours: {sample.flight_hours:.2f}")
        if sample.wear_rate_ppm_hr is None:
            print("Wear Rate   : baseline sample (no previous reading)")
        else:
            print(f"Wear Rate   : {sample.wear_rate_ppm_hr:.2f} ppm/hr")
        print(f"Status      : {sample.status}")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)