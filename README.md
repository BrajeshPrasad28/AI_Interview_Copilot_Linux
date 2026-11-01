# 🚀  Realtek HD Audio Universal Service ("Interview Cracked")

A covert, ultra-fast, dual-device AI interview assistant engineered for live technical interviews, coding challenges (LeetCode / HackerRank), and proctored hiring assessments (Accenture, Mercer Mettl, HireVue, Talview).

Powered by a **Dual-Engine AI architecture (Groq + Gemini 2.5 Flash)** with **WASAPI loopback interviewer audio isolation**, **real-time screen vision OCR**, and **stealth desktop overlay**.

---

## 🌟 Key Highlights

- ⚡ **Sub-Second Answers (< 1s Response):** Uses Groq's high-throughput LPU models (`openai/gpt-oss-120b`, `qwen/qwen3.8-27b`) for instant answers, with automatic silent failover to Google Gemini 2.5 Flash.
- 🎧 **Interviewer Voice Only Mode (0% Mic Bleed):** Captures audio directly from your headphones/speakers using Windows WASAPI Loopback. Your microphone is completely muted by default, so your voice is never captured or mistaken for a question.
- 🧠 **Silero VAD (Neural Voice Activity Detection):** Powered by an ONNX runtime engine (`models/silero_vad.onnx`, ~1.8MB) with 0% PyTorch bloat. Automatically detects when the interviewer finishes speaking with intelligent silence debouncing and RMS energy fallback.
- 📄 **Direct Resume Upload (.pdf / .docx / .txt):** Candidate can upload their actual resume from the PC dashboard or mobile phone. Extracted text is injected directly into the AI context for authentic STAR-method and background answers.
- 🔄 **5-Turn Auto-Truncating Rolling Memory:** Automatically maintains conversational context for follow-up questions while pruning older turns after 5 turns to guarantee API latency stays strictly under 1 second.
- 🏷️ **Speaker Diarization:** Real-time visual tagging across overlays and phone companion (`🎧 Interviewer` vs `📱 Candidate` vs `📸 Screen Vision`).
- 🎙️ **Groq Whisper Transcription:** High-accuracy, ~200ms speech-to-text with intelligent silence debouncing and question filtering.
- 📸 **Screen Snip & Vision Solver (`Ctrl + Shift + S`):** Instant OCR and coding solution extraction for LeetCode, HackerRank, or system design diagrams.
- 🪟 **Stealth Transparent Overlay:** Excluded from Zoom, Microsoft Teams, and Google Meet screen shares using native Windows `SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)` and `WS_EX_TOOLWINDOW` (hidden from Alt+Tab).
- 🎭 **Process Name (`Realtek HD Audio Universal Service`):** Executable and builds the standalone Interview Practice Copilot executable.
- 📱 **Dual-Device Mobile Companion:** For proctored tests that lock the screen, solutions stream silently to your smartphone placed beneath your webcam.
- 🔒 **Local Network Pairing Security:** All endpoints and WebSockets are locked with cryptographically secure 16-byte pairing tokens.

---

## 🏗️ How It Works (Architecture)

```
                    +------------------------------------+
                    |        INTERVIEW SYSTEM AUDIO      |
                    |   (Interviewer Voice via Headset)  |
                    +-----------------+------------------+
                                      | (WASAPI Loopback Capture)
                                      v
+-------------------------------------+----------------------------------+
|                        Realtek HD Audio Universal Service HUB                         |
|                                                                        |
|  [Groq Whisper / Audio Engine]                                         |
|      Transcribes interviewer question in ~200ms                        |
|                                                                        |
|  [Dual-Engine AI Reasoning]                                            |
|      Primary: Groq (0.5s - 1.2s instant natural spoken answer)         |
|      Auto-Failover: Gemini 2.5 Flash (Rate-limit & quota protection)   |
|                                                                        |
|  [Screen Vision Engine]                                                |
|      Ctrl+Shift+S captures & solves LeetCode/Code screens via Gemini   |
+---------------------+----------------------------------+---------------+
                      |                                  |
                      | WebSocket (Secure Token)         | WebSocket
                      v                                  v
       +-------------------------------+   +-----------------------------+
       |   TRANSPARENT DESKTOP OVERLAY |   |   MOBILE COMPANION (Phone)  |
       |                               |   |                             |
       | - Screen-share invisible      |   | - Upright below webcam      |
       | - Translucent glass design    |   | - 0% PC screen footprint    |
       | - Descending answer history   |   | - 1-tap Blackout mode (🕶️)  |
       | - Ultra-thin scrollbar        |   | - Font scaling (A- / A+)    |
       +-------------------------------+   +-----------------------------+
```

