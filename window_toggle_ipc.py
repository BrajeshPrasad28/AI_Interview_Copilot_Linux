import errno
import logging
import os
import socket
import stat
import threading

logger = logging.getLogger(__name__)
_TOGGLE_MESSAGE = b"toggle"
_DISABLE_CLICK_THROUGH_MESSAGE = b"disable-click-through"
_SOCKET_NAME = "ai-interview-copilot-toggle.sock"


def _socket_path(runtime_dir=None):
    runtime_dir = runtime_dir or os.environ.get("XDG_RUNTIME_DIR")
    if not runtime_dir:
        return None
    return os.path.join(runtime_dir, _SOCKET_NAME)


def _send_request(message, runtime_dir=None):
    path = _socket_path(runtime_dir)
    if not path:
        return False

    client = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        client.sendto(message, path)
        return True
    except OSError as exc:
        if exc.errno in (errno.ENOENT, errno.ECONNREFUSED):
            return False
        raise
    finally:
        client.close()


def send_toggle_request(runtime_dir=None):
    return _send_request(_TOGGLE_MESSAGE, runtime_dir)


def send_disable_click_through_request(runtime_dir=None):
    return _send_request(_DISABLE_CLICK_THROUGH_MESSAGE, runtime_dir)


class WindowToggleIpc:
    def __init__(self, toggle_callback, disable_click_through_callback=None, runtime_dir=None):
        self.path = _socket_path(runtime_dir)
        if not self.path:
            raise RuntimeError("XDG_RUNTIME_DIR is not set; cannot register the GNOME toggle shortcut.")

        self._callbacks = {_TOGGLE_MESSAGE: toggle_callback}
        if disable_click_through_callback:
            self._callbacks[_DISABLE_CLICK_THROUGH_MESSAGE] = disable_click_through_callback
        self._stopping = threading.Event()
        self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        try:
            self._socket.bind(self.path)
        except OSError as exc:
            self._socket.close()
            if exc.errno == errno.EADDRINUSE and os.path.exists(self.path):
                if not stat.S_ISSOCK(os.stat(self.path).st_mode):
                    raise RuntimeError(f"Refusing to replace non-socket path: {self.path}") from exc
                if send_toggle_request(runtime_dir):
                    raise RuntimeError("Another window-toggle listener is already active.") from exc
                os.unlink(self.path)
                self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
                self._socket.bind(self.path)
            else:
                raise

        os.chmod(self.path, 0o600)
        self._socket.settimeout(0.25)
        self._thread = threading.Thread(target=self._serve, name="window-toggle-ipc", daemon=True)
        self._thread.start()

    def _serve(self):
        while not self._stopping.is_set():
            try:
                message = self._socket.recv(64)
            except socket.timeout:
                continue
            except OSError:
                if not self._stopping.is_set():
                    logger.exception("Window-toggle IPC socket failed.")
                return

            callback = self._callbacks.get(message)
            if callback:
                try:
                    callback()
                except Exception:
                    logger.exception("Could not handle a GNOME desktop shortcut request.")

    def close(self):
        self._stopping.set()
        self._socket.close()
        self._thread.join(timeout=1)
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass
