import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from create_shortcut import install_gnome_toggle_shortcut


class GnomeShortcutTests(unittest.TestCase):
    @patch.dict(os.environ, {"XDG_SESSION_TYPE": "wayland", "XDG_CURRENT_DESKTOP": "ubuntu:GNOME"})
    @patch("create_shortcut.shutil.which", return_value="/usr/bin/gsettings")
    @patch("create_shortcut._gsettings")
    def test_registers_wayland_shortcut_without_overwriting_existing_bindings(
        self, gsettings, _which
    ):
        existing = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/existing/"
        gsettings.side_effect = [
            SimpleNamespace(stdout=f"['{existing}']"),
            *([None] * 7),
        ]

        installed = install_gnome_toggle_shortcut("/app/.venv/bin/python", "/app/run.py")

        self.assertTrue(installed)
        self.assertEqual(gsettings.call_args_list[0].args, (
            "get", "org.gnome.settings-daemon.plugins.media-keys", "custom-keybindings"
        ))
        self.assertEqual(
            gsettings.call_args_list[-1].args,
            (
                "set",
                "org.gnome.settings-daemon.plugins.media-keys",
                "custom-keybindings",
                repr([
                    existing,
                    "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/ai-interview-copilot/",
                    "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/ai-interview-copilot-disable-pass-through/",
                ]),
            ),
        )

    @patch.dict(os.environ, {"XDG_SESSION_TYPE": "wayland", "XDG_CURRENT_DESKTOP": "KDE"})
    @patch("create_shortcut._gsettings")
    def test_skips_non_gnome_wayland_sessions(self, gsettings):
        self.assertFalse(install_gnome_toggle_shortcut("/app/python", "/app/run.py"))
        gsettings.assert_not_called()


if __name__ == "__main__":
    unittest.main()
