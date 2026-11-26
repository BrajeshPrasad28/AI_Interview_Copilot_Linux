import unittest

from run import _set_gtk_window_pass_through


class FakeGdkWindow:
    def __init__(self, children=None):
        self.pass_through = False
        self.children = children or []

    def set_pass_through(self, enabled):
        self.pass_through = enabled

    def get_pass_through(self):
        return self.pass_through

    def get_children(self):
        return self.children


class FakeGtkWindow:
    def __init__(self, gdk_window):
        self.gdk_window = gdk_window

    def get_window(self):
        return self.gdk_window


class GtkClickThroughTests(unittest.TestCase):
    def test_sets_and_clears_native_pass_through_on_gui_callback(self):
        nested_child = FakeGdkWindow()
        child = FakeGdkWindow([nested_child])
        gdk_window = FakeGdkWindow([child])
        gtk_window = FakeGtkWindow(gdk_window)

        def run_on_gui_thread(callback):
            callback()

        _set_gtk_window_pass_through(gtk_window, True, run_on_gui_thread)
        self.assertTrue(gdk_window.get_pass_through())
        self.assertTrue(child.get_pass_through())
        self.assertTrue(nested_child.get_pass_through())

        _set_gtk_window_pass_through(gtk_window, False, run_on_gui_thread)
        self.assertFalse(gdk_window.get_pass_through())
        self.assertFalse(child.get_pass_through())
        self.assertFalse(nested_child.get_pass_through())

    def test_reports_unrealized_gtk_window(self):
        gtk_window = FakeGtkWindow(None)

        with self.assertRaisesRegex(RuntimeError, "not realized"):
            _set_gtk_window_pass_through(gtk_window, True, lambda callback: callback())

    def test_cancelled_timeout_does_not_apply_late_change(self):
        gdk_window = FakeGdkWindow()
        gtk_window = FakeGtkWindow(gdk_window)
        callbacks = []

        with self.assertRaisesRegex(RuntimeError, "Timed out"):
            _set_gtk_window_pass_through(
                gtk_window,
                True,
                callbacks.append,
                timeout=0.001,
            )

        callbacks[0]()
        self.assertFalse(gdk_window.get_pass_through())


if __name__ == "__main__":
    unittest.main()
