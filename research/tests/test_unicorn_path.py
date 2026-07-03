from __future__ import annotations

import shutil
import unittest
import uuid
from pathlib import Path

from hub.app import app, _aviation_db_path


class UnicornPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = app.test_client()
        self.tenant_id = f"unicorn-{uuid.uuid4().hex[:12]}"
        self.org_id = f"org-{uuid.uuid4().hex[:10]}"

    def tearDown(self) -> None:
        db_path = _aviation_db_path(self.tenant_id)
        tenant_dir = db_path.parent
        if tenant_dir.exists():
            shutil.rmtree(tenant_dir, ignore_errors=True)

    def test_ingestor_pulse_records_provenance_and_risk_score(self) -> None:
        ingest = self.client.post(
            f"/api/ingestor/flight-log?organization_id={self.org_id}",
            json={
                "tenant_id": self.tenant_id,
                "tail_number": "N14UP",
                "provider": "pytest-ingestor",
            },
        )
        self.assertEqual(201, ingest.status_code)
        ingest_payload = ingest.get_json()
        pulse = ingest_payload["pulse"]
        self.assertTrue(pulse["rationale_hash"])
        self.assertTrue(pulse["external_philosophy_version"])
        self.assertIn("telemetry_window", pulse)
        self.assertEqual(24, pulse["telemetry_window"]["hours"])

        ack = self.client.post(
            "/api/mobile/pulse-notifications/ack",
            json={
                "tenant_id": self.tenant_id,
                "organization_id": self.org_id,
                "pulse_id": pulse["id"],
                "rationale_hash": pulse["rationale_hash"],
            },
        )
        self.assertEqual(200, ack.status_code)

        risk = self.client.get("/api/sovereign/risk-score?tenant_slug=internal&user_role=Admin")
        self.assertEqual(200, risk.status_code)
        risk_payload = risk.get_json()
        self.assertGreaterEqual(risk_payload["pulse_count"], 1)
        self.assertGreaterEqual(risk_payload["acknowledged_count"], 1)
        self.assertIn("risk_score", risk_payload)
        self.assertIn("average_time_to_action_label", risk_payload)

        audit = self.client.get(f"/api/admin/governance/audit?org_id={self.org_id}&limit=20")
        self.assertEqual(200, audit.status_code)
        entries = audit.get_json()["entries"]
        pulse_entries = [entry for entry in entries if entry.get("action_type") == "ai_pulse"]
        self.assertTrue(pulse_entries)
        self.assertEqual(pulse["rationale_hash"], pulse_entries[0]["rationale_hash"])
        self.assertTrue(pulse_entries[0]["external_philosophy_version"])

    def test_expedition_guest_invite_is_single_use(self) -> None:
        created = self.client.post(
            "/api/navigator/expeditions",
            json={
                "tenant_id": self.tenant_id,
                "user_id": 1,
                "location_name": "Guest Hook Test Site",
                "latitude": 39.1,
                "longitude": -94.6,
                "specimen_types": "agate",
                "yield_rating": 4.8,
            },
        )
        self.assertEqual(201, created.status_code)
        expedition_id = created.get_json()["id"]

        invite = self.client.post(
            "/api/navigator/expeditions/invite",
            json={
                "tenant_id": self.tenant_id,
                "expedition_id": expedition_id,
                "external_email": "guest@example.com",
            },
        )
        self.assertEqual(201, invite.status_code)
        invite_payload = invite.get_json()["invite"]
        token = invite_payload["one_time_access_token"]
        self.assertTrue(token)
        self.assertIn("share_url", invite_payload)

        redeem = self.client.get(f"/api/navigator/expeditions/shared/{token}?tenant_id={self.tenant_id}")
        self.assertEqual(200, redeem.status_code)
        access = redeem.get_json()["access"]
        self.assertEqual(expedition_id, access["expedition"]["id"])
        self.assertEqual("g***@example.com", access["external_email_hint"])

        second_redeem = self.client.get(f"/api/navigator/expeditions/shared/{token}?tenant_id={self.tenant_id}")
        self.assertEqual(410, second_redeem.status_code)
