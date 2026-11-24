import json
import os
import sys
import tempfile
import unittest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure repository root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Isolated test environment
_test_dir = tempfile.mkdtemp(prefix="test_restore_")
os.environ["INTERVIEW_TOOL_DATA_DIR"] = _test_dir

from hotkeys import GlobalHotkeyManager
from loopback_audio import SystemAudioLoopback

GlobalHotkeyManager.start = lambda self: None
GlobalHotkeyManager.stop = lambda self: None
SystemAudioLoopback.start = lambda self, *args, **kwargs: True
SystemAudioLoopback.stop = lambda self: None

import server
from core import state

@asynccontextmanager
async def dummy_lifespan(app):
    yield

server.app.router.lifespan_context = dummy_lifespan

from starlette.testclient import TestClient


class TestDesktopProfileRestoreAndSync(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(server.app)
        self.pairing_token = state.get_pairing_token()
        initial_data = {
            "balance": 100.0,
            "has_redeemed_referral": False,
            "referral_code": "REF-TEST01",
            "redeemed_codes": [],
            "transactions": []
        }
        state.save_app_credits(initial_data)

    def test_default_billing_rates_includes_referral_reward(self):
        """DEFAULT_BILLING_RATES and current_billing_rates must include referral_reward."""
        self.assertIn("referral_reward", state.DEFAULT_BILLING_RATES)
        self.assertEqual(state.DEFAULT_BILLING_RATES["referral_reward"], 10.00)

    def test_api_credits_returns_dynamic_referral_reward(self):
        """GET /api/credits must return referral_reward from active billing rates."""
        state.set_billing_rates({"referral_reward": 25.0})
        resp = self.client.get(
            "/api/credits",
            headers={"X-Pairing-Token": self.pairing_token}
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("referral_reward", data)
        self.assertEqual(data["referral_reward"], 25.0)

    @patch("httpx.Client.post")
    def test_sync_usage_balance_to_dashboard_posts_transaction(self, mock_post):
        """sync_usage_balance_to_dashboard sends current_balance and transaction to backend."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"success": True, "current_balance": 85.0}
        mock_post.return_value = mock_resp

        tx = {
            "id": "TXN-TEST-123",
            "type": "debit",
            "amount": -2.50,
            "balance_after": 85.0,
            "description": "Copilot call minute 1"
        }
        res = state.sync_usage_balance_to_dashboard(tx, 85.0, dashboard_url="http://localhost:5000")
        self.assertTrue(res)

        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertIn("/api/user/sync-balance", args[0])
        payload = kwargs.get("json", {})
        self.assertEqual(payload.get("balance"), 85.0)
        self.assertEqual(payload.get("transaction", {}).get("id"), "TXN-TEST-123")

    @patch("httpx.Client.post")
    def test_lookup_and_restore_user_account_success(self, mock_post):
        """lookup_and_restore_user_account restores UUID, balance, and transactions on email match."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "status": "success",
            "found": True,
            "user": {
                "uuid": "restored-user-uuid-9999",
                "name": "Restored Aarav",
                "email": "aarav@example.com",
                "phone": "+91 99999 88888",
                "current_balance": 120.0,
                "referral_code": "REF-REST01",
                "has_redeemed_referral": True
            },
            "transactions": [
                {
                    "id": "TXN-001",
                    "type": "credit",
                    "amount": 100.0,
                    "balance_after": 100.0,
                    "description": "Voucher Recharge"
                }
            ]
        }
        mock_post.return_value = mock_resp

        with patch("core.state.save_app_preferences") as mock_save_prefs, \
             patch("core.state.save_app_credits") as mock_save_credits:
            res = state.lookup_and_restore_user_account("aarav@example.com", dashboard_url="http://localhost:5000")
            self.assertTrue(res.get("success"))
            self.assertTrue(res.get("found"))
            self.assertEqual(state.get_user_uuid(), "restored-user-uuid-9999")
            self.assertEqual(state.current_state.get("profile_name"), "Restored Aarav")

            # Check that credits and preferences were saved
            mock_save_prefs.assert_called()
            mock_save_credits.assert_called()
            saved_credits = mock_save_credits.call_args[0][0]
            self.assertEqual(saved_credits["balance"], 120.0)
            self.assertEqual(saved_credits["referral_code"], "REF-REST01")
            self.assertEqual(len(saved_credits["transactions"]), 1)

    @patch("routers.settings.lookup_and_restore_user_account")
    def test_api_user_restore_endpoint(self, mock_restore):
        """POST /api/user/restore calls lookup_and_restore_user_account and returns result."""
        mock_restore.return_value = {
            "success": True,
            "found": True,
            "user": {
                "name": "Restored Aarav",
                "email": "aarav@example.com",
                "current_balance": 120.0
            }
        }
        resp = self.client.post(
            "/api/user/restore",
            headers={"X-Pairing-Token": self.pairing_token},
            json={"email": "aarav@example.com"}
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("found"))
        self.assertEqual(data.get("user", {}).get("name"), "Restored Aarav")

    @patch("httpx.Client.post")
    def test_sync_startup_handshake_sends_balance_and_transactions(self, mock_post):
        """sync_startup_handshake includes client balance and transactions in handshake payload."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "status": "success",
            "rates": {"call_per_minute": 2.50},
            "referral_code": "REF-ABC123"
        }
        mock_post.return_value = mock_resp

        state.save_app_credits({
            "balance": 845.0,
            "has_redeemed_referral": False,
            "referral_code": "REF-ABC123",
            "redeemed_codes": [],
            "transactions": [{"id": "TXN-TEST-1", "type": "credit", "amount": 100.0, "balance_after": 845.0, "description": "Test"}]
        })

        res = state.sync_startup_handshake(dashboard_url="http://localhost:5000")
        self.assertIsNotNone(res)

        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertIn("/api/app/startup-check", args[0])
        payload = kwargs.get("json", {})
        self.assertEqual(payload.get("balance"), 845.0)
        self.assertIsInstance(payload.get("transactions"), list)
        self.assertEqual(len(payload.get("transactions")), 1)
        self.assertEqual(payload.get("transactions")[0]["id"], "TXN-TEST-1")


if __name__ == "__main__":
    unittest.main()
