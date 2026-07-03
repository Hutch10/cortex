"""
Tests for Aviation OCR Worker:
  - Metal parsing from synthetic Blackstone-Alpha fixture text
  - OilExtraction delta/flag computed properties
  - process() with dry_run (no DB write needed)
  - process_folder() fleet health summary
  - _build_fleet_health_summary() aggregation
  - upsert: re-processing the same PDF replaces the row (no duplicates)
  - summarise_drift_log() narrative enrichment with iron_delta_ppm and session context
"""

from __future__ import annotations

import sqlite3
import tempfile
import textwrap
import unittest
from pathlib import Path

from nerves.aviation.ocr_worker import (
    BASELINE_IRON_PPM,
    OcrWorker,
    OilExtraction,
    _build_fleet_health_summary,
    _CREATE_SENTINEL,
    _parse_metals,
    _write_to_db,
)
from nerves.consulting.drift_optimizer import DriftOptimizer, summarise_drift_log


# ── Blackstone-Alpha synthetic fixture strings ─────────────────────────────────
# Represents a realistic Blackstone Labs report text block.
_FIXTURE_ALPHA = textwrap.dedent("""\
    BLACKSTONE LABORATORIES — OIL ANALYSIS REPORT
    Sample ID: BLACKSTONE-ALPHA
    Customer: HutchSolves Aviation / N6424P

    WEAR METALS (ppm)
    Iron (Fe): 53
    Copper (Cu): 8
    Aluminium (Al): 4

    REPORT STATUS: REVIEW RECOMMENDED
""")

_FIXTURE_BETA = textwrap.dedent("""\
    Blackstone Labs Report
    Order #: BLACKSTONE-BETA

    Fe   38
    Cu   12
    Al   3
""")

_FIXTURE_NO_METALS = textwrap.dedent("""\
    Report with no usable numeric data.
    Iron: n/a  Copper: pending  Aluminium: pending
""")


class MetalParsingTests(unittest.TestCase):
    """_parse_metals() correctly extracts values from varied text formats."""

    def test_alpha_fixture_iron(self) -> None:
        metals = _parse_metals(_FIXTURE_ALPHA)
        self.assertAlmostEqual(53.0, metals["iron"])

    def test_alpha_fixture_copper(self) -> None:
        metals = _parse_metals(_FIXTURE_ALPHA)
        self.assertAlmostEqual(8.0, metals["copper"])

    def test_alpha_fixture_aluminium(self) -> None:
        metals = _parse_metals(_FIXTURE_ALPHA)
        self.assertAlmostEqual(4.0, metals["aluminium"])

    def test_beta_fixture_inline_format(self) -> None:
        metals = _parse_metals(_FIXTURE_BETA)
        self.assertAlmostEqual(38.0, metals["iron"])
        self.assertAlmostEqual(12.0, metals["copper"])
        self.assertAlmostEqual(3.0, metals["aluminium"])

    def test_no_metals_returns_none(self) -> None:
        metals = _parse_metals(_FIXTURE_NO_METALS)
        self.assertIsNone(metals["iron"])
        self.assertIsNone(metals["copper"])
        self.assertIsNone(metals["aluminium"])


class OilExtractionPropertiesTests(unittest.TestCase):
    """OilExtraction computed properties are correct."""

    def _make(self, iron=None, copper=None, aluminium=None) -> OilExtraction:
        return OilExtraction(
            source_pdf="test.pdf",
            report_name="TEST",
            iron=iron,
            copper=copper,
            aluminium=aluminium,
            analyzed_at="2026-03-15T00:00:00Z",
            extraction_method="text-layer",
        )

    def test_iron_delta_from_baseline(self) -> None:
        # 53 ppm → delta = (53 - 38) / 38 * 100 ≈ +39.47 %
        e = self._make(iron=53.0)
        self.assertIsNotNone(e.iron_delta_pct)
        self.assertAlmostEqual((53.0 - BASELINE_IRON_PPM) / BASELINE_IRON_PPM * 100,
                               e.iron_delta_pct, places=1)

    def test_iron_flagged_when_deviation_exceeds_threshold(self) -> None:
        e = self._make(iron=53.0)   # 53 - 38 = 15 > 5 threshold
        self.assertTrue(e.iron_flagged)

    def test_iron_not_flagged_at_baseline(self) -> None:
        e = self._make(iron=38.0)
        self.assertFalse(e.iron_flagged)

    def test_copper_flagged_above_15(self) -> None:
        e = self._make(copper=20.0)
        self.assertTrue(e.copper_flagged)

    def test_copper_not_flagged_at_8(self) -> None:
        e = self._make(copper=8.0)
        self.assertFalse(e.copper_flagged)

    def test_flagged_aggregates_either_metal(self) -> None:
        self.assertTrue(self._make(iron=53.0).flagged)
        self.assertFalse(self._make(iron=38.0, copper=8.0).flagged)

    def test_delta_none_when_iron_none(self) -> None:
        self.assertIsNone(self._make().iron_delta_pct)


