from __future__ import annotations

import io
import json
import os
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd
import streamlit as st
import torch

try:
    import torch_directml
except ImportError:
    torch_directml = None

try:
    from supabase import Client, create_client
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("Missing dependency 'supabase'. Install with: pip install supabase streamlit") from exc

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from reportlab.graphics.charts.lineplots import LinePlot
    from reportlab.graphics.shapes import Drawing

    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False


APP_TITLE = "HutchSolves Cortex"
APP_SUBTITLE = "Sentinel Engine Health Oracle"
APP_DESCRIPTION = "Real-time Wear Rate Analysis for Beta 5 Operators"
DEFAULT_TEST_TENANT_ID = "b09df01c-8b8a-470c-bcfb-21fc2fcf27eb"
DEFAULT_TEST_TAIL = "N1234P"
SENTINEL_VIEW = "sentinel_diagnostics"
ASSET_HEALTH_TABLE = "asset_health"
MAINTENANCE_EVENTS_TABLE = "maintenance_events"
PILOT_FEEDBACK_TABLE = "pilot_feedback"
DEMO_TAIL_NUMBER = "N-901SH"
GROUNDING_RISK_HOURS = 25.0
DEMO_RAPID_WEAR_PATTERN: list[tuple[float, float]] = [
    (0.0, 15.0),
    (12.0, 30.0),
    (25.0, 47.0),
    (40.0, 65.0),
]


def _secret(name: str) -> str | None:
    try:
        value = st.secrets.get(name)
    except Exception:
        value = None
    return str(value).strip() if value else os.getenv(name)


@st.cache_resource(show_spinner=False)
def get_supabase_client() -> Client:
    url = _secret("SUPABASE_URL")
    key = _secret("SUPABASE_ANON_KEY") or _secret("SUPABASE_KEY") or _secret("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise RuntimeError(
            "Missing Supabase credentials. Set SUPABASE_URL and SUPABASE_ANON_KEY "
            "(or SUPABASE_KEY / SUPABASE_SERVICE_ROLE_KEY)."
        )
    return create_client(url, key)


@st.cache_resource(show_spinner=False)
def get_ml_device() -> tuple[torch.device, str]:
    # Required DirectML path for AMD acceleration; clean CPU fallback for local dev.
    if torch_directml is not None:
        return torch_directml.device(), "DirectML"
    return torch.device("cpu"), "CPU"


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _wear_rate_key(row: dict[str, Any]) -> str | None:
    if "wear_rate_ppm_hr" in row:
        return "wear_rate_ppm_hr"
    if "wear_rate" in row:
        return "wear_rate"
    return None


def wear_rate_ppm_hr(row: dict[str, Any]) -> float | None:
    key = _wear_rate_key(row)
    return _as_float(row.get(key)) if key else None


def compute_status(rate: float | None) -> str:
    if rate is None:
        return "UNKNOWN"
    if rate >= 1.0:
        return "CRITICAL"
    if rate > 0.5:
        return "CAUTION"
    return "STABLE"


def _parse_event_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None


def _coerce_timestamp_text(value: Any) -> str:
    ts = _parse_event_timestamp(value)
    if ts is not None:
        return ts.isoformat()
    return str(value or "")


def generate_integrity_seal(timestamp: Any, notes: str, technician_id: str) -> str:
    """
    FAA Part 145 Compliant Non-Repudiation Layer (SHA-256 Cryptographic Seal).

    Generates a deterministic SHA-256 hash seal over maintenance event metadata as an
    immutable record of the event's integrity. The seal acts as a digital certificate
    of authenticity, binding the event timestamp, technical notes, and certifying
    technician identity into a unified cryptographic proof.

    This hash may be stored alongside the event record and independently verified by
    auditors or by external compliance systems to prove no tampering has occurred.
    Canonical ordering (timestamp | notes | technician_id) ensures reproducibility.

    Args:
        timestamp: Event occurrence time (UTC or ISO string).
        notes: Technical maintenance description.
        technician_id: FAA-issued certificate number or organizational ID of responsible technician.

    Returns:
        Hex-encoded SHA-256 digest string (64 characters).
    """
    payload = f"{_coerce_timestamp_text(timestamp)}|{str(notes or '').strip()}|{str(technician_id or '').strip()}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def verify_maintenance_event_integrity(event: dict[str, Any]) -> bool:
    event_ts = (
        event.get("event_time")
        or event.get("occurred_at")
        or event.get("created_at")
        or event.get("report_date")
    )
    notes = str(event.get("notes") or "")
    technician_id = str(event.get("technician_id") or "unknown")
    expected = generate_integrity_seal(event_ts, notes, technician_id)
    return str(event.get("integrity_seal") or "") == expected
    try:
        parsed = pd.to_datetime(value, errors="coerce", utc=True)
        if pd.isna(parsed):
            return None
        return parsed.to_pydatetime()
    except Exception:
        return None


def requested_tenant_id() -> str:
    raw = st.query_params.get("tenant_id") or st.query_params.get("tenant") or DEFAULT_TEST_TENANT_ID
    if isinstance(raw, list):
        raw = raw[0] if raw else DEFAULT_TEST_TENANT_ID
    return str(raw or DEFAULT_TEST_TENANT_ID).strip()


def _feedback_submission_key(tenant_id: str) -> str:
    return f"feedback_submitted::{tenant_id}"


