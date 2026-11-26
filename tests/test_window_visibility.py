import unittest

from run import _toggle_gtk_window_visibility


class FakeGdkWindow:
    def __init__(self, state=0):
        self.state = state

    def get_state(self):
        return self.state


class FakeGtkWindow:
    def __init__(self, visible=True, state=0):
        self.visible = visible
        self.gdk_window = FakeGdkWindow(state)
        self.presented = False

    def get_window(self):
        return self.gdk_window

    def get_visible(self):
        return self.visible

    def hide(self):
        self.visible = False

    def show(self):
        self.visible = True

    def deiconify(self):
        self.gdk_window.state = 0

    def present(self):
        self.presented = True


class GtkWindowVisibilityTests(unittest.TestCase):
    def run_toggle(self, window):
        _toggle_gtk_window_visibility(window, iconified_state=1, idle_add=lambda callback: callback())

    def test_hotkey_hides_visible_window_and_shows_hidden_window(self):
        window = FakeGtkWindow(visible=True)

        self.run_toggle(window)
        self.assertFalse(window.visible)

        self.run_toggle(window)
        self.assertTrue(window.visible)
        self.assertTrue(window.presented)

    def test_hotkey_restores_minimized_window(self):
        window = FakeGtkWindow(visible=True, state=1)

        self.run_toggle(window)

        self.assertTrue(window.visible)
        self.assertEqual(window.gdk_window.state, 0)
        self.assertTrue(window.presented)


if __name__ == "__main__":
    unittest.main()
