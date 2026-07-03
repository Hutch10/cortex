"""
Flow & Grow Report Generator Nerve
Converts a DriftReport into a professionally branded PDF.

Usage
-----
    from nerves.consulting.drift_optimizer import DriftOptimizer
    from nerves.consulting.report_gen import ReportGenerator

    report = DriftOptimizer("Acme Corp", revenue_trend=-0.03, ...).analyse()
    path   = ReportGenerator(report, tenant_slug="acme-corp").generate()
    print(f"Saved: {path}")
"""

from __future__ import annotations

import math
import re
import sys
from datetime import datetime
from pathlib import Path

# Ensure project root is on path when run directly
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageTemplate,
    Paragraph,
    Spacer,
    HRFlowable,
    Table,
    TableStyle,
    KeepTogether,
)
from reportlab.platypus.flowables import Flowable

from config.branding import (
    DEEP_OCEAN_PRIMARY, DEEP_OCEAN_SECONDARY, DEEP_OCEAN_ACCENT,
    DEEP_OCEAN_LIGHT, DEEP_OCEAN_TEXT, WHITE,
    PULSE_HEALTHY, PULSE_DRIFTING, PULSE_CRITICAL,
    FONT_TITLE, FONT_HEADING, FONT_BODY, FONT_CAPTION,
    BRAND_NAME, SUITE_NAME, PRODUCT_NAME, REPORT_TITLE,
    FOOTER_TEXT, WATERMARK_TEXT,
    pulse_color,
)
from nerves.consulting.drift_optimizer import DriftReport
from nerves.billing.engagement import (
    calculate_engagement, write_event,
    format_duration, format_currency, event_label,
)

# ── Page geometry ─────────────────────────────────────────────────────────────
PAGE_W, PAGE_H = A4
MARGIN_LEFT  = 20 * mm
MARGIN_RIGHT = 20 * mm
MARGIN_TOP   = 28 * mm
MARGIN_BOT   = 22 * mm

# ── Zone colour bands (light tints used in gauge background) ─────────────────
_ZONE_CRITICAL = HexColor("#FFEBEE")   # 0 – 45 : light red
_ZONE_DRIFTING = HexColor("#FFF8E1")   # 45 – 75: light amber
_ZONE_HEALTHY  = HexColor("#E0F2F1")   # 75 – 100: light teal


# ── Slug helper ───────────────────────────────────────────────────────────────
def _sanitize_slug(raw: str) -> str:
    """Lower-case alphanumeric-plus-hyphens slug, max 48 chars."""
    slug = raw.lower().strip()
    slug = re.sub(r"[^a-z0-9\-]+", "-", slug)
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug[:48] or "default"


