import os
import tempfile
import threading
import unittest

from window_toggle_ipc import (
    WindowToggleIpc,
    send_disable_click_through_request,
    send_toggle_request,
)


class WindowToggleIpcTests(unittest.TestCase):
    def test_request_invokes_callback_and_close_removes_socket(self):
        with tempfile.TemporaryDirectory() as runtime_dir:
            toggled = threading.Event()
            click_through_disabled = threading.Event()
            listener = WindowToggleIpc(
                toggled.set,
                click_through_disabled.set,
                runtime_dir=runtime_dir,
            )
            try:
                self.assertTrue(os.path.exists(listener.path))
                self.assertTrue(send_toggle_request(runtime_dir=runtime_dir))
                self.assertTrue(toggled.wait(timeout=1))
                self.assertTrue(send_disable_click_through_request(runtime_dir=runtime_dir))
                self.assertTrue(click_through_disabled.wait(timeout=1))
            finally:
                listener.close()

            self.assertFalse(os.path.exists(listener.path))

    def test_request_returns_false_when_listener_is_missing(self):
        with tempfile.TemporaryDirectory() as runtime_dir:
            self.assertFalse(send_toggle_request(runtime_dir=runtime_dir))
            self.assertFalse(send_disable_click_through_request(runtime_dir=runtime_dir))


if __name__ == "__main__":
    unittest.main()
