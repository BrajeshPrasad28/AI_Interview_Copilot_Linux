import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import tempfile
import unittest
from unittest.mock import patch, MagicMock

_test_dir = tempfile.mkdtemp(prefix="test_offline_sync_")
os.environ["INTERVIEW_TOOL_DATA_DIR"] = _test_dir

from hotkeys import GlobalHotkeyManager
from loopback_audio import SystemAudioLoopback

GlobalHotkeyManager.start = lambda self: None
GlobalHotkeyManager.stop = lambda self: None
SystemAudioLoopback.start = lambda self, *args, **kwargs: True
SystemAudioLoopback.stop = lambda self: None

class TestCreditsOfflineSync(unittest.TestCase):
    def setUp(self):
        from core.state import save_app_credits
        save_app_credits({
            "balance": 100.0,
            "redeemed_codes": ["CODE-EXISTING-1"],
            "transactions": [
                {
                    "id": "TXN-LOCAL-1",
                    "type": "debit",
                    "amount": 2.50,
                    "balance_after": 97.50,
                    "description": "Copilot Session",
                    "timestamp": "2026-11-25 01:00 AM"
                }
            ]
        })

    @patch("httpx.post")
    def test_redeem_credit_code_non_200_json_error(self, mock_post):
        """When backend returns 404/400 with JSON message, redeem_credit_code must surface that message, not raw 404 code."""
        from core.state import redeem_credit_code

        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.json.return_value = {
            "status": "error",
            "success": False,
            "message": "Voucher code does not exist."
        }
        mock_post.return_value = mock_resp

        res = redeem_credit_code("ABCD-1234-EFGH-5678")
        self.assertFalse(res["success"])
        self.assertEqual(res["error"], "Voucher code does not exist.")
        self.assertNotIn("404", res["error"])

    @patch("httpx.post")
    def test_redeem_credit_code_offline_error_message(self, mock_post):
        """When server is unreachable, redeem_credit_code must show friendly short error message."""
        from core.state import redeem_credit_code

        mock_post.side_effect = Exception("Connection refused")

        res = redeem_credit_code("ABCD-1234-EFGH-5678")
        self.assertFalse(res["success"])
        self.assertIn("unable to connect to the server", res["error"].lower())

    @patch("httpx.post")
    def test_redeem_referral_code_offline_error_message(self, mock_post):
        """When server is unreachable, redeem_referral_code must show friendly short error message."""
        from core.state import redeem_referral_code

        mock_post.side_effect = Exception("Connection refused")

        res = redeem_referral_code("REF-ABC123")
        self.assertFalse(res["success"])
        self.assertIn("unable to connect to the server", res["error"].lower())

    @patch("httpx.Client")
    def test_sync_startup_handshake_merges_remote_transactions(self, mock_client_cls):
        """Handshake should merge remote transactions into local credits.json without clobbering existing local transactions."""
        from core.state import sync_startup_handshake, load_app_credits

        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "status": "success",
            "rates": {"call_per_minute": 2.50},
            "transactions": [
                {
                    "id": "TXN-REMOTE-99",
                    "type": "credit",
                    "amount": 100.0,
                    "balance_after": 200.0,
                    "description": "Credit Points Added via Dashboard",
                    "timestamp": "2026-11-24 10:00 PM"
                }
            ],
            "redeemed_codes": []
        }
        mock_client.post.return_value = mock_resp

        result = sync_startup_handshake()
        self.assertEqual(result["status"], "success")

        # Verify local credits.json now has both TXN-LOCAL-1 and TXN-REMOTE-99
        data = load_app_credits()
        txn_ids = [tx.get("id") or tx.get("txn_id") for tx in data.get("transactions", [])]
        self.assertIn("TXN-LOCAL-1", txn_ids)
        self.assertIn("TXN-REMOTE-99", txn_ids)
        self.assertEqual(len(data.get("transactions", [])), 2)

    @patch("httpx.Client")
    def test_offline_grace_mode_preserves_all_transactions(self, mock_client_cls):
        """When dashboard is offline, local transactions and balance must remain intact."""
        from core.state import sync_startup_handshake, load_app_credits

        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client
        mock_client.post.side_effect = Exception("Network down")

        res = sync_startup_handshake()
        self.assertTrue(res["offline"])
        self.assertEqual(res["status"], "offline_grace")

        data = load_app_credits()
        self.assertEqual(len(data["transactions"]), 1)
        self.assertEqual(data["transactions"][0]["id"], "TXN-LOCAL-1")

    @patch("routers.settings.sync_startup_handshake")
    def test_api_credits_sync_endpoint_online(self, mock_handshake):
        """POST /api/credits/sync triggers handshake and returns updated balance and transactions."""
        import server
        from core import state
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def dummy_lifespan(app):
            yield

        server.app.router.lifespan_context = dummy_lifespan
        from starlette.testclient import TestClient

        mock_handshake.return_value = {
            "status": "success",
            "offline": False,
            "data": {"rates": {"call_per_minute": 2.50}}
        }

        client = TestClient(server.app)
        pairing_token = state.get_pairing_token()
        resp = client.post("/api/credits/sync", headers={"X-Pairing-Token": pairing_token})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["success"])
        self.assertFalse(body["offline"])
        self.assertIn("balance", body)
        self.assertIn("transactions", body)
        mock_handshake.assert_called_once()

    @patch("routers.settings.sync_startup_handshake")
    def test_api_credits_sync_endpoint_offline(self, mock_handshake):
        """POST /api/credits/sync handles offline mode gracefully without throwing 500."""
        import server
        from core import state
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def dummy_lifespan(app):
            yield

        server.app.router.lifespan_context = dummy_lifespan
        from starlette.testclient import TestClient

        mock_handshake.return_value = {
            "status": "offline_grace",
            "offline": True,
            "balance": 100.0
        }

        client = TestClient(server.app)
        pairing_token = state.get_pairing_token()
        resp = client.post("/api/credits/sync", headers={"X-Pairing-Token": pairing_token})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body["success"])
        self.assertTrue(body["offline"])
        self.assertEqual(body["balance"], 100.0)

    def test_api_get_credits_includes_billing_rates(self):
        """GET /api/credits must include complete active billing rates dictionary."""
        import server
        from core import state
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def dummy_lifespan(app):
            yield

        server.app.router.lifespan_context = dummy_lifespan
        from starlette.testclient import TestClient

        client = TestClient(server.app)
        pairing_token = state.get_pairing_token()
        resp = client.get("/api/credits", headers={"X-Pairing-Token": pairing_token})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("rates", body)
        self.assertEqual(body["rates"]["call_per_minute"], 2.50)
        self.assertEqual(body["rates"]["snap_per_count"], 5.00)
        self.assertEqual(body["rates"]["note_per_count"], 2.00)
        self.assertEqual(body["rates"]["referral_reward"], 10.00)


