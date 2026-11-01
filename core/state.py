import os
import io
import re
import json
import socket
import logging
import secrets
import threading
import asyncio
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional

from fastapi import Request, HTTPException, WebSocket
from dotenv import load_dotenv

from ai_engine import InterviewAIEngine
from screen_snipper import ScreenSnipper
from hotkeys import GlobalHotkeyManager
from loopback_audio import SystemAudioLoopback
from session_history import SessionHistory, question_from_result

# Load environment
load_dotenv()

logger = logging.getLogger("server")

BASE_DIR = getattr(sys, '_MEIPASS', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

APP_DATA_DIR = os.path.join(os.getenv("APPDATA", os.path.expanduser("~")), "InterviewTool")
APP_PREFERENCES_PATH = os.path.join(APP_DATA_DIR, "preferences.json")
SESSION_HISTORY_PATH = os.path.join(APP_DATA_DIR, "session_history.json")
RESUME_DATA_PATH = os.path.join(APP_DATA_DIR, "saved_resume.json")
NOTES_PATH = os.path.join(APP_DATA_DIR, "notes.json")
CREDITS_PATH = os.path.join(APP_DATA_DIR, "credits.json")

session_history = SessionHistory(SESSION_HISTORY_PATH, max_sessions=5)

DEFAULT_PREFERENCES = {
    "profile_name": "",
    "profile_email": "",
    "profile_phone": "",
    "custom_instructions": "",
    "background_opacity": 61,
    "font_opacity": 100,
    "response_font_size": 15,
    "show_screen_capture_button": True,
    "screen_quality": 90,
    "neural_vad_enabled": True,
    "vad_mode": "smart",
    "google_search_enabled": False,
}

def load_app_preferences() -> Dict[str, Any]:
    try:
        with open(APP_PREFERENCES_PATH, "r", encoding="utf-8") as preferences_file:
            saved = json.load(preferences_file)
        return {**DEFAULT_PREFERENCES, **{key: value for key, value in saved.items() if key in DEFAULT_PREFERENCES}}
    except (OSError, ValueError, TypeError, AttributeError):
        return DEFAULT_PREFERENCES.copy()

def save_app_preferences(preferences: Dict[str, Any]) -> None:
    os.makedirs(APP_DATA_DIR, exist_ok=True)
    temporary_path = APP_PREFERENCES_PATH + ".tmp"
    with open(temporary_path, "w", encoding="utf-8") as preferences_file:
        json.dump(preferences, preferences_file, ensure_ascii=False, indent=2)
    os.replace(temporary_path, APP_PREFERENCES_PATH)

def load_saved_resume() -> Dict[str, Any]:
    try:
        with open(RESUME_DATA_PATH, "r", encoding="utf-8") as resume_file:
            data = json.load(resume_file)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def save_saved_resume(filename: str, text: str) -> None:
    os.makedirs(APP_DATA_DIR, exist_ok=True)
    data = {
        "filename": filename or "resume.pdf",
        "text": text,
        "char_count": len(text),
        "updated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    }
    temporary_path = RESUME_DATA_PATH + ".tmp"
    with open(temporary_path, "w", encoding="utf-8") as resume_file:
        json.dump(data, resume_file, ensure_ascii=False, indent=2)
    os.replace(temporary_path, RESUME_DATA_PATH)

def delete_saved_resume() -> None:
    try:
        if os.path.exists(RESUME_DATA_PATH):
            os.remove(RESUME_DATA_PATH)
    except Exception as e:
        logger.warning(f"Error removing resume file: {e}")

DEFAULT_STARTER_NOTES = [
    {
        "id": "note_starter_intro",
        "title": "📌 Self Introduction & Pitch",
        "content": "Hi, I am a software engineer focused on building robust, scalable applications.\n\nKey Highlights:\n• Core Strengths: Full-stack architecture, clean code, algorithmic problem-solving\n• Impact: Built high-throughput microservices and responsive user interfaces\n• Passion: Continuous learning, system reliability, and product quality",
        "created_at": "2026-10-24T10:00:00",
        "updated_at": "2026-10-24T10:00:00"
    },
    {
        "id": "note_starter_star",
        "title": "⭐ STAR Method Template",
        "content": "• Situation: The business context or technical challenge faced\n• Task: My specific goal and responsibility\n• Action: Decisions made, technical tradeoffs, and code implemented\n• Result: Metrics improved (latency, cost, throughput), business outcome, and key learnings",
        "created_at": "2026-10-24T10:00:00",
        "updated_at": "2026-10-24T10:00:00"
    }
]

def load_app_notes() -> List[Dict[str, Any]]:
    try:
        if os.path.exists(NOTES_PATH):
            with open(NOTES_PATH, "r", encoding="utf-8") as notes_file:
                loaded = json.load(notes_file)
            if isinstance(loaded, list):
                return loaded
        else:
            save_app_notes(DEFAULT_STARTER_NOTES)
            return list(DEFAULT_STARTER_NOTES)
    except Exception as exc:
        logger.warning("Could not read notes: %s", exc)
    return []

def save_app_notes(notes: List[Dict[str, Any]]) -> None:
    os.makedirs(APP_DATA_DIR, exist_ok=True)
    temp_path = NOTES_PATH + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as notes_file:
        json.dump(notes, notes_file, ensure_ascii=False, indent=2)
    os.replace(temp_path, NOTES_PATH)

def load_app_credits() -> Dict[str, Any]:
    try:
        if os.path.exists(CREDITS_PATH):
            with open(CREDITS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and "balance" in data and "transactions" in data:
                    changed = False
                    for tx in data.get("transactions", []):
                        desc = tx.get("description", "")
                        if tx.get("type") == "credit":
                            if "voucher" in desc.lower() or "starter" in desc.lower() or "bonus" in desc.lower() or "(" in desc:
                                tx["description"] = "Credit Points Added"
                                changed = True
                        elif tx.get("type") == "debit":
                            if "voucher" in desc.lower() or "ai q" in desc.lower() or "(" in desc:
                                tx["description"] = "Credit Points Used"
                                changed = True
                    if changed:
                        save_app_credits(data)
                    return data
    except Exception as exc:
        logger.warning("Could not read credits data: %s", exc)

    starter_data = {
        "balance": 100,
        "redeemed_codes": ["WELCOME-100-STARTER"],
        "transactions": [
            {
                "id": "TXN-10001",
                "type": "credit",
                "amount": 100,
                "balance_after": 100,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "code": "WELCOME-100-STARTER",
                "expiry_date": (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d"),
                "description": "Credit Points Added",
                "user_name": current_state.get("profile_name") or "User",
                "user_email": current_state.get("profile_email") or "user@example.com",
                "user_phone": current_state.get("profile_phone") or "N/A"
            }
        ]
    }
    save_app_credits(starter_data)
    return starter_data

def save_app_credits(credits_data: Dict[str, Any]) -> None:
    try:
        os.makedirs(APP_DATA_DIR, exist_ok=True)
        try:
            temp_path = CREDITS_PATH + ".tmp"
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(credits_data, f, ensure_ascii=False, indent=2)
            os.replace(temp_path, CREDITS_PATH)
        except Exception:
            with open(CREDITS_PATH, "w", encoding="utf-8") as f:
                json.dump(credits_data, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        logger.error("Error saving credits: %s", exc)

# Live Session Metrics Tracker
session_metrics: Dict[str, Any] = {
    "started_at": datetime.now(),
    "total_snaps": 0,
    "qa_count": 0,
}

def reset_session_metrics() -> None:
    session_metrics["started_at"] = datetime.now()
    session_metrics["total_snaps"] = 0
    session_metrics["qa_count"] = 0

def get_session_duration_str() -> str:
    try:
        secs = max(0, int((datetime.now() - session_metrics["started_at"]).total_seconds()))
        if secs < 60:
            return f"{secs}s"
        mins = secs // 60
        rem_secs = secs % 60
        if mins < 60:
            return f"{mins}m {rem_secs}s"
        hours = mins // 60
        rem_mins = mins % 60
        return f"{hours}h {rem_mins}m"
    except Exception:
        return "0s"

def redeem_credit_code(raw_code: str, user_name: str, user_email: str, user_phone: str) -> Dict[str, Any]:
    cleaned = re.sub(r"[^A-Za-z0-9]", "", raw_code).upper()
    if len(cleaned) != 16:
        return {
            "success": False,
            "error": "Invalid code format. Voucher code must be exactly 16 alphanumeric characters (e.g. ABCD-1234-EFGH-5678)."
        }

    formatted_code = f"{cleaned[:4]}-{cleaned[4:8]}-{cleaned[8:12]}-{cleaned[12:]}"
    credits_data = load_app_credits()
    redeemed = set(credits_data.get("redeemed_codes", []))

    if formatted_code in redeemed or cleaned in redeemed:
        return {
            "success": False,
            "error": f"Voucher code {formatted_code} has already been redeemed!"
        }

    amount = 100
    if "500" in cleaned or "GOLD" in cleaned:
        amount = 500
    elif "1000" in cleaned or "MAX" in cleaned:
        amount = 1000
    elif "250" in cleaned:
        amount = 250

    new_balance = credits_data.get("balance", 0) + amount
    credits_data["balance"] = new_balance

    if "redeemed_codes" not in credits_data:
        credits_data["redeemed_codes"] = []
    credits_data["redeemed_codes"].append(formatted_code)

    now = datetime.now()
    tx_id = f"TXN-{int(now.timestamp()) % 1000000:06d}"
    expiry = (now + timedelta(days=30)).strftime("%Y-%m-%d")

    transaction = {
        "id": tx_id,
        "type": "credit",
        "amount": amount,
        "balance_after": new_balance,
        "timestamp": now.strftime("%Y-%m-%d %I:%M %p"),
        "code": formatted_code,
        "expiry_date": expiry,
        "description": "Credit Points Added",
        "user_name": (user_name or "").strip() or current_state.get("profile_name") or "User",
        "user_email": (user_email or "").strip() or current_state.get("profile_email") or "user@example.com",
        "user_phone": (user_phone or "").strip() or current_state.get("profile_phone") or "N/A"
    }

    if "transactions" not in credits_data:
        credits_data["transactions"] = []
    credits_data["transactions"].insert(0, transaction)

    save_app_credits(credits_data)
    return {
        "success": True,
        "message": f"Successfully recharged +{amount} credit points!",
        "amount": amount,
        "balance": new_balance,
        "transaction": transaction
    }

def deduct_credit_usage(
    amount: int,
    user_name: str,
    user_email: str,
    user_phone: str,
    description: str = "",
    duration: str = "",
    total_snaps: int = 0,
    count: int = 0
) -> Optional[Dict[str, Any]]:
    credits_data = load_app_credits()
    cur_bal = credits_data.get("balance", 0)
    new_bal = max(0, cur_bal - amount)
    credits_data["balance"] = new_bal

    now = datetime.now()
    tx_id = f"TXN-{int(now.timestamp()) % 1000000:06d}"

    transaction = {
        "id": tx_id,
        "type": "debit",
        "amount": -amount,
        "balance_after": new_bal,
        "timestamp": now.strftime("%Y-%m-%d %I:%M %p"),
        "code": "",
        "expiry_date": "",
        "description": description or "Credit Points Used",
        "duration": duration or "N/A",
        "total_snaps": total_snaps,
        "count": count,
        "user_name": (user_name or "").strip() or current_state.get("profile_name") or "User",
        "user_email": (user_email or "").strip() or current_state.get("profile_email") or "user@example.com",
        "user_phone": (user_phone or "").strip() or current_state.get("profile_phone") or "N/A"
    }

    if "transactions" not in credits_data:
        credits_data["transactions"] = []
    credits_data["transactions"].insert(0, transaction)

    save_app_credits(credits_data)
    return transaction

main_event_loop: Optional[asyncio.AbstractEventLoop] = None

# Active WebSocket Connection Manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.mobile_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket, is_mobile: bool = False):
        await websocket.accept()
        self.active_connections.append(websocket)
        if is_mobile and websocket not in self.mobile_connections:
            self.mobile_connections.append(websocket)
        logger.info(f"WebSocket client connected. Total clients: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        if websocket in self.mobile_connections:
            self.mobile_connections.remove(websocket)
        logger.info(f"WebSocket client disconnected. Total clients: {len(self.active_connections)}")

    async def disconnect_mobile_clients(self):
        """Forcefully disconnect all paired mobile sockets with policy code 4001."""
        for ws in list(self.mobile_connections):
            try:
                await ws.send_json({
                    "type": "companion_disconnected",
                    "reason": "host_disconnected"
                })
                await ws.close(code=4001, reason="Disconnected by host PC")
            except Exception as e:
                logger.debug(f"Error disconnecting mobile client: {e}")
            if ws in self.active_connections:
                self.active_connections.remove(ws)
            if ws in self.mobile_connections:
                self.mobile_connections.remove(ws)
        logger.info("All mobile companion sockets closed by host PC.")

    async def broadcast(self, message: Dict[str, Any]):
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.debug(f"Broadcast error: {e}")
                if connection in self.active_connections:
                    self.active_connections.remove(connection)

manager = ConnectionManager()

def record_session_qa(result: Dict[str, Any], question: str = "") -> None:
    """Persist successful answers without coupling saved history to AI context."""
    if not result.get("success"):
        return
    resolved_question = question_from_result(result, question)
    answer = str(result.get("answer") or "").strip()
    if not resolved_question or not answer:
        return
    result["question"] = resolved_question
    try:
        session_history.add_qa(
            question=resolved_question,
            answer=answer,
            user_name=current_state.get("profile_name", ""),
            metadata=result,
        )
    except Exception as exc:
        logger.warning("Could not persist session Q&A history: %s", exc)

    # Record credit usage (-5 credits) with session metrics
    try:
        session_metrics["qa_count"] += 1
        tx = deduct_credit_usage(
            amount=5,
            description="Voucher Used (-5 Credits)",
            user_name=current_state.get("profile_name", ""),
            user_email=current_state.get("profile_email", ""),
            user_phone=current_state.get("profile_phone", ""),
            duration=get_session_duration_str(),
            total_snaps=session_metrics["total_snaps"],
            count=session_metrics["qa_count"]
        )
        if tx and main_event_loop and main_event_loop.is_running():
            asyncio.run_coroutine_threadsafe(
                manager.broadcast({"type": "credits_updated", "balance": tx["balance_after"], "transaction": tx}),
                main_event_loop
            )
    except Exception as exc:
        logger.warning("Could not record credit debit: %s", exc)

# IP Helper
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

LOCAL_IP = get_local_ip()
PORT = int(os.getenv("PORT", 8585))

PAIRING_TOKEN = os.getenv("PAIRING_TOKEN", "").strip() or secrets.token_hex(16)
os.environ["PAIRING_TOKEN"] = PAIRING_TOKEN
MOBILE_URL = f"http://{LOCAL_IP}:{PORT}/mobile?token={PAIRING_TOKEN}"

def get_pairing_token() -> str:
    return PAIRING_TOKEN

def get_mobile_url() -> str:
    return MOBILE_URL

def regenerate_pairing_token() -> str:
    global PAIRING_TOKEN, MOBILE_URL
    PAIRING_TOKEN = secrets.token_hex(16)
    os.environ["PAIRING_TOKEN"] = PAIRING_TOKEN
    MOBILE_URL = f"http://{LOCAL_IP}:{PORT}/mobile?token={PAIRING_TOKEN}"
    logger.info(f"Regenerated new pairing token: {PAIRING_TOKEN[:6]}***")
    return PAIRING_TOKEN

# Core AI & Screen instances
ai_engine = InterviewAIEngine()
screen_snipper = ScreenSnipper()

# Auth Helpers
def is_valid_token(token: Optional[str]) -> bool:
    if not token:
        return False
    return secrets.compare_digest(token.strip(), PAIRING_TOKEN)

def get_auth_token_from_request(request: Request) -> Optional[str]:
    token = request.headers.get("x-pairing-token")
    if token:
        return token
    auth = request.headers.get("authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth[7:].strip()
    token = request.query_params.get("token")
    if token:
        return token
    token = request.cookies.get("pairing_token")
    if token:
        return token
    return None

def verify_pairing_token(request: Request):
    """Enforce pairing token on all API routes. Localhost loopback allowed for local browser ease."""
    client_host = request.client.host if request.client else ""
    is_localhost = client_host in ("127.0.0.1", "::1", "localhost", "testclient")
    token = get_auth_token_from_request(request)
    if is_valid_token(token) or is_localhost:
        return True
    raise HTTPException(status_code=401, detail="Unauthorized: Valid pairing token required.")

def verify_ws_auth(websocket: WebSocket) -> bool:
    client_host = websocket.client.host if websocket.client else ""
    is_localhost = client_host in ("127.0.0.1", "::1", "localhost", "testclient")
    token = (
        websocket.query_params.get("token")
        or websocket.headers.get("x-pairing-token")
        or websocket.cookies.get("pairing_token")
    )
    return is_valid_token(token) or is_localhost

# Audio callback & Loopback
audio_processing_lock = threading.Lock()

def on_interviewer_audio(wav_bytes: bytes):
    """Callback fired when the interviewer finishes speaking through system speakers."""
    if not audio_processing_lock.acquire(blocking=False):
        logger.info("Audio already being processed. Skipping overlapping audio chunk.")
        return

    logger.info("Interviewer voice captured via System Loopback! Processing...")

    async def _handle_audio():
        try:
            await manager.broadcast({
                "type": "status",
                "status": "thinking",
                "is_interviewer_voice": True,
                "message": "🎧 Interviewer question detected! Generating spoken answer..."
            })
            result = await asyncio.to_thread(
                ai_engine.solve_audio, wav_bytes, mime_type="audio/wav", mode=current_state["mode"]
            )
            if result.get("success"):
                record_session_qa(result)
                await manager.broadcast({
                    "type": "new_answer",
                    "data": result
                })
            elif result.get("is_small_talk"):
                text_heard = result.get("transcribed_text", "")
                logger.info(f"Filtered greeting/small talk from broadcast: '{text_heard}'")
                await manager.broadcast({
                    "type": "status",
                    "status": "idle",
                    "message": f"🎧 Heard: \"{text_heard}\" (Greeting filtered • 0 tokens spent)"
                })
            else:
                await manager.broadcast({
                    "type": "status",
                    "status": "idle"
                })
        except Exception as e:
            logger.error(f"Error handling interviewer audio: {e}")
        finally:
            audio_processing_lock.release()

    if main_event_loop and main_event_loop.is_running():
        asyncio.run_coroutine_threadsafe(_handle_audio(), main_event_loop)
    else:
        audio_processing_lock.release()

loopback_listener = SystemAudioLoopback(callback=on_interviewer_audio)
loopback_was_running_before_ptt = False

def ptt_pause_loopback() -> bool:
    global loopback_was_running_before_ptt
    if loopback_listener.is_running:
        loopback_listener.stop()
        loopback_was_running_before_ptt = True
        logger.info("PTT: Paused interviewer loopback audio while candidate is speaking.")
    return True

def ptt_resume_loopback() -> bool:
    global loopback_was_running_before_ptt
    try:
        if not loopback_listener.is_running:
            loopback_listener.start()
            logger.info("PTT: Resumed interviewer loopback audio.")
    except Exception as exc:
        logger.warning("PTT: Could not resume loopback: %s", exc)
    return loopback_listener.is_running

# Global Hotkey Handlers
def handle_global_snip():
    """Triggered by Ctrl+Shift+S (runs in dedicated worker thread; dispatches to server loop)."""
    logger.info("Global hotkey triggered: Snip & Solve")
    def _worker():
        try:
            if main_event_loop and main_event_loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    manager.broadcast({"type": "status", "status": "capturing_screen"}),
                    main_event_loop
                )
            img_bytes = screen_snipper.capture_primary_screen(current_state["screen_quality"])
            session_metrics["total_snaps"] += 1
            if main_event_loop and main_event_loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    manager.broadcast({"type": "status", "status": "thinking", "is_snip": True}),
                    main_event_loop
                )
            result = ai_engine.solve_screen_snip(img_bytes, mode=current_state["mode"])
            record_session_qa(result, "Screen question (screenshot)")
            if main_event_loop and main_event_loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    manager.broadcast({"type": "new_answer", "data": result}),
                    main_event_loop
                )
        except Exception as e:
            logger.error(f"Error in global snip: {e}")
    threading.Thread(target=_worker, daemon=True).start()

def handle_global_clear():
    """Triggered by Ctrl+Shift+C (safely scheduled on server main loop)."""
    logger.info("Global hotkey triggered: Panic Clear")
    reset_session_metrics()
    if main_event_loop and main_event_loop.is_running():
        asyncio.run_coroutine_threadsafe(
            manager.broadcast({"type": "panic_clear"}),
            main_event_loop
        )

hotkey_manager = GlobalHotkeyManager(on_snip=handle_global_snip, on_clear=handle_global_clear)

# Desktop Overlay Process
desktop_overlay_process: Optional[subprocess.Popen] = None
desktop_overlay_lock = threading.Lock()

def stop_desktop_overlay():
    global desktop_overlay_process
    with desktop_overlay_lock:
        process = desktop_overlay_process
        desktop_overlay_process = None

    if process is None or process.poll() is not None:
        return

    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        logger.warning("Desktop overlay did not close after 5 seconds; terminating it.")
        process.kill()
        process.wait(timeout=5)

def launch_desktop_overlay():
    global desktop_overlay_process
    with desktop_overlay_lock:
        if desktop_overlay_process and desktop_overlay_process.poll() is None:
            return {"success": True, "already_running": True}

        if getattr(sys, "frozen", False):
            command = [sys.executable, "--overlay"]
            working_directory = os.path.dirname(sys.executable)
        else:
            launcher_path = os.path.join(BASE_DIR, "run.py")
            command = [sys.executable, launcher_path, "--overlay"]
            working_directory = os.path.dirname(launcher_path)

        try:
            desktop_overlay_process = subprocess.Popen(
                command,
                cwd=working_directory,
                env=os.environ.copy(),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as exc:
            logger.exception("Could not launch the native desktop overlay.")
            raise HTTPException(
                status_code=500,
                detail=f"Could not launch the desktop overlay: {exc}",
            ) from exc

    return {"success": True, "already_running": False}

# Persistent Resume
saved_resume_data = load_saved_resume()
saved_resume_text = saved_resume_data.get("text", "")
saved_resume_filename = saved_resume_data.get("filename", "")

# Active Copilot Session State (synchronized timer)
copilot_session_state: Dict[str, Any] = {
    "is_active": False,
    "started_at": None,
}

# Mobile Companion Connection State
companion_state: Dict[str, Any] = {
    "mobile_connected": False,
    "mobile_client_ip": None,
    "connected_at": None,
}

def reset_companion_state() -> None:
    companion_state["mobile_connected"] = False
    companion_state["mobile_client_ip"] = None
    companion_state["connected_at"] = None

# Current State
current_state: Dict[str, Any] = {
    "mode": os.getenv("DEFAULT_MODE", "qa_testing"),
    "language": os.getenv("DEFAULT_CODING_LANG", "python"),
    "has_api_key": bool(ai_engine.api_key or ai_engine.groq_api_key),
    "has_gemini_key": bool(ai_engine.api_key),
    "has_groq_key": bool(ai_engine.groq_api_key),
    "has_resume": bool(saved_resume_text),
    "resume_filename": saved_resume_filename,
    "local_ip": LOCAL_IP,
    "mobile_url": MOBILE_URL,
    "port": PORT,
    "pairing_token": PAIRING_TOKEN,
    **load_app_preferences(),
}

ai_engine.update_profile(
    resume=saved_resume_text if saved_resume_text else None,
    custom_instructions=current_state["custom_instructions"],
    candidate_name=current_state.get("profile_name"),
    candidate_email=current_state.get("profile_email"),
    candidate_phone=current_state.get("profile_phone"),
)
if saved_resume_text:
    logger.info(f"Loaded persistent resume on startup: {saved_resume_filename} ({len(saved_resume_text)} chars)")
ai_engine.google_search_enabled = current_state["google_search_enabled"]
loopback_listener.use_neural_vad = current_state["neural_vad_enabled"]
