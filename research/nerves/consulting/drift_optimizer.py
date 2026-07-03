"""
Drift Optimizer Nerve
Analyses business alignment drift and produces a structured report payload:
  - drift_score   : float 0–100  (100 = fully aligned)
  - observations  : list[str]    (client-specific findings)
  - recommendations: list[str]   (systemic actions)
  - systems_pulse : str          (HEALTHY | DRIFTING | CRITICAL)
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
from typing import Optional


# ── Score thresholds ────────────────────────────────────────────────────────
_HEALTHY  = 75
_DRIFTING = 45

# Fe baseline (mirrors ocr_worker.BASELINE_IRON_PPM — kept local to avoid circular import)
_BASELINE_IRON_PPM = 38.0
_ROCKHOUNDING_DB = (
    Path.home() / "AppData" / "Roaming" / "Aero Cortex Hub"
    / "data" / "tenants" / "internal" / "marine.sqlite"
)
_HIGH_YIELD_THRESHOLD = 7.5

# ── Consulting weights ───────────────────────────────────────────────────────
# Loaded once at import time from tenant_config.json.  Falls back to 1.0 if the
# file is absent so the module is always importable in test environments.
_CONSULTING_WEIGHTS: dict = {}

def _load_consulting_weights() -> dict:
    """Return the _consulting_weights block from tenant_config.json, or {}."""
    import json as _json
    from pathlib import Path as _Path
    cfg = _Path(__file__).resolve().parents[2] / "tenant_config.json"
    try:
        raw = _json.loads(cfg.read_text(encoding="utf-8"))
        return {k: float(v) for k, v in raw.get("_consulting_weights", {}).items()
                if not k.startswith("_")}
    except (OSError, ValueError, TypeError):
        return {}

_CONSULTING_WEIGHTS = _load_consulting_weights()

# Combined legal-tier multiplier: geometric mean of KCPA and STF, capped at 1.0
# so confidence stays within [0, 1].  With both at 3.0 the normalised factor is
# min(1, sqrt(3*3)/6) = min(1, 0.5) = 0.5 — which upweights stable legal reads.
_LEGAL_CONFIDENCE_FACTOR: float = round(
    min(1.0, (_CONSULTING_WEIGHTS.get("KCPA", 1.0) * _CONSULTING_WEIGHTS.get("STF", 1.0)) ** 0.5 / 6.0),
    4,
) if _CONSULTING_WEIGHTS else 1.0


def _pulse_from_score(score: float) -> str:
    if score >= _HEALTHY:
        return "HEALTHY"
    elif score >= _DRIFTING:
        return "DRIFTING"
    return "CRITICAL"


# ── Data model ───────────────────────────────────────────────────────────────
@dataclass
class DriftReport:
    client_name: str
    generated_at: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M"))
    drift_score: float = 0.0
    systems_pulse: str = "CRITICAL"
    observations: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "client_name": self.client_name,
            "generated_at": self.generated_at,
            "drift_score": round(self.drift_score, 1),
            "systems_pulse": self.systems_pulse,
            "observations": self.observations,
            "recommendations": self.recommendations,
        }


# ── Optimizer logic ──────────────────────────────────────────────────────────
class DriftOptimizer:
    """
    Calculates a Drift Score from raw client signal data and surfaces
    targeted observations and systemic recommendations.

    Parameters
    ----------
    client_name     : Display name shown on the final report.
    revenue_trend   : Month-over-month revenue change as a decimal (-1.0 → +1.0).
    process_score   : Self-assessed process efficiency  0–100.
    team_alignment  : Team alignment rating             0–100.
    market_response : Speed of market response rating  0–100.
    custom_signals  : Optional extra {label: 0–100} metrics.
    """

    def __init__(
        self,
        client_name: str,
        revenue_trend: float = 0.0,
        process_score: float = 50.0,
        team_alignment: float = 50.0,
        market_response: float = 50.0,
        custom_signals: Optional[dict[str, float]] = None,
    ) -> None:
        self.client_name    = client_name
        self.revenue_trend  = max(-1.0, min(1.0, revenue_trend))
        self.process_score  = max(0.0, min(100.0, process_score))
        self.team_alignment = max(0.0, min(100.0, team_alignment))
        self.market_response = max(0.0, min(100.0, market_response))
        self.custom_signals  = custom_signals or {}

    # ── Core computation ─────────────────────────────────────────────────────
    def _compute_score(self) -> float:
        revenue_component = (self.revenue_trend + 1) / 2 * 100  # map [-1,1] → [0,100]

        weights = {
            "revenue":  0.30,
            "process":  0.25,
            "team":     0.25,
            "market":   0.20,
        }
        base = (
            revenue_component     * weights["revenue"] +
            self.process_score    * weights["process"] +
            self.team_alignment   * weights["team"]    +
            self.market_response  * weights["market"]
        )

        # Blend in custom signals (equal weight, capped at 20 % total influence)
        if self.custom_signals:
            custom_avg = sum(self.custom_signals.values()) / len(self.custom_signals)
            blend = min(0.20, 0.05 * len(self.custom_signals))
            base = base * (1 - blend) + custom_avg * blend

        return round(max(0.0, min(100.0, base)), 1)

    def _build_observations(self, score: float) -> list[str]:
        obs = []

        if self.revenue_trend < -0.05:
            obs.append(
                f"Revenue trend is negative ({self.revenue_trend:+.0%}), indicating cash-flow pressure "
                "that may limit reinvestment capacity."
            )
        elif self.revenue_trend >= 0.10:
            obs.append(
                f"Revenue trajectory is strong ({self.revenue_trend:+.0%}), creating an opportunity "
                "to accelerate strategic initiatives."
            )

        if self.process_score < 50:
            obs.append(
                "Process efficiency scores below threshold — bottlenecks are likely reducing output "
                "quality and team bandwidth."
            )
        elif self.process_score >= 80:
            obs.append(
                "Core processes are highly efficient; focus can shift to scaling rather than fixing."
            )

        if self.team_alignment < 50:
            obs.append(
                "Team alignment is low, which typically leads to duplicated effort, miscommunication, "
                "and slowed decision-making."
            )

        if self.market_response < 50:
            obs.append(
                "Market responsiveness is below par — the business risks falling behind competitor "
                "positioning and customer expectation shifts."
            )

        for label, val in self.custom_signals.items():
            if val < 40:
                obs.append(f"'{label}' signal is critically low ({val:.0f}/100) and warrants immediate review.")
            elif val >= 85:
                obs.append(f"'{label}' signal is performing excellently ({val:.0f}/100).")

        if not obs:
            obs.append(
                f"All monitored signals are within healthy ranges. Overall Drift Score: {score}."
            )

        return obs

    def _build_recommendations(self, score: float) -> list[str]:
        recs = []

        if score < _DRIFTING:
            recs.append(
                "Initiate a business realignment sprint: convene leadership within 2 weeks to "
                "define a 90-day recovery roadmap."
            )
        if self.process_score < 60:
            recs.append(
                "Conduct a process-mapping workshop to identify the top 3 bottlenecks and assign "
                "dedicated owners for resolution."
            )
        if self.team_alignment < 55:
            recs.append(
                "Run a team alignment session using a structured facilitation framework "
                "(e.g., OKRs or Working Agreements) to synchronise goals."
            )
        if self.revenue_trend < 0:
            recs.append(
                "Review pricing strategy and customer retention programmes; prioritise high-LTV "
                "segments to stabilise revenue within Q1."
            )
        if self.market_response < 55:
            recs.append(
                "Implement a bi-weekly competitive intelligence review to sharpen market awareness "
                "and reduce response lag."
            )
        if score >= _HEALTHY:
            recs.append(
                "Leverage the current alignment health to document and codify best practices — "
                "build systems that sustain this momentum at scale."
            )
            recs.append(
                "Explore growth levers: strategic partnerships, new service verticals, or geographic "
                "expansion are viable given the current operational health."
            )

        if not recs:
            recs.append(
                "Maintain current trajectory. Schedule a quarterly Drift Review to catch any "
                "early regression signals before they compound."
            )

        return recs

    # ── Public API ────────────────────────────────────────────────────────────
    def analyse(self) -> DriftReport:
        score  = self._compute_score()
        pulse  = _pulse_from_score(score)
        obs    = self._build_observations(score)
        recs   = self._build_recommendations(score)

        return DriftReport(
            client_name=self.client_name,
            drift_score=score,
            systems_pulse=pulse,
            observations=obs,
            recommendations=recs,
        )


# ── Drift Log Summariser ──────────────────────────────────────────────────────
def _fetch_aviation_fe_delta() -> Optional[float]:
    """
    Lazily query the RecencyChecker to obtain the latest Fe delta from the
    aviation vault.  Returns None if the vault is unavailable or contains no
    Fe reading, so callers remain safe when the aviation module is absent.
    """
    try:
        from nerves.aviation.recency_check import RecencyChecker
        status = RecencyChecker().check()
        if status.latest_reading and status.latest_reading.iron_delta_ppm is not None:
            return status.latest_reading.iron_delta_ppm
    except Exception:
        pass
    return None


def _fetch_recent_rockhounding_context(days: int = 7) -> dict:
    """
    Return summary context from rockhounding_expeditions for the last ``days``.
    Safe fallback shape is always returned when the DB is unavailable.
    """
    fallback = {
        "find_count": 0,
        "high_yield_count": 0,
        "next_location": None,
    }

    if not _ROCKHOUNDING_DB.exists():
        return fallback

    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, days))

    try:
        conn = sqlite3.connect(str(_ROCKHOUNDING_DB))
        try:
            rows = conn.execute(
                """
                SELECT timestamp, location_name, yield_rating
                FROM rockhounding_expeditions
                ORDER BY timestamp DESC
                LIMIT 500
                """
            ).fetchall()
        finally:
            conn.close()
    except Exception:
        return fallback

    find_count = 0
    high_yield_count = 0
    next_location = None

    for ts_raw, location_name, yield_rating_raw in rows:
        ts_text = str(ts_raw or "").strip()
        if not ts_text:
            continue
        try:
            ts = datetime.fromisoformat(ts_text.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            ts = ts.astimezone(timezone.utc)
        except ValueError:
            continue

        if ts < cutoff:
            continue

        find_count += 1
        try:
            y = float(yield_rating_raw) if yield_rating_raw is not None else None
        except (TypeError, ValueError):
            y = None

        if y is not None and y >= _HIGH_YIELD_THRESHOLD:
            high_yield_count += 1
            if not next_location and location_name:
                next_location = str(location_name).strip() or None

    return {
        "find_count": find_count,
        "high_yield_count": high_yield_count,
        "next_location": next_location,
    }


def summarise_drift_log(
    reports: list[DriftReport],
    iron_delta_ppm: Optional[float] = None,
    active_session_min: Optional[int] = None,
    tenant_type: str = "default",
) -> dict:
    """
    Summarise a chronological sequence of DriftReport objects and return a
    confidence-aware overview of the client's alignment trend.

    Parameters
    ----------
    reports           : Ordered list of DriftReport (oldest first).
    iron_delta_ppm    : Latest Fe deviation from the 38 ppm baseline,
                        e.g. +15.0 means 53 ppm current reading.
                        When omitted the function auto-fetches from the
                        aviation vault so the narrative can cross-reference
                        aircraft maintenance load against legal workload.
    active_session_min: Minutes elapsed in the current engagement session.
                        When provided, adds session context to the narrative.
    tenant_type       : When ``"legal"``, the KCPA/STF consulting weights from
                        tenant_config.json are applied to the confidence score.

    The confidence score (0.0–1.0) weights two factors:
      - Sample depth    (40 %): scales linearly from 0 to 1 at 10+ reports.
      - Score stability (60 %): high variance in drift scores reduces confidence.
    For legal tenants the score is further shaped by the KCPA/STF weights
    (loaded from ``_consulting_weights`` in tenant_config.json).

    Returns
    -------
    dict with keys:
        report_count        - int
        avg_score           - float | None
        min_score           - float | None
        max_score           - float | None
        trend               - "IMPROVING" | "DECLINING" | "STABLE" | "INSUFFICIENT_DATA"
        current_pulse       - systems_pulse of the most recent report | None
        confidence_score    - float 0.0–1.0
        confidence_label    - "Low" | "Moderate" | "High"
        iron_delta_ppm      - echoed back, or None
        active_session_min  - echoed back, or None
        narrative           - human-readable contextual recommendation string
        consulting_weights  - dict of applied weights (empty for non-legal tenants)
    """
    # ── Auto-fetch Fe delta from aviation vault if not supplied ───────────────
    # This is the Intelligence Cross-Link: the narrative can then mention the
    # aircraft maintenance situation alongside the client's legal workload,
    # e.g. "Given your +15 ppm Fe spike in N6424P and your 40-min session…"
    fe_sourced_from_vault = False
    if iron_delta_ppm is None:
        fetched = _fetch_aviation_fe_delta()
        if fetched is not None:
            iron_delta_ppm        = fetched
            fe_sourced_from_vault = True

    if not reports:
        return {
            "report_count":      0,
            "avg_score":         None,
            "min_score":         None,
            "max_score":         None,
            "trend":             "INSUFFICIENT_DATA",
            "current_pulse":     None,
            "confidence_score":  0.0,
            "confidence_label":  "Low",
            "iron_delta_ppm":    iron_delta_ppm,
            "active_session_min": active_session_min,
            "narrative":         "Insufficient drift history to generate a contextual recommendation.",
            "consulting_weights": _CONSULTING_WEIGHTS if tenant_type == "legal" else {},
        }

    rockhounding_context = _fetch_recent_rockhounding_context(days=7)
    high_yield_count = int(rockhounding_context.get("high_yield_count", 0) or 0)
    next_location = rockhounding_context.get("next_location") or "your next target site"

    scores = [r.drift_score for r in reports]
    n      = len(scores)
    avg    = round(sum(scores) / n, 1)

    # Trend: compare mean of the older half against the newer half
    if n >= 2:
        mid     = max(1, n // 2)
        old_avg = sum(scores[:mid]) / mid
        new_avg = sum(scores[mid:]) / max(len(scores[mid:]), 1)
        delta   = new_avg - old_avg
        if delta > 3.0:
            trend = "IMPROVING"
        elif delta < -3.0:
            trend = "DECLINING"
        else:
            trend = "STABLE"
    else:
        trend = "STABLE"

    # Confidence: sample depth + stability
    sample_factor = min(1.0, n / 10)
    if n > 1:
        mean_s         = sum(scores) / n
        variance       = sum((s - mean_s) ** 2 for s in scores) / n
        stability_factor = max(0.0, 1.0 - (variance ** 0.5) / 50.0)
    else:
        stability_factor = 0.5

    confidence = round(sample_factor * 0.4 + stability_factor * 0.6, 3)

    # Apply KCPA/STF consulting weights for legal tenants.  The factor is a
    # normalised geometric mean of KCPA and STF, kept ≤ 1.0 so the score stays
    # within bounds.  This tightens confidence for high-stakes legal analysis.
    applied_weights: dict = {}
    if tenant_type == "legal" and _CONSULTING_WEIGHTS:
        confidence      = round(confidence * _LEGAL_CONFIDENCE_FACTOR, 3)
        applied_weights = dict(_CONSULTING_WEIGHTS)

    if confidence >= 0.70:
        confidence_label = "High"
    elif confidence >= 0.40:
        confidence_label = "Moderate"
    else:
        confidence_label = "Low"

    # ── Narrative ────────────────────────────────────────────────────────────
    parts: list[str] = []

    if iron_delta_ppm is not None:
        direction  = "spike" if iron_delta_ppm > 0 else "drop"
        fe_current = round(_BASELINE_IRON_PPM + iron_delta_ppm, 1)
        if fe_sourced_from_vault:
            # Cross-link: the Fe data came from the aviation vault automatically
            parts.append(
                f"Given your current workload and the {iron_delta_ppm:+.1f} ppm Iron {direction} "
                f"in your aircraft (N6424P reads {fe_current} ppm vs {_BASELINE_IRON_PPM} ppm baseline)"
            )
        else:
            parts.append(
                f"Given your {iron_delta_ppm:+.1f} ppm Iron {direction} "
                f"(current reading: {fe_current} ppm vs {_BASELINE_IRON_PPM} ppm baseline)"
            )

    if active_session_min is not None and active_session_min > 0:
        h, m  = divmod(active_session_min, 60)
        dur   = f"{h}h {m}m" if h else f"{m}-minute"
        parts.append(f"and your current {dur} engagement session")

    if parts:
        context = ", ".join(parts) + ", "
    else:
        context = ""

    # Pulse-specific action
    pulse    = reports[-1].systems_pulse
    rec_last = reports[-1].recommendations[0] if reports[-1].recommendations else ""
    if pulse == "CRITICAL":
        action = "I recommend initiating an immediate business realignment sprint and reviewing all flagged signals before the next session."
    elif pulse == "DRIFTING":
        action = f"I recommend addressing the top drift signals now: {rec_last}".rstrip(".")
        action = action + "." if action and not action.endswith(".") else action
    else:
        action = "I recommend sustaining the current aligned trajectory and scheduling a quarterly Drift Review to catch early regression signals."

    # If the Fe delta was auto-pulled from the aviation vault, append the
    # cross-system optimisation suggestion ("save time for Y").
    if fe_sourced_from_vault and iron_delta_ppm is not None:
        action = (
            action.rstrip(".") +
            " — consider optimising your scheduling cadence to free capacity "
            "for proactive aircraft maintenance follow-up before it becomes overdue."
        )

    narrative = context + action if context else action

    # Rockhounding-aware executive narrative enrichment. Apply only when the
    # caller explicitly provides Fe context (not auto-fetched from vault), so
    # session-only narratives remain intact.
    if iron_delta_ppm is not None and not fe_sourced_from_vault and high_yield_count > 0:
        day_hint = "Tuesday" if iron_delta_ppm >= 0 else "Monday"
        session_hint = (
            f" and your current {active_session_min}-minute engagement session"
            if active_session_min is not None and active_session_min > 0
            else ""
        )
        narrative = (
            f"Given your {iron_delta_ppm:+.1f}ppm Iron {('spike' if iron_delta_ppm > 0 else 'drop')} "
            f"and your {high_yield_count} high-yield finds last week{session_hint}, "
            f"I recommend prioritizing N6424P maintenance on {day_hint} "
            f"to ensure your next expedition to {next_location} is mission-ready."
        )

    return {
        "report_count":       n,
        "avg_score":          avg,
        "min_score":          round(min(scores), 1),
        "max_score":          round(max(scores), 1),
        "trend":              trend,
        "current_pulse":      reports[-1].systems_pulse,
        "confidence_score":   confidence,
        "confidence_label":   confidence_label,
        "iron_delta_ppm":     iron_delta_ppm,
        "active_session_min": active_session_min,
        "narrative":          narrative,
        "consulting_weights": applied_weights,
    }


# ── Quick standalone test ─────────────────────────────────────────────────────
if __name__ == "__main__":
    import json

    demo = DriftOptimizer(
        client_name="Acme Corp",
        revenue_trend=-0.03,
        process_score=62,
        team_alignment=48,
        market_response=55,
        custom_signals={"Customer NPS": 38, "Delivery Speed": 71},
    )
    report = demo.analyse()
    print(json.dumps(report.to_dict(), indent=2))
