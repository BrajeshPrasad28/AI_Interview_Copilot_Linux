import os
import sys
import socket
import webbrowser
import argparse
import ctypes
import ctypes.util
import logging
import threading
import time
import uvicorn
from dotenv import load_dotenv
from window_toggle_ipc import (
    WindowToggleIpc,
    send_disable_click_through_request,
    send_toggle_request,
)

logger = logging.getLogger(__name__)

# Store application data under the Linux XDG data directory.
_XDG_DATA = os.getenv("XDG_DATA_HOME", os.path.join(os.path.expanduser("~"), ".local", "share"))
APP_DATA_DIR = os.path.join(_XDG_DATA, "InterviewTool")
os.makedirs(APP_DATA_DIR, exist_ok=True)
LOG_FILE_PATH = os.path.join(APP_DATA_DIR, "app.log")
CRASH_LOG_PATH = os.path.join(APP_DATA_DIR, "crash.log")

# Keep diagnostics available when stdout or stderr is not attached.
if sys.stdout is None:
    try:
        sys.stdout = open(LOG_FILE_PATH, "a", encoding="utf-8", buffering=1)
    except Exception:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
elif hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

if sys.stderr is None:
    try:
        sys.stderr = open(LOG_FILE_PATH, "a", encoding="utf-8", buffering=1)
    except Exception:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
elif hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import traceback
def _global_exception_hook(exc_type, exc_val, exc_tb):
    try:
        with open(CRASH_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"\n--- Crash at {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
            traceback.print_exception(exc_type, exc_val, exc_tb, file=f)
    except Exception:
        pass
sys.excepthook = _global_exception_hook

# Load env
load_dotenv(dotenv_path=os.getenv("APP_ENV_FILE") or None)

def get_local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip

def bind_server_socket(host: str, preferred_port: int | None = None) -> socket.socket:
    """Reserve a preferred port or let the OS assign a free port silently."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.bind((host, preferred_port or 0))
    except OSError:
        listener.close()
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind((host, 0))
    listener.listen(socket.SOMAXCONN)
    listener.setblocking(False)
    return listener


def _set_gtk_window_pass_through(native_window, enabled: bool, idle_add, timeout: float = 5.0) -> None:
    completed = threading.Event()
    cancelled = threading.Event()
    errors = []

    def apply_pass_through():
        if cancelled.is_set():
            return False
        try:
            gdk_window = native_window.get_window()
            if gdk_window is None:
                raise RuntimeError("The GTK window is not realized yet.")
            windows = []
            pending = [gdk_window]
            while pending:
                current = pending.pop()
                windows.append(current)
                pending.extend(current.get_children())
            for window in windows:
                window.set_pass_through(enabled)
            if any(window.get_pass_through() != enabled for window in windows):
                raise RuntimeError("GTK did not apply the requested click-through state to every window.")
        except Exception as exc:
            errors.append(exc)
        finally:
            completed.set()
        return False

    idle_add(apply_pass_through)
    if not completed.wait(timeout):
        cancelled.set()
        raise RuntimeError("Timed out while applying GTK click-through.")
    if errors:
        raise RuntimeError(f"Could not update GTK click-through: {errors[0]}") from errors[0]


class _WindowVisibilityState:
    def __init__(self) -> None:
        self.hidden: bool = False


def _send_x11_activation_request(window_id: int) -> bool:
    library = ctypes.util.find_library("X11")
    if not library:
        logger.warning("Cannot activate Copilot window: libX11 was not found.")
        return False

    try:
        x11 = ctypes.CDLL(library)
    except OSError as exc:
        logger.warning("Cannot load libX11 to activate Copilot window: %s", exc)
        return False

    Display = ctypes.c_void_p
    Window = ctypes.c_ulong
    Atom = ctypes.c_ulong

    class ClientMessageData(ctypes.Union):
        _fields_ = [
            ("b", ctypes.c_char * 20),
            ("s", ctypes.c_short * 10),
            ("l", ctypes.c_long * 5),
        ]

    class ClientMessageEvent(ctypes.Structure):
        _fields_ = [
            ("type", ctypes.c_int),
            ("serial", ctypes.c_ulong),
            ("send_event", ctypes.c_int),
            ("display", Display),
            ("window", Window),
            ("message_type", Atom),
            ("format", ctypes.c_int),
            ("data", ClientMessageData),
        ]

    class XEvent(ctypes.Union):
        _fields_ = [
            ("type", ctypes.c_int),
            ("xclient", ClientMessageEvent),
            ("pad", ctypes.c_long * 24),
        ]

    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XOpenDisplay.restype = Display
    x11.XDefaultRootWindow.argtypes = [Display]
    x11.XDefaultRootWindow.restype = Window
    x11.XInternAtom.argtypes = [Display, ctypes.c_char_p, ctypes.c_int]
    x11.XInternAtom.restype = Atom
    x11.XSendEvent.argtypes = [
        Display,
        Window,
        ctypes.c_int,
        ctypes.c_long,
        ctypes.POINTER(XEvent),
    ]
    x11.XSendEvent.restype = ctypes.c_int
    x11.XFlush.argtypes = [Display]
    x11.XCloseDisplay.argtypes = [Display]

    display = x11.XOpenDisplay(None)
    if not display:
        logger.warning("Cannot connect to X11 to activate Copilot window.")
        return False

    try:
        event = XEvent()
        event.xclient.type = 33  # ClientMessage
        event.xclient.send_event = 1
        event.xclient.display = display
        event.xclient.window = window_id
        event.xclient.message_type = x11.XInternAtom(
            display, b"_NET_ACTIVE_WINDOW", 0
        )
        event.xclient.format = 32
        event.xclient.data.l[0] = 2  # EWMH pager-style activation request.
        root = x11.XDefaultRootWindow(display)
        sent = x11.XSendEvent(
            display,
            root,
            0,
            (1 << 19) | (1 << 20),
            ctypes.byref(event),
        )
        x11.XFlush(display)
        if not sent:
            logger.warning("The X11 window manager rejected Copilot activation.")
        return bool(sent)
    finally:
        x11.XCloseDisplay(display)


def _activate_x11_window(native_window) -> bool:
    gdk_window = native_window.get_window()
    if not gdk_window:
        return False

    try:
        import gi

        gi.require_version("GdkX11", "3.0")
        from gi.repository import GdkX11

        window_id = GdkX11.X11Window.get_xid(gdk_window)
    except (ImportError, TypeError, ValueError):
        return False

    return _send_x11_activation_request(window_id)


def _toggle_gtk_window_visibility(
    native_window,
    iconified_state,
    idle_add,
    visibility_state,
    activate_window=_activate_x11_window,
) -> None:
    def toggle():
        gdk_window = native_window.get_window()
        is_minimized = bool(gdk_window and gdk_window.get_state() & iconified_state)
        should_show = (
            visibility_state.hidden
            or not native_window.get_visible()
            or is_minimized
        )
        if should_show:
            native_window.show()
            native_window.deiconify()
            native_window.present()
            activate_window(native_window)
            visibility_state.hidden = False
        else:
            native_window.hide()
            visibility_state.hidden = True
        return False

    idle_add(toggle)


def _prepare_linux_gtk_environment() -> None:
    if not sys.platform.startswith("linux"):
        return

    # Avoid loading GTK schemas and modules bundled by a Snap-hosted editor.
    snap_code_roots = (
        os.path.realpath(os.path.join(os.path.expanduser("~"), "snap", "code")),
        os.path.realpath("/snap/code"),
    )

    def is_snap_code_path(path: str) -> bool:
        if not path:
            return False
        resolved = os.path.realpath(path)
        return any(
            resolved == root or os.path.commonpath((root, resolved)) == root
            for root in snap_code_roots
        )

    schema_dir = os.environ.get("GSETTINGS_SCHEMA_DIR", "")
    if is_snap_code_path(schema_dir):
        system_schema_dir = "/usr/share/glib-2.0/schemas"
        if not os.path.isdir(system_schema_dir):
            raise RuntimeError(f"Host GSettings schemas were not found in {system_schema_dir}.")
        os.environ["GSETTINGS_SCHEMA_DIR"] = system_schema_dir

    gtk_path_variables = (
        "GIO_MODULE_DIR",
        "GIO_EXTRA_MODULES",
        "GTK_EXE_PREFIX",
        "GTK_PATH",
        "GTK_DATA_PREFIX",
        "GDK_PIXBUF_MODULEDIR",
        "GDK_PIXBUF_MODULE_FILE",
        "GTK_IM_MODULE_FILE",
    )
    for variable in gtk_path_variables:
        value = os.environ.get(variable)
        if not value:
            continue
        entries = value.split(os.pathsep)
        host_entries = [entry for entry in entries if not is_snap_code_path(entry)]
        if len(host_entries) != len(entries):
            if host_entries:
                os.environ[variable] = os.pathsep.join(host_entries)
            else:
                os.environ.pop(variable, None)

    # pywebview's GTK easy-drag uses Gtk.Window.move, which Wayland does not support.
    if os.environ.get("WAYLAND_DISPLAY") and os.environ.get("DISPLAY"):
        backends = [item.strip().lower() for item in os.environ.get("GDK_BACKEND", "").split(",")]
        if not backends or backends[0] != "x11":
            os.environ["GDK_BACKEND"] = "x11,wayland"


def start_desktop_window(dashboard_url: str, host: str, port: int, listener_socket: socket.socket):
    _prepare_linux_gtk_environment()

    try:
        import webview
    except ImportError as exc:
        listener_socket.close()
        raise RuntimeError(
            "Desktop window support is missing. Install dependencies with "
            "'pip install -r requirements.txt' and try again.\n"
            "On Linux also install: sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-webkit2-4.0"
        ) from exc

    config = uvicorn.Config(
        "server:app",
        host=host,
        port=port,
        reload=False,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    server_thread = threading.Thread(
        target=server.run,
        args=([listener_socket],),
        name="interview-tool-server",
        daemon=True,
    )
    server_thread.start()

    startup_deadline = time.monotonic() + 30
    while not server.started and server_thread.is_alive():
        if time.monotonic() >= startup_deadline:
            server.should_exit = True
            server_thread.join(timeout=5)
            raise RuntimeError("The local web server did not start within 30 seconds.")
        time.sleep(0.1)

    if not server.started:
        raise RuntimeError("The local web server stopped before it finished starting.")

    app_title = os.getenv("APP_NAME", "Bluetooth Driver").strip() or "Bluetooth Driver"

    class DesktopApi:
        def __init__(self):
            self._window = None
            self._visibility_state = _WindowVisibilityState()
            # Default alpha matching default background opacity (61% = ~155 alpha)
            self.current_alpha = 155
            self.click_through = False
            self._click_through_timer = None

        def minimize(self):
            if self._window:
                self._window.minimize()

        def toggle_visibility(self):
            if not self._window or not self._window.native:
                raise RuntimeError("The GTK desktop window is not available.")

            import gi

            gi.require_version("Gtk", "3.0")
            gi.require_version("Gdk", "3.0")
            from gi.repository import Gdk, GLib

            _toggle_gtk_window_visibility(
                self._window.native,
                Gdk.WindowState.ICONIFIED,
                GLib.idle_add,
                self._visibility_state,
            )
            return True

        def close(self):
            if self._click_through_timer:
                self._click_through_timer.cancel()
                self._click_through_timer = None
            if self._window:
                self._window.destroy()

        def _apply_window_opacity(self):
            if not self._window or not self._window.native:
                return
            try:
                import gi

                gi.require_version("Gtk", "3.0")
                from gi.repository import GLib

                GLib.idle_add(self._window.native.set_opacity, self.current_alpha / 255.0)
            except Exception as e:
                print(f"Error applying window opacity: {e}")

        def set_opacity(self, alpha):
            try:
                val = max(40, min(255, int(alpha)))
                self.current_alpha = val
                self._apply_window_opacity()
                return self.current_alpha
            except Exception as e:
                print(f"Error setting opacity: {e}")
                return self.current_alpha

        def adjust_opacity(self, delta):
            return self.set_opacity(self.current_alpha + int(delta))

        def get_opacity(self):
            return self.current_alpha

        def _apply_click_through(self, enabled: bool):
            if not self._window or not self._window.native:
                raise RuntimeError("The GTK desktop window is not available.")

            import gi

            gi.require_version("Gtk", "3.0")
            gi.require_version("Gdk", "3.0")
            from gi.repository import GLib

            _set_gtk_window_pass_through(
                self._window.native,
                enabled,
                GLib.idle_add,
            )

        def toggle_click_through(self):
            requested_state = not self.click_through
            self._apply_click_through(requested_state)
            self.click_through = requested_state
            if self._click_through_timer:
                self._click_through_timer.cancel()
                self._click_through_timer = None
            if self.click_through:
                self._click_through_timer = threading.Timer(30.0, self._auto_disable_click_through)
                self._click_through_timer.daemon = True
                self._click_through_timer.start()
            return self.click_through

        def disable_click_through(self):
            if not self.click_through:
                return False
            self.toggle_click_through()
            if self._window:
                try:
                    self._window.evaluate_js(
                        "document.querySelectorAll('.btn-click-through').forEach(b => b.classList.remove('active'));"
                    )
                except Exception as exc:
                    print(f"Could not update click-through button state: {exc}")
            return False

        def _auto_disable_click_through(self):
            """Safety: automatically disable click-through after timeout to prevent lockout."""
            if self.click_through:
                try:
                    self._apply_click_through(False)
                    self.click_through = False
                    self._click_through_timer = None
                    # Notify the frontend to update the button state
                    if self._window:
                        self._window.evaluate_js(
                            "document.querySelectorAll('.btn-click-through').forEach(b => b.classList.remove('active'));"
                            "showStealthToast('Click-Through auto-disabled (30s safety)');"
                        )
                    print("🛡️ Click-through auto-disabled after 30s safety timeout.")
                except Exception as e:
                    print(f"Error auto-disabling click-through: {e}")

        def resize_window(self, width: int, height: int):
            try:
                if self._window:
                    w = max(640, min(1920, int(width)))
                    h = max(360, min(1200, int(height)))
                    # pywebview marshals resize calls to the GUI thread. Apply
                    # each preset in one call so rapid intermediate updates do
                    # not block or overwhelm the native window message loop.
                    self._window.resize(w, h)
                    return {"width": w, "height": h}
            except Exception as e:
                print(f"Error resizing window: {e}")
            return None

        def resize_window_from_corner(self, width: int, height: int, corner: str):
            try:
                if not self._window:
                    return None
                from webview.window import FixPoint

                anchors = {
                    "nw": FixPoint.SOUTH | FixPoint.EAST,
                    "ne": FixPoint.SOUTH | FixPoint.WEST,
                    "sw": FixPoint.NORTH | FixPoint.EAST,
                    "se": FixPoint.NORTH | FixPoint.WEST,
                    "n": FixPoint.SOUTH | FixPoint.WEST,
                    "s": FixPoint.NORTH | FixPoint.WEST,
                    "w": FixPoint.NORTH | FixPoint.EAST,
                    "e": FixPoint.NORTH | FixPoint.WEST,
                }
                anchor = anchors.get(str(corner).lower())
                if anchor is None:
                    return None

                w = max(640, min(1920, int(width)))
                h = max(360, min(1200, int(height)))
                self._window.resize(w, h, fix_point=anchor)
                return {"width": w, "height": h}
            except Exception as e:
                print(f"Error resizing window from corner: {e}")
                return None

        def cycle_size(self):
            try:
                if self._window:
                    presets = [
                        {"name": "Normal", "width": 800, "height": 460},
                        {"name": "Large", "width": 960, "height": 550},
                        {"name": "Compact", "width": 700, "height": 400},
                    ]
                    current_w = self._window.width
                    if current_w < 750:
                        next_p = presets[0]
                    elif current_w < 880:
                        next_p = presets[1]
                    else:
                        next_p = presets[2]

                    self.resize_window(next_p["width"], next_p["height"])
                    return next_p
            except Exception as e:
                print(f"Error cycling size: {e}")
            return None

    desktop_api = DesktopApi()

    from core.state import hotkey_manager

    hotkey_manager.on_toggle_visibility = desktop_api.toggle_visibility
    hotkey_manager.on_disable_click_through = desktop_api.disable_click_through

    toggle_ipc = None

    def on_gui_ready():
        nonlocal toggle_ipc
        """Called safely once pywebview's native message loop has initialized."""
        try:
            if hasattr(desktop_api._window, 'events') and hasattr(desktop_api._window.events, 'loaded'):
                desktop_api._window.events.loaded.wait(timeout=10)
            elif hasattr(desktop_api._window, 'events') and hasattr(desktop_api._window.events, 'shown'):
                desktop_api._window.events.shown.wait(timeout=10)
            time.sleep(0.3)
            toggle_ipc = WindowToggleIpc(
                desktop_api.toggle_visibility,
                desktop_api.disable_click_through,
            )
            print(f"✅ Desktop window ready: {app_title}")
        except Exception as e:
            print(f"Error in on_gui_ready: {e}")

    try:
        window = webview.create_window(
            app_title,
            dashboard_url,
            width=800,
            height=460,
            min_size=(640, 360),
            resizable=True,
            frameless=True,
            transparent=True,
            easy_drag=True,
            on_top=True,
            background_color="#000000",
            js_api=desktop_api,
        )
        desktop_api._window = window

        def keep_window_off_taskbar(window):
            if not window.native:
                raise RuntimeError("The GTK desktop window is not available before showing.")
            window.native.set_skip_taskbar_hint(True)

        window.events.before_show += keep_window_off_taskbar

        webview.start(on_gui_ready, gui="gtk")
    finally:
        if toggle_ipc:
            toggle_ipc.close()
        server.should_exit = True
        server_thread.join(timeout=10)
        if server_thread.is_alive():
            print("Warning: the local web server did not shut down within 10 seconds.")


def acquire_single_instance_lock(app_title: str):
    """Ensure only one instance runs at a time (Linux: file-lock based)."""
    import fcntl
    _xdg = os.getenv("XDG_DATA_HOME", os.path.join(os.path.expanduser("~"), ".local", "share"))
    lock_dir = os.path.join(_xdg, "InterviewTool")
    os.makedirs(lock_dir, exist_ok=True)
    lock_path = os.path.join(lock_dir, "instance.lock")
    try:
        lock_file = open(lock_path, "w")
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return lock_file  # Keep file open to hold lock
    except (IOError, OSError):
        print(f"Another instance of {app_title} is already running.")
        sys.exit(0)


def main():
    if not sys.platform.startswith("linux"):
        raise SystemExit("AI Interview Copilot is supported on Linux only.")

    parser = argparse.ArgumentParser(description="AI Interview Copilot")
    parser.add_argument(
        "--browser",
        action="store_true",
        help="Open the dashboard in the default browser instead of a desktop window.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Keep the console window visible for debug logs.",
    )
    parser.add_argument(
        "--overlay",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--toggle-window",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--disable-click-through",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args()

    if args.toggle_window and send_toggle_request():
        return
    if args.disable_click_through:
        send_disable_click_through_request()
        return

    if args.debug:
        os.environ["DEBUG_CONSOLE"] = "1"

    if args.overlay:
        from desktop_overlay import StealthDesktopOverlay

        StealthDesktopOverlay().run()
        return

    app_title = os.getenv("APP_NAME", "Bluetooth Driver").strip() or "Bluetooth Driver"
    instance_lock = acquire_single_instance_lock(app_title)

    host = os.getenv("HOST", "0.0.0.0")
    configured_port_value = os.getenv("PORT", "").strip()
    try:
        configured_port = int(configured_port_value) if configured_port_value else None
    except ValueError:
        configured_port = None
    listener_socket = bind_server_socket(host, configured_port)
    port = listener_socket.getsockname()[1]
    os.environ["PORT"] = str(port)
    # Use the Linux XDG data directory.
    _xdg = os.getenv("XDG_DATA_HOME", os.path.join(os.path.expanduser("~"), ".local", "share"))
    app_data_dir = os.path.join(_xdg, "InterviewTool")
    os.makedirs(app_data_dir, exist_ok=True)
    with open(os.path.join(app_data_dir, "server_port.txt"), "w", encoding="ascii") as port_file:
        port_file.write(str(port))

    # Generate or load pairing token for local network protection
    import secrets
    pairing_token = os.getenv("PAIRING_TOKEN", "").strip() or secrets.token_hex(16)
    os.environ["PAIRING_TOKEN"] = pairing_token

    dashboard_url = f"http://localhost:{port}/?token={pairing_token}"

    port_file_path = os.path.join(app_data_dir, "server_port.txt")
    try:
        if args.browser:
            webbrowser.open(dashboard_url)
            config = uvicorn.Config("server:app", host=host, port=port, reload=False, log_level="warning", access_log=False)
            uvicorn.Server(config).run(sockets=[listener_socket])
        else:
            start_desktop_window(dashboard_url, host, port, listener_socket)
    finally:
        if instance_lock:
            try:
                import fcntl
                fcntl.flock(instance_lock, fcntl.LOCK_UN)
                instance_lock.close()
            except Exception:
                pass
        listener_socket.close()
        try:
            with open(port_file_path, "r", encoding="ascii") as port_file:
                if port_file.read().strip() == str(port):
                    os.remove(port_file_path)
        except OSError:
            pass


if __name__ == "__main__":
    main()