# ── Custom flowable: enhanced Score Gauge ────────────────────────────────────
class ScoreBar(Flowable):
    """
    Tri-zone horizontal gauge bar.

    Zones painted left-to-right as background bands:
      Critical  0 – 45 %  (light red)
      Drifting 45 – 75 %  (light amber)
      Healthy  75 – 100%  (light teal)

    A solid fill (pulse colour) covers 0 → score.
    Tick marks and zone labels sit above the bar.
    Score label sits to the right.
    """

    TICK_45 = 0.45
    TICK_75 = 0.75

    def __init__(
        self,
        score: float,
        pulse: str,
        width: float = 160 * mm,
        height: float = 18 * mm,
    ):
        super().__init__()
        self.score  = max(0.0, min(100.0, score))
        self.pulse  = pulse
        self.width  = width
        self.height = height

    def draw(self):
        c   = self.canv
        bar_h = self.height * 0.38          # bar thickness
        y0    = self.height * 0.18          # bar baseline (leaves room for labels above)
        r     = bar_h / 2                   # corner radius

        # ── Zone background bands ────────────────────────────────────────────
        zones = [
            (0.0,      self.TICK_45, _ZONE_CRITICAL),
            (self.TICK_45, self.TICK_75, _ZONE_DRIFTING),
            (self.TICK_75, 1.0,      _ZONE_HEALTHY),
        ]
        for z_start, z_end, z_color in zones:
            x0 = self.width * z_start
            x1 = self.width * z_end
            c.setFillColor(z_color)
            # First zone: rounded left; last zone: rounded right; middle: square
            if z_start == 0.0:
                c.roundRect(x0, y0, x1 - x0 + r, bar_h, r, fill=1, stroke=0)
                c.rect(x0 + r, y0, x1 - x0, bar_h, fill=1, stroke=0)
            elif z_end == 1.0:
                c.roundRect(x0 - r, y0, x1 - x0 + r, bar_h, r, fill=1, stroke=0)
                c.rect(x0 - r, y0, x1 - x0, bar_h, fill=1, stroke=0)
            else:
                c.rect(x0, y0, x1 - x0, bar_h, fill=1, stroke=0)

        # ── Pulse-colour fill (0 → score) ────────────────────────────────────
        fill_w = max(r * 2, self.width * (self.score / 100))
        c.setFillColor(pulse_color(self.pulse))
        c.roundRect(0, y0, fill_w, bar_h, r, fill=1, stroke=0)

        # ── Tick marks at zone boundaries ────────────────────────────────────
        tick_h = bar_h * 0.7
        c.setStrokeColor(DEEP_OCEAN_ACCENT)
        c.setLineWidth(0.8)
        for ratio in (self.TICK_45, self.TICK_75):
            tx = self.width * ratio
            c.line(tx, y0 - 1, tx, y0 + tick_h)

        # ── Zone labels above bar ─────────────────────────────────────────────
        label_y = y0 + bar_h + 2
        c.setFont(FONT_CAPTION, 6)
        zones_labels = [
            (self.TICK_45 / 2,                   "CRITICAL", PULSE_CRITICAL),
            ((self.TICK_45 + self.TICK_75) / 2,  "DRIFTING", PULSE_DRIFTING),
            ((self.TICK_75 + 1.0) / 2,           "HEALTHY",  PULSE_HEALTHY),
        ]
        for ratio, label, color in zones_labels:
            c.setFillColor(color)
            c.drawCentredString(self.width * ratio, label_y, label)

        # ── Score label right of bar ──────────────────────────────────────────
        c.setFillColor(DEEP_OCEAN_ACCENT)
        c.setFont(FONT_HEADING, 9)
        c.drawRightString(
            self.width,
            y0 + bar_h + 2,
            f"{self.score:.1f} / 100",
        )

    def wrap(self, *_):
        return self.width, self.height


# ── Custom flowable: Pulse Badge (in story, below header) ────────────────────
class PulseBadge(Flowable):
    """Inline coloured badge — used in the report story body."""

    def __init__(self, pulse: str):
        super().__init__()
        self.pulse  = pulse
        self.width  = 58 * mm
        self.height = 9 * mm

    def draw(self):
        c = self.canv
        c.setFillColor(pulse_color(self.pulse))
        c.roundRect(0, 0, self.width, self.height, 3, fill=1, stroke=0)
        c.setFillColor(WHITE)
        c.setFont(FONT_HEADING, 8)
        c.drawCentredString(self.width / 2, self.height / 2 - 3,
                            f"SYSTEMS PULSE  -  {self.pulse}")

    def wrap(self, *_):
        return self.width, self.height


