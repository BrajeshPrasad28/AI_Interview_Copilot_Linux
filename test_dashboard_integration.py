import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

# Isolated test environment
_test_dir = tempfile.mkdtemp(prefix="test_dash_")
os.environ["INTERVIEW_TOOL_DATA_DIR"] = _test_dir

from hotkeys import GlobalHotkeyManager
from loopback_audio import SystemAudioLoopback

GlobalHotkeyManager.start = lambda self: None
GlobalHotkeyManager.stop = lambda self: None
SystemAudioLoopback.start = lambda self, *args, **kwargs: True
SystemAudioLoopback.stop = lambda self: None

class TestDashboardIntegration(unittest.TestCase):
    def test_get_machine_id_format(self):
        """Machine ID must return a non-empty hardware GUID or UUID string."""
        from core.state import get_machine_id
        mid = get_machine_id()
        self.assertIsInstance(mid, str)
        self.assertTrue(len(mid) >= 8)
        # Calling again returns same machine ID
        self.assertEqual(mid, get_machine_id())

    def test_get_user_uuid_format_and_persistence(self):
        """User UUID must return a persistent UUID string."""
        from core.state import get_user_uuid
        uid1 = get_user_uuid()
        self.assertIsInstance(uid1, str)
        self.assertEqual(len(uid1), 36)
        # Calling again returns exact same persisted UUID
        uid2 = get_user_uuid()
        self.assertEqual(uid1, uid2)

    def test_hmac_signature_detects_tampering(self):
        """If user tampers local credits.json balance, HMAC verification must fail."""
        from core.state import (
            generate_credits_signature,
            verify_credits_signature,
            save_app_credits,
            load_app_credits,
            CREDITS_PATH
        )
        import json

        data = {
            "balance": 50.00,
            "redeemed_codes": ["TEST-CODE-1"],
            "transactions": []
        }
        save_app_credits(data)
        loaded = load_app_credits()
        self.assertEqual(loaded["balance"], 50.00)
        self.assertTrue(verify_credits_signature(loaded))

        # Attacker modifies credits.json in Notepad to 99999.00
        with open(CREDITS_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
        raw["balance"] = 99999.00
        with open(CREDITS_PATH, "w", encoding="utf-8") as f:
            json.dump(raw, f)

        # Loading tampered data must fail signature verification and reset to 0 or safe state
        tampered_loaded = load_app_credits()
        self.assertNotEqual(tampered_loaded["balance"], 99999.00)
        self.assertEqual(tampered_loaded["balance"], 0.00)

    def test_startup_handshake_offline_fallback(self):
        """If dashboard is unreachable at startup, handshake falls back to cached balance gracefully."""
        from core.state import (
            sync_startup_handshake,
            save_app_credits,
            load_app_credits
        )
        # Seed safe balance
        save_app_credits({"balance": 75.00, "redeemed_codes": [], "transactions": []})
        
        # Test against non-existent port (offline server)
        res = sync_startup_handshake(dashboard_url="http://127.0.0.1:59999")
        self.assertEqual(res.get("status"), "offline_grace")
        self.assertTrue(res.get("offline"))
        # Local balance is preserved for the ongoing session
        self.assertEqual(load_app_credits()["balance"], 75.00)

    def test_redeem_credit_code_remote_success(self):
        """Redeeming voucher calls dashboard API and updates local balance with remote amount."""
        from core.state import redeem_credit_code, save_app_credits, load_app_credits
        import httpx

        save_app_credits({"balance": 10.00, "redeemed_codes": [], "transactions": []})

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "success": True,
            "amount": 250,
            "code": "ABCD-1234-EFGH-5678",
            "message": "Recharged +250 points!"
        }

        with patch("httpx.post", return_value=mock_resp):
            res = redeem_credit_code(
                raw_code="ABCD-1234-EFGH-5678",
                user_name="Test User",
                user_email="test@example.com",
                user_phone="9999999999"
            )

        self.assertTrue(res["success"])
        self.assertEqual(res["amount"], 250)
        self.assertEqual(res["balance"], 260.00)
        self.assertEqual(load_app_credits()["balance"], 260.00)

    def test_redeem_credit_code_blocks_when_server_unreachable(self):
        """When credit server is unreachable, redeeming new codes is safely blocked."""
        from core.state import redeem_credit_code
        import httpx

        with patch("httpx.post", side_effect=httpx.ConnectError("Connection refused")):
            res = redeem_credit_code(
                raw_code="ANY1-CODE-1234-5678",
                user_name="Test User",
                user_email="test@example.com",
                user_phone="9999999999"
            )

        self.assertFalse(res["success"])
        self.assertIn("server", res["error"].lower())

if __name__ == "__main__":
    unittest.main()