class DbWriteAndUpsertTests(unittest.TestCase):
    """_write_to_db upserts correctly — re-processing a PDF replaces the row."""

    def setUp(self) -> None:
        # Use a TemporaryDirectory so Windows doesn't hold the file lock in tearDown.
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "test.sqlite"
        conn = sqlite3.connect(str(self.db_path))
        conn.execute(_CREATE_SENTINEL)
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_osr_source_pdf "
            "ON oil_sentinel_reports (source_pdf)"
        )
        conn.commit()
        conn.close()

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def _extraction(self, iron: float, source: str = "test.pdf") -> OilExtraction:
        return OilExtraction(
            source_pdf=source,
            report_name="TEST",
            iron=iron,
            copper=5.0,
            aluminium=2.0,
            analyzed_at="2026-03-15T00:00:00Z",
            extraction_method="text-layer",
        )

    def test_write_inserts_row(self) -> None:
        _write_to_db(self._extraction(38.0), self.db_path)
        conn = sqlite3.connect(str(self.db_path))
        count = conn.execute("SELECT COUNT(*) FROM oil_sentinel_reports").fetchone()[0]
        conn.close()
        self.assertEqual(1, count)

    def test_upsert_replaces_not_duplicates(self) -> None:
        """Writing the same source_pdf twice should result in exactly 1 row."""
        _write_to_db(self._extraction(38.0), self.db_path)
        _write_to_db(self._extraction(53.0), self.db_path)   # same source_pdf
        conn = sqlite3.connect(str(self.db_path))
        count = conn.execute("SELECT COUNT(*) FROM oil_sentinel_reports").fetchone()[0]
        iron  = conn.execute("SELECT iron FROM oil_sentinel_reports").fetchone()[0]
        conn.close()
        self.assertEqual(1, count)
        self.assertAlmostEqual(53.0, iron)  # latest value replaces old

    def test_different_pdfs_insert_separate_rows(self) -> None:
        _write_to_db(self._extraction(38.0, source="a.pdf"), self.db_path)
        _write_to_db(self._extraction(45.0, source="b.pdf"), self.db_path)
        conn = sqlite3.connect(str(self.db_path))
        count = conn.execute("SELECT COUNT(*) FROM oil_sentinel_reports").fetchone()[0]
        conn.close()
        self.assertEqual(2, count)


class OcrWorkerDryRunTests(unittest.TestCase):
    """OcrWorker.process() with dry_run=True does not touch the DB."""

    def _make_pdf(self, content: str, path: Path) -> Path:
        """Write minimal PDF-like bytes containing the fixture text.
        Uses a plain-text fallback so pdfminer returns the text directly."""
        # Write a text file disguised as a PDF — pdfminer will fail, but the
        # OCR path is opt-in (pytesseract not required). We patch _parse_metals
        # by testing through OilExtraction directly, so dry_run path is safe.
        path.write_text(content, encoding="utf-8")
        return path

    def test_dry_run_does_not_write_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "test.sqlite"
            # No DB at all before dry_run
            worker = OcrWorker(db_path=db)
            pdf = Path(tmp) / "alpha.pdf"
            pdf.write_bytes(b"%PDF-1.4 fake")  # minimal bytes, extraction will yield None
            worker.process(pdf, dry_run=True)
            self.assertFalse(db.exists(), "dry_run must not create the database")


