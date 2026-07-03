"""
Hangar Briefing PDF Generator
==============================
Produces a single-page (expandable) aviation maintenance briefing for N6424P.

Sections:
    1. Cover band  — tail number, date, status badge (CURRENT / OVERDUE)
    2. Oil Analysis — Fe delta from 38 ppm baseline, last analysis date
    3. Drift Log   — most recent drift entries tagged to N6424P
    4. Engagement  — billable time logged against the internal tenant
    5. Footer      — watermark + branding

Usage:
    from nerves.aviation.hangar_briefing import HangarBriefingGenerator
    path = HangarBriefingGenerator().generate()
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]   # nerves/aviation -> nerves -> Cortex
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageTemplate,
    Paragraph, Spacer, HRFlowable, Table, TableStyle,
)
from reportlab.platypus.flowables import Flowable

from config.branding import (
    DEEP_OCEAN_PRIMARY, DEEP_OCEAN_SECONDARY, DEEP_OCEAN_ACCENT,
    DEEP_OCEAN_LIGHT, DEEP_OCEAN_TEXT, WHITE,
    FONT_TITLE, FONT_HEADING, FONT_BODY, FONT_CAPTION,
    BRAND_NAME, SUITE_NAME, WATERMARK_TEXT,
)
from nerves.aviation.recency_check import RecencyChecker, TAIL_NUMBER, BASELINE_IRON_PPM
from nerves.billing.engagement import (
    calculate_engagement, format_duration, format_currency,
)

# ── Overdue red (safety signal) ───────────────────────────────────────────────
COLOUR_OVERDUE  = HexColor("#EF4444")
COLOUR_CURRENT  = HexColor("#26A69A")
COLOUR_UNKNOWN  = HexColor("#9E9E9E")
COLOUR_ELEVATED = HexColor("#FFA726")

PAGE_W, PAGE_H  = A4
MARGIN          = 20 * mm
CONTENT_W       = PAGE_W - 2 * MARGIN


# ── Status-colour helper ──────────────────────────────────────────────────────
def _status_colour(status: str) -> HexColor:
    return {
        "CURRENT": COLOUR_CURRENT,
        "WARNING": HexColor("#F97316"),  # 🟠 orange
        "OVERDUE": COLOUR_OVERDUE,
    }.get(status, COLOUR_UNKNOWN)


def _delta_colour(flag: str) -> HexColor:
    return {"STABLE": COLOUR_CURRENT, "ELEVATED": COLOUR_ELEVATED,
            "REDUCED": DEEP_OCEAN_PRIMARY}.get(flag, COLOUR_UNKNOWN)


# ── Paragraph styles ──────────────────────────────────────────────────────────
def _styles() -> dict:
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_LEFT, TA_CENTER

    def S(name, **kw):
        return ParagraphStyle(name, **kw)

    return {
        "h1":     S("h1",     fontName=FONT_TITLE,   fontSize=16, textColor=DEEP_OCEAN_ACCENT,
                              leading=20, spaceAfter=3),
        "h2":     S("h2",     fontName=FONT_HEADING, fontSize=11, textColor=DEEP_OCEAN_ACCENT,
                              leading=14, spaceAfter=2),
        "body":   S("body",   fontName=FONT_BODY,    fontSize=9,  textColor=DEEP_OCEAN_TEXT,
                              leading=13),
        "meta":   S("meta",   fontName=FONT_CAPTION, fontSize=8,  textColor=DEEP_OCEAN_TEXT,
                              leading=11),
        "center": S("center", fontName=FONT_BODY,    fontSize=9,  textColor=DEEP_OCEAN_TEXT,
                              leading=12, alignment=TA_CENTER),
        "alert":  S("alert",  fontName=FONT_HEADING, fontSize=10, textColor=COLOUR_OVERDUE,
                              leading=14),
    }


BANNER_H = 7 * mm   # height of the WARNING / OVERDUE alert banner


# ── Page callback (header + footer + watermark) ───────────────────────────────
def _page_callback(canvas, doc, status: str, generated: str, days_remaining=None):
    canvas.saveState()

    # ── Sentinel alert banner (WARNING → orange, OVERDUE → red) ──────────────
    # Drawn on page 1 only, immediately below the header bar.
    if doc.page == 1 and status in ("WARNING", "OVERDUE"):
        bar_h    = 12 * mm
        banner_y = PAGE_H - bar_h - BANNER_H
        if status == "WARNING":
            banner_fill = HexColor("#F97316")   # 🟠 orange
            dr_str = f"{days_remaining} days remaining" if days_remaining is not None else "service due soon"
            banner_text = (
                f"\u26a0  OIL ANALYSIS WARNING  \u2014  {dr_str}. Schedule before the 120-day threshold."
            )
        else:  # OVERDUE
            banner_fill = COLOUR_OVERDUE        # 🔴 red
            banner_text = (
                "\u26d4  OIL ANALYSIS OVERDUE  \u2014  "
                "120-day threshold exceeded. Ground action required."
            )
        canvas.setFillColor(banner_fill)
        canvas.rect(0, banner_y, PAGE_W, BANNER_H, fill=1, stroke=0)
        canvas.setFillColor(WHITE)
        canvas.setFont(FONT_HEADING, 8)
        canvas.drawCentredString(PAGE_W / 2, banner_y + 2.2 * mm, banner_text)

    # ── Watermark ─────────────────────────────────────────────────────────────
    canvas.translate(PAGE_W / 2, PAGE_H / 2)
    canvas.rotate(45)
    canvas.setFillColorRGB(0.0, 0.592, 0.655, alpha=0.06)
    canvas.setFont(FONT_TITLE, 52)
    canvas.drawCentredString(0, 0, WATERMARK_TEXT)
    canvas.rotate(-45)
    canvas.translate(-(PAGE_W / 2), -(PAGE_H / 2))

    # ── Header bar ────────────────────────────────────────────────────────────
    bar_h = 12 * mm
    canvas.setFillColor(DEEP_OCEAN_ACCENT)
    canvas.rect(0, PAGE_H - bar_h, PAGE_W, bar_h, fill=1, stroke=0)
    canvas.setFillColor(WHITE)
    canvas.setFont(FONT_TITLE, 10)
    canvas.drawString(MARGIN, PAGE_H - bar_h + 4 * mm, f"HANGAR BRIEFING  //  {TAIL_NUMBER}")
    canvas.setFont(FONT_BODY, 8)
    canvas.drawRightString(PAGE_W - MARGIN, PAGE_H - bar_h + 4 * mm, generated)

    # ── Sentinel alert sub-banner (WARNING / OVERDUE only) ────────────────────
    # Narrow coloured band immediately below the main header bar.
    if status in ("WARNING", "OVERDUE"):
        alert_h   = 7 * mm
        alert_y   = PAGE_H - bar_h - alert_h
        alert_col = _status_colour(status)
        canvas.setFillColor(alert_col)
        canvas.rect(0, alert_y, PAGE_W, alert_h, fill=1, stroke=0)
        canvas.setFillColor(WHITE)
        canvas.setFont(FONT_HEADING, 7.5)
        if status == "WARNING" and days_remaining is not None:
            alert_text = (
                f"\u26a0  SENTINEL WARNING  \u2014  "
                f"{days_remaining} Days Remaining until 120-day overdue threshold"
            )
        elif status == "OVERDUE":
            alert_text = (
                "\u1f534  OVERDUE  \u2014  "
                "Oil analysis is past the 120-day threshold. Schedule service immediately."
            )
        else:
            alert_text = f"\u26a0  SENTINEL {status}"
        canvas.drawCentredString(PAGE_W / 2, alert_y + 2.2 * mm, alert_text)

    # ── Status badge (top-right of content area) ──────────────────────────────
    badge_x = PAGE_W - MARGIN - 38 * mm
    badge_y = PAGE_H - bar_h - 8 * mm
    badge_w, badge_h = 38 * mm, 6.5 * mm
    canvas.setFillColor(_status_colour(status))
    canvas.roundRect(badge_x, badge_y, badge_w, badge_h, 3, fill=1, stroke=0)
    canvas.setFillColor(WHITE)
    canvas.setFont(FONT_HEADING, 8)
    canvas.drawCentredString(badge_x + badge_w / 2, badge_y + 2 * mm, status)

    # ── Footer ────────────────────────────────────────────────────────────────
    canvas.setFillColor(DEEP_OCEAN_ACCENT)
    canvas.setFont(FONT_CAPTION, 7)
    canvas.drawString(MARGIN, 12, f"{SUITE_NAME}  //  {BRAND_NAME} Confidential  //  Page {doc.page}")
    canvas.drawRightString(PAGE_W - MARGIN, 12, f"Generated: {generated}")

    canvas.restoreState()


# ── Main generator ────────────────────────────────────────────────────────────
class HangarBriefingGenerator:
    """Generates the N6424P Hangar Briefing PDF to outputs/reports/internal/."""

    def __init__(self, tenant_slug: str = "internal"):
        self.tenant_slug = tenant_slug
        self.generated   = datetime.now().strftime("%Y-%m-%d %H:%M")
        slug_safe        = tenant_slug.lower().replace(" ", "-")
        out_dir          = _ROOT / "outputs" / "reports" / slug_safe
        out_dir.mkdir(parents=True, exist_ok=True)
        ts               = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.filepath    = out_dir / f"hangar_briefing_{ts}.pdf"

    def _build_story(self, checker_result, engagement) -> list:
        S    = _styles()
        r    = checker_result
        eng  = engagement
        story = []

        # ── Extra top clearance when a sentinel banner is present ─────────────
        # The banner (BANNER_H = 7 mm) is drawn on the canvas above the frame,
        # so push the story down to prevent overlap.
        if r.status in ("WARNING", "OVERDUE"):
            story.append(Spacer(1, BANNER_H + 2 * mm))

        # ── Title ─────────────────────────────────────────────────────────────
        story.append(Spacer(1, 6 * mm))
        story.append(Paragraph(f"Hangar Briefing &nbsp; // &nbsp; {TAIL_NUMBER}", S["h1"]))
        story.append(Paragraph(
            f"Prepared by <b>{BRAND_NAME} Cortex</b> &nbsp;|&nbsp; {self.generated}",
            S["meta"],
        ))
        story.append(Spacer(1, 2 * mm))
        story.append(HRFlowable(width="100%", thickness=1.5, color=DEEP_OCEAN_SECONDARY))
        story.append(Spacer(1, 4 * mm))

        # ── Maintenance Status ────────────────────────────────────────────────
        story.append(Paragraph("Maintenance Status", S["h2"]))

        status_colour = _status_colour(r.status)
        days_str = f"{r.days_since_analysis} days" if r.days_since_analysis is not None else "Unknown"
        overdue_note = (
            f"<b>ACTION REQUIRED:</b> Oil analysis is {r.days_since_analysis} days overdue "
            f"(threshold: {r.overdue_threshold_days} days). Schedule immediately."
            if r.is_overdue() and r.days_since_analysis is not None
            else f"<b>ACTION REQUIRED:</b> No oil analysis on record. Schedule immediately."
            if r.is_overdue()
            else f"Oil analysis is current. Next due within "
                 f"{r.overdue_threshold_days - (r.days_since_analysis or 0)} days."
        )

        status_data = [
            ["Field",           "Value"],
            ["Status",          r.status],
            ["Days Since Analysis", days_str],
            ["Last Date",       r.last_analysis_date or "No record"],
            ["Threshold",       f"{r.overdue_threshold_days} days"],
            ["Baseline Fe",     f"{BASELINE_IRON_PPM} ppm (38 ppm ICP reference)"],
        ]

        st = Table(status_data, colWidths=[CONTENT_W * 0.45, CONTENT_W * 0.55])
        st.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, 0),  DEEP_OCEAN_ACCENT),
            ("TEXTCOLOR",     (0, 0), (-1, 0),  WHITE),
            ("FONTNAME",      (0, 0), (-1, 0),  FONT_HEADING),
            ("FONTSIZE",      (0, 0), (-1, 0),  8),
            # Status row coloured by result
            ("BACKGROUND",    (0, 1), (-1, 1),  status_colour),
            ("TEXTCOLOR",     (0, 1), (-1, 1),  WHITE),
            ("FONTNAME",      (0, 1), (-1, 1),  FONT_HEADING),
            ("ROWBACKGROUNDS", (0, 2), (-1, -1), [DEEP_OCEAN_LIGHT, WHITE]),
            ("TEXTCOLOR",     (0, 2), (-1, -1), DEEP_OCEAN_TEXT),
            ("FONTNAME",      (0, 2), (-1, -1), FONT_BODY),
            ("FONTSIZE",      (0, 2), (-1, -1), 8),
            ("GRID",          (0, 0), (-1, -1), 0.3, DEEP_OCEAN_PRIMARY),
            ("TOPPADDING",    (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ]))
        story.append(st)
        story.append(Spacer(1, 3 * mm))
        story.append(Paragraph(overdue_note,
                                S["alert"] if r.is_overdue() else S["body"]))
        story.append(Spacer(1, 5 * mm))

        # ── Oil Analysis Delta ────────────────────────────────────────────────
        story.append(Paragraph("Oil Analysis — Iron (Fe) Delta", S["h2"]))
        story.append(HRFlowable(width="100%", thickness=0.5, color=DEEP_OCEAN_LIGHT))
        story.append(Spacer(1, 2 * mm))

        if r.latest_reading:
            rd = r.latest_reading
            delta_colour = _delta_colour(rd.delta_flag)
            delta_str = (
                f"{rd.iron_delta_ppm:+.1f} ppm vs {BASELINE_IRON_PPM} ppm baseline"
                if rd.iron_delta_ppm is not None else "N/A"
            )
            oil_data = [
                ["Metric",          "Value",                       "Flag"],
                ["Baseline Fe",     f"{BASELINE_IRON_PPM} ppm",    "REFERENCE"],
                ["Latest Fe",       f"{rd.iron_ppm} ppm" if rd.iron_ppm is not None else "N/A",
                                    rd.delta_flag if rd.iron_ppm is not None else "N/A"],
                ["Delta",           delta_str,                     ""],
                ["Analysis Date",   rd.timestamp[:10],             ""],
                ["Source",          rd.report_name or "—",         ""],
            ]
            ot = Table(oil_data, colWidths=[CONTENT_W * 0.35, CONTENT_W * 0.42, CONTENT_W * 0.23])
            ot.setStyle(TableStyle([
                ("BACKGROUND",    (0, 0), (-1, 0),  DEEP_OCEAN_ACCENT),
                ("TEXTCOLOR",     (0, 0), (-1, 0),  WHITE),
                ("FONTNAME",      (0, 0), (-1, 0),  FONT_HEADING),
                ("FONTSIZE",      (0, 0), (-1, 0),  8),
                # Highlight the delta flag cell
                ("BACKGROUND",    (2, 2), (2, 2),   delta_colour),
                ("TEXTCOLOR",     (2, 2), (2, 2),   WHITE),
                ("FONTNAME",      (2, 2), (2, 2),   FONT_HEADING),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [DEEP_OCEAN_LIGHT, WHITE]),
                ("TEXTCOLOR",     (0, 1), (-1, -1), DEEP_OCEAN_TEXT),
                ("FONTNAME",      (0, 1), (-1, -1), FONT_BODY),
                ("FONTSIZE",      (0, 1), (-1, -1), 8),
                ("GRID",          (0, 0), (-1, -1), 0.3, DEEP_OCEAN_PRIMARY),
                ("TOPPADDING",    (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING",   (0, 0), (-1, -1), 6),
            ]))
            story.append(ot)
        else:
            story.append(Paragraph(
                "No oil analysis data found in the internal vault. "
                "Ingest a report using the Oil Analyzer nerve.",
                S["body"],
            ))
        story.append(Spacer(1, 6 * mm))

        # ── Engagement Summary ────────────────────────────────────────────────
        story.append(Paragraph("Engagement Summary", S["h2"]))
        story.append(HRFlowable(width="100%", thickness=0.5, color=DEEP_OCEAN_LIGHT))
        story.append(Spacer(1, 2 * mm))

        eng_data = [
            ["Metric",                  "Value"],
            ["Tenant",                  eng["tenant_name"]],
            ["Active Sessions (10 min)",str(eng["pulse_count"])],
            ["Total Logged Time",        format_duration(eng["total_minutes"])],
            ["Hourly Rate",              format_currency(eng["hourly_rate"], eng["currency"])],
            ["Reports Generated",        str(eng["report_count"])],
            ["Project Total Investment", format_currency(eng["investment"], eng["currency"])],
        ]
        et = Table(eng_data, colWidths=[CONTENT_W * 0.55, CONTENT_W * 0.45])
        et.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, 0),  DEEP_OCEAN_ACCENT),
            ("TEXTCOLOR",     (0, 0), (-1, 0),  WHITE),
            ("FONTNAME",      (0, 0), (-1, 0),  FONT_HEADING),
            ("FONTSIZE",      (0, 0), (-1, 0),  8),
            ("BACKGROUND",    (0, -1), (-1, -1), DEEP_OCEAN_ACCENT),
            ("TEXTCOLOR",     (0, -1), (-1, -1), WHITE),
            ("FONTNAME",      (0, -1), (-1, -1), FONT_HEADING),
            ("FONTSIZE",      (0, -1), (-1, -1), 9),
            ("ROWBACKGROUNDS", (0, 1), (-1, -2), [DEEP_OCEAN_LIGHT, WHITE]),
            ("TEXTCOLOR",     (0, 1), (-1, -2), DEEP_OCEAN_TEXT),
            ("FONTNAME",      (0, 1), (-1, -2), FONT_BODY),
            ("FONTSIZE",      (0, 1), (-1, -2), 8),
            ("ALIGN",         (1, 1), (1, -1),  "RIGHT"),
            ("FONTNAME",      (1, 1), (1, -1),  FONT_HEADING),
            ("GRID",          (0, 0), (-1, -1), 0.3, DEEP_OCEAN_PRIMARY),
            ("TOPPADDING",    (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING",   (0, 0), (-1, -1), 6),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
        ]))
        story.append(et)

        # ── Executive Recommendation (Intelligence Cross-Link) ─────────────────
        # Only rendered when an Iron spike is detected so the section stays
        # relevant and is not a boilerplate block on every report.
        latest_fe_delta = r.latest_reading.iron_delta_ppm if r.latest_reading else None
        if latest_fe_delta is not None and abs(latest_fe_delta) > 5.0:
            story.append(Spacer(1, 5 * mm))
            story.append(Paragraph("⚠️  Executive Recommendation", S["h2"]))
            story.append(HRFlowable(width="100%", thickness=0.5, color=COLOUR_ELEVATED))
            story.append(Spacer(1, 2 * mm))

            direction  = "spike" if latest_fe_delta > 0 else "drop"
            fe_current = round(BASELINE_IRON_PPM + latest_fe_delta, 1)

            # Cross-link: pull workload context from drift_optimizer vault
            workload_context = ""
            try:
                from nerves.consulting.drift_optimizer import _fetch_aviation_fe_delta
                # If delta available, enrich narrative with workload hint
                workload_context = (
                    " Given current consulting workload, consider scheduling the "
                    "oil analysis during a natural gap in client engagements to "
                    "minimise schedule disruption."
                )
            except Exception:
                pass

            rec_text = (
                f"An Iron {direction} of <b>{latest_fe_delta:+.1f} ppm</b> has been detected "
                f"(current: <b>{fe_current} ppm</b> vs {BASELINE_IRON_PPM} ppm ICP baseline). "
                f"This level is outside the ±5 ppm stable range and warrants follow-up with "
                f"your Blackstone Labs contact before the next {r.overdue_threshold_days}-day "
                f"limit."
                + workload_context
            )
            story.append(Paragraph(rec_text, S["alert"]))

        return story

    def generate(self) -> str:
        checker = RecencyChecker()
        result  = checker.check()
        eng     = calculate_engagement(self.tenant_slug)

        status = result.status

        days_remaining = result.days_remaining

        def _cb(canvas, doc):
            _page_callback(canvas, doc, status, self.generated, days_remaining=days_remaining)

        frame    = Frame(MARGIN, 18 * mm, CONTENT_W, PAGE_H - 32 * mm - 18 * mm, id="main")
        template = PageTemplate(id="briefing", frames=[frame], onPage=_cb)
        doc      = BaseDocTemplate(
            str(self.filepath),
            pagesize=A4,
            pageTemplates=[template],
            title=f"Hangar Briefing - {TAIL_NUMBER}",
            author=BRAND_NAME,
        )
        doc.build(self._build_story(result, eng))
        return str(self.filepath.resolve())
