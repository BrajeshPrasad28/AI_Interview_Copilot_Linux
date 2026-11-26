import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ["INTERVIEW_TOOL_DATA_DIR"] = tempfile.mkdtemp(prefix="test_credit_defaults_")

from core import state


class TestCreditDefaults(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="credits_")
        self.credits_path_patch = patch.object(
            state,
            "CREDITS_PATH",
            os.path.join(self.temp_dir.name, "credits.json"),
        )
        self.credits_path_patch.start()

    def tearDown(self):
        self.credits_path_patch.stop()
        self.temp_dir.cleanup()

    def test_new_install_starts_with_no_unearned_credits(self):
        credits = state.load_app_credits()

        self.assertEqual(credits["balance"], 0.0)
        self.assertEqual(credits["redeemed_codes"], [])
        self.assertEqual(credits["transactions"], [])
        self.assertTrue(state.verify_credits_signature(credits))

    def test_migration_removes_starter_credit_but_keeps_later_paid_balance(self):
        starter_code = state.LEGACY_STARTER_CODE
        state.save_app_credits({
            "balance": 50.0,
            "redeemed_codes": [starter_code, "ABCD-1234-EFGH-5678"],
            "transactions": [
                {
                    "id": "TXN-PAID",
                    "type": "credit",
                    "amount": 50.0,
                    "balance_after": 50.0,
                    "timestamp": "2026-11-25 12:00 PM",
                    "code": "ABCD-1234-EFGH-5678",
                    "description": "Credit Points Added",
                },
                {
                    "id": "TXN-SPENT",
                    "type": "debit",
                    "amount": -100.0,
                    "balance_after": 0.0,
                    "timestamp": "2026-11-25 11:00 AM",
                    "code": "",
                    "description": "Copilot Session",
                },
                {
                    "id": "TXN-10001",
                    "type": "credit",
                    "amount": 100.0,
                    "balance_after": 100.0,
                    "timestamp": "2026-11-25 10:00 AM",
                    "code": starter_code,
                    "description": "Credit Points Added",
                },
            ],
        })

        credits = state.load_app_credits()

        self.assertEqual(credits["balance"], 50.0)
        self.assertEqual(credits["redeemed_codes"], ["ABCD-1234-EFGH-5678"])
        self.assertNotIn(starter_code, [tx.get("code") for tx in credits["transactions"]])
        self.assertTrue(state.verify_credits_signature(credits))

    def test_migration_removes_unspent_starter_balance(self):
        starter_code = state.LEGACY_STARTER_CODE
        state.save_app_credits({
            "balance": 97.5,
            "redeemed_codes": [starter_code],
            "transactions": [
                {
                    "id": "TXN-SESSION",
                    "type": "debit",
                    "amount": -2.5,
                    "balance_after": 97.5,
                    "timestamp": "2026-11-25 11:00 AM",
                    "code": "",
                    "description": "Copilot Session",
                },
                {
                    "id": "TXN-10001",
                    "type": "credit",
                    "amount": 100.0,
                    "balance_after": 100.0,
                    "timestamp": "2026-11-25 10:00 AM",
                    "code": starter_code,
                    "description": "Credit Points Added",
                },
            ],
        })

        credits = state.load_app_credits()

        self.assertEqual(credits["balance"], 0.0)
        self.assertEqual(credits["redeemed_codes"], [])
        self.assertEqual(len(credits["transactions"]), 1)


if __name__ == "__main__":
    unittest.main()