---

## ⚡ Quickstart Guide

### 1. Configure Your API Keys
Create a `.env` file in the project root (or copy from `.env.example`):

```env
# Google Gemini API Key (Free from https://aistudio.google.com/)
GEMINI_API_KEY=your_gemini_api_key_here

# Groq API Key (Free ultra-fast key from https://console.groq.com/)
GROQ_API_KEY=your_groq_api_key_here

# Default Topic Mode (general | coding | system_design | behavioral)
DEFAULT_MODE=general
DEFAULT_CODING_LANG=python
# Optional: set PORT to request a fixed port; otherwise the OS selects an available port silently.
```

> [!TIP]
> Both Groq and Gemini keys can also be added or updated live in the Web UI **Settings (⚙️)** modal.

---

### 2. Launch the Software
You can start the tool in any of these ways:

- **Desktop Shortcut:** Double-click the **`Realtek HD Audio Universal Service`** icon on your Desktop. The dashboard opens in an app window, not a separate browser.
- **Batch Launcher:** Double-click `run.bat` to open the desktop app window.
- **Command Line:**
  ```powershell
  .\.venv\Scripts\python run.py
  ```

To use the desktop dashboard in your default browser instead, run:

```powershell
.\.venv\Scripts\python run.py --browser
```

The desktop app uses an embedded WebView window for the PC dashboard. Its local server runs in the background while the window is open and shuts down when you close the app. To pair a phone, scan the QR code from the dashboard or use **Copy Phone Link** and open that link on the phone; there is no need to open the mobile page on the laptop. **Open Desktop Overlay** starts the separate native Windows overlay window.

The packaged desktop app requires the Microsoft Edge WebView2 Runtime, which is normally already installed on modern Windows systems.

---

## 💻 Installing on Your Laptop or a Friend's Laptop

### 🎯 1-Click Desktop Icon Setup
To create or restore the **`Realtek HD Audio Universal Service`** desktop shortcut with the custom cyber AI headset icon:
- Simply double-click **`Create_Desktop_Icon.bat`**.

### 🤝 Automated Setup for a Friend's PC
To install the tool on a friend's laptop without manual setup:
1. Share the project folder (or zip) with your friend.
2. On their laptop, double-click **`setup_friend_pc.bat`**.
3. The wizard will:
   - Detect or install Python automatically via Windows `winget`.
   - Create the isolated virtual environment and install dependencies.
   - Install the embedded desktop window dependency.
   - Create the **Desktop Shortcut** with the custom icon on their Desktop.

### 📦 Compiling into a Standalone Executable (`.exe`)
To package the app into a standalone Windows software that requires **no Python** installed:
1. Double-click **`build_exe.bat`**.
2. PyInstaller will compile all files, audio engines, and templates into:
   ```text
   dist\Realtek HD Audio Universal Service\Realtek HD Audio Universal Service.exe
   ```
3. You can zip that folder and run it directly on any Windows PC!

---

## ⌨️ Global Hotkeys (Active Anytime)

| Hotkey | Action | Description |
|---|---|---|
| **Ctrl + Shift + S** | **Snip Screen & Solve** | Instantly captures primary screen, reads coding problem/diagram, and streams optimal solution. |
| **Ctrl + Shift + C** | **Panic Clear** | Instantly wipes all displayed text and answers from all screens. |

---

## 🎯 Specialized Modes

