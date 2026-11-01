import os
import sys
import socket
import webbrowser
import argparse
import threading
import time
import uvicorn
from dotenv import load_dotenv

APP_DATA_DIR = os.path.join(os.getenv("APPDATA", os.path.expanduser("~")), "InterviewTool")
os.makedirs(APP_DATA_DIR, exist_ok=True)
LOG_FILE_PATH = os.path.join(APP_DATA_DIR, "app.log")
CRASH_LOG_PATH = os.path.join(APP_DATA_DIR, "crash.log")

# In pythonw.exe, stdout and stderr are None; redirect to app.log so errors are never lost
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
load_dotenv()

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

def start_desktop_window(dashboard_url: str, host: str, port: int, listener_socket: socket.socket):
    try:
        import webview
    except ImportError as exc:
        listener_socket.close()
        raise RuntimeError(
            "Desktop window support is missing. Install dependencies with "
            "'pip install -r requirements.txt' and try again."
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

    app_title = os.getenv("APP_NAME", "Realtek HD Audio Universal Service").strip() or "Realtek HD Audio Universal Service"
    try:
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.kernel32.SetConsoleTitleW(app_title)
            # Auto-hide terminal window so only the GUI window is visible (0% terminal footprint)
            if not os.getenv("DEBUG_CONSOLE"):
                hwnd = ctypes.windll.kernel32.GetConsoleWindow()
                if hwnd:
                    ctypes.windll.user32.ShowWindow(hwnd, 0)  # 0 = SW_HIDE
    except Exception:
        pass

    class DesktopApi:
        def __init__(self):
            self._window = None
            self._hwnd = None
            # Default alpha matching default background opacity (61% = ~155 alpha)
            self.current_alpha = 155
            self.click_through = False
            self._click_through_timer = None

        def minimize(self):
            if self._window:
                self._window.minimize()

        def close(self):
            if self._window:
                self._window.destroy()

        def _apply_layered_alpha(self):
            if not self._hwnd:
                return
            try:
                import ctypes
                GWL_EXSTYLE = -20
                WS_EX_LAYERED = 0x00080000
                style = ctypes.windll.user32.GetWindowLongW(self._hwnd, GWL_EXSTYLE)
                if not (style & WS_EX_LAYERED):
                    ctypes.windll.user32.SetWindowLongW(self._hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED)
                ctypes.windll.user32.SetLayeredWindowAttributes(self._hwnd, 0, self.current_alpha, 0x00000002)
            except Exception as e:
                print(f"Error applying layered alpha: {e}")

        def set_opacity(self, alpha):
            try:
                val = max(40, min(255, int(alpha)))
                self.current_alpha = val
                self._apply_layered_alpha()
                return self.current_alpha
            except Exception as e:
                print(f"Error setting opacity: {e}")
                return self.current_alpha

        def adjust_opacity(self, delta):
            return self.set_opacity(self.current_alpha + int(delta))

        def get_opacity(self):
            return self.current_alpha

        def toggle_click_through(self):
            try:
                import ctypes
                GWL_EXSTYLE = -20
                WS_EX_TRANSPARENT = 0x00000020
                self.click_through = not self.click_through
                if self._hwnd:
                    style = ctypes.windll.user32.GetWindowLongW(self._hwnd, GWL_EXSTYLE)
                    if self.click_through:
                        style |= WS_EX_TRANSPARENT
                    else:
                        style &= ~WS_EX_TRANSPARENT
                    ctypes.windll.user32.SetWindowLongW(self._hwnd, GWL_EXSTYLE, style)
                # Auto-disable safety: if click-through is on, schedule auto-off after 30s
                if self._click_through_timer:
                    self._click_through_timer.cancel()
                    self._click_through_timer = None
                if self.click_through:
                    self._click_through_timer = threading.Timer(30.0, self._auto_disable_click_through)
                    self._click_through_timer.daemon = True
                    self._click_through_timer.start()
                return self.click_through
            except Exception as e:
                print(f"Error toggling click-through: {e}")
                return False

        def _auto_disable_click_through(self):
            """Safety: automatically disable click-through after timeout to prevent lockout."""
            if self.click_through:
                try:
                    import ctypes
                    GWL_EXSTYLE = -20
                    WS_EX_TRANSPARENT = 0x00000020
                    self.click_through = False
                    if self._hwnd:
                        style = ctypes.windll.user32.GetWindowLongW(self._hwnd, GWL_EXSTYLE)
                        style &= ~WS_EX_TRANSPARENT
                        ctypes.windll.user32.SetWindowLongW(self._hwnd, GWL_EXSTYLE, style)
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

    def _apply_stealth_flags(title: str):
        import ctypes

        WDA_EXCLUDEFROMCAPTURE = 0x00000011
        GWL_EXSTYLE = -20
        WS_EX_TOOLWINDOW = 0x00000080
        WS_EX_APPWINDOW = 0x00040000

        hwnd = None
        try:
            if hasattr(desktop_api._window, 'native') and desktop_api._window.native:
                hwnd = int(desktop_api._window.native.Handle.ToInt64())
        except Exception:
            pass

        if not hwnd:
            # Fallback: Safely locate window handle by title
            for _ in range(25):
                hwnd = ctypes.windll.user32.FindWindowW(None, title)
                if hwnd:
                    break
                time.sleep(0.2)

        if not hwnd:
            print("⚠️ Window HWND not found for stealth flags.")
            return

        desktop_api._hwnd = hwnd

        # 0. Apply initial layered window transparency immediately on startup
        desktop_api._apply_layered_alpha()

        # 1. Screen-share Invisibility (Zoom, Teams, Meet, OBS, Snipping Tool, Discord)
        try:
            res = ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)
            if res:
                print(f"🔒 [STEALTH ACTIVE] Window '{title}' is EXCLUDED from screen capture.")
        except Exception as e:
            print(f"Screen capture exclusion warning: {e}")

        # 2. Hide native window border outline
        try:
            DWMWA_BORDER_COLOR = 34
            DWMWA_COLOR_NONE = 0xFFFFFFFE
            color_val = ctypes.c_uint32(DWMWA_COLOR_NONE)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_BORDER_COLOR, ctypes.byref(color_val), ctypes.sizeof(color_val))
        except Exception:
            pass

        # 3. Soft toolwindow style (exclude from Alt+Tab without blocking frame messages)
        try:
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, (style & ~WS_EX_APPWINDOW) | WS_EX_TOOLWINDOW)
        except Exception:
            pass

        # 4. Register global hotkey Ctrl+M safely
        threading.Thread(target=_register_global_hotkey, args=(desktop_api,), daemon=True).start()

    def _register_global_hotkey(api):
        """Register Ctrl+M as a global hotkey so the user can always toggle click-through,
        even when WS_EX_TRANSPARENT is active and the window ignores mouse events."""
        try:
            import ctypes
            from ctypes import wintypes

            MOD_CONTROL = 0x0002
            MOD_NOREPEAT = 0x4000
            VK_M = 0x4D
            HOTKEY_ID = 0x0001
            WM_HOTKEY = 0x0312

            user32 = ctypes.windll.user32
            # Register Ctrl+M globally
            if not user32.RegisterHotKey(None, HOTKEY_ID, MOD_CONTROL | MOD_NOREPEAT, VK_M):
                print("⚠️ Could not register Ctrl+M global hotkey (may be in use by another app).")
                return

            print("✅ Global hotkey Ctrl+M registered for click-through toggle.")

            msg = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
                if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                    is_active = api.toggle_click_through()
                    # Sync frontend button state + show toast safely
                    if api._window:
                        try:
                            js_state = 'true' if is_active else 'false'
                            toast_msg = "Click-Through: ON — Press Ctrl+M to disable (auto-off in 30s)" if is_active else "Click-Through: Off (Normal clicks)"
                            api._window.evaluate_js(
                                f"document.querySelectorAll('.btn-click-through').forEach(b => b.classList.toggle('active', {js_state}));"
                                f"showStealthToast('{toast_msg}');"
                            )
                        except Exception:
                            pass

            user32.UnregisterHotKey(None, HOTKEY_ID)
        except Exception as e:
            print(f"Global hotkey registration error: {e}")

    def on_gui_ready():
        """Called safely once pywebview's native message loop has initialized and page is loaded."""
        try:
            if hasattr(desktop_api._window, 'events') and hasattr(desktop_api._window.events, 'loaded'):
                desktop_api._window.events.loaded.wait(timeout=10)
            elif hasattr(desktop_api._window, 'events') and hasattr(desktop_api._window.events, 'shown'):
                desktop_api._window.events.shown.wait(timeout=10)
            time.sleep(0.3)
            _apply_stealth_flags(app_title)
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
        webview.start(on_gui_ready, gui="edgechromium")
    finally:
        server.should_exit = True
        server_thread.join(timeout=10)
        if server_thread.is_alive():
            print("Warning: the local web server did not shut down within 10 seconds.")


