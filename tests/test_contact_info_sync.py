import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tempfile
import unittest
from unittest.mock import patch, MagicMock
from starlette.testclient import TestClient

_test_dir = tempfile.mkdtemp(prefix="test_contact_sync_")
os.environ["INTERVIEW_TOOL_DATA_DIR"] = _test_dir

from hotkeys import GlobalHotkeyManager
from loopback_audio import SystemAudioLoopback

GlobalHotkeyManager.start = lambda self: None
GlobalHotkeyManager.stop = lambda self: None
SystemAudioLoopback.start = lambda self, *args, **kwargs: True
SystemAudioLoopback.stop = lambda self: None

import core.state as state
import server


class TestContactInfoSync(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(server.app)
        state._cached_contact_info = None

    def tearDown(self):
        state._cached_contact_info = None

    def test_default_contact_info(self):
        """When not synced from backend, get_contact_info returns default values."""
        contact = state.get_contact_info()
        self.assertIsInstance(contact, dict)
        self.assertEqual(contact.get("support_email"), "admin@avintrax.com")
        self.assertEqual(contact.get("company_name"), "Avintrax")
        self.assertEqual(contact.get("software_version"), "v1.0.0")
        self.assertIn("Avintrax", contact.get("copyright_text", ""))

    def test_sync_startup_handshake_caches_contact_info(self):
        """sync_startup_handshake should cache contact settings returned by backend."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "success",
            "device_status": "matched",
            "authenticated": True,
            "rates": {"live_rate_per_min": 1.0},
            "contact": {
                "support_email": "helpdesk@avintrax.com",
                "support_phone": "+91-9876543210",
                "company_name": "Avintrax Global",
                "software_version": "v1.2.0",
                "copyright_text": "© 2026 Avintrax Global. All rights reserved.",
                "website_url": "https://avintrax.com"
            }
        }

        mock_client = MagicMock()
        mock_client.post.return_value = mock_response

        with patch("httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value = mock_client
            res = state.sync_startup_handshake()
            self.assertTrue(res.get("success"))
            contact = state.get_contact_info()
            self.assertEqual(contact.get("support_email"), "helpdesk@avintrax.com")
            self.assertEqual(contact.get("software_version"), "v1.2.0")

    def test_api_contact_endpoint(self):
        """GET /api/contact should return current contact info."""
        resp = self.client.get("/api/contact")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get("status"), "success")
        self.assertIn("contact", data)
        self.assertEqual(data["contact"].get("support_email"), "admin@avintrax.com")

    def test_api_credits_and_sync_include_contact(self):
        """GET /api/credits and POST /api/credits/sync should include contact info."""
        resp_credits = self.client.get("/api/credits")
        self.assertEqual(resp_credits.status_code, 200)
        self.assertIn("contact", resp_credits.json())

        with patch("routers.settings.sync_startup_handshake", return_value={"success": True, "error": None}):
            resp_sync = self.client.post("/api/credits/sync")
            self.assertEqual(resp_sync.status_code, 200)
            self.assertIn("contact", resp_sync.json())