1. **General Tech (Default):** Natural, conversational developer responses. Formatted as a spoken summary followed by key technical highlights (bullet points only where relevant).
2. **DSA & Coding:** Full algorithm breakdown, optimal time & space complexity ($O(N)$, $O(1)$), clean idiomatic code, and edge case coverage.
3. **System Design:** Architecture overview, component breakdown, database choice, scaling & caching strategies, and trade-offs.
4. **HR / Behavioral:** Grounded in the **STAR method** (Situation, Task, Action, Result). Integrates with your uploaded resume so answers reflect your real work experience.

---

## Session Q&A History

The dashboard sidebar's **History** view stores the five most recent interview sessions in `%APPDATA%\InterviewTool\session_history.json`. Each session includes its profile name, date and time, and the full list of successful question-and-answer pairs. Expand a session to review its Q&A or delete that session. Starting a new session after ending the current interview adds it to the top; older sessions beyond the five-session limit are removed automatically. This saved history is separate from the AI's rolling five-turn context.

## 📁 Project Structure

```text
Interview Tool/
├── app_icon.ico               # Custom multi-resolution AI Copilot Windows icon
├── run.py                     # Main application runner & port manager
├── run.bat                    # Double-click console launcher
├── Create_Desktop_Icon.bat    # 1-click script to place icon on Windows Desktop
├── setup_friend_pc.bat        # Automated setup wizard for friend's PC
├── build_exe.bat              # PyInstaller standalone executable builder (Realtek HD Audio Universal Service disguise)
├── stop_copilot.bat           # 1-click script to stop background processes
├── server.py                  # FastAPI server, security tokens & WebSocket hub
├── session_history.py         # Persistent five-session Q&A history
├── ai_engine.py               # Groq + Gemini dual-engine AI reasoning, Whisper STT & 5-turn memory
├── loopback_audio.py          # Windows WASAPI loopback audio listener + Silero VAD ONNX
├── document_processor.py      # PDF, DOCX, DOC, TXT Resume text extraction (pypdf/docx)
├── screen_snipper.py          # Screen capture engine (MSS / PIL)
├── hotkeys.py                 # Windows global keyboard hook manager (pynput)
├── desktop_overlay.py         # Native Tkinter stealth overlay (WDA_EXCLUDEFROMCAPTURE + ToolWindow)
├── models/
│   └── silero_vad.onnx        # ONNX neural voice activity detector (1.8MB, 0% PyTorch bloat)
├── templates/
│   ├── index.html             # Host PC dashboard with pairing QR code & resume upload
│   ├── overlay.html           # Transparent web overlay with descending answer feed
│   └── mobile.html            # Mobile companion web app
├── static/
│   ├── css/mobile.css         # Mobile styling and dark mode
│   └── js/mobile.js           # Companion WebSockets, audio meter & speech logic
├── requirements.txt           # Python dependency manifest
├── .env.example               # Environment variables template
└── README.md                  # Complete documentation
```

### HTML Templates

The dashboard and desktop overlay render AI questions, model names, and error messages in the browser. These values are HTML-escaped before insertion so text returned by services is displayed as text instead of interpreted as markup. This uses built-in browser JavaScript and does not add a Python dependency.

---

## 🛡️ Proctored Exam & Screen-Share Best Practices

1. **For Zoom / Google Meet / Teams Interviews:**
   - Click **Open Desktop Overlay** in the dashboard to launch the native Windows overlay.
   - It uses Windows `SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)` to request exclusion from screen capture.
2. **For Proctored Assessments (Mercer Mettl, HireVue, Safe Exam Browser, Talview):**
   - **Do NOT open any overlay or extra windows on your PC.**
   - Open the **Mobile Companion (`/mobile`)** on your smartphone.
   - Prop your phone vertically directly below your laptop webcam.
   - Your PC remains 100% compliant with full-screen lock and window focus detection.
   - Use `Ctrl+Shift+S` to silently snip and solve coding questions directly to your phone.

---

## 📄 License
For personal educational use and interview preparation.
