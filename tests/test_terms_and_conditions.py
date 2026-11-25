import os
import sys
import tempfile
import shutil
import unittest
from unittest.mock import patch, MagicMock
from starlette.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import core.state as state
import server


class TestDesktopTermsAndConditions(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="interview_terms_test_")
        self.orig_data_dir = state.APP_DATA_DIR
        self.orig_prefs = state.APP_PREFERENCES_PATH
        self.orig_credits = state.CREDITS_PATH

        state.APP_DATA_DIR = self.temp_dir
        state.APP_PREFERENCES_PATH = os.path.join(self.temp_dir, "preferences.json")
        state.CREDITS_PATH = os.path.join(self.temp_dir, "credits.json")
        state.current_state["accepted_terms_version"] = 0
        state.current_state["accepted_terms_on"] = ""
        if hasattr(state, "DEFAULT_TERMS_CONDITIONS"):
            state.set_terms_conditions(dict(state.DEFAULT_TERMS_CONDITIONS))
        self.client = TestClient(server.app)

    def tearDown(self):
        state.APP_DATA_DIR = self.orig_data_dir
        state.APP_PREFERENCES_PATH = self.orig_prefs
        state.CREDITS_PATH = self.orig_credits
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch("httpx.Client.post")
    def test_startup_handshake_syncs_dynamic_terms_and_persists_cache(self, mock_post):
        """sync_startup_handshake updates active terms from backend and caches them locally."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "status": "success",
            "rates": {"call_per_minute": 2.5},
            "terms": {
                "title": "Updated App Terms",
                "content": "Dynamic Terms Version 4 from Admin",
                "version": 4,
                "published_on": "25-11-2026 01:40 AM",
            },
        }
        mock_post.return_value = mock_resp

        state.save_app_credits({"balance": 100.0, "transactions": [], "redeemed_codes": []})
        res = state.sync_startup_handshake(dashboard_url="http://localhost:5000")
        self.assertEqual(res.get("status"), "success")

        terms = state.get_terms_conditions()
        self.assertEqual(terms["title"], "Updated App Terms")
        self.assertEqual(terms["content"], "Dynamic Terms Version 4 from Admin")
        self.assertEqual(terms["version"], 4)

    def test_api_terms_get_and_accept_updates_needs_acceptance(self):
        """GET /api/terms reports needs_acceptance=True until POST /api/terms/accept is called for current version."""
        state.set_terms_conditions({
            "title": "Software Terms",
            "content": "Sample dynamic terms v2",
            "version": 2,
            "published_on": "25-11-2026 01:40 AM",
        })
        state.current_state["accepted_terms_version"] = 1

        token = state.get_pairing_token()
        headers = {"X-Pairing-Token": token}

        resp = self.client.get("/api/terms", headers=headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["version"], 2)
        self.assertTrue(data["needs_acceptance"])

        resp_accept = self.client.post("/api/terms/accept", json={"version": 2}, headers=headers)
        self.assertEqual(resp_accept.status_code, 200)
        self.assertEqual(state.current_state["accepted_terms_version"], 2)

        resp_after = self.client.get("/api/terms", headers=headers)
        self.assertEqual(resp_after.status_code, 200)
        self.assertFalse(resp_after.json()["needs_acceptance"])

    def test_help_tab_and_acceptance_modal_rendered(self):
        """Help & User Guide includes dynamic T&C container and index.html includes #terms-acceptance-modal."""
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        html = resp.text
        self.assertIn("help-terms-content", html)
        self.assertIn("terms-acceptance-modal", html)

    def test_installer_requires_terms_and_conditions(self):
        """setup.iss configures LicenseFile and installer_core enforces T&C acceptance."""
        root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        terms_txt = os.path.join(root_dir, "TERMS_AND_CONDITIONS.txt")
        self.assertTrue(os.path.exists(terms_txt), "TERMS_AND_CONDITIONS.txt must exist for installer")

        with open(os.path.join(root_dir, "setup.iss"), "r", encoding="utf-8") as f:
            iss_content = f.read()
        self.assertIn("LicenseFile=TERMS_AND_CONDITIONS.txt", iss_content)

        import installer_builder.installer_core as installer_core
        self.assertTrue(hasattr(installer_core, "fetch_latest_terms_for_installer"))
        self.assertTrue(hasattr(installer_core, "prompt_terms_acceptance"))

        # Declining terms in installer must abort installation
        with patch.object(installer_core, "prompt_terms_acceptance", return_value=False), \
             patch("installer_builder.installer_core.register_in_control_panel") as mock_reg:
            result = installer_core.install_app(root_dir, target_dir=self.temp_dir)
            self.assertFalse(result)
            mock_reg.assert_not_called()


if __name__ == "__main__":
    unittest.main()