class FleetHealthSummaryTests(unittest.TestCase):
    """_build_fleet_health_summary() aggregates correctly."""

    def _ex(self, iron, copper=5.0, al=2.0, src="x.pdf") -> OilExtraction:
        return OilExtraction(
            source_pdf=src, report_name=None,
            iron=iron, copper=copper, aluminium=al,
            analyzed_at="2026-03-15T00:00:00Z",
            extraction_method="text-layer",
        )

    def test_empty_returns_message(self) -> None:
        result = _build_fleet_health_summary([])
        self.assertIn("message", result)

    def test_all_healthy_fleet_status(self) -> None:
        results = [self._ex(38.0), self._ex(37.0), self._ex(39.0)]
        summary = _build_fleet_health_summary(results)
        self.assertEqual("HEALTHY", summary["fleet_status"])
        self.assertEqual(0, summary["flagged_count"])

    def test_single_flagged_is_attention(self) -> None:
        # 1 flagged out of 3 → 33 % < 50 % threshold → ATTENTION
        results = [
            self._ex(38.0, src="a.pdf"),
            self._ex(38.0, src="b.pdf"),
            self._ex(53.0, src="c.pdf"),
        ]
        summary = _build_fleet_health_summary(results)
        self.assertEqual("ATTENTION", summary["fleet_status"])
        self.assertEqual(1, summary["flagged_count"])

    def test_majority_flagged_is_critical(self) -> None:
        results = [self._ex(53.0, src=f"{i}.pdf") for i in range(3)]
        results.append(self._ex(38.0, src="ok.pdf"))
        summary = _build_fleet_health_summary(results)
        self.assertEqual("CRITICAL", summary["fleet_status"])

    def test_iron_stats_computed(self) -> None:
        results = [self._ex(36.0, src="a.pdf"), self._ex(40.0, src="b.pdf")]
        summary = _build_fleet_health_summary(results)
        self.assertAlmostEqual(36.0, summary["iron"]["min"])
        self.assertAlmostEqual(40.0, summary["iron"]["max"])
        self.assertAlmostEqual(38.0, summary["iron"]["avg"])

    def test_health_pct_100_when_no_flags(self) -> None:
        results = [self._ex(38.0, src="a.pdf"), self._ex(37.5, src="b.pdf")]
        summary = _build_fleet_health_summary(results)
        self.assertAlmostEqual(100.0, summary["health_pct"])


class ProcessFolderTests(unittest.TestCase):
    """OcrWorker.process_folder() raises on non-directory and returns correct shape."""

    def test_raises_on_plain_file(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".sqlite") as f:
            worker = OcrWorker(db_path=Path(f.name))
            with self.assertRaises(NotADirectoryError):
                worker.process_folder(f.name)

    def test_empty_folder_returns_no_pdfs_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "test.sqlite"
            worker = OcrWorker(db_path=db)
            result = worker.process_folder(tmp, dry_run=True)
            self.assertIn("message", result["fleet_health"])
            self.assertEqual([], result["processed"])
            self.assertEqual([], result["errors"])


class SummariseDriftLogNarrativeTests(unittest.TestCase):
    """summarise_drift_log() produces contextual narrative when given iron/session context."""

    def _report(self, score: float) -> object:
        opt = DriftOptimizer(
            client_name="TestCo",
            process_score=score,
            team_alignment=score,
            market_response=score,
        )
        return opt.analyse()

    def test_iron_spike_appears_in_narrative(self) -> None:
        reports = [self._report(60.0)]
        result  = summarise_drift_log(reports, iron_delta_ppm=+15.0)
        self.assertIn("+15.0", result["narrative"])
        self.assertIn("Iron", result["narrative"])

    def test_session_context_appears_in_narrative(self) -> None:
        reports = [self._report(60.0)]
        result  = summarise_drift_log(reports, active_session_min=40)
        self.assertIn("40", result["narrative"])

    def test_combined_context_references_both(self) -> None:
        reports = [self._report(55.0)]
        result  = summarise_drift_log(reports, iron_delta_ppm=+15.0, active_session_min=40)
        narrative = result["narrative"]
        self.assertIn("+15.0", narrative)
        self.assertIn("40", narrative)

    def test_empty_reports_returns_insufficient_data(self) -> None:
        result = summarise_drift_log([], iron_delta_ppm=+15.0, active_session_min=40)
        self.assertEqual("INSUFFICIENT_DATA", result["trend"])
        self.assertEqual(0, result["report_count"])

    def test_iron_delta_echoed_in_result(self) -> None:
        reports = [self._report(70.0)]
        result  = summarise_drift_log(reports, iron_delta_ppm=+15.0)
        self.assertAlmostEqual(15.0, result["iron_delta_ppm"])

    def test_narrative_key_always_present(self) -> None:
        result = summarise_drift_log([self._report(80.0)])
        self.assertIn("narrative", result)
        self.assertIsInstance(result["narrative"], str)
        self.assertTrue(len(result["narrative"]) > 10)

    def test_negative_delta_uses_drop_wording(self) -> None:
        reports = [self._report(60.0)]
        result  = summarise_drift_log(reports, iron_delta_ppm=-8.0)
        self.assertIn("drop", result["narrative"])


if __name__ == "__main__":
    unittest.main()
