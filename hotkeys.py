import os
import threading
import logging
from typing import Callable, Optional

logger = logging.getLogger("hotkeys")

class GlobalHotkeyManager:
    """
    Manages global keyboard shortcuts using pynput.
    - Ctrl+Shift+S: Screen Snip & Solve
    - Ctrl+Shift+C: Clear / Panic
    - Ctrl+Shift+M: Toggle desktop window visibility
    - Ctrl+Alt+M: Disable click-through mode
    """

    def __init__(
        self,
        on_snip: Optional[Callable] = None,
        on_clear: Optional[Callable] = None,
        on_toggle_visibility: Optional[Callable] = None,
        on_disable_click_through: Optional[Callable] = None,
    ):
        self.on_snip = on_snip
        self.on_clear = on_clear
        self.on_toggle_visibility = on_toggle_visibility
        self.on_disable_click_through = on_disable_click_through
        self.listener = None
        self.running = False

    def _toggle_visibility(self):
        if self.on_toggle_visibility:
            self.on_toggle_visibility()

    def _disable_click_through(self):
        if self.on_disable_click_through:
            self.on_disable_click_through()

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
            is_gnome_wayland = (
                os.getenv("XDG_SESSION_TYPE") == "wayland"
                and "gnome" in os.getenv("XDG_CURRENT_DESKTOP", "").lower()
            )
            if not is_gnome_wayland and (
                self.on_snip or self.on_clear or self.on_toggle_visibility or self.on_disable_click_through
            ):
                hotkey_map['<ctrl>+<shift>+m'] = self._toggle_visibility
                hotkey_map['<ctrl>+<alt>+m'] = self._disable_click_through

            if not hotkey_map:
                return

            self.listener = keyboard.GlobalHotKeys(hotkey_map)
            self.listener.daemon = True
            self.listener.start()
            self.running = True
            if is_gnome_wayland:
                logger.info(
                    "Global hotkeys initialized; GNOME custom shortcuts handle window controls on Wayland."
                )
            else:
                logger.info(
                    "Global hotkeys initialized: [Ctrl+Shift+S: Snip] "
                    "[Ctrl+Shift+C: Clear] [Ctrl+Shift+M: Toggle window] "
                    "[Ctrl+Alt+M: Disable click-through]"
                )
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