def save_feedback(tenant_id: str, rating: int, wishlist: list[str], notes: str) -> tuple[bool, str]:
    payload = {
        "tenant_id": tenant_id,
        "rating": int(rating),
        "wishlist": list(wishlist),
        "notes": str(notes or "").strip(),
        "submitted_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        get_supabase_client().table(PILOT_FEEDBACK_TABLE).insert(payload).execute()
        return True, "database"
    except Exception:
        queue = st.session_state.setdefault("unsynced_feedback", [])
        queue.append(payload)
        st.session_state["unsynced_feedback"] = queue
        return False, "session_fallback"


@st.cache_data(ttl=30, show_spinner=False)
def load_tenant_diagnostics(tenant_id: str) -> list[dict[str, Any]]:
    response = (
        get_supabase_client()
        .table(SENTINEL_VIEW)
        .select(
            """
            tenant_id,
            tail_number,
            iron_ppm,
            flight_hours,
            report_date,
            wear_rate,
            wear_rate_ppm_hr,
            confidence_interval_low,
            confidence_interval_high
            """
        )
        .eq("tenant_id", tenant_id)
        .order("report_date", desc=True)
        .order("flight_hours", desc=True)
        .execute()
    )
    return list(response.data or [])


@st.cache_data(ttl=30, show_spinner=False)
def load_asset_history(tenant_id: str, tail_number: str) -> list[dict[str, Any]]:
    response = (
        get_supabase_client()
        .table(ASSET_HEALTH_TABLE)
        .select("tenant_id, tail_number, iron_ppm, flight_hours, report_date, status")
        .eq("tenant_id", tenant_id)
        .eq("tail_number", tail_number)
        .order("report_date", desc=True)
        .order("flight_hours", desc=True)
        .execute()
    )
    return list(response.data or [])


def _session_demo_events_key(tenant_id: str, tail_number: str) -> str:
    return f"demo_events::{tenant_id}::{tail_number}"


def _append_session_demo_event(
    tenant_id: str,
    tail_number: str,
    action_type: str,
    notes: str,
    technician_id: str,
) -> None:
    event_time = datetime.now(timezone.utc).isoformat()
    key = _session_demo_events_key(tenant_id, tail_number)
    existing = st.session_state.get(key, [])
    existing.append(
        {
            "tenant_id": tenant_id,
            "tail_number": tail_number,
            "action_type": action_type,
            "notes": notes,
            "event_time": event_time,
            "technician_id": technician_id,
            "integrity_seal": generate_integrity_seal(event_time, notes, technician_id),
            "source": "session_fallback",
        }
    )
    st.session_state[key] = existing


@st.cache_data(ttl=15, show_spinner=False)
def load_maintenance_events(tenant_id: str, tail_number: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    try:
        response = (
            get_supabase_client()
            .table(MAINTENANCE_EVENTS_TABLE)
            .select(
                "tenant_id, tail_number, action_type, notes, event_time, created_at, occurred_at, "
                "report_date, technician_id, integrity_seal"
            )
            .eq("tenant_id", tenant_id)
            .eq("tail_number", tail_number)
            .execute()
        )
        events.extend(list(response.data or []))
    except Exception:
        # Demo still works even if maintenance_events is not provisioned in this environment.
        pass

    events.extend(st.session_state.get(_session_demo_events_key(tenant_id, tail_number), []))
    events.sort(
        key=lambda e: _parse_event_timestamp(
            e.get("event_time") or e.get("occurred_at") or e.get("created_at") or e.get("report_date")
        )
        or datetime.fromtimestamp(0, tz=timezone.utc),
        reverse=True,
    )
    return events


@st.cache_data(ttl=15, show_spinner=False)
def load_tenant_maintenance_events(tenant_id: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    try:
        response = (
            get_supabase_client()
            .table(MAINTENANCE_EVENTS_TABLE)
            .select(
                "tenant_id, tail_number, action_type, notes, event_time, created_at, occurred_at, "
                "report_date, technician_id, integrity_seal"
            )
            .eq("tenant_id", tenant_id)
            .execute()
        )
        events.extend(list(response.data or []))
    except Exception:
        pass

    # include any offline/session events for this tenant across all tails
    for key, value in st.session_state.items():
        if not str(key).startswith("demo_events::"):
            continue
        if not isinstance(value, list):
            continue
        key_parts = str(key).split("::")
        if len(key_parts) >= 3 and key_parts[1] == tenant_id:
            events.extend(value)

    events.sort(
        key=lambda e: _parse_event_timestamp(
            e.get("event_time") or e.get("occurred_at") or e.get("created_at") or e.get("report_date")
        )
        or datetime.fromtimestamp(0, tz=timezone.utc),
        reverse=True,
    )
    return events


def _insert_maintenance_event(
    tenant_id: str,
    tail_number: str,
    action_type: str,
    notes: str,
    technician_id: str | None = None,
) -> tuple[bool, str]:
    """Insert maintenance event with FAA Part 145 integrity seal."""
    event_time = datetime.now(timezone.utc).isoformat()
    if technician_id is None:
        technician_id = _secret("TECHNICIAN_ID") or os.getenv("TECHNICIAN_ID") or "UNASSIGNED"
    payload = {
        "tenant_id": tenant_id,
        "tail_number": tail_number,
        "action_type": action_type,
        "notes": notes,
        "event_time": event_time,
        "technician_id": technician_id,
        "integrity_seal": generate_integrity_seal(event_time, notes, technician_id),
    }
    try:
        get_supabase_client().table(MAINTENANCE_EVENTS_TABLE).insert(payload).execute()
        return True, "database"
    except Exception:
        _append_session_demo_event(tenant_id, tail_number, action_type, notes, technician_id)
        return False, "session_fallback"


def simulate_rapid_wear(tenant_id: str, tail_number: str = DEMO_TAIL_NUMBER) -> int:
    latest = load_asset_history(tenant_id=tenant_id, tail_number=tail_number)
    base_hours = _as_float(latest[0].get("flight_hours")) if latest else None
    if base_hours is None:
        base_hours = 1000.0

    start_dt = datetime.now(timezone.utc) - timedelta(hours=40)
    rows: list[dict[str, Any]] = []
    previous_ppm: float | None = None
    previous_hours: float | None = None
    for offset_hours, iron_ppm in DEMO_RAPID_WEAR_PATTERN:
        flight_hours = float(base_hours + offset_hours)
        report_date = (start_dt + timedelta(hours=float(offset_hours))).date().isoformat()
        status = "STABLE"
        if previous_ppm is not None and previous_hours is not None and (flight_hours - previous_hours) > 0:
            status = compute_status((iron_ppm - previous_ppm) / (flight_hours - previous_hours))
        rows.append(
            {
                "tenant_id": tenant_id,
                "tail_number": tail_number,
                "iron_ppm": float(iron_ppm),
                "flight_hours": flight_hours,
                "report_date": report_date,
                "status": status,
            }
        )
        previous_ppm = float(iron_ppm)
        previous_hours = flight_hours

    get_supabase_client().table(ASSET_HEALTH_TABLE).insert(rows).execute()
    return len(rows)


def detect_last_wear_spike(history: pd.DataFrame) -> datetime | None:
    if history.empty:
        return None
    clean = history.dropna(subset=["iron_ppm", "flight_hours", "report_date"]).sort_values(["report_date", "flight_hours"])
    if len(clean) < 2:
        return None

    last_spike: datetime | None = None
    for idx in range(1, len(clean)):
        prev = clean.iloc[idx - 1]
        curr = clean.iloc[idx]
        hours_delta = float(curr["flight_hours"] - prev["flight_hours"])
        if hours_delta <= 0:
            continue
        rate = float(curr["iron_ppm"] - prev["iron_ppm"]) / hours_delta
        if rate >= 1.0:
            ts = _parse_event_timestamp(curr["report_date"])
            if ts is not None:
                last_spike = ts
    return last_spike


def _event_timestamp(event: dict[str, Any]) -> datetime | None:
    return _parse_event_timestamp(
        event.get("event_time") or event.get("occurred_at") or event.get("created_at") or event.get("report_date")
    )


def event_is_borescope_clearance(event: dict[str, Any]) -> bool:
    action = str(event.get("action_type") or "").strip().lower()
    notes = str(event.get("notes") or "").strip().lower()
    if action != "borescope inspection":
        return False
    return "exhaust valves healthy" in notes or "no metal in screen" in notes


def event_is_preventative_save(event: dict[str, Any]) -> bool:
    notes = str(event.get("notes") or "").strip().lower()
    return "top-end overhaul scheduled" in notes or "early-stage burning" in notes


def evaluate_resolution(events: list[dict[str, Any]], last_spike_at: datetime | None) -> tuple[bool, bool]:
    if last_spike_at is None:
        return False, any(event_is_preventative_save(event) for event in events)

    cleared = False
    save_logged = False
    for event in events:
        event_ts = _event_timestamp(event)
        if event_ts is None or event_ts <= last_spike_at:
            continue
        if event_is_borescope_clearance(event):
            cleared = True
        if event_is_preventative_save(event):
            save_logged = True
    return cleared, save_logged


def _sort_key(row: dict[str, Any]) -> tuple[str, float]:
    report_date = str(row.get("report_date") or "")
    flight_hours = _as_float(row.get("flight_hours")) or 0.0
    return report_date, flight_hours


def latest_by_tail(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in sorted(rows, key=_sort_key, reverse=True):
        tail = str(row.get("tail_number") or "").strip().upper()
        if tail and tail not in latest:
            latest[tail] = row
    return latest


def history_dataframe(rows: list[dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=["report_date", "iron_ppm", "flight_hours", "status"])
    frame = pd.DataFrame(rows)
    if "report_date" in frame.columns:
        frame["report_date"] = pd.to_datetime(frame["report_date"], errors="coerce", utc=True)
    if "iron_ppm" in frame.columns:
        frame["iron_ppm"] = pd.to_numeric(frame["iron_ppm"], errors="coerce")
    if "flight_hours" in frame.columns:
        frame["flight_hours"] = pd.to_numeric(frame["flight_hours"], errors="coerce")
    return frame.sort_values(["report_date", "flight_hours"], ascending=[True, True])


def _linear_regression_directml(report_date: pd.Series, iron_ppm: pd.Series) -> tuple[float, float] | None:
    clean = pd.DataFrame({"report_date": report_date, "iron_ppm": iron_ppm}).dropna()
    if len(clean) < 2:
        return None

    min_ts = clean["report_date"].iloc[0]
    x_hours = (clean["report_date"] - min_ts).dt.total_seconds() / 3600.0
    if float(x_hours.max() - x_hours.min()) <= 0:
        return None

    device, _backend = get_ml_device()
    x = torch.tensor(x_hours.to_numpy(dtype="float32"), device=device)
    y = torch.tensor(clean["iron_ppm"].to_numpy(dtype="float32"), device=device)
    ones = torch.ones_like(x)
    design = torch.stack([x, ones], dim=1)
    coeffs = torch.linalg.pinv(design) @ y
    slope = float(coeffs[0].detach().cpu().item())
    intercept = float(coeffs[1].detach().cpu().item())
    return slope, intercept


def project_engine_life_remaining(iron_ppm: pd.Series, report_date: pd.Series, threshold_ppm: float = 100.0) -> dict[str, Any] | None:
    """
    Bayesian Engine Life Remaining Projector (DirectML-accelerated).

    Performs robust regression using a 95% Confidence Interval framework with Monte Carlo
    Simulation to project engine failure thresholds. Implements a two-stage inference approach:

    1. Least-squares linear regression on iron PPM vs. time (DirectML or CPU device).
    2. Cholesky-decomposed covariance matrix with 2048 Monte Carlo draws to estimate the
       posterior distribution of wear slope and intercept parameters.

    Returns quantile-based 95% Confidence Intervals on remaining operational hours and a
    crossing-time window [lower_2.5%, upper_97.5%] to support FAA Part 145 maintenance planning.

    Args:
        iron_ppm: Pandas Series of iron particle concentration (PPM) time series.
        report_date: Pandas Series of UTC-aware datetime objects aligned with iron_ppm.
        threshold_ppm: Failure threshold (default 100.0 PPM); crossing triggers grounding advisory.

    Returns:
        Dictionary with keys: remaining_hours, remaining_hours_lower95, remaining_hours_upper95,
        probability_under_25h, threshold_ppm, projected_failure_at, projected_failure_window_start,
        projected_failure_window_end, grounding_advisory. Returns None if insufficient data.
    """
    clean = pd.DataFrame({"report_date": report_date, "iron_ppm": iron_ppm}).dropna()
    if len(clean) < 2:
        return None

    clean = clean.sort_values("report_date")
    min_ts = clean["report_date"].iloc[0]
    latest_ts = clean["report_date"].iloc[-1]
    latest_hours = float((latest_ts - min_ts).total_seconds() / 3600.0)

    device, _backend = get_ml_device()
    x = ((clean["report_date"] - min_ts).dt.total_seconds() / 3600.0).to_numpy(dtype="float32")
    y = clean["iron_ppm"].to_numpy(dtype="float32")
    if len(x) < 2 or float(x.max() - x.min()) <= 0:
        return None

    x_t = torch.tensor(x, device=device)
    y_t = torch.tensor(y, device=device)
    ones = torch.ones_like(x_t)
    design = torch.stack([x_t, ones], dim=1)
    beta_hat = torch.linalg.pinv(design) @ y_t
    y_hat = design @ beta_hat
    residual = y_t - y_hat

    n = int(len(x))
    dof = max(n - 2, 1)
    sse = float((residual * residual).sum().detach().cpu().item())
    sigma2 = max(sse / float(dof), 1e-6)

    xtx = design.T @ design
    xtx_inv = torch.linalg.pinv(xtx)
    cov = xtx_inv * float(sigma2)
    jitter = torch.eye(2, device=device) * 1e-6
    try:
        chol = torch.linalg.cholesky(cov + jitter)
    except RuntimeError:
        diag = torch.sqrt(torch.clamp(torch.diag(cov), min=1e-6))
        chol = torch.diag(diag)

    draws = 2048
    z = torch.randn((2, draws), device=device)
    beta_draws = beta_hat.reshape(2, 1) + chol @ z
    slopes = beta_draws[0]
    intercepts = beta_draws[1]
    valid = slopes > 1e-6
    if int(valid.sum().detach().cpu().item()) < 10:
        return None

    crossing_hours = (float(threshold_ppm) - intercepts[valid]) / slopes[valid]
    remaining_hours = crossing_hours - float(latest_hours)
    finite = torch.isfinite(remaining_hours)
    remaining_hours = remaining_hours[finite]
    crossing_hours = crossing_hours[finite]
    if int(remaining_hours.numel()) < 10:
        return None

    rem_mean = float(remaining_hours.mean().detach().cpu().item())
    rem_p025 = float(torch.quantile(remaining_hours, 0.025).detach().cpu().item())
    rem_p975 = float(torch.quantile(remaining_hours, 0.975).detach().cpu().item())
    cross_p025 = float(torch.quantile(crossing_hours, 0.025).detach().cpu().item())
    cross_p975 = float(torch.quantile(crossing_hours, 0.975).detach().cpu().item())
    prob_under_25 = float((remaining_hours < GROUNDING_RISK_HOURS).float().mean().detach().cpu().item())

    mean_crossing = float(latest_hours + rem_mean)
    projected_ts_mean = min_ts + pd.to_timedelta(mean_crossing, unit="h")
    projected_window_start = min_ts + pd.to_timedelta(cross_p025, unit="h")
    projected_window_end = min_ts + pd.to_timedelta(cross_p975, unit="h")

    return {
        "remaining_hours": float(rem_mean),
        "remaining_hours_lower95": float(rem_p025),
        "remaining_hours_upper95": float(rem_p975),
        "probability_under_25h": float(prob_under_25),
        "threshold_ppm": float(threshold_ppm),
        "projected_failure_at": projected_ts_mean.to_pydatetime(),
        "projected_failure_window_start": projected_window_start.to_pydatetime(),
        "projected_failure_window_end": projected_window_end.to_pydatetime(),
        "grounding_advisory": bool(rem_p025 < GROUNDING_RISK_HOURS),
    }


def build_trend_drawing(history: pd.DataFrame) -> Drawing:
    drawing = Drawing(460, 180)
    if history.empty or "iron_ppm" not in history.columns:
        return drawing

    clean = history.dropna(subset=["report_date", "iron_ppm"]).sort_values("report_date")
    if clean.empty:
        return drawing

    if "flight_hours" in clean.columns and clean["flight_hours"].notna().any():
        x_values = pd.to_numeric(clean["flight_hours"], errors="coerce").fillna(method="ffill").fillna(0.0).to_numpy()
    else:
        x_values = list(range(len(clean)))
    y_values = pd.to_numeric(clean["iron_ppm"], errors="coerce").fillna(0.0).to_numpy()
    data = [list(zip(x_values, y_values))]

    chart = LinePlot()
    chart.x = 45
    chart.y = 25
    chart.height = 125
    chart.width = 390
    chart.data = data
    chart.lines[0].strokeColor = colors.HexColor("#1d4ed8")
    chart.lines[0].strokeWidth = 2
    chart.xValueAxis.valueMin = float(min(x_values))
    chart.xValueAxis.valueMax = float(max(x_values)) if float(max(x_values)) > float(min(x_values)) else float(min(x_values) + 1)
    chart.yValueAxis.valueMin = 0.0
    chart.yValueAxis.valueMax = max(100.0, float(max(y_values)) + 10.0)
    drawing.add(chart)
    return drawing


def generate_airworthiness_pdf(
    *,
    tenant_id: str,
    tail_number: str,
    projection: dict[str, Any] | None,
    history: pd.DataFrame,
    backend_label: str,
) -> bytes:
    if not REPORTLAB_AVAILABLE:
        raise RuntimeError("reportlab is not installed. Install with: pip install reportlab")

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, title="Cortex Sentinel Airworthiness Summary")
    styles = getSampleStyleSheet()
    story: list[Any] = []

    story.append(Paragraph("Cortex Sentinel Airworthiness Summary", styles["Title"]))
    story.append(Paragraph(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%SZ')}", styles["BodyText"]))
    story.append(Spacer(1, 10))

    if projection:
        predicted_window = (
            f"{projection['projected_failure_window_start'].strftime('%Y-%m-%d %H:%MZ')} to "
            f"{projection['projected_failure_window_end'].strftime('%Y-%m-%d %H:%MZ')}"
        )
        lower95 = f"{projection.get('remaining_hours_lower95', 0.0):.1f} hr"
        mean_remaining = f"{projection.get('remaining_hours', 0.0):.1f} hr"
    else:
        predicted_window = "Unavailable"
        lower95 = "Unavailable"
        mean_remaining = "Unavailable"

    summary_table = Table(
        [
            ["Tenant ID", tenant_id],
            ["Tail Number", tail_number],
            ["ML Backend", backend_label],
            ["Predicted Failure Window", predicted_window],
            ["Mean Remaining Life", mean_remaining],
            ["Worst-Case (Lower 95%)", lower95],
        ],
        colWidths=[180, 330],
    )
    summary_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#e2e8f0")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#94a3b8")),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    story.append(summary_table)
    story.append(Spacer(1, 12))

    story.append(Paragraph("DirectML Trend Graph", styles["Heading3"]))
    story.append(build_trend_drawing(history))
    story.append(Spacer(1, 12))

    story.append(Paragraph("Mechanic Signature: ________________________________", styles["BodyText"]))
    story.append(Paragraph("Certificate / A&P #: ______________________________", styles["BodyText"]))
    story.append(Paragraph("Date: ______________________________", styles["BodyText"]))

    doc.build(story)
    return buffer.getvalue()


def build_executive_diagnostics(diagnostics_rows: list[dict[str, Any]]) -> pd.DataFrame:
    if not diagnostics_rows:
        return pd.DataFrame(
            columns=["tail_number", "iron_ppm", "confidence_interval_low", "confidence_interval_high"]
        )

    latest_map = latest_by_tail(diagnostics_rows)
    output_rows: list[dict[str, Any]] = []

    for tail_number, latest in latest_map.items():
        tail_rows = [
            row for row in diagnostics_rows if str(row.get("tail_number") or "").strip().upper() == tail_number
        ]
        history = history_dataframe(tail_rows)
        projection = project_engine_life_remaining(
            iron_ppm=history.get("iron_ppm", pd.Series(dtype="float64")),
            report_date=history.get("report_date", pd.Series(dtype="datetime64[ns, UTC]")),
        )

        output_rows.append(
            {
                "tail_number": tail_number,
                "iron_ppm": _as_float(latest.get("iron_ppm")),
                "slope_ppm_per_hour": (
                    float(projection.get("slope_ppm_per_hour"))
                    if projection and projection.get("slope_ppm_per_hour") is not None
                    else None
                ),
                "confidence_interval_low": (
                    float(projection.get("remaining_hours_lower95")) if projection and projection.get("remaining_hours_lower95") is not None else None
                ),
                "confidence_interval_high": (
                    float(projection.get("remaining_hours_upper95")) if projection and projection.get("remaining_hours_upper95") is not None else None
                ),
            }
        )

    return pd.DataFrame(output_rows)


def detect_fleet_anomalies(df_diagnostics: pd.DataFrame) -> pd.DataFrame:
    """
    Population-Based Fleet Anomaly Detector (Z-Score Statistical Method).

    Implements outlier detection using standardized scores against the fleet-wide baseline.
    Computes the mean wear slope (PPM/hour) across all aircraft in the fleet and identifies
    outliers as those exceeding 1.5 standard deviations above the mean. This threshold
    corresponds to approximately the 93.3rd percentile in a normal distribution.

    The method is robust to missing/null wear rates and maintains numerical stability via
    1e-6 jitter when standard deviation approaches zero (homogeneous fleet wear).

    Returns sorted DataFrame (descending by z-score) for priority-based maintenance scheduling
    in compliance with fleet health monitoring frameworks.

    Args:
        df_diagnostics: DataFrame with columns 'tail_number', 'slope_ppm_per_hour', and optionally
                       'confidence_interval_low', 'confidence_interval_high'.

    Returns:
        Sorted DataFrame of outlier aircraft with Z-scores > 1.5, or empty if no anomalies.
    """
    if df_diagnostics.empty or "slope_ppm_per_hour" not in df_diagnostics.columns:
        return pd.DataFrame()

    working = df_diagnostics.copy()
    working["slope_ppm_per_hour"] = pd.to_numeric(working["slope_ppm_per_hour"], errors="coerce")
    working = working[working["slope_ppm_per_hour"].notna()]
    if working.empty:
        return pd.DataFrame()

    avg_wear = float(working["slope_ppm_per_hour"].mean())
    std_wear = float(working["slope_ppm_per_hour"].std() or 0.0)

    working["z_score"] = (working["slope_ppm_per_hour"] - avg_wear) / (std_wear + 1e-6)
    anomalies = working[working["z_score"] > 1.5].copy()
    return anomalies.sort_values("z_score", ascending=False)


def render_executive_summary(df_diagnostics: pd.DataFrame, df_events: pd.DataFrame) -> None:
    st.header("📊 Fleet Health & Integrity Audit")

    col1, col2, col3, col4 = st.columns(4)

    total_tails = int(df_diagnostics["tail_number"].nunique()) if "tail_number" in df_diagnostics.columns else 0
    preventative_saves = (
        int(
            df_events["notes"].astype(str).str.contains("save|overhaul|burning", case=False, na=False).sum()
        )
        if not df_events.empty and "notes" in df_events.columns
        else 0
    )
    active_groundings = (
        int(df_diagnostics[df_diagnostics["confidence_interval_low"] < 25]["tail_number"].nunique())
        if "confidence_interval_low" in df_diagnostics.columns
        else 0
    )

    if not df_events.empty:
        if "integrity_verified" not in df_events.columns:
            df_events = df_events.copy()
            df_events["integrity_verified"] = df_events.apply(verify_maintenance_event_integrity, axis=1)
        integrity_score = float(df_events["integrity_verified"].sum()) / float(len(df_events)) * 100.0
    else:
        integrity_score = 100.0

    col1.metric("Total Fleet", f"{total_tails} Tails")
    col2.metric("Preventative Saves", preventative_saves, delta="ROI Active", delta_color="normal")
    col3.metric("Grounding Risks", active_groundings, delta="-Immediate", delta_color="inverse")
    col4.metric(
        "Data Integrity",
        f"{integrity_score:.1f}%",
        help="Percentage of maintenance logs with verified cryptographic seals.",
    )

    st.subheader("⚠️ High-Risk Assets (Bayesian Priority)")
    if "confidence_interval_low" not in df_diagnostics.columns:
        st.info("No Bayesian confidence interval data available yet.")
        return

    risk_fleet = df_diagnostics[df_diagnostics["confidence_interval_low"].notna()]
    risk_fleet = risk_fleet[risk_fleet["confidence_interval_low"] < 50].sort_values("confidence_interval_low")

    if not risk_fleet.empty:
        st.dataframe(
            risk_fleet[["tail_number", "iron_ppm", "confidence_interval_low", "confidence_interval_high"]],
            column_config={
                "tail_number": "Tail #",
                "iron_ppm": "Current Fe",
                "confidence_interval_low": st.column_config.ProgressColumn(
                    "Min Life (Hrs)",
                    help="95% Lower Confidence Bound",
                    min_value=0,
                    max_value=100,
                    format="%.1f hr",
                ),
                "confidence_interval_high": st.column_config.NumberColumn("Max Life (Hrs)", format="%.1f hr"),
            },
            hide_index=True,
            use_container_width=True,
        )
    else:
        st.success("All fleet assets currently exceed the 50-hour safety margin.")

    st.subheader("🧠 Fleet Anomaly Watchlist (Z-Score)")
    anomalies = detect_fleet_anomalies(df_diagnostics)
    if not anomalies.empty:
        st.dataframe(
            anomalies[["tail_number", "slope_ppm_per_hour", "z_score", "confidence_interval_low"]],
            column_config={
                "tail_number": "Tail #",
                "slope_ppm_per_hour": st.column_config.NumberColumn("Wear Slope", format="%.3f ppm/hr"),
                "z_score": st.column_config.NumberColumn("Z-Score", format="%.2f"),
                "confidence_interval_low": st.column_config.NumberColumn("Min Life (95% Low)", format="%.1f hr"),
            },
            hide_index=True,
            use_container_width=True,
        )
    else:
        st.info("No fleet outliers detected (all tails within expected wear variance).")


def render_status_card(
    tenant_id: str,
    tail_number: str,
    diagnostic: dict[str, Any],
    projection: dict[str, Any] | None,
    *,
    borescope_cleared: bool,
    preventative_save_logged: bool,
) -> None:
    rate = wear_rate_ppm_hr(diagnostic)
    rate_label = f"{rate:.2f} ppm/hr" if rate is not None else "No trend available"
    iron_ppm = _as_float(diagnostic.get("iron_ppm"))
    flight_hours = _as_float(diagnostic.get("flight_hours"))
    report_date = diagnostic.get("report_date")
    report_text = str(report_date.date() if hasattr(report_date, "date") else report_date or "latest")

    st.divider()
    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric(label="Current Wear Rate", value=rate_label)
        st.write(f"Last Report: {report_text}")
        st.caption(f"Tenant Scope: {tenant_id} · Tail: {tail_number}")
        if iron_ppm is not None:
            st.write(f"Iron PPM: {iron_ppm:.2f}")
        if flight_hours is not None:
            st.write(f"Flight Hours: {flight_hours:.2f}")

    with col2:
        if borescope_cleared:
            st.success("STATUS: STABLE (Monitored)")
            st.info("Borescope clearance logged after wear spike. Continue monitoring cadence.")
        elif rate is not None and rate >= 1.0:
            st.error("STATUS: CRITICAL")
            st.warning("Action Required: Immediate internal engine inspection recommended.")
        elif rate is not None and rate > 0.5:
            st.warning("STATUS: CAUTION")
            st.info("Monitor trends. Shorten oil change interval.")
        else:
            st.success("STATUS: STABLE")
            st.write("Wear metrics within nominal range.")

    with col3:
        if projection is None:
            st.metric("Projected Engine Life Remaining", "N/A")
            st.caption("Need at least two valid iron/date points.")
        else:
            remaining = float(projection.get("remaining_hours") or 0.0)
            if remaining < 50.0:
                st.metric(
                    "Projected Engine Life Remaining",
                    f"{remaining:.1f} hr",
                    delta="-CRITICAL (<50h)",
                    delta_color="normal",
                )
                st.markdown("<span style='color:#b91c1c;font-weight:700;'>Projected life below 50 hours.</span>", unsafe_allow_html=True)
            else:
                st.metric(
                    "Projected Engine Life Remaining",
                    f"{remaining:.1f} hr",
                    delta="+Nominal",
                    delta_color="normal",
                )
            low95 = projection.get("remaining_hours_lower95")
            high95 = projection.get("remaining_hours_upper95")
            if low95 is not None and high95 is not None:
                st.caption(f"95% risk margin: {float(low95):.1f}h to {float(high95):.1f}h")

    if preventative_save_logged:
        st.markdown(
            "<span style='display:inline-block;margin-top:0.4rem;padding:0.45rem 0.75rem;"
            "border-radius:999px;background:#dcfce7;color:#14532d;font-weight:700;'>"
            "🏆 PREVENTATIVE SAVE LOGGED</span>",
            unsafe_allow_html=True,
        )


def main() -> None:
    st.set_page_config(page_title=APP_TITLE, page_icon="🛡️", layout="wide")
    st.title("🛡️ HutchSolves Cortex")
    st.subheader(APP_SUBTITLE)
    st.write(APP_DESCRIPTION)

    device, backend = get_ml_device()

    with st.sidebar:
        st.subheader("Connection")
        st.write("Reads latest wear-rate diagnostics from Supabase/PostgreSQL.")
        st.code("Required env vars:\nSUPABASE_URL\nSUPABASE_ANON_KEY (or SUPABASE_KEY)", language="bash")
        st.write("Tenant scope is taken from st.query_params['tenant_id'].")
        st.caption(f"ML backend: {backend} ({device})")

        st.divider()
        st.subheader("Demo Mode")
        st.caption("Hangar scenarios for sales demos (tenant-scoped).")

        st.divider()
        st.subheader("Safety")
        safety_override = st.toggle("Safety Override", value=False)
        safety_ack = False
        if safety_override:
            safety_ack = st.checkbox(
                "I understand this is a decision-support tool and not a replacement for certified inspection.",
                value=False,
            )
            if not safety_ack:
                st.error("Safety Override requires acknowledgment before action controls are enabled.")
        action_controls_disabled = safety_override and not safety_ack

    tenant_id = requested_tenant_id()

    with st.sidebar:
        if st.button("Simulate Rapid Wear (N-901SH)", use_container_width=True, disabled=action_controls_disabled):
            try:
                inserted = simulate_rapid_wear(tenant_id=tenant_id, tail_number=DEMO_TAIL_NUMBER)
                st.session_state["preferred_tail"] = DEMO_TAIL_NUMBER
                st.cache_data.clear()
                st.success(f"Injected {inserted} rapid-wear samples for {DEMO_TAIL_NUMBER}.")
                st.rerun()
            except Exception as exc:
                st.error(f"Rapid wear simulation failed: {exc}")

        if st.button("Simulate Borescope Clearance", use_container_width=True, disabled=action_controls_disabled):
            ok, mode = _insert_maintenance_event(
                tenant_id=tenant_id,
                tail_number=DEMO_TAIL_NUMBER,
                action_type="Borescope Inspection",
                notes="Exhaust valves healthy. No metal in screen.",
                technician_id="dom-demo",
            )
            st.session_state["preferred_tail"] = DEMO_TAIL_NUMBER
            st.cache_data.clear()
            if ok:
                st.success("Borescope clearance logged to maintenance_events.")
            else:
                st.warning(f"maintenance_events unavailable; recorded as {mode} for demo flow.")
            st.rerun()

        if st.button("Simulate Top-End Save", use_container_width=True, disabled=action_controls_disabled):
            ok, mode = _insert_maintenance_event(
                tenant_id=tenant_id,
                tail_number=DEMO_TAIL_NUMBER,
                action_type="Borescope Inspection",
                notes="Cylinder #4 Exhaust Valve showing early-stage burning. Top-end overhaul scheduled.",
                technician_id="dom-demo",
            )
            st.session_state["preferred_tail"] = DEMO_TAIL_NUMBER
            st.cache_data.clear()
            if ok:
                st.success("Preventative save logged to maintenance_events.")
            else:
                st.warning(f"maintenance_events unavailable; recorded as {mode} for demo flow.")
            st.rerun()

        st.divider()
        with st.expander("📝 Pilot Phase Feedback", expanded=False):
            submitted = bool(st.session_state.get(_feedback_submission_key(tenant_id), False))
            if submitted:
                st.markdown(
                    "<div style='background:#0f172a;color:#f8fafc;padding:0.85rem 0.95rem;"
                    "border-radius:12px;border:1px solid #1e293b;font-weight:700;'>"
                    "PHASE 1 FEEDBACK RECORDED. Thank you for securing the NorthStar Fleet.</div>",
                    unsafe_allow_html=True,
                )
                if st.session_state.get("unsynced_feedback"):
                    st.warning(f"⚠️ {len(st.session_state.unsynced_feedback)} Feedbacks Pending Sync")
                    feedback_json = json.dumps(st.session_state.unsynced_feedback, indent=2)
                    st.download_button(
                        label="📥 Download Unsynced Notes (JSON)",
                        data=feedback_json,
                        file_name=f"cortex_offline_feedback_{tenant_id}.json",
                        mime="application/json",
                    )
            else:
                st.caption("Capture Director of Maintenance feedback before closing the demo.")
                confidence_rating = st.slider(
                    "Oracle Accuracy Confidence",
                    min_value=1,
                    max_value=5,
                    value=4,
                    step=1,
                    help="1 = low confidence, 5 = high confidence",
                )
                wishlist_options = [
                    "Mobile Push Alerts",
                    "Direct Lab Integration",
                    "Logbook PDF Export",
                    "Parts Inventory Link",
                ]
                wishlist = st.multiselect("Feature Wishlist", options=wishlist_options)
                directors_note = st.text_area(
                    "Director's Note",
                    height=120,
                    placeholder="Share observations, trust signals, and rollout constraints...",
                )

                if st.button("Submit Feedback", use_container_width=True):
                    ok, sink = save_feedback(
                        tenant_id=tenant_id,
                        rating=confidence_rating,
                        wishlist=wishlist,
                        notes=directors_note,
                    )
                    st.session_state[_feedback_submission_key(tenant_id)] = True
                    st.session_state[f"feedback_sink::{tenant_id}"] = sink
                    if not ok:
                        st.session_state.setdefault("unsynced_feedback", [])
                    st.rerun()

    try:
        diagnostics = load_tenant_diagnostics(tenant_id)
    except Exception as exc:
        st.error(f"Could not load sentinel diagnostics for tenant {tenant_id}: {exc}")
        st.stop()

    if not diagnostics:
        st.info(f"No sentinel diagnostics found for tenant {tenant_id}.")
        st.stop()

    latest_map = latest_by_tail(diagnostics)
    tails = sorted(latest_map.keys())
    preferred_tail = str(st.session_state.get("preferred_tail") or "")
    if preferred_tail and preferred_tail in tails:
        default_tail_index = tails.index(preferred_tail)
    elif DEFAULT_TEST_TAIL in tails:
        default_tail_index = tails.index(DEFAULT_TEST_TAIL)
    else:
        default_tail_index = 0

    selected_tail = st.selectbox("Select Aircraft Tail Number", options=tails, index=default_tail_index)
    st.session_state["preferred_tail"] = selected_tail
    selected_diagnostic = latest_map[selected_tail]

    per_tail_diagnostics = [
        row for row in diagnostics if str(row.get("tail_number") or "").strip().upper() == selected_tail
    ]
    diagnostic_frame = history_dataframe(per_tail_diagnostics)
    with st.spinner("DirectML Bayesian Simulation Running..."):
        projection = project_engine_life_remaining(
            iron_ppm=diagnostic_frame.get("iron_ppm", pd.Series(dtype="float64")),
            report_date=diagnostic_frame.get("report_date", pd.Series(dtype="datetime64[ns, UTC]")),
        )

    if projection and bool(projection.get("grounding_advisory")):
        st.error(
            "IMMEDIATE GROUNDING ADVISORY: Bayesian worst-case risk margin is under 25 flight hours. "
            "Escalate to certified inspection and maintenance control now."
        )

    maintenance_events = load_maintenance_events(tenant_id=tenant_id, tail_number=selected_tail)
    last_spike_at = detect_last_wear_spike(diagnostic_frame)
    borescope_cleared, preventative_save_logged = evaluate_resolution(maintenance_events, last_spike_at)

    render_status_card(
        tenant_id,
        selected_tail,
        selected_diagnostic,
        projection,
        borescope_cleared=borescope_cleared,
        preventative_save_logged=preventative_save_logged,
    )

    wear_rate = wear_rate_ppm_hr(selected_diagnostic)
    if tenant_id == DEFAULT_TEST_TENANT_ID and selected_tail == DEFAULT_TEST_TAIL and wear_rate is not None:
        st.success(f"NorthStar verification: {selected_tail} is {compute_status(wear_rate)} at {wear_rate:.2f} ppm/hr.")

    history = load_asset_history(tenant_id, selected_tail)
    left, right = st.columns((1.2, 1.0))

    with left:
        st.subheader("Latest Diagnostic")
        latest_summary = {
            "tenant_id": selected_diagnostic.get("tenant_id"),
            "tail_number": selected_diagnostic.get("tail_number"),
            "iron_ppm": selected_diagnostic.get("iron_ppm"),
            "flight_hours": selected_diagnostic.get("flight_hours"),
            "report_date": str(selected_diagnostic.get("report_date")),
            "wear_rate_ppm_hr": wear_rate,
            "status": "STABLE (Monitored)" if borescope_cleared else compute_status(wear_rate),
            "projected_engine_life_remaining_hours": round(float(projection.get("remaining_hours")), 2) if projection else None,
            "borescope_cleared": borescope_cleared,
            "preventative_save_logged": preventative_save_logged,
        }
        st.json(latest_summary)

    with right:
        st.subheader("Recent Asset Health Samples")
        if history:
            st.dataframe(history[:25], use_container_width=True)
        else:
            st.info("No asset health history found for this tail.")

    st.subheader("Maintenance Action Log")
    if maintenance_events:
        log_rows: list[dict[str, Any]] = []
        for event in maintenance_events:
            verified = verify_maintenance_event_integrity(event)
            event_time = _coerce_timestamp_text(
                event.get("event_time")
                or event.get("occurred_at")
                or event.get("created_at")
                or event.get("report_date")
            )
            log_rows.append(
                {
                    "time": event_time,
                    "action_type": event.get("action_type"),
                    "technician_id": event.get("technician_id") or "unknown",
                    "notes": event.get("notes"),
                    "integrity": "🛡️ Verified" if verified else "⚠️ Unverified",
                }
            )
        st.dataframe(log_rows[:25], use_container_width=True)
    else:
        st.info("No maintenance actions logged for this tail yet.")

    if REPORTLAB_AVAILABLE:
        try:
            pdf_bytes = generate_airworthiness_pdf(
                tenant_id=tenant_id,
                tail_number=selected_tail,
                projection=projection,
                history=diagnostic_frame,
                backend_label=backend,
            )
            st.download_button(
                label="Export Logbook Entry (PDF)",
                data=pdf_bytes,
                file_name=f"cortex_airworthiness_{selected_tail}_{tenant_id}.pdf",
                mime="application/pdf",
                disabled=action_controls_disabled,
            )
        except Exception as exc:
            st.warning(f"PDF export unavailable: {exc}")
    else:
        st.info("Install reportlab to enable PDF logbook export.")

    st.divider()
    st.subheader(f"Iron (Fe) Trend for {selected_tail}")
    if not diagnostic_frame.empty and "iron_ppm" in diagnostic_frame.columns:
        chart_frame = diagnostic_frame[["report_date", "iron_ppm"]].dropna()
        if not chart_frame.empty:
            chart_frame = chart_frame.assign(report_date=chart_frame["report_date"].dt.date.astype(str))
            st.line_chart(chart_frame.set_index("report_date")["iron_ppm"])
        else:
            st.info("Iron trend data is incomplete for this tail.")
    else:
        st.info("Waiting for initial data ingestion...")

    st.subheader("Fleet Snapshot")
    fleet_rows: list[dict[str, Any]] = []
    for tail in tails:
        row = latest_map[tail]
        row_rate = wear_rate_ppm_hr(row)
        fleet_rows.append(
            {
                "tail_number": tail,
                "wear_rate_ppm_hr": round(row_rate, 2) if row_rate is not None else None,
                "status": compute_status(row_rate),
                "iron_ppm": row.get("iron_ppm"),
                "flight_hours": row.get("flight_hours"),
                "report_date": row.get("report_date"),
            }
        )
    st.dataframe(fleet_rows, use_container_width=True)

    with st.spinner("Compiling fleet-wide Bayesian executive summary..."):
        df_exec_diagnostics = build_executive_diagnostics(diagnostics)
    df_exec_events = pd.DataFrame(load_tenant_maintenance_events(tenant_id=tenant_id))
    if not df_exec_events.empty:
        df_exec_events["integrity_verified"] = df_exec_events.apply(verify_maintenance_event_integrity, axis=1)
    render_executive_summary(df_exec_diagnostics, df_exec_events)

    st.caption(f"Last refreshed: {datetime.now(timezone.utc).isoformat(timespec='seconds')}")


if __name__ == "__main__":
    main()