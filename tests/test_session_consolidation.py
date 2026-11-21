import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

_test_dir = tempfile.mkdtemp(prefix="test_session_consolidation_")
os.environ["INTERVIEW_TOOL_DATA_DIR"] = _test_dir

from core.state import (
    load_app_credits,
    save_app_credits,
    deduct_credit_usage,
    finalize_session_transaction,
    get_billing_rate,
    set_billing_rates,
    DEFAULT_BILLING_RATES,
)


class TestSessionTransactionConsolidation(unittest.TestCase):
    def setUp(self):
        set_billing_rates(DEFAULT_BILLING_RATES)
        self.credits = {
            "balance": 100.0,
            "redeemed_codes": ["TEST-100"],
            "transactions": []
        }
        save_app_credits(self.credits)

    def test_first_minute_creates_single_session_transaction(self):
        """Starting a session creates a single transaction associated with session_id."""
        call_rate = get_billing_rate("call_per_minute")
        session_id = "session_test_123"

        tx = deduct_credit_usage(
            amount=call_rate,
            user_name="Brajesh Pasad",
            user_email="brajesh.prasad28@gmail.com",
            user_phone="+918723969733",
            description="Copilot Session (In Progress)",
            duration="1m",
            total_snaps=0,
            count=0,
            session_id=session_id
        )

        data = load_app_credits()
        self.assertEqual(data["balance"], 97.50)
        self.assertEqual(len(data["transactions"]), 1)
        self.assertEqual(data["transactions"][0]["amount"], -2.50)
        self.assertEqual(data["transactions"][0]["duration"], "1m")
        self.assertEqual(data["transactions"][0]["session_id"], session_id)

    def test_subsequent_minutes_update_existing_transaction_in_place(self):
        """Minutes 2, 3... update the same session transaction in-place instead of creating new cards."""
        call_rate = get_billing_rate("call_per_minute")
        session_id = "session_test_multi_min"

        # Minute 1
        deduct_credit_usage(
            amount=call_rate,
            user_name="Brajesh Pasad",
            user_email="brajesh.prasad28@gmail.com",
            user_phone="+918723969733",
            description="Copilot Session (In Progress)",
            duration="1m",
            total_snaps=0,
            count=0,
            session_id=session_id
        )

        # Minute 2
        deduct_credit_usage(
            amount=call_rate,
            user_name="Brajesh Pasad",
            user_email="brajesh.prasad28@gmail.com",
            user_phone="+918723969733",
            description="Copilot Session (In Progress)",
            duration="2m",
            total_snaps=0,
            count=0,
            session_id=session_id
        )

        # Minute 3
        deduct_credit_usage(
            amount=call_rate,
            user_name="Brajesh Pasad",
            user_email="brajesh.prasad28@gmail.com",
            user_phone="+918723969733",
            description="Copilot Session (In Progress)",
            duration="3m",
            total_snaps=0,
            count=0,
            session_id=session_id
        )

        data = load_app_credits()
        self.assertEqual(data["balance"], 92.50)
        self.assertEqual(len(data["transactions"]), 1, "Must maintain exactly ONE transaction card for the entire session")
        self.assertEqual(data["transactions"][0]["amount"], -7.50)
        self.assertEqual(data["transactions"][0]["duration"], "3m")
        self.assertEqual(data["transactions"][0]["session_id"], session_id)

    def test_session_snaps_aggregate_into_same_transaction(self):
        """Snaps taken during active session aggregate into the single session card."""
        call_rate = get_billing_rate("call_per_minute")
        snap_rate = get_billing_rate("snap_per_count")
        session_id = "session_test_snaps"

        # Minute 1
        deduct_credit_usage(
            amount=call_rate,
            user_name="Brajesh Pasad",
            user_email="brajesh.prasad28@gmail.com",
            user_phone="+918723969733",
            description="Copilot Session (In Progress)",
            duration="1m",
            total_snaps=0,
            count=0,
            session_id=session_id
        )

        # Snap 1
        deduct_credit_usage(
            amount=snap_rate,
            user_name="Brajesh Pasad",
            user_email="brajesh.prasad28@gmail.com",
            user_phone="+918723969733",
            description="Copilot Session (In Progress)",
            duration="1m",
            total_snaps=1,
            count=1,
            session_id=session_id
        )

        data = load_app_credits()
        self.assertEqual(data["balance"], 100.0 - 2.50 - 5.00)
        self.assertEqual(len(data["transactions"]), 1)
        self.assertEqual(data["transactions"][0]["amount"], -7.50)
        self.assertEqual(data["transactions"][0]["total_snaps"], 1)

    def test_finalize_session_transaction(self):
        """Ending session finalizes description with clean summary text."""
        call_rate = get_billing_rate("call_per_minute")
        session_id = "session_test_finalize"

        deduct_credit_usage(
            amount=call_rate,
            user_name="Brajesh Pasad",
            user_email="brajesh.prasad28@gmail.com",
            user_phone="+918723969733",
            description="Copilot Session (In Progress)",
            duration="1m",
            total_snaps=0,
            count=0,
            session_id=session_id
        )

        final_tx = finalize_session_transaction(session_id, duration="21m", total_snaps=20)
        self.assertIsNotNone(final_tx)
        self.assertIn("21m", final_tx["description"])
        self.assertIn("20 snaps", final_tx["description"])

        data = load_app_credits()
        self.assertEqual(len(data["transactions"]), 1)
        self.assertIn("21m", data["transactions"][0]["description"])
        self.assertIn("20 snaps", data["transactions"][0]["description"])


if __name__ == "__main__":
    unittest.main()
