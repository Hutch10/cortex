"""
Aviation OCR Worker Nerve
=========================
Scans Blackstone Labs (or compatible) oil-analysis PDF reports and extracts
Iron (Fe), Copper (Cu), and Aluminium (Al) values.

Extraction pipeline
-------------------
1. Text layer (pdfminer)   -- fast, works on all digitally-generated PDFs.
2. Pytesseract OCR fallback -- used if pdfminer yields no numeric hits AND
   pytesseract + pdf2image are installed (optional, not required).

Extracted rows are written to ``oil_sentinel_reports`` in the internal tenant
SQLite DB and a delta trend is computed against the 38 ppm Fe baseline.

Usage
-----
    python nerves/aviation/ocr_worker.py path/to/report.pdf
    python nerves/aviation/ocr_worker.py path/to/report.pdf --json
    python nerves/aviation/ocr_worker.py path/to/report.pdf --dry-run

Programmatic
------------
    from nerves.aviation.ocr_worker import OcrWorker
    result = OcrWorker().process("path/to/report.pdf")
    print(result)
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ── Paths ──────────────────────────────────────────────────────────────────────
_APPDATA     = Path.home() / "AppData" / "Roaming"
_VAULT_ROOT  = _APPDATA / "Aero Cortex Hub" / "data" / "tenants"
_INTERNAL_DB = _VAULT_ROOT / "internal" / "marine.sqlite"

# ── Constants ──────────────────────────────────────────────────────────────────
BASELINE_IRON_PPM     = 38.0
IRON_FLAG_THRESHOLD   = 5.0    # ppm deviation triggers ELEVATED / REDUCED flag
COPPER_WARN_PPM       = 15.0   # copper baseline warn level
ALUMINIUM_WARN_PPM    = 10.0

# Regex patterns — match "Iron  38" / "Fe 38 ppm" / "Fe:38" / "Iron (Fe)  38" etc.
# Each pattern: element keyword, optional " (symbol)" group, optional separator, then value.
_METAL_PATTERNS: dict[str, list[str]] = {
    "iron":      [
        r"(?:iron)\s*(?:\([^)]*\))?\s*[:\-]?\s*(\d+(?:\.\d+)?)",
        r"\bfe\b\s*(?:\([^)]*\))?\s*[:\-]?\s*(\d+(?:\.\d+)?)",
    ],
    "copper":    [
        r"(?:copper)\s*(?:\([^)]*\))?\s*[:\-]?\s*(\d+(?:\.\d+)?)",
        r"\bcu\b\s*(?:\([^)]*\))?\s*[:\-]?\s*(\d+(?:\.\d+)?)",
    ],
    "aluminium": [
        r"(?:alumin(?:i?um)?)\s*(?:\([^)]*\))?\s*[:\-]?\s*(\d+(?:\.\d+)?)",
        r"\bal\b\s*(?:\([^)]*\))?\s*[:\-]?\s*(\d+(?:\.\d+)?)",
    ],
}


# ── Data classes ───────────────────────────────────────────────────────────────
@dataclass
class OilExtraction:
    source_pdf:    str
    report_name:   Optional[str]
    iron:          Optional[float]
    copper:        Optional[float]
    aluminium:     Optional[float]
    analyzed_at:   str
    extraction_method: str          # "text-layer" | "ocr" | "manual"

    @property
    def iron_delta_pct(self) -> Optional[float]:
        if self.iron is None:
            return None
        if BASELINE_IRON_PPM == 0:
            return None
        return round((self.iron - BASELINE_IRON_PPM) / BASELINE_IRON_PPM * 100, 2)

    @property
    def copper_delta_pct(self) -> Optional[float]:
        if self.copper is None or COPPER_WARN_PPM == 0:
            return None
        return round((self.copper - COPPER_WARN_PPM) / COPPER_WARN_PPM * 100, 2)

    @property
    def iron_flagged(self) -> bool:
        if self.iron is None:
            return False
        return abs(self.iron - BASELINE_IRON_PPM) > IRON_FLAG_THRESHOLD

    @property
    def copper_flagged(self) -> bool:
        return (self.copper or 0.0) > COPPER_WARN_PPM

    @property
    def flagged(self) -> bool:
        return self.iron_flagged or self.copper_flagged

    def summary(self) -> str:
        def fmt(val: Optional[float], unit: str = "ppm") -> str:
            return f"{val} {unit}" if val is not None else "N/A"

        lines = [
            f"PDF           : {self.source_pdf}",
            f"Report        : {self.report_name or 'unknown'}",
            f"Analyzed At   : {self.analyzed_at}",
            f"Method        : {self.extraction_method}",
            f"Iron (Fe)     : {fmt(self.iron)}  (baseline {BASELINE_IRON_PPM} ppm"
            + (f"  delta {self.iron_delta_pct:+.1f}%  {'[FLAGGED]' if self.iron_flagged else '[OK]'}"
               if self.iron is not None else "") + ")",
            f"Copper (Cu)   : {fmt(self.copper)}",
            f"Aluminium (Al): {fmt(self.aluminium)}",
            f"Flagged       : {'YES' if self.flagged else 'no'}",
        ]
        return "\n".join(lines)


# ── Text-layer extraction (pdfminer) ───────────────────────────────────────────
def _extract_text_pdfminer(pdf_path: Path) -> str:
    """Return all text from a PDF using pdfminer.six (text-layer only)."""
    from pdfminer.high_level import extract_text
    try:
        return extract_text(str(pdf_path))
    except Exception:
        return ""


# ── OCR extraction (pytesseract, optional) ─────────────────────────────────────
def _extract_text_ocr(pdf_path: Path) -> str:
    """Rasterise each page and run Tesseract OCR.
    Requires: pip install pytesseract pdf2image  +  Tesseract-OCR binary.
    """
    import pytesseract                          # noqa: F401 – guarded import
    from pdf2image import convert_from_path    # noqa: F401 – guarded import

    pages = convert_from_path(str(pdf_path), dpi=300)
    return "\n".join(pytesseract.image_to_string(page) for page in pages)


# ── Numeric extraction ─────────────────────────────────────────────────────────
def _parse_metals(text: str) -> dict[str, Optional[float]]:
    """Extract iron, copper, aluminium ppm from raw text."""
    text_lower = text.lower()
    result: dict[str, Optional[float]] = {"iron": None, "copper": None, "aluminium": None}

    for metal, patterns in _METAL_PATTERNS.items():
        for pattern in patterns:
            match = re.search(pattern, text_lower)
            if match:
                try:
                    result[metal] = float(match.group(1))
                    break
                except (ValueError, IndexError):
                    continue
    return result


def _infer_report_name(text: str, pdf_path: Path) -> Optional[str]:
    """Try to pull a report / sample ID from the text, else use filename."""
    for pattern in (
        r"(?:report\s*(?:no|#|id)[:\s]*)([\w\-/]+)",
        r"(?:sample\s*id[:\s]*)([\w\-/]+)",
        r"(?:order\s*(?:no|#)[:\s]*)([\w\-/]+)",
    ):
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return pdf_path.stem


# ── Database write ─────────────────────────────────────────────────────────────
_CREATE_SENTINEL = """
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

