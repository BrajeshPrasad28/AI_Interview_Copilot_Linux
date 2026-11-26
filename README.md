# 🚀 AI Interview Copilot — Linux Edition

A covert, ultra-fast, dual-device AI interview assistant engineered for live technical interviews, coding challenges (LeetCode / HackerRank), and proctored hiring assessments.

Powered by a **Dual-Engine AI architecture (Groq + Gemini 2.5 Flash)** with **PulseAudio/PipeWire system audio loopback**, **real-time screen vision OCR**, and **stealth desktop overlay**.

Designed for Ubuntu and other Linux desktop distributions.

---

## 🌟 Key Highlights

- ⚡ **Sub-Second Answers (< 1s Response):** Uses Groq's high-throughput LPU models for instant answers, with automatic failover to Google Gemini 2.5 Flash.
- 🎧 **System Audio Loopback (0% Mic Bleed):** Captures audio from your speakers/headphones using a **PulseAudio / PipeWire monitor source**. Your microphone is never captured.
- 🧠 **Silero VAD (Neural Voice Activity Detection):** ONNX runtime engine with 0% PyTorch bloat. Detects when the interviewer finishes speaking.
- 📄 **Direct Resume Upload (.pdf / .docx / .txt):** Resume text injected into AI context for STAR-method answers.
- 🔄 **5-Turn Auto-Truncating Rolling Memory:** Keeps conversational context while pruning older turns for sub-1s latency.
- 🎙️ **Groq Whisper Transcription:** ~200ms speech-to-text with intelligent silence debouncing.
- 📸 **Screen Snip & Vision Solver (`Ctrl + Shift + S`):** OCR and coding solution for LeetCode, HackerRank, or system design diagrams.
- 🖥️ **Desktop Overlay:** Transparent always-on-top Linux desktop overlay.
- 📱 **Dual-Device Mobile Companion:** Solutions stream silently to your smartphone.
- 🔒 **Local Network Pairing Security:** All endpoints locked with cryptographically secure 16-byte pairing tokens.

---

## 🏗️ Linux platform notes

- The desktop window uses GTK and WebKit2.
- Application data is stored in `$XDG_DATA_HOME/InterviewTool`, falling back to `~/.local/share/InterviewTool`.
- Linux does not provide an application-level screen-capture exclusion feature; desktop overlays may appear in screen sharing or recording.

---

## ⚡ Quickstart Guide

### 1. Configure Your API Keys
```bash
cp .env.example .env
# Edit .env and add your keys:
#   GEMINI_API_KEY=your_gemini_api_key_here
#   GROQ_API_KEY=your_groq_api_key_here
```

### 2. Install System Dependencies (Ubuntu/Debian)
```bash
sudo apt install -y \
    portaudio19-dev \
    python3-gi python3-gi-cairo \
    gir1.2-gtk-3.0 gir1.2-webkit2-4.0 \
    libgirepository1.0-dev
```

**Fedora:**
```bash
sudo dnf install -y portaudio-devel gobject-introspection-devel webkit2gtk3-devel
```

**Arch Linux:**
```bash
sudo pacman -Sy portaudio python-gobject webkit2gtk
```

### 3. Run Automated Setup
```bash
bash setup.sh
```
This will create a virtualenv, install Python dependencies, and create a desktop shortcut.

### 4. Launch the App
```bash
# Desktop GUI window (default)
bash run.sh

# Browser mode (open in your default browser)
bash run.sh --browser

# Debug mode (keep terminal visible)
bash run.sh --debug
```

---

## 🔊 PulseAudio Loopback Setup

The app automatically finds your default sink's monitor source. To verify it works:
```bash
# List all audio sources — look for lines containing "monitor"
pactl list short sources | grep monitor

# Example output:
# 1  alsa_output.pci-0000_00_1f.3.analog-stereo.monitor  ...
```

If audio capture doesn't work:
1. Make sure PulseAudio or PipeWire-pulse is running: `systemctl --user status pipewire-pulse`
2. Play audio from any app — the monitor source only captures when audio is actively playing.

---

## ⌨️ Global Hotkeys (Active Anytime)

| Hotkey | Action |
|---|---|
| **Ctrl + Shift + S** | Snip screen & solve coding problem |
| **Ctrl + Shift + C** | Panic clear — wipe all displayed text |

---

## 🎯 Specialized Modes

1. **General Tech:** Natural developer responses.
2. **DSA & Coding:** Algorithm breakdown, complexity, clean code.
3. **System Design:** Architecture, components, scaling, trade-offs.
4. **HR / Behavioral:** STAR method, integrates with uploaded resume.

---

## 📁 Project Structure

```text
AI Interview Copilot (Linux)/
├── run.py                     # Main application runner & port manager
├── run.sh                     # 🐧 Linux launch script
├── setup.sh                   # 🐧 Linux automated setup wizard
├── stop_copilot.sh            # 🐧 Linux stop script
├── create_shortcut.py         # 🐧 Linux XDG .desktop shortcut creator
├── server.py                  # FastAPI server, security tokens & WebSocket hub
├── session_history.py         # Persistent five-session Q&A history
├── ai_engine.py               # Groq + Gemini dual-engine AI, Whisper STT
├── loopback_audio.py          # 🐧 PulseAudio/PipeWire monitor source loopback
├── document_processor.py      # PDF, DOCX, TXT resume text extraction
├── screen_snipper.py          # Screen capture engine (MSS / PIL)
├── hotkeys.py                 # Global keyboard hook (pynput)
├── desktop_overlay.py         # 🐧 Transparent Tkinter overlay (Linux GTK hints)
├── models/
│   └── silero_vad.onnx        # ONNX neural voice activity detector (1.8MB)
├── templates/
│   ├── index.html             # Host PC dashboard
│   ├── overlay.html           # Transparent web overlay
│   └── mobile.html            # Mobile companion web app
├── static/                    # CSS & JS assets
├── requirements.txt           # 🐧 Linux Python dependencies
├── .env.example               # Environment variables template
└── README.md                  # This file
```

---

## 📄 Session History

Session history is stored in `~/.local/share/InterviewTool/session_history.json`.
The dashboard sidebar's **History** view stores the five most recent interview sessions.

---

## 📄 License
For personal educational use and interview preparation.
