import threading
import logging
from typing import Callable, Optional

logger = logging.getLogger("hotkeys")

class GlobalHotkeyManager:
    """
    Manages global keyboard shortcuts using pynput.
    - Ctrl+Shift+S: Screen Snip & Solve
    - Ctrl+Shift+C: Clear / Panic
    """

    def __init__(self, on_snip: Optional[Callable] = None, on_clear: Optional[Callable] = None):
        self.on_snip = on_snip
        self.on_clear = on_clear
        self.listener = None
        self.running = False

    def start(self):
        """Start listening for hotkeys in a background thread."""
        try:
            from pynput import keyboard

            def for_canonical(f):
                return lambda k: f(l.canonical(k))

            hotkey_map = {}
            if self.on_snip:
                hotkey_map['<ctrl>+<shift>+s'] = self.on_snip
            if self.on_clear:
                hotkey_map['<ctrl>+<shift>+c'] = self.on_clear

            if not hotkey_map:
                return

            self.listener = keyboard.GlobalHotKeys(hotkey_map)
            self.listener.daemon = True
            self.listener.start()
            self.running = True
            logger.info("Global hotkeys initialized: [Ctrl+Shift+S: Snip] [Ctrl+Shift+C: Clear]")
        except Exception as e:
            logger.warning(f"Could not initialize global hotkeys: {e}. (Hotkeys can still be triggered via Web UI)")

    def stop(self):
        """Stop hotkey listener."""
        if self.listener:
            try:
                self.listener.stop()
            except Exception:
                pass
            self.running = False