# Migration: add UNIQUE constraint to existing tables that predate this column definition.
_MIGRATE_SENTINEL_UNIQUE = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_osr_source_pdf
    ON oil_sentinel_reports (source_pdf)
"""

def _write_to_db(extraction: OilExtraction, db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(_CREATE_SENTINEL)
        # Best-effort migration: add the unique index on existing DBs (no-op if already present).
        try:
            conn.execute(_MIGRATE_SENTINEL_UNIQUE)
        except sqlite3.OperationalError:
            pass
        conn.execute(
            """INSERT OR REPLACE INTO oil_sentinel_reports
               (report_name, source_pdf, iron, copper, aluminium,
                iron_delta_pct, copper_delta_pct, iron_flagged, copper_flagged,
                flagged, analyzed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                extraction.report_name,
                extraction.source_pdf,
                extraction.iron,
                extraction.copper,
                extraction.aluminium,
                extraction.iron_delta_pct,
                extraction.copper_delta_pct,
                int(extraction.iron_flagged),
                int(extraction.copper_flagged),
                int(extraction.flagged),
                extraction.analyzed_at,
            ),
        )
        conn.commit()
    finally:
        conn.close()


# ── Public API ─────────────────────────────────────────────────────────────────
class OcrWorker:
    """
    Process a Blackstone Labs (or compatible) PDF and persist extracted values.

    Parameters
    ----------
    db_path : Path, optional
        Override for the internal tenant SQLite DB.
    """

    def __init__(self, db_path: Path = _INTERNAL_DB):
        self.db_path = db_path

    def process(self, pdf_path: str | Path, dry_run: bool = False) -> OilExtraction:
        """
        Extract metals from *pdf_path* and (unless dry_run) write to DB.

        Returns
        -------
        OilExtraction
        """
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        # -- Step 1: text layer
        text = ""
        method = "text-layer"
        try:
            text = _extract_text_pdfminer(pdf_path)
        except ImportError:
            pass  # pdfminer not installed — fall through to OCR

        metals = _parse_metals(text)
        any_found = any(v is not None for v in metals.values())

        # -- Step 2: OCR fallback (only if text layer yielded nothing)
        if not any_found:
            try:
                text   = _extract_text_ocr(pdf_path)
                metals = _parse_metals(text)
                method = "ocr"
            except ImportError:
                method = "text-layer"  # OCR unavailable, keep whatever we got

        analyzed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        extraction = OilExtraction(
            source_pdf         = str(pdf_path),
            report_name        = _infer_report_name(text, pdf_path),
            iron               = metals["iron"],
            copper             = metals["copper"],
            aluminium          = metals["aluminium"],
            analyzed_at        = analyzed_at,
            extraction_method  = method,
        )

        if not dry_run:
            _write_to_db(extraction, self.db_path)

        return extraction

    def process_folder(
        self,
        folder_path: str | Path,
        dry_run: bool = False,
        recursive: bool = False,
    ) -> dict:
        """
        Process every PDF in *folder_path* and return a Fleet Health summary.

        Parameters
        ----------
        folder_path : path to a directory containing Blackstone Labs PDFs.
        dry_run     : if True, extract but do not write to the DB.
        recursive   : if True, also search sub-directories.

        Returns
        -------
        dict with keys:
            processed    – list of OilExtraction results
            errors       – list of {"pdf": str, "error": str}
            fleet_health – summary dict
        """
        folder = Path(folder_path)
        if not folder.is_dir():
            raise NotADirectoryError(f"Not a directory: {folder}")

        pattern   = "**/*.pdf" if recursive else "*.pdf"
        pdf_files = sorted(folder.glob(pattern))

        if not pdf_files:
            return {
                "processed":    [],
                "errors":       [],
                "fleet_health": {"message": "No PDF files found in the specified folder."},
            }

        results: list[OilExtraction] = []
        errors: list[dict] = []
        for pdf in pdf_files:
            try:
                results.append(self.process(pdf, dry_run=dry_run))
            except Exception as exc:
                errors.append({"pdf": str(pdf), "error": str(exc)})

        return {
            "processed":    results,
            "errors":       errors,
            "fleet_health": _build_fleet_health_summary(results),
        }


