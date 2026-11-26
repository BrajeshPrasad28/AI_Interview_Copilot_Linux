"""Linux desktop overlay implemented with Tkinter."""

import json
import threading
import tkinter as tk
import websocket


class StealthDesktopOverlay:
    """
    Linux desktop overlay:
    - Transparent, always-on-top Tkinter window.
    - Excluded from taskbar (Linux WM hint).
    - WebSocket sync with Interview Copilot server.

    The overlay is not excluded from screen sharing or screen recording.
    """

    def __init__(self, ws_url=None):
        import os
        from dotenv import load_dotenv
        load_dotenv()
        port = os.getenv("PORT", "").strip()
        if not port:
            # Use the Linux XDG data directory.
            xdg_data = os.getenv("XDG_DATA_HOME", os.path.join(os.path.expanduser("~"), ".local", "share"))
            app_data_dir = os.path.join(xdg_data, "InterviewTool")
            try:
                with open(os.path.join(app_data_dir, "server_port.txt"), "r", encoding="ascii") as port_file:
                    port = port_file.read().strip()
            except OSError:
                port = "8585"
        token = os.getenv("PAIRING_TOKEN", "").strip()
        token_param = f"?token={token}" if token else ""
        self.ws_url = ws_url or f"ws://127.0.0.1:{port}/ws{token_param}"
        self.root = tk.Tk()
        self.root.title("AI Interview Copilot Overlay")
        self.root.geometry("450x600+100+100")
        self.root.attributes("-topmost", True)
        self.alpha = 0.61  # 61% transparent
        self.root.attributes("-alpha", self.alpha)
        self.root.configure(bg="#000000")

        # Make frameless
        self.root.overrideredirect(True)

        # Linux: skip taskbar via WM type hint
        self._apply_linux_window_hints()
        self.create_ui()
        self.bind_drag_events()
        self.bind_hotkeys()

        # Connect WebSocket in background
        self.ws_thread = threading.Thread(target=self.start_websocket_listener, daemon=True)
        self.ws_thread.start()

    def _apply_linux_window_hints(self):
        """Apply Linux-compatible window manager hints for overlay behaviour."""
        try:
            # Keep the overlay out of the taskbar and pager.
            self.root.wm_attributes("-type", "dock")
        except tk.TclError:
            # Some WMs/display servers don't support -type; fall back gracefully
            try:
                self.root.wm_overrideredirect(True)
            except Exception:
                pass
        try:
            # Ensure it stays on top even under compositing WMs
            self.root.wm_attributes("-topmost", True)
        except Exception:
            pass
        print("ℹ️  [LINUX OVERLAY] Window is on top. "
              "Note: screen-share capture exclusion is not available on Linux.")

    def create_ui(self):
        # Header / Titlebar for dragging
        self.header = tk.Frame(self.root, bg="#0a0a0c", height=34)
        self.header.pack(fill="x", side="top")

        self.title_label = tk.Label(
            self.header,
            text="● AI INTERVIEW COPILOT",
            bg="#0a0a0c",
            fg="#10b981",
            font=("DejaVu Sans", 9, "bold")
        )
        self.title_label.pack(side="left", padx=10, pady=6)

        # Controls in header
        self.btn_min = tk.Label(self.header, text=" — ", bg="#0a0a0c", fg="#94a3b8", cursor="hand2",
                                font=("DejaVu Sans", 9, "bold"))
        self.btn_min.pack(side="right", padx=6)
        self.btn_min.bind("<Button-1>", lambda e: self.toggle_minimize())

        self.btn_close = tk.Label(self.header, text=" ✕ ", bg="#0a0a0c", fg="#ef4444", cursor="hand2",
                                  font=("DejaVu Sans", 9, "bold"))
        self.btn_close.pack(side="right", padx=6)
        self.btn_close.bind("<Button-1>", lambda e: self.root.destroy())

        # Main Text Display
        self.text_frame = tk.Frame(self.root, bg="#000000")
        self.text_frame.pack(fill="both", expand=True, padx=6, pady=6)

        self.text_display = tk.Text(
            self.text_frame,
            bg="#0d0d12",
            fg="#f8fafc",
            insertbackground="#10b981",
            font=("DejaVu Sans Mono", 10),
            wrap="word",
            bd=0,
            padx=12,
            pady=12
        )
        self.text_display.pack(fill="both", expand=True)

        self.text_display.tag_configure("bold",   font=("DejaVu Sans", 10, "bold"), foreground="#38bdf8")
        self.text_display.tag_configure("code",   font=("DejaVu Sans Mono", 9),    background="#050811", foreground="#a5f3fc")
        self.text_display.tag_configure("green",  foreground="#10b981",             font=("DejaVu Sans", 10, "bold"))
        self.text_display.tag_configure("muted",  foreground="#64748b",             font=("DejaVu Sans", 9, "italic"))

        self.text_display.insert("end", "Waiting for question or screen snip (Ctrl+Shift+S)...\n", "muted")
        self.text_display.config(state="disabled")

        # Bottom Bar
        self.footer = tk.Frame(self.root, bg="#0a0a0c", height=24)
        self.footer.pack(fill="x", side="bottom")

        self.status_label = tk.Label(
            self.footer,
            text="Ctrl+Shift+S: Snip | Ctrl+Shift+C: Clear | Ctrl+[/]: Opacity",
            bg="#0a0a0c",
            fg="#64748b",
            font=("DejaVu Sans", 8)
        )
        self.status_label.pack(side="left", padx=10, pady=3)

    def bind_hotkeys(self):
        """Bind in-window opacity hotkeys."""
        self.root.bind("<Control-bracketleft>",  lambda e: self.adjust_alpha(-0.08))
        self.root.bind("<Control-bracketright>", lambda e: self.adjust_alpha(0.08))

    def adjust_alpha(self, delta):
        self.alpha = max(0.15, min(1.0, round(self.alpha + delta, 2)))
        self.root.attributes("-alpha", self.alpha)
        pct = int(self.alpha * 100)
        self.status_label.config(text=f"Glass Transparency: {pct}% | Ctrl+Shift+S: Snip | Ctrl+Shift+C: Clear")

    def bind_drag_events(self):
        """Allow dragging the frameless window."""
        self.header.bind("<Button-1>", self.start_move)
        self.header.bind("<B1-Motion>", self.do_move)
        self.title_label.bind("<Button-1>", self.start_move)
        self.title_label.bind("<B1-Motion>", self.do_move)

    def start_move(self, event):
        self.x = event.x
        self.y = event.y

    def do_move(self, event):
        deltax = event.x - self.x
        deltay = event.y - self.y
        x = self.root.winfo_x() + deltax
        y = self.root.winfo_y() + deltay
        self.root.geometry(f"+{x}+{y}")

    def toggle_minimize(self):
        if self.text_frame.winfo_ismapped():
            self.text_frame.pack_forget()
            self.footer.pack_forget()
            self.root.geometry(f"{self.root.winfo_width()}x34")
        else:
            self.text_frame.pack(fill="both", expand=True, padx=8, pady=8)
            self.footer.pack(fill="x", side="bottom")
            self.root.geometry(f"{self.root.winfo_width()}x600")

    def prepend_answer(self, answer_text: str, question: str = "", speaker: str = ""):
        """Prepend new answer at the top in descending order (recent always on top)."""
        def _update():
            from datetime import datetime
            timestamp = datetime.now().strftime("%I:%M:%S %p")
            speaker_tag = ""
            if speaker == "interviewer":
                speaker_tag = " • 🎧 Interviewer"
            elif speaker == "candidate":
                speaker_tag = " • 📱 Candidate"
            elif speaker == "screen":
                speaker_tag = " • 📸 Screen Vision"

            header = f"\n{'═'*45}\n[⚡ ANSWER • {timestamp}{speaker_tag}]\n"
            if question:
                header += f"Q: \"{question}\"\n{'─'*45}\n"
            entry = f"{header}{answer_text.strip()}\n"

            self.text_display.config(state="normal")
            self.text_display.insert("1.0", entry)
            self.text_display.config(state="disabled")
            self.text_display.see("1.0")
        self.root.after(0, _update)

    def prepend_notice(self, notice_text: str):
        """Prepend a brief system notice at the top of the feed."""
        def _update():
            from datetime import datetime
            timestamp = datetime.now().strftime("%I:%M:%S %p")
            entry = f"\n[{timestamp}] {notice_text}\n"
            self.text_display.config(state="normal")
            self.text_display.insert("1.0", entry, "muted")
            self.text_display.config(state="disabled")
            self.text_display.see("1.0")
        self.root.after(0, _update)

    def clear_text(self):
        """Clear all content when panic clear is pressed."""
        def _update():
            self.text_display.config(state="normal")
            self.text_display.delete("1.0", "end")
            self.text_display.insert("end", "✨ Cleared. Listening for next question...\n")
            self.text_display.config(state="disabled")
        self.root.after(0, _update)

    def start_websocket_listener(self):
        """Connect to local backend and stream updates."""
        def on_message(ws, message):
            try:
                data = json.loads(message)
                msg_type = data.get("type")
                if msg_type == "new_answer" and data.get("data", {}).get("success"):
                    ans = data["data"]["answer"]
                    q = data["data"].get("question", "")
                    spk = data["data"].get("speaker")
                    if not spk:
                        if data["data"].get("is_screenshot"):
                            spk = "screen"
                        elif data["data"].get("is_audio"):
                            spk = "interviewer"
                        else:
                            spk = "candidate"
                    self.prepend_answer(ans, question=q, speaker=spk)
                elif msg_type == "resume_updated":
                    fn = data.get("filename", "Candidate Resume")
                    self.prepend_notice(f"📄 Resume Context Loaded: {fn}")
                elif msg_type == "history_cleared":
                    self.prepend_notice("🧹 Rolling Memory Cleared (5-turn context reset)")
                elif msg_type == "panic_clear":
                    self.clear_text()
            except Exception as e:
                print("Overlay WS Error:", e)

        def on_error(ws, error):
            pass

        def on_close(ws, close_status_code, close_msg):
            pass

        ws = websocket.WebSocketApp(
            self.ws_url,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close
        )
        ws.run_forever()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    overlay = StealthDesktopOverlay()
    overlay.run()
