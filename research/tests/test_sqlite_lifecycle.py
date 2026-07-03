"""
SQLite lifecycle regression tests.

Covers the three guarantees introduced by the open_sqlite refactor:
  1. Connections are always closed after a normal exit.
  2. Connections are always closed after an exception.
  3. Uncommitted writes are rolled back when an exception propagates.

Also provides focused regression tests for:
  4. _create_investigation_manifest returns the correct persisted record
     (regression guard for the post-close cursor.lastrowid fix).
  5. Billing engagement write + read round-trip after migration to open_sqlite.
"""

from __future__ import annotations

import sqlite3
import unittest
import uuid
import warnings
from pathlib import Path

from hub.sqlite_utils import open_sqlite


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_temp_db() -> Path:
    return Path(__file__).parent / f"lifecycle-{uuid.uuid4().hex}.sqlite"


def _cleanup(path: Path) -> None:
    if path.exists():
        try:
            path.unlink()
        except PermissionError as exc:
            warnings.warn(
                f"Could not delete test DB {path}: {exc}",
                ResourceWarning,
                stacklevel=2,
            )


# ── open_sqlite core lifecycle ────────────────────────────────────────────────

class OpenSqliteLifecycleTests(unittest.TestCase):
    """Prove open_sqlite closes connections and rolls back on exception."""

    def setUp(self) -> None:
        self.db_path = _make_temp_db()
        with open_sqlite(self.db_path) as conn:
            conn.execute(
                "CREATE TABLE items "
                "(id INTEGER PRIMARY KEY AUTOINCREMENT, val TEXT NOT NULL)"
            )
            conn.commit()

    def tearDown(self) -> None:
        _cleanup(self.db_path)

    # ── closure tests ─────────────────────────────────────────────────────────

    def test_connection_is_closed_after_normal_exit(self) -> None:
        """Connection must be unusable (ProgrammingError) after normal exit."""
        conn_ref: sqlite3.Connection | None = None
        with open_sqlite(self.db_path) as conn:
            conn_ref = conn
            conn.execute("SELECT 1")           # sanity: usable inside block
        self.assertIsNotNone(conn_ref)
        with self.assertRaises(Exception):     # ProgrammingError: closed database
            conn_ref.execute("SELECT 1")

    def test_connection_is_closed_after_exception(self) -> None:
        """Connection must be unusable even when an exception propagates."""
        conn_ref: sqlite3.Connection | None = None
        try:
            with open_sqlite(self.db_path) as conn:
                conn_ref = conn
                raise ValueError("simulated failure")
        except ValueError:
            pass
        self.assertIsNotNone(conn_ref)
        with self.assertRaises(Exception):
            conn_ref.execute("SELECT 1")

    # ── rollback tests ────────────────────────────────────────────────────────

    def test_partial_write_is_rolled_back_on_exception(self) -> None:
        """Rows inserted before an exception but not yet committed must not persist."""
        with self.assertRaises(RuntimeError):
            with open_sqlite(self.db_path) as conn:
                conn.execute("INSERT INTO items (val) VALUES (?)", ("uncommitted",))
                raise RuntimeError("abort before commit")

        with open_sqlite(self.db_path) as conn:
            count = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
        self.assertEqual(0, count)

    def test_committed_write_survives_normal_exit(self) -> None:
        """Rows committed inside the block must persist after the connection closes."""
        with open_sqlite(self.db_path) as conn:
            conn.execute("INSERT INTO items (val) VALUES (?)", ("persisted",))
            conn.commit()

        with open_sqlite(self.db_path) as conn:
            count = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
        self.assertEqual(1, count)

    def test_exception_is_reraised_after_rollback(self) -> None:
        """The original exception must propagate unchanged after rollback."""
        with self.assertRaises(ValueError) as ctx:
            with open_sqlite(self.db_path) as conn:
                conn.execute("INSERT INTO items (val) VALUES (?)", ("x",))
                raise ValueError("specific error message")
        self.assertEqual("specific error message", str(ctx.exception))


# ── _create_investigation_manifest regression ─────────────────────────────────