# ── Fleet Health summary ───────────────────────────────────────────────────────
def _build_fleet_health_summary(results: list[OilExtraction]) -> dict:
    """Aggregate multiple oil-analysis extractions into a Fleet Health summary."""
    if not results:
        return {"message": "No extractions to summarise."}

    fe_values  = [r.iron      for r in results if r.iron      is not None]
    cu_values  = [r.copper    for r in results if r.copper    is not None]
    al_values  = [r.aluminium for r in results if r.aluminium is not None]
    flagged    = [r for r in results if r.flagged]

    def _stats(values: list[float], label: str) -> dict:
        if not values:
            return {"label": label, "min": None, "max": None, "avg": None, "samples": 0}
        return {
            "label":   label,
            "min":     round(min(values), 2),
            "max":     round(max(values), 2),
            "avg":     round(sum(values) / len(values), 2),
            "samples": len(values),
        }

    total         = len(results)
    flagged_count = len(flagged)
    health_pct    = round((total - flagged_count) / total * 100, 1) if total else 0.0

    if total and flagged_count / total >= 0.5:
        fleet_status = "CRITICAL"
    elif flagged_count > 0:
        fleet_status = "ATTENTION"
    else:
        fleet_status = "HEALTHY"

    return {
        "total_reports":   total,
        "flagged_count":   flagged_count,
        "health_pct":      health_pct,
        "fleet_status":    fleet_status,
        "fe_baseline_ppm": BASELINE_IRON_PPM,
        "iron":            _stats(fe_values, "Iron (Fe)"),
        "copper":          _stats(cu_values, "Copper (Cu)"),
        "aluminium":       _stats(al_values, "Aluminium (Al)"),
        "flagged_reports": [r.source_pdf for r in flagged],
    }


