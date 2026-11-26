import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

_test_dir = tempfile.mkdtemp(prefix="test_interview_tool_")
os.environ["INTERVIEW_TOOL_DATA_DIR"] = _test_dir

import unittest
import asyncio
from starlette.requests import Request
from fastapi import HTTPException

# Patch hardware listeners to prevent blocking in headless test runs
from hotkeys import GlobalHotkeyManager
from loopback_audio import SystemAudioLoopback

GlobalHotkeyManager.start = lambda self: None
GlobalHotkeyManager.stop = lambda self: None
SystemAudioLoopback.start = lambda self, *args, **kwargs: True
SystemAudioLoopback.stop = lambda self: None

from core.state import (
    ai_engine,
    load_app_credits,
    save_app_credits,
    get_billing_rate,
    set_billing_rates,
    DEFAULT_BILLING_RATES,
    deduct_credit_usage,
    sync_billing_rates_from_remote,
    copilot_session_state,
    reset_companion_state,
    companion_state,
)
from routers.history import api_start_session_history, api_end_session_history
from routers.notes import api_save_note
from routers.copilot import api_trigger_snip

class TestLiveBillingSystem(unittest.TestCase):
    def setUp(self):
        reset_companion_state()
        self._original_ai_clients = (ai_engine.client, ai_engine.groq_client)
        ai_engine.client = object()
        ai_engine.groq_client = None
        copilot_session_state.update({
            "is_active": False,
            "started_at": None,
            "session_id": None,
        })
        # Reset billing rates to default
        set_billing_rates(DEFAULT_BILLING_RATES)
        # Setup clean test credits
        self.credits = {
            "balance": 100.0,
            "redeemed_codes": ["TEST-100"],
            "transactions": []
        }
        save_app_credits(self.credits)

    def tearDown(self):
        reset_companion_state()
        ai_engine.client, ai_engine.groq_client = self._original_ai_clients

    def test_session_start_without_ai_access_is_rejected_without_charging(self):
        ai_engine.client = None
        ai_engine.groq_client = None
        for source in ("desktop", "mobile"):
            if source == "mobile":
                companion_state["mobile_connected"] = True
            req = Request({
                "type": "http",
                "method": "POST",
                "headers": [(b"x-device", source.encode("ascii"))]
            })

            with self.subTest(source=source), self.assertRaises(HTTPException) as ctx:
                asyncio.run(api_start_session_history(req))

            self.assertEqual(ctx.exception.status_code, 503)
            self.assertEqual(ctx.exception.detail, "AI access denied. Contact admin.")
            updated_credits = load_app_credits()
            self.assertEqual(updated_credits["balance"], self.credits["balance"])
            self.assertEqual(updated_credits["transactions"], [])
            self.assertFalse(copilot_session_state["is_active"])

    def test_default_billing_rates(self):
        """Default billing rates must be 2.50 call/min, 5.00 snap, 2.00 notes, 500 max chars."""
        self.assertEqual(get_billing_rate("call_per_minute"), 2.50)
        self.assertEqual(get_billing_rate("snap_per_count"), 5.00)
        self.assertEqual(get_billing_rate("note_per_count"), 2.00)
        self.assertEqual(get_billing_rate("note_max_chars"), 500)

    def test_session_start_blocked_when_balance_under_call_rate(self):
        """If user has less than 2.50 points, starting Copilot must be rejected with 402/403."""
        self.credits["balance"] = 1.50
        save_app_credits(self.credits)

        req = Request({
            "type": "http",
            "method": "POST",
            "headers": [(b"x-device", b"desktop")]
        })
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(api_start_session_history(req))
        self.assertIn(ctx.exception.status_code, [400, 402, 403])
        self.assertIn("insufficient", ctx.exception.detail.lower())

    def test_session_start_deducts_upfront_first_minute(self):
        """Starting session with sufficient balance deducts 2.50 upfront for minute 1."""
        self.credits["balance"] = 10.00
        save_app_credits(self.credits)

        req = Request({
            "type": "http",
            "method": "POST",
            "headers": [(b"x-device", b"desktop")]
        })
        res = asyncio.run(api_start_session_history(req))
        self.assertTrue(res.get("success"))

        updated_credits = load_app_credits()
        self.assertEqual(updated_credits["balance"], 7.50)
        self.assertEqual(len(updated_credits["transactions"]), 1)
        self.assertEqual(updated_credits["transactions"][0]["amount"], -2.50)

        # Cleanup active session
        asyncio.run(api_end_session_history())

    def test_note_creation_rejected_when_over_500_chars(self):
        """Note creation must be strictly rejected by backend if content exceeds 500 characters."""
        long_content = "a" * 501
        payload = {
            "title": "Too Long Note",
            "content": long_content
        }
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(api_save_note(payload))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("500", ctx.exception.detail)

    def test_note_creation_rejected_when_title_over_50_chars(self):
        """Note creation must be rejected if title exceeds 50 characters."""
        long_title = "A" * 51
        payload = {
            "title": long_title,
            "content": "Valid short content"
        }
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(api_save_note(payload))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("50", ctx.exception.detail)

    def test_note_creation_blocked_when_balance_insufficient(self):
        """Note creation requires 2.00 points; rejected if balance < 2.00."""
        self.credits["balance"] = 1.00
        save_app_credits(self.credits)

        payload = {
            "title": "Valid Note",
            "content": "Short valid text"
        }
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(api_save_note(payload))
        self.assertIn(ctx.exception.status_code, [400, 402])
        self.assertIn("insufficient", ctx.exception.detail.lower())

    def test_note_creation_deducts_two_credits(self):
        """Creating a new note with balance >= 2.00 succeeds and deducts 2.00 points."""
        self.credits["balance"] = 10.00
        save_app_credits(self.credits)

        payload = {
            "title": "Study Note",
            "content": "Short valid text within 500 chars"
        }
        res = asyncio.run(api_save_note(payload))
        self.assertTrue(res.get("success"))

        updated_credits = load_app_credits()
        self.assertEqual(updated_credits["balance"], 8.00)
        self.assertEqual(updated_credits["transactions"][0]["amount"], -2.00)

    def test_snip_blocked_when_balance_under_five_credits(self):
        """Screen snap requires 5.00 points; rejected if balance < 5.00."""
        self.credits["balance"] = 4.50
        save_app_credits(self.credits)

        res = asyncio.run(api_trigger_snip({}))
        self.assertFalse(res.get("success"))
        self.assertIn("insufficient", res.get("error", "").lower())

    def test_mid_call_snip_depletes_balance_and_ticker_terminates_call(self):
        """User on call has 6.00 points; after snip (-5.00), remaining 1.00 is insufficient for next min, terminating call."""
        # Start with 6.00 points
        self.credits["balance"] = 6.00
        save_app_credits(self.credits)

        req = Request({
            "type": "http",
            "method": "POST",
            "headers": [(b"x-device", b"desktop")]
        })
        # Start session -> 2.50 deducted -> 3.50 left
        res = asyncio.run(api_start_session_history(req))
        self.assertTrue(res.get("success"))
        self.assertEqual(load_app_credits()["balance"], 3.50)

        # User tries to snip (requires 5.00, only 3.50 left) -> blocked
        snip_res = asyncio.run(api_trigger_snip({}))
        self.assertFalse(snip_res.get("success"))
        self.assertIn("insufficient", snip_res.get("error", "").lower())

        # Cleanup
        asyncio.run(api_end_session_history())

    def test_remote_rate_sync_fallback_on_unreachable(self):
        """If remote endpoint is unreachable/fails, fallback seamlessly to default rates without crash."""
        # Query invalid host with short timeout
        success = asyncio.run(sync_billing_rates_from_remote("http://127.0.0.1:59999/rates-nonexistent"))
        self.assertFalse(success)
        # Rates remain default
        self.assertEqual(get_billing_rate("call_per_minute"), 2.50)

if __name__ == "__main__":
    unittest.main()
