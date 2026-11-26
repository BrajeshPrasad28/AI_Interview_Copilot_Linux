import os
import unittest
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from hotkeys import GlobalHotkeyManager


class GlobalHotkeyManagerTests(unittest.TestCase):
    def test_visibility_callback_is_looked_up_when_hotkey_fires(self):
        calls = []
        manager = GlobalHotkeyManager()
        manager.on_toggle_visibility = lambda: calls.append("toggled")

        manager._toggle_visibility()

        self.assertEqual(calls, ["toggled"])

    def test_click_through_disable_callback_is_looked_up_when_hotkey_fires(self):
        calls = []
        manager = GlobalHotkeyManager()
        manager.on_disable_click_through = lambda: calls.append("disabled")

        manager._disable_click_through()

        self.assertEqual(calls, ["disabled"])

    @patch.dict(os.environ, {"XDG_SESSION_TYPE": "x11", "XDG_CURRENT_DESKTOP": "GNOME"})
    def test_global_click_through_hotkey_uses_callback_assigned_after_start(self):
        calls = []

        class FakeGlobalHotKeys:
            def __init__(self, hotkey_map):
                self.hotkey_map = hotkey_map

            def start(self):
                pass

        pynput = ModuleType("pynput")
        pynput.keyboard = SimpleNamespace(GlobalHotKeys=FakeGlobalHotKeys)
        manager = GlobalHotkeyManager(on_snip=lambda: None)

        with patch.dict(sys.modules, {"pynput": pynput}):
            manager.start()
            manager.on_disable_click_through = lambda: calls.append("disabled")
            manager.listener.hotkey_map["<ctrl>+<alt>+m"]()

        self.assertEqual(calls, ["disabled"])

    @patch.dict(os.environ, {"XDG_SESSION_TYPE": "wayland", "XDG_CURRENT_DESKTOP": "ubuntu:GNOME"})
    def test_gnome_wayland_uses_compositor_shortcuts_instead_of_pynput_duplicates(self):
        class FakeGlobalHotKeys:
            def __init__(self, hotkey_map):
                self.hotkey_map = hotkey_map

            def start(self):
                pass

        pynput = ModuleType("pynput")
        pynput.keyboard = SimpleNamespace(GlobalHotKeys=FakeGlobalHotKeys)
        manager = GlobalHotkeyManager(on_snip=lambda: None, on_clear=lambda: None)

        with patch.dict(sys.modules, {"pynput": pynput}):
            manager.start()

        self.assertIn("<ctrl>+<shift>+s", manager.listener.hotkey_map)
        self.assertNotIn("<ctrl>+<shift>+m", manager.listener.hotkey_map)
        self.assertNotIn("<ctrl>+<alt>+m", manager.listener.hotkey_map)


if __name__ == "__main__":
    unittest.main()
