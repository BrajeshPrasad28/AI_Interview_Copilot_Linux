import io
import logging
from PIL import Image

logger = logging.getLogger("screen_snipper")

class ScreenSnipper:
    """
    Multi-tier screen capture utility with robust fallbacks:
    1. PIL.ImageGrab
    2. MSS
    3. Graceful fallback for non-interactive / locked sessions
    """

    def __init__(self):
        self.mss_instance = None

    def capture_primary_screen(self, quality: int = 85) -> bytes:
        """Capture the primary display and return a compressed JPEG image."""
        quality = max(35, min(95, int(quality)))
        # Tier 1: PIL ImageGrab
        try:
            from PIL import ImageGrab
            img = ImageGrab.grab(all_screens=False)
            return self._encode_image(img, quality)
        except Exception as e1:
            logger.debug(f"ImageGrab failed ({e1}), trying MSS...")

        # Tier 2: MSS
        try:
            import mss
            if not self.mss_instance:
                self.mss_instance = mss.mss()
            monitor = self.mss_instance.monitors[1] if len(self.mss_instance.monitors) > 1 else self.mss_instance.monitors[0]
            sct_img = self.mss_instance.grab(monitor)
            img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
            return self._encode_image(img, quality)
        except Exception as e2:
            logger.error(f"MSS capture failed: {e2}")

        raise RuntimeError(
            "Screen capture failed. Ensure the application is running in an active Linux desktop session, "
            "or upload/paste the screenshot directly in the Mobile Companion web app."
        )

    @staticmethod
    def _encode_image(image: Image.Image, quality: int) -> bytes:
        buffer = io.BytesIO()
        image.convert("RGB").save(buffer, format="JPEG", quality=quality, optimize=True)
        return buffer.getvalue()