def acquire_single_instance_lock(app_title: str):
    """Ensure only one instance runs at a time.
    If already running, bring existing window to front and exit gracefully."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        MUTEX_NAME = "Local\\AI_Interview_Copilot_SingleInstance_Mutex"
        ERROR_ALREADY_EXISTS = 183
        mutex = ctypes.windll.kernel32.CreateMutexW(None, True, MUTEX_NAME)
        if ctypes.windll.kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
            try:
                hwnd = ctypes.windll.user32.FindWindowW(None, app_title)
                if hwnd:
                    SW_RESTORE = 9
                    ctypes.windll.user32.ShowWindow(hwnd, SW_RESTORE)
                    ctypes.windll.user32.SetForegroundWindow(hwnd)
            except Exception:
                pass
            if mutex:
                ctypes.windll.kernel32.CloseHandle(mutex)
            sys.exit(0)
        return mutex
    except Exception:
        return None


def main():
    parser = argparse.ArgumentParser(description="AI Interview Copilot desktop app")
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
    args = parser.parse_args()

    if args.debug:
        os.environ["DEBUG_CONSOLE"] = "1"

    if args.overlay:
        from desktop_overlay import StealthDesktopOverlay

        StealthDesktopOverlay().run()
        return

    app_title = os.getenv("APP_NAME", "Realtek HD Audio Universal Service").strip() or "Realtek HD Audio Universal Service"
    instance_mutex = acquire_single_instance_lock(app_title)

    try:
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.kernel32.SetConsoleTitleW(app_title)
            # Auto-hide terminal window so only the GUI window is visible (0% terminal footprint)
            if not os.getenv("DEBUG_CONSOLE"):
                hwnd = ctypes.windll.kernel32.GetConsoleWindow()
                if hwnd:
                    ctypes.windll.user32.ShowWindow(hwnd, 0)  # 0 = SW_HIDE
    except Exception:
        pass

    host = os.getenv("HOST", "0.0.0.0")
    configured_port_value = os.getenv("PORT", "").strip()
    try:
        configured_port = int(configured_port_value) if configured_port_value else None
    except ValueError:
        configured_port = None
    listener_socket = bind_server_socket(host, configured_port)
    port = listener_socket.getsockname()[1]
    os.environ["PORT"] = str(port)
    app_data_dir = os.path.join(os.getenv("APPDATA", os.path.expanduser("~")), "InterviewTool")
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
        if instance_mutex:
            try:
                import ctypes
                ctypes.windll.kernel32.CloseHandle(instance_mutex)
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
