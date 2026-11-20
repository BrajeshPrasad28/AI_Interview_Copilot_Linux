import unittest
from unittest.mock import MagicMock, patch
import os

from ai_engine import InterviewAIEngine


class TestVisionErrorSanitization(unittest.TestCase):
    def setUp(self):
        self.engine = InterviewAIEngine()

    def test_sanitize_504_deadline_exceeded(self):
        raw = "504 DEADLINE_EXCEEDED. {'error': {'code': 504, 'message': 'Deadline expired before operation could complete.', 'status': 'DEADLINE_EXCEEDED'}}"
        cleaned = self.engine.sanitize_error(raw)
        self.assertNotIn("DEADLINE_EXCEEDED", cleaned)
        self.assertNotIn("{'error'", cleaned)
        self.assertIn("Analysis timed out", cleaned)
        self.assertIn("snip a specific question region", cleaned)

    def test_sanitize_429_quota_exceeded(self):
        raw = "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'Resource has been exhausted', 'status': 'RESOURCE_EXHAUSTED'}}"
        cleaned = self.engine.sanitize_error(raw)
        self.assertEqual(cleaned, "Quota exceeded. Please wait a few moments before trying again.")
        self.assertNotIn("Gemini", cleaned)

    def test_sanitize_503_service_overloaded(self):
        raw = "503 UNAVAILABLE. {'error': {'code': 503, 'message': 'The model is overloaded. Please try again later.'}}"
        cleaned = self.engine.sanitize_error(raw)
        self.assertEqual(cleaned, "AI service is temporarily overloaded. Please retry in a few seconds.")
        self.assertNotIn("Google", cleaned)
        self.assertNotIn("Gemini", cleaned)

    def test_sanitize_api_key_invalid(self):
        raw = "400 API_KEY_INVALID. {'error': {'code': 400, 'message': 'API key not valid. Please pass a valid API key.'}}"
        cleaned = self.engine.sanitize_error(raw)
        self.assertEqual(cleaned, "API key is invalid or unauthorized. Please connect admin.")
        self.assertNotIn("Gemini", cleaned)

    def test_sanitize_permission_denied(self):
        raw = "403 PERMISSION_DENIED. {'error': {'code': 403, 'message': 'Permission denied.'}}"
        cleaned = self.engine.sanitize_error(raw)
        self.assertEqual(cleaned, "API key is invalid or unauthorized. Please connect admin.")

    def test_sanitize_connection_network_error(self):
        raw = "httpcore.ConnectError: [Errno 11001] getaddrinfo failed"
        cleaned = self.engine.sanitize_error(raw)
        self.assertEqual(cleaned, "Unable to connect to Copilot. Please check your internet connection.")

    def test_sanitize_generic_strips_raw_json(self):
        raw = "GenerationError: {'error': {'code': 500, 'message': 'Internal worker failed unexpectedly'}}"
        cleaned = self.engine.sanitize_error(raw)
        self.assertNotIn("{'error'", cleaned)
        self.assertNotIn("code': 500", cleaned)
        self.assertIn("Internal worker failed unexpectedly", cleaned)

    def test_solve_screen_snip_returns_sanitized_error_on_deadline_timeout(self):
        # Mock client to raise 504 Deadline Exceeded
        fake_client = MagicMock()
        fake_client.models.generate_content.side_effect = Exception(
            "504 DEADLINE_EXCEEDED. {'error': {'code': 504, 'message': 'Deadline expired before operation could complete.', 'status': 'DEADLINE_EXCEEDED'}}"
        )
        self.engine.client = fake_client

        # Create 1x1 valid png/jpeg bytes
        from PIL import Image
        import io
        img = Image.new("RGB", (10, 10), color="white")
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        image_bytes = buf.getvalue()

        result = self.engine.solve_screen_snip(image_bytes)
        self.assertFalse(result["success"])
        self.assertNotIn("DEADLINE_EXCEEDED", result["error"])
        self.assertNotIn("{'error'", result["error"])
        self.assertIn("Analysis timed out", result["error"])

    def test_solve_screen_snip_missing_api_key(self):
        self.engine.client = None
        self.engine.api_key = ""
        result = self.engine.solve_screen_snip(b"some_bytes")
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "API key is invalid or unauthorized. Please connect admin.")
        self.assertNotIn("Gemini", result["error"])


if __name__ == "__main__":
    unittest.main()