class InvestigationManifestLifecycleTests(unittest.TestCase):
    """
    Regression guard for the post-close cursor.lastrowid fix in
    _create_investigation_manifest (hub/app.py).

    The fix: row_id is captured inside the open connection scope, and the row
    is reloaded within the same connection rather than via a second open.
    """

    def setUp(self) -> None:
        from hub.app import app  # import here to avoid module-level side-effects
        self.db_path = _make_temp_db()
        self.original_db_path = app.config.get("MARINE_DB_PATH")
        app.config["MARINE_DB_PATH"] = str(self.db_path)
        self.app = app

    def tearDown(self) -> None:
        self.app.config["MARINE_DB_PATH"] = self.original_db_path
        _cleanup(self.db_path)

    def test_create_manifest_returns_correct_record(self) -> None:
        """
        The returned manifest must reflect exactly what was inserted, with the
        correct auto-incremented id — proving row_id was read before close.
        """
        from hub.app import _create_investigation_manifest

        manifest = _create_investigation_manifest(
            name="Test Investigation",
            scope_type="marine",
            dataset="sst",
            station_id="",
            limit=50,
            path="/marine",
            query_string="dataset=sst&limit=50",
        )

        self.assertIsNotNone(manifest)
        self.assertEqual(1, manifest["id"])
        self.assertEqual("Test Investigation", manifest["name"])
        self.assertEqual("marine", manifest["scope_type"])
        self.assertEqual("sst", manifest["dataset"])
        self.assertIsNone(manifest["station_id"])
        self.assertEqual(50, manifest["limit"])
        self.assertEqual("/marine", manifest["path"])
        self.assertEqual("dataset=sst&limit=50", manifest["query_string"])
        self.assertEqual("/marine?dataset=sst&limit=50", manifest["open_url"])

    def test_create_manifest_increments_id_for_each_insert(self) -> None:
        """Consecutive inserts must receive sequentially increasing IDs."""
        from hub.app import _create_investigation_manifest

        first = _create_investigation_manifest(
            name="First",
            scope_type="marine",
            path="/marine",
            query_string="",
        )
        second = _create_investigation_manifest(
            name="Second",
            scope_type="marine",
            path="/marine",
            query_string="",
        )

        self.assertEqual(1, first["id"])
        self.assertEqual(2, second["id"])
        self.assertEqual("First", first["name"])
        self.assertEqual("Second", second["name"])

    def test_create_manifest_open_url_omits_query_when_empty(self) -> None:
        """open_url must not append a bare '?' when query_string is empty."""
        from hub.app import _create_investigation_manifest

        manifest = _create_investigation_manifest(
            name="No Query",
            scope_type="marine",
            path="/marine",
            query_string="",
        )

        self.assertEqual("/marine", manifest["open_url"])


# ── Billing engagement round-trip ─────────────────────────────────────────────

class BillingEngagementLifecycleTests(unittest.TestCase):
    """
    Write + read round-trip for the billing engagement path after its migration
    from the local _open_db helper to open_sqlite.

    _DB_PATH is patched at the module level so every function in the module
    (write_event, query_events, total_pulse_count) sees the temp path.
    """

    def setUp(self) -> None:
        import nerves.billing.engagement as eng
        self.eng = eng
        self.db_path = _make_temp_db()
        self._original_db_path = eng._DB_PATH
        eng._DB_PATH = self.db_path

    def tearDown(self) -> None:
        self.eng._DB_PATH = self._original_db_path
        _cleanup(self.db_path)

    def test_write_event_creates_schema_on_first_call(self) -> None:
        """write_event must bootstrap the schema even when the DB file does not yet exist."""
        self.assertFalse(self.db_path.exists())
        self.eng.write_event("test-tenant", "engagement_pulse", {"duration_min": 10})
        self.assertTrue(self.db_path.exists())

    def test_write_event_and_query_events_round_trip(self) -> None:
        """A row written by write_event must be returned by query_events."""
        self.eng.write_event("test-tenant", "engagement_pulse", {"duration_min": 10})
        events = self.eng.query_events("test-tenant")

        self.assertEqual(1, len(events))
        self.assertEqual("test-tenant", events[0]["tenant_slug"])
        self.assertEqual("engagement_pulse", events[0]["event"])
        self.assertEqual({"duration_min": 10}, events[0]["payload"])

    def test_total_pulse_count_counts_only_pulse_events(self) -> None:
        """total_pulse_count must count engagement_pulse rows only, not other events."""
        self.eng.write_event("test-tenant", "engagement_pulse", {})
        self.eng.write_event("test-tenant", "engagement_pulse", {})
        self.eng.write_event("test-tenant", "report_gen", {})

        count = self.eng.total_pulse_count("test-tenant")

        self.assertEqual(2, count)

    def test_query_events_returns_empty_when_db_missing(self) -> None:
        """query_events must short-circuit and return [] if the DB file does not exist."""
        self.assertFalse(self.db_path.exists())
        events = self.eng.query_events("test-tenant")
        self.assertEqual([], events)

    def test_total_pulse_count_returns_zero_when_db_missing(self) -> None:
        """total_pulse_count must return 0 if the DB file does not exist."""
        self.assertFalse(self.db_path.exists())
        count = self.eng.total_pulse_count("test-tenant")
        self.assertEqual(0, count)

    def test_event_filter_in_query_events(self) -> None:
        """query_events must return only events matching the event_filter list."""
        self.eng.write_event("test-tenant", "engagement_pulse", {})
        self.eng.write_event("test-tenant", "report_gen", {})
        self.eng.write_event("test-tenant", "engagement_pulse", {})

        pulse_events = self.eng.query_events("test-tenant", event_filter=["engagement_pulse"])
        self.assertEqual(2, len(pulse_events))
        self.assertTrue(all(e["event"] == "engagement_pulse" for e in pulse_events))

    def test_different_tenants_are_isolated(self) -> None:
        """Events for tenant A must not appear in results for tenant B."""
        self.eng.write_event("tenant-a", "engagement_pulse", {})
        self.eng.write_event("tenant-b", "engagement_pulse", {})

        a_events = self.eng.query_events("tenant-a")
        b_events = self.eng.query_events("tenant-b")

        self.assertEqual(1, len(a_events))
        self.assertEqual(1, len(b_events))
        self.assertEqual("tenant-a", a_events[0]["tenant_slug"])
        self.assertEqual("tenant-b", b_events[0]["tenant_slug"])


if __name__ == "__main__":
    unittest.main()
