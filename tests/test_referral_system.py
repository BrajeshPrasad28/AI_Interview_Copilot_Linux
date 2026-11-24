import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

# Ensure repository root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Isolated test environment
_test_dir = tempfile.mkdtemp(prefix="test_referral_")
os.environ["INTERVIEW_TOOL_DATA_DIR"] = _test_dir

from hotkeys import GlobalHotkeyManager
from loopback_audio import SystemAudioLoopback

GlobalHotkeyManager.start = lambda self: None
GlobalHotkeyManager.stop = lambda self: None
SystemAudioLoopback.start = lambda self, *args, **kwargs: True
SystemAudioLoopback.stop = lambda self: None

from core.state import (
    load_app_credits,
    save_app_credits,
    get_credits_balance,
    generate_credits_signature,
    redeem_referral_code,
    sync_startup_handshake,
)


class TestReferralSystem(unittest.TestCase):
    def setUp(self):
        # Reset test credits file
        initial_data = {
            "balance": 100.0,
            "has_redeemed_referral": False,
            "referral_code": "REF-TEST01",
            "redeemed_codes": [],
            "transactions": [
                {
                    "id": "TXN-INIT",
                    "type": "credit",
                    "amount": 100.0,
                    "balance_after": 100.0,
                    "timestamp": "2026-11-24 10:00 AM",
                    "description": "Initial Balance",
                }
            ]
        }
        save_app_credits(initial_data)

    def test_redeem_referral_code_success_adds_10_credits_and_transaction(self):
        """Successful referral redemption must add 10 credits, sign HMAC, and mark has_redeemed_referral=True."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "success",
            "success": True,
            "reward": 10.0,
            "message": "Referral code applied! You received +10 credit points."
        }

        with patch("httpx.post", return_value=mock_response):
            res = redeem_referral_code("REF-FRIEND99")

        self.assertTrue(res.get("success"))
        self.assertEqual(res.get("reward"), 10.0)
        self.assertEqual(res.get("balance"), 110.0)

        # Check local state on disk
        credits = load_app_credits()
        self.assertEqual(credits["balance"], 110.0)
        self.assertTrue(credits.get("has_redeemed_referral"))
        self.assertEqual(credits.get("applied_referral_code"), "REF-FRIEND99")

        # Verify transaction
        tx = credits["transactions"][0]
        self.assertEqual(tx["amount"], 10.0)
        self.assertEqual(tx["type"], "credit")
        self.assertIn("Referral Bonus", tx["description"])
        self.assertEqual(tx["balance_after"], 110.0)

    def test_redeem_referral_code_rejects_empty_code(self):
        """Redeeming empty referral code must fail immediately without network call."""
        res = redeem_referral_code("   ")
        self.assertFalse(res.get("success"))
        self.assertIn("code is required", res.get("error", "").lower())

    def test_redeem_referral_code_blocks_when_already_redeemed_locally(self):
        """If user has already redeemed a referral code locally, block without network call."""
        credits = load_app_credits()
        credits["has_redeemed_referral"] = True
        save_app_credits(credits)

        res = redeem_referral_code("REF-SOMECODE")
        self.assertFalse(res.get("success"))
        self.assertIn("already redeemed", res.get("error", "").lower())

    def test_redeem_referral_code_handles_backend_rejection(self):
        """When backend rejects (e.g. self-referral or daily cap), error must be returned and balance untouched."""
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {
            "status": "error",
            "success": False,
            "message": "You cannot redeem your own referral code."
        }

        with patch("httpx.post", return_value=mock_response):
            res = redeem_referral_code("REF-MYSELF")

        self.assertFalse(res.get("success"))
        self.assertEqual(res.get("error"), "You cannot redeem your own referral code.")
        self.assertEqual(get_credits_balance(), 100.0)

    def test_startup_handshake_syncs_pending_referrer_rewards(self):
        """Startup handshake must add unclaimed referral points to balance and log transaction."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "success",
            "device_status": "matched",
            "authenticated": True,
            "rates": {"call_per_minute": 2.5, "snap_per_count": 5.0, "note_per_count": 2.0},
            "user": {"id": 1, "uuid": "test-uuid", "name": "Test User", "email": "test@app.com"},
            "referral_code": "REF-STAT12",
            "has_redeemed_referral": False,
            "pending_referral_credits": 20.0,
            "new_friends_count": 2,
            "friends_referred_count": 2,
            "total_redeemed": 100.0,
            "redeemed_codes": []
        }

        with patch("httpx.Client.post", return_value=mock_response):
            res = sync_startup_handshake()

        self.assertEqual(res.get("status"), "success")

        # Check balance increased by 20.0 (from 100.0 to 120.0)
        credits = load_app_credits()
        self.assertEqual(credits["balance"], 120.0)
        self.assertEqual(credits.get("referral_code"), "REF-STAT12")

        # Verify transaction created
        tx = credits["transactions"][0]
        self.assertEqual(tx["amount"], 20.0)
        self.assertEqual(tx["type"], "credit")
        self.assertIn("Referral Reward", tx["description"])
        self.assertEqual(tx["balance_after"], 120.0)

    def test_api_get_credits_includes_referral_info(self):
        """GET /api/credits endpoint must include referral_code and has_redeemed_referral fields."""
        from server import app
        from starlette.testclient import TestClient
        from core.state import get_pairing_token

        client = TestClient(app)
        token = get_pairing_token()
        resp = client.get("/api/credits", headers={"X-Pairing-Token": token})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("referral_code", data)
        self.assertIn("has_redeemed_referral", data)
        self.assertTrue(str(data["referral_code"]).startswith("REF-"))

    def test_api_redeem_referral_endpoint_validates_and_redeems(self):
        """POST /api/credits/referral/redeem endpoint validates input and calls redemption logic."""
        from server import app
        from starlette.testclient import TestClient
        from core.state import get_pairing_token

        client = TestClient(app)
        token = get_pairing_token()

        # Empty code rejection
        resp_empty = client.post("/api/credits/referral/redeem", headers={"X-Pairing-Token": token}, json={"code": ""})
        self.assertEqual(resp_empty.status_code, 400)

        # Successful redemption mock
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "success",
            "success": True,
            "reward": 10.0,
            "message": "Referral applied! +10 points added."
        }
        with patch("httpx.post", return_value=mock_response):
            resp = client.post(
                "/api/credits/referral/redeem",
                headers={"X-Pairing-Token": token},
                json={"code": "REF-ABC123"}
            )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("reward"), 10.0)


if __name__ == "__main__":
    unittest.main()