# ── Page-level callback factory ───────────────────────────────────────────────
def _make_page_callback(pulse: str, tenant_slug: str):
    """
    Returns a ReportLab onPage callback with pulse + tenant bound in closure.
    Renders on every page:
      - Deep Ocean header band (with Systems Pulse badge top-right on p.1)
      - HutchSolves Suite watermark (diagonal, very low opacity)
      - Branded footer with page number, date, FOOTER_TEXT, tenant slug
    """

    def _callback(canvas, doc):
        canvas.saveState()
        w, h = A4

        # ── Watermark (every page, behind everything) ─────────────────────────
        canvas.saveState()
        canvas.translate(w / 2, h / 2)
        canvas.rotate(45)
        # Deep Ocean primary at ~6 % opacity (RGB 0,151,167 ≈ 0.0/0.592/0.655)
        canvas.setFillColorRGB(0.0, 0.592, 0.655, alpha=0.06)
        canvas.setFont(FONT_TITLE, 52)
        canvas.drawCentredString(0, 0, WATERMARK_TEXT)
        canvas.restoreState()

        # ── Header band ───────────────────────────────────────────────────────
        band_h = 18 * mm
        canvas.setFillColor(DEEP_OCEAN_ACCENT)
        canvas.rect(0, h - band_h, w, band_h, fill=1, stroke=0)

        # Brand name (left)
        canvas.setFillColor(WHITE)
        canvas.setFont(FONT_TITLE, 12)
        canvas.drawString(MARGIN_LEFT, h - band_h + 6.5 * mm, BRAND_NAME)

        # Suite name (small, right of brand)
        canvas.setFont(FONT_CAPTION, 7)
        canvas.setFillColor(DEEP_OCEAN_SECONDARY)
        canvas.drawString(MARGIN_LEFT + 62, h - band_h + 6.8 * mm, SUITE_NAME)

        # Page 1 only: Systems Pulse badge (top-right of header)
        if doc.page == 1:
            badge_w = 52 * mm
            badge_h = 6.5 * mm
            bx = w - MARGIN_RIGHT - badge_w
            by = h - band_h + (band_h - badge_h) / 2
            canvas.setFillColor(pulse_color(pulse))
            canvas.roundRect(bx, by, badge_w, badge_h, 3, fill=1, stroke=0)
            canvas.setFillColor(WHITE)
            canvas.setFont(FONT_HEADING, 7)
            canvas.drawCentredString(bx + badge_w / 2, by + badge_h / 2 - 2.5,
                                     f"SYSTEMS PULSE  -  {pulse}")
        else:
            # Subsequent pages: right-align product name only
            canvas.setFillColor(WHITE)
            canvas.setFont(FONT_BODY, 8)
            canvas.drawRightString(w - MARGIN_RIGHT, h - band_h + 6.5 * mm, PRODUCT_NAME)

        # Cyan accent stripe under the band
        canvas.setFillColor(DEEP_OCEAN_SECONDARY)
        canvas.rect(0, h - band_h - 1.5 * mm, w, 1.5 * mm, fill=1, stroke=0)

        # ── Footer ────────────────────────────────────────────────────────────
        footer_h = MARGIN_BOT - 2 * mm
        canvas.setFillColor(DEEP_OCEAN_LIGHT)
        canvas.rect(0, 0, w, footer_h, fill=1, stroke=0)

        canvas.setFont(FONT_CAPTION, 7)
        canvas.setFillColor(DEEP_OCEAN_PRIMARY)

        # Left: page number
        canvas.drawString(MARGIN_LEFT, 8, f"Page {doc.page}")

        # Centre: confidential notice
        canvas.drawCentredString(w / 2, 8, FOOTER_TEXT)

        # Right: tenant slug + date
        date_str = datetime.now().strftime("%d %b %Y")
        right_label = f"{tenant_slug}  |  {date_str}" if tenant_slug != "default" else date_str
        canvas.drawRightString(w - MARGIN_RIGHT, 8, right_label)

        canvas.restoreState()

    return _callback


# ── Style sheet ───────────────────────────────────────────────────────────────
def _styles() -> dict:
    base = dict(fontName=FONT_BODY, textColor=DEEP_OCEAN_TEXT)

    return {
        "h1": ParagraphStyle("h1", fontName=FONT_TITLE,   fontSize=20, textColor=DEEP_OCEAN_ACCENT,
                              spaceAfter=4, leading=24),
        "h2": ParagraphStyle("h2", fontName=FONT_HEADING, fontSize=13, textColor=DEEP_OCEAN_PRIMARY,
                              spaceBefore=10, spaceAfter=4, leading=16),
        "h3": ParagraphStyle("h3", fontName=FONT_HEADING, fontSize=10, textColor=DEEP_OCEAN_ACCENT,
                              spaceBefore=6, spaceAfter=2, leading=13),
        "body":    ParagraphStyle("body",    fontSize=9,  leading=13, **base),
        "caption": ParagraphStyle("caption", fontSize=8,  leading=11,
                                  fontName=FONT_CAPTION, textColor=DEEP_OCEAN_PRIMARY),
        "bullet":  ParagraphStyle("bullet",  fontSize=9,  leading=13,
                                  leftIndent=10, bulletIndent=2, **base),
        "meta":    ParagraphStyle("meta",    fontSize=8,  leading=11,
                                  fontName=FONT_CAPTION, textColor=DEEP_OCEAN_PRIMARY),
        "footer":  ParagraphStyle("footer",  fontSize=7,  leading=10,
                                  fontName=FONT_CAPTION, textColor=DEEP_OCEAN_PRIMARY,
                                  alignment=TA_CENTER),
    }