# ── CLI ────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Aviation OCR Worker — oil analysis PDF extractor")
    parser.add_argument(
        "path",
        help="Path to a Blackstone Labs PDF, or a folder to batch-process all PDFs within it",
    )
    parser.add_argument("--json",      action="store_true", help="Output JSON")
    parser.add_argument("--dry-run",   action="store_true", help="Extract but do not write to DB")
    parser.add_argument("--recursive", action="store_true", help="Recurse into sub-directories (folder mode)")
    parser.add_argument("--db",        default=str(_INTERNAL_DB), help="Override internal DB path")
    args = parser.parse_args()

    worker    = OcrWorker(db_path=Path(args.db))
    input_path = Path(args.path)

    # ── Folder / Batch mode ──────────────────────────────────────────────────
    if input_path.is_dir():
        try:
            batch = worker.process_folder(input_path, dry_run=args.dry_run, recursive=args.recursive)
        except NotADirectoryError as exc:
            print(f"  ERROR: {exc}", file=sys.stderr)
            sys.exit(1)

        if args.json:
            output = {
                "fleet_health": batch["fleet_health"],
                "errors":       batch["errors"],
                "reports":      [
                    {**asdict(r),
                     "iron_delta_pct":   r.iron_delta_pct,
                     "copper_delta_pct": r.copper_delta_pct,
                     "iron_flagged":     r.iron_flagged,
                     "copper_flagged":   r.copper_flagged,
                     "flagged":          r.flagged}
                    for r in batch["processed"]
                ],
            }
            print(json.dumps(output, indent=2))
        else:
            fh = batch["fleet_health"]
            print()
            print("  Fleet Health Summary")
            print("  =====================")
            if "message" in fh:
                print(f"  {fh['message']}")
            else:
                print(f"  Status        : {fh['fleet_status']}")
                print(f"  Total reports : {fh['total_reports']}")
                print(f"  Flagged       : {fh['flagged_count']} ({100 - fh['health_pct']:.1f}% flagged)")
                print(f"  Health        : {fh['health_pct']}%")
                print(f"  Fe baseline   : {fh['fe_baseline_ppm']} ppm")
                for metal in ("iron", "copper", "aluminium"):
                    s = fh[metal]
                    if s["samples"]:
                        print(f"  {s['label']:14}: avg {s['avg']} ppm  (min {s['min']}  max {s['max']})")
            if batch["errors"]:
                print()
                print(f"  Errors ({len(batch['errors'])})")
                for e in batch["errors"]:
                    print(f"    {e['pdf']}: {e['error']}")
            if args.dry_run:
                print()
                print("  [dry-run] DB writes skipped")
            print()
        sys.exit(0)

    # ── Single PDF mode ──────────────────────────────────────────────────────
    try:
        result = worker.process(args.path, dry_run=args.dry_run)
    except FileNotFoundError as exc:
        print(f"  ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.json:
        out = asdict(result)
        out["iron_delta_pct"]   = result.iron_delta_pct
        out["copper_delta_pct"] = result.copper_delta_pct
        out["iron_flagged"]     = result.iron_flagged
        out["copper_flagged"]   = result.copper_flagged
        out["flagged"]          = result.flagged
        print(json.dumps(out, indent=2))
    else:
        print()
        print("  Oil Analysis OCR Worker")
        print("  -----------------------")
        for line in result.summary().splitlines():
            print(f"  {line}")
        if args.dry_run:
            print()
            print("  [dry-run] DB write skipped")
        print()