# ── Main generator class ─────────────────────────────────────────────────────
class ReportGenerator:
    """
    Renders a DriftReport to a branded PDF with tenant isolation.

    Parameters
    ----------
    report       : DriftReport instance from DriftOptimizer.analyse()
    tenant_slug  : Tenant identifier — output goes to outputs/reports/{slug}/
                   Defaults to "default". Sanitised to lowercase alphanum + hyphens.
    output_dir   : Full override of the output directory (ignores tenant_slug).
    filename     : Override the auto-generated filename.
    """

    def __init__(
        self,
        report: DriftReport,
        tenant_slug: str = "default",
        output_dir: str | Path | None = None,
        filename: str | None = None,
    ) -> None:
        self.report      = report
        self.tenant_slug = _sanitize_slug(tenant_slug)

        if output_dir:
            self.out_dir = Path(output_dir)
        else:
            self.out_dir = _ROOT / "outputs" / "reports" / self.tenant_slug

        self.out_dir.mkdir(parents=True, exist_ok=True)

        if filename:
            self.filepath = self.out_dir / filename
        else:
            slug = report.client_name.lower().replace(" ", "_")
            ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.filepath = self.out_dir / f"flow_grow_{slug}_{ts}.pdf"

    # ── Build story ───────────────────────────────────────────────────────────
    def _build_story(self) -> list:
        S = _styles()
        r = self.report
        story = []

        # ── Cover section ─────────────────────────────────────────────────────
        story.append(Spacer(1, 6 * mm))
        story.append(Paragraph(REPORT_TITLE, S["h1"]))
        story.append(Paragraph(f"Prepared for: <b>{r.client_name}</b>", S["body"]))
        story.append(Paragraph(f"Generated: {r.generated_at}", S["meta"]))
        story.append(Spacer(1, 3 * mm))
        story.append(PulseBadge(r.systems_pulse))
        story.append(Spacer(1, 5 * mm))
        story.append(HRFlowable(width="100%", thickness=1, color=DEEP_OCEAN_SECONDARY))
        story.append(Spacer(1, 4 * mm))

        # ── Drift Score section ───────────────────────────────────────────────
        story.append(Paragraph("Drift Score Overview", S["h2"]))
        story.append(
            Paragraph(
                "The Drift Score measures business alignment across revenue, process efficiency, "
                "team cohesion, and market responsiveness. "
                "A score above 75 indicates a <b>Healthy</b> system; 45 – 75 signals "
                "<b>Drifting</b>; below 45 requires <b>Critical</b> intervention.",
                S["body"],
            )
        )
        story.append(Spacer(1, 3 * mm))
        story.append(ScoreBar(r.drift_score, r.systems_pulse))
        story.append(Spacer(1, 2 * mm))

        # Score summary table
        score_data = [
            ["Drift Score", "Systems Pulse", "Status"],
            [
                f"{r.drift_score:.1f} / 100",
                r.systems_pulse,
                _status_label(r.drift_score),
            ],
        ]
        score_table = Table(score_data, colWidths=[55 * mm, 55 * mm, 50 * mm])
        score_table.setStyle(
            TableStyle([
                ("BACKGROUND",    (0, 0), (-1, 0),  DEEP_OCEAN_ACCENT),
                ("TEXTCOLOR",     (0, 0), (-1, 0),  WHITE),
                ("FONTNAME",      (0, 0), (-1, 0),  FONT_HEADING),
                ("FONTSIZE",      (0, 0), (-1, 0),  9),
                ("BACKGROUND",    (0, 1), (-1, 1),  DEEP_OCEAN_LIGHT),
                ("TEXTCOLOR",     (0, 1), (-1, 1),  DEEP_OCEAN_TEXT),
                ("FONTNAME",      (0, 1), (-1, 1),  FONT_BODY),
                ("FONTSIZE",      (0, 1), (-1, 1),  9),
                ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
                ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
                ("GRID",          (0, 0), (-1, -1), 0.4, DEEP_OCEAN_PRIMARY),
                ("TOPPADDING",    (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ])
        )
        story.append(score_table)
        story.append(Spacer(1, 6 * mm))

        # ── Client Observations ───────────────────────────────────────────────
        story.append(KeepTogether([
            Paragraph("Client Observations", S["h2"]),
            HRFlowable(width="100%", thickness=0.5, color=DEEP_OCEAN_LIGHT),
            Spacer(1, 2 * mm),
        ]))
        for i, obs in enumerate(r.observations, 1):
            story.append(Paragraph(f"<b>{i}.</b>  {obs}", S["bullet"]))
            story.append(Spacer(1, 2 * mm))

        story.append(Spacer(1, 4 * mm))

        # ── Systemic Recommendations ──────────────────────────────────────────
        story.append(KeepTogether([
            Paragraph("Systemic Recommendations", S["h2"]),
            HRFlowable(width="100%", thickness=0.5, color=DEEP_OCEAN_LIGHT),
            Spacer(1, 2 * mm),
        ]))
        for rec in r.recommendations:
            story.append(Paragraph(f"&gt;  {rec}", S["bullet"]))
            story.append(Spacer(1, 2 * mm))

        story.append(Spacer(1, 6 * mm))

        # ── Closing callout ───────────────────────────────────────────────────
        closing_text = (
            "This report was generated by the <b>HutchSolves Cortex</b> platform using the "
            "Flow &amp; Grow framework. For implementation support, strategic workshops, or a "
            "follow-up Drift Review, contact your HutchSolves consultant."
        )
        closing_table = Table(
            [[Paragraph(closing_text, S["caption"])]],
            colWidths=[PAGE_W - MARGIN_LEFT - MARGIN_RIGHT],
        )
        closing_table.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), DEEP_OCEAN_LIGHT),
            ("LEFTPADDING",   (0, 0), (-1, -1), 8),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
            ("TOPPADDING",    (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LINEABOVE",     (0, 0), (-1, 0),  1, DEEP_OCEAN_SECONDARY),
            ("LINEBELOW",     (0, -1), (-1, -1), 1, DEEP_OCEAN_SECONDARY),
        ]))
        story.append(closing_table)

        # ── Engagement Summary appendix ────────────────────────────────────────
        story += self._build_engagement_appendix(S)

        return story

    # ── Engagement appendix ────────────────────────────────────────────────────
    def _build_engagement_appendix(self, S: dict) -> list:
        """
        Queries the cortex telemetry DB for this tenant and renders an
        Engagement Summary section: event table + Project Total Investment.
        """
        eng = calculate_engagement(self.tenant_slug)
        appendix = []

        appendix.append(Spacer(1, 8 * mm))
        appendix.append(HRFlowable(width="100%", thickness=1.5, color=DEEP_OCEAN_ACCENT))
        appendix.append(Spacer(1, 4 * mm))
        appendix.append(Paragraph("Engagement Summary", S["h2"]))
        appendix.append(
            Paragraph(
                f"Billable activity logged for <b>{eng['tenant_name']}</b> "
                f"at <b>{format_currency(eng['hourly_rate'], eng['currency'])}/hr</b>.",
                S["body"],
            )
        )
        appendix.append(Spacer(1, 4 * mm))

        # ── Event table ───────────────────────────────────────────────────────
        col_w = [
            PAGE_W - MARGIN_LEFT - MARGIN_RIGHT - 60 * mm - 32 * mm,  # Date
            60 * mm,   # Activity
            32 * mm,   # Duration
        ]
        header = ["Date", "Activity", "Duration"]
        rows   = [header]

        events = eng["events_preview"]
        if events:
            for ev in events:
                ts_raw  = ev.get("timestamp", "")
                ts_disp = ts_raw[:10] if len(ts_raw) >= 10 else ts_raw
                dur     = "10 min" if ev["event"] == "engagement_pulse" else "—"
                rows.append([ts_disp, event_label(ev["event"]), dur])
        else:
            rows.append(["—", "No engagement activity recorded yet", "—"])

        if eng["events_total"] > len(events):
            rows.append([
                "…",
                f"({eng['events_total'] - len(events)} earlier events not shown)",
                "…",
            ])

        tbl = Table(rows, colWidths=col_w)
        tbl.setStyle(TableStyle([
            # Header row
            ("BACKGROUND",    (0, 0), (-1, 0),  DEEP_OCEAN_ACCENT),
            ("TEXTCOLOR",     (0, 0), (-1, 0),  WHITE),
            ("FONTNAME",      (0, 0), (-1, 0),  FONT_HEADING),
            ("FONTSIZE",      (0, 0), (-1, 0),  8),
            # Body rows — alternating tint
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, DEEP_OCEAN_LIGHT]),
            ("FONTNAME",      (0, 1), (-1, -1), FONT_BODY),
            ("FONTSIZE",      (0, 1), (-1, -1), 8),
            ("TEXTCOLOR",     (0, 1), (-1, -1), DEEP_OCEAN_TEXT),
            # All cells
            ("ALIGN",         (0, 0), (-1, -1), "LEFT"),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("GRID",          (0, 0), (-1, -1), 0.3, DEEP_OCEAN_PRIMARY),
            ("TOPPADDING",    (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ]))
        appendix.append(tbl)
        appendix.append(Spacer(1, 5 * mm))

        # ── Investment summary ─────────────────────────────────────────────────
        inv_data = [
            ["Total Time Logged",        format_duration(eng["total_minutes"])],
            ["Hourly Rate",              format_currency(eng["hourly_rate"], eng["currency"])],
            ["Reports Generated",        str(eng["report_count"])],
            ["Project Total Investment", format_currency(eng["investment"], eng["currency"])],
        ]
        inv_tbl = Table(inv_data, colWidths=[90 * mm, 70 * mm])
        inv_tbl.setStyle(TableStyle([
            ("BACKGROUND",    (0, 3), (-1, 3),  DEEP_OCEAN_ACCENT),
            ("TEXTCOLOR",     (0, 3), (-1, 3),  WHITE),
            ("FONTNAME",      (0, 3), (-1, 3),  FONT_HEADING),
            ("FONTSIZE",      (0, 3), (-1, 3),  9),
            ("ROWBACKGROUNDS", (0, 0), (-1, 2),  [DEEP_OCEAN_LIGHT, WHITE, DEEP_OCEAN_LIGHT]),
            ("FONTNAME",      (0, 0), (-1, 2),  FONT_BODY),
            ("FONTSIZE",      (0, 0), (-1, 2),  8),
            ("TEXTCOLOR",     (0, 0), (-1, 2),  DEEP_OCEAN_TEXT),
            ("ALIGN",         (1, 0), (1, -1),  "RIGHT"),
            ("FONTNAME",      (1, 0), (1, -1),  FONT_HEADING),
            ("GRID",          (0, 0), (-1, -1), 0.3, DEEP_OCEAN_PRIMARY),
            ("TOPPADDING",    (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING",   (0, 0), (-1, -1), 8),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
        ]))
        appendix.append(inv_tbl)

        return appendix

    # ── Render ────────────────────────────────────────────────────────────────
    def generate(self) -> str:
        """Build and save the PDF, write a report_gen telemetry event, return path."""
        frame = Frame(
            MARGIN_LEFT,
            MARGIN_BOT,
            PAGE_W - MARGIN_LEFT - MARGIN_RIGHT,
            PAGE_H - MARGIN_TOP - MARGIN_BOT,
            id="main",
        )
        callback = _make_page_callback(self.report.systems_pulse, self.tenant_slug)
        template = PageTemplate(id="standard", frames=[frame], onPage=callback)
        doc = BaseDocTemplate(
            str(self.filepath),
            pagesize=A4,
            pageTemplates=[template],
            title=f"{REPORT_TITLE} — {self.report.client_name}",
            author=BRAND_NAME,
            subject=f"Tenant: {self.tenant_slug}",
        )
        doc.build(self._build_story())
        path = str(self.filepath.resolve())

        # Record the generation event for billing telemetry
        write_event(
            self.tenant_slug,
            "report_gen",
            {
                "client_name":  self.report.client_name,
                "drift_score":  self.report.drift_score,
                "pulse":        self.report.systems_pulse,
                "filename":     self.filepath.name,
            },
        )
        return path


# ── Standalone engagement page builder ───────────────────────────────────────
def draw_engagement_page(tenant_slug: str) -> list:
    """
    Build a list of ReportLab flowables representing a full Engagement Summary
    page for *tenant_slug*.

    Queries the cortex telemetry DB for ``engagement_pulse`` events, multiplies
    the total active minutes by the ``base_hourly_rate`` from
    ``tenant_config.json``, and renders a Deep Ocean-themed table.

    Returns a list that can be appended to any story or built into its own doc.
    """
    from nerves.billing.engagement import (
        calculate_engagement,
        format_currency,
        format_duration,
        event_label,
    )

    slug = _sanitize_slug(tenant_slug)
    eng  = calculate_engagement(slug)
    S    = _styles()

    # Colour constants reused from module scope
    _PRIMARY  = DEEP_OCEAN_PRIMARY   # #0097A7
    _ACCENT   = DEEP_OCEAN_ACCENT
    _LIGHT    = DEEP_OCEAN_LIGHT
    _TEXT     = DEEP_OCEAN_TEXT

    story: list = []

    # ── Section heading ────────────────────────────────────────────────────────
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph("Engagement Summary", S["h1"]))
    story.append(
        Paragraph(
            f"Tenant: <b>{eng['tenant_name']}</b> &nbsp;·&nbsp; "
            f"Rate: <b>{format_currency(eng['hourly_rate'], eng['currency'])}/hr</b> &nbsp;·&nbsp; "
            f"Logged: <b>{format_duration(eng['total_minutes'])}</b>",
            S["body"],
        )
    )
    story.append(Spacer(1, 4 * mm))
    story.append(HRFlowable(width="100%", thickness=1.5, color=_PRIMARY))
    story.append(Spacer(1, 4 * mm))

    # ── Pulse event table ──────────────────────────────────────────────────────
    col_date     = (PAGE_W - MARGIN_LEFT - MARGIN_RIGHT) * 0.28
    col_activity = (PAGE_W - MARGIN_LEFT - MARGIN_RIGHT) * 0.48
    col_duration = (PAGE_W - MARGIN_LEFT - MARGIN_RIGHT) * 0.24
    col_widths   = [col_date, col_activity, col_duration]

    rows = [["Date (UTC)", "Activity", "Duration"]]
    events = eng["events_preview"]
    if events:
        for ev in events:
            ts_raw  = ev.get("timestamp", "")
            ts_disp = ts_raw[:10] if len(ts_raw) >= 10 else ts_raw
            dur     = "10 min" if ev["event"] == "engagement_pulse" else "—"
            rows.append([ts_disp, event_label(ev["event"]), dur])
    else:
        rows.append(["—", "No engagement activity recorded yet", "—"])

    if eng["events_total"] > len(events):
        rows.append([
            "…",
            f"({eng['events_total'] - len(events)} earlier events not shown)",
            "…",
        ])

    tbl = Table(rows, colWidths=col_widths, repeatRows=1)
    tbl.setStyle(TableStyle([
        # Header
        ("BACKGROUND",     (0, 0), (-1, 0),  _ACCENT),
        ("TEXTCOLOR",      (0, 0), (-1, 0),  WHITE),
        ("FONTNAME",       (0, 0), (-1, 0),  FONT_HEADING),
        ("FONTSIZE",       (0, 0), (-1, 0),  8),
        ("ALIGN",          (0, 0), (-1, 0),  "CENTER"),
        # Body
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, _LIGHT]),
        ("FONTNAME",       (0, 1), (-1, -1), FONT_BODY),
        ("FONTSIZE",       (0, 1), (-1, -1), 8),
        ("TEXTCOLOR",      (0, 1), (-1, -1), _TEXT),
        # Grid
        ("GRID",           (0, 0), (-1, -1), 0.3, _PRIMARY),
        ("TOPPADDING",     (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING",  (0, 0), (-1, -1), 4),
        ("LEFTPADDING",    (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",   (0, 0), (-1, -1), 6),
        ("VALIGN",         (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 6 * mm))

    # ── Investment summary table ───────────────────────────────────────────────
    investment_rows = [
        ["Metric", "Value"],
        ["Total Active Time",         format_duration(eng["total_minutes"])],
        ["Engagement Sessions",       str(eng["pulse_count"])],
        ["Reports Generated",         str(eng["report_count"])],
        ["Hourly Rate",               format_currency(eng["hourly_rate"], eng["currency"])],
        ["Project Total Investment",  format_currency(eng["investment"], eng["currency"])],
    ]
    inv_col_w = [(PAGE_W - MARGIN_LEFT - MARGIN_RIGHT) * 0.6,
                 (PAGE_W - MARGIN_LEFT - MARGIN_RIGHT) * 0.4]
    inv_tbl = Table(investment_rows, colWidths=inv_col_w)
    inv_tbl.setStyle(TableStyle([
        # Sub-header
        ("BACKGROUND",    (0, 0), (-1, 0),  _PRIMARY),
        ("TEXTCOLOR",     (0, 0), (-1, 0),  WHITE),
        ("FONTNAME",      (0, 0), (-1, 0),  FONT_HEADING),
        ("FONTSIZE",      (0, 0), (-1, 0),  8),
        ("ALIGN",         (0, 0), (-1, 0),  "CENTER"),
        # Body
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [_LIGHT, WHITE, _LIGHT, WHITE]),
        ("FONTNAME",      (0, 1), (-1, -1), FONT_BODY),
        ("FONTSIZE",      (0, 1), (-1, -1), 9),
        ("TEXTCOLOR",     (0, 1), (-1, -1), _TEXT),
        # Investment total row — highlighted
        ("BACKGROUND",    (0, -1), (-1, -1), _ACCENT),
        ("TEXTCOLOR",     (0, -1), (-1, -1), WHITE),
        ("FONTNAME",      (0, -1), (-1, -1), FONT_HEADING),
        ("FONTSIZE",      (0, -1), (-1, -1), 10),
        # Alignment
        ("ALIGN",         (1, 1), (1, -1),  "RIGHT"),
        ("FONTNAME",      (1, 1), (1, -1),  FONT_HEADING),
        ("GRID",          (0, 0), (-1, -1), 0.3, _PRIMARY),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
    ]))
    story.append(inv_tbl)

    return story


# ── Helpers ───────────────────────────────────────────────────────────────────
def _status_label(score: float) -> str:
    if score >= 75:
        return "On Track"
    elif score >= 45:
        return "Review Needed"
    return "Intervention Required"


# ── CLI / quick test ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    from nerves.consulting.drift_optimizer import DriftOptimizer

    demo = DriftOptimizer(
        client_name="Lakeside Legal",
        revenue_trend=-0.03,
        process_score=62,
        team_alignment=48,
        market_response=55,
        custom_signals={"Client NPS": 38, "Case Turnaround": 71},
    )
    report = demo.analyse()
    gen    = ReportGenerator(report, tenant_slug="lakeside-legal")
    path   = gen.generate()
    print(f"\n  Report saved : {path}\n")
