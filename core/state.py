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
import hmac
import hashlib
import math
import uuid
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

# Store application data under the Linux XDG data directory.
_XDG_DATA = os.getenv("XDG_DATA_HOME", os.path.join(os.path.expanduser("~"), ".local", "share"))
APP_DATA_DIR = os.getenv("INTERVIEW_TOOL_DATA_DIR") or os.path.join(_XDG_DATA, "InterviewTool")
APP_PREFERENCES_PATH = os.path.join(APP_DATA_DIR, "preferences.json")
SESSION_HISTORY_PATH = os.path.join(APP_DATA_DIR, "session_history.json")
RESUME_DATA_PATH = os.path.join(APP_DATA_DIR, "saved_resume.json")
NOTES_PATH = os.path.join(APP_DATA_DIR, "notes.json")
CREDITS_PATH = os.path.join(APP_DATA_DIR, "credits.json")
LEGACY_STARTER_CODE = "WELCOME-100-STARTER"

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
    "user_uuid": "",
    "accepted_terms_version": 0,
    "accepted_terms_on": "",
    "terms_cache": {},
}

_cached_machine_id: Optional[str] = None
_cached_user_uuid: Optional[str] = None
CREDITS_HMAC_SECRET: str = os.getenv("CREDITS_HMAC_SECRET", "InterviewTool_HMAC_SecKey_2026")

def get_machine_id() -> str:
    """Retrieve permanent unique hardware identifier (Linux: /etc/machine-id or uuid node fallback)."""
    global _cached_machine_id
    if _cached_machine_id:
        return _cached_machine_id

    # Linux: read /etc/machine-id (systemd) or /var/lib/dbus/machine-id
    for mid_path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            with open(mid_path, "r") as f:
                mid = f.read().strip()
            if mid and len(mid) >= 8:
                _cached_machine_id = mid
                return _cached_machine_id
        except (OSError, PermissionError):
            continue

    # Fallback: MAC-address-based UUID
    try:
        node = uuid.getnode()
        _cached_machine_id = str(uuid.UUID(int=node))
        return _cached_machine_id
    except Exception:
        _cached_machine_id = "UNKNOWN-MACHINE-ID"
        return _cached_machine_id

def get_user_uuid() -> str:
    """Retrieve or generate persistent UUID for this user client installation."""
    global _cached_user_uuid
    if _cached_user_uuid:
        return _cached_user_uuid
    prefs = load_app_preferences()
    uid = str(prefs.get("user_uuid") or "").strip()
    if uid and len(uid) == 36:
        _cached_user_uuid = uid
        return _cached_user_uuid

    new_uid = str(uuid.uuid4())
    prefs["user_uuid"] = new_uid
    save_app_preferences(prefs)
    _cached_user_uuid = new_uid
    return _cached_user_uuid

def generate_credits_signature(credits_data: Dict[str, Any]) -> str:
    """Generate SHA256-HMAC signature for local credits data tied to this machine and secret salt."""
    key = f"{get_machine_id()}:{CREDITS_HMAC_SECRET}".encode("utf-8")
    try:
        balance_val = float(credits_data.get("balance", 0.0))
    except (ValueError, TypeError):
        balance_val = 0.0
    balance_str = f"{balance_val:.2f}"
    codes = credits_data.get("redeemed_codes") or []
    codes_str = ",".join(sorted([str(c) for c in codes]))
    txs = credits_data.get("transactions") or []
    tx_count_str = str(len(txs))
    msg = f"{balance_str}|{codes_str}|{tx_count_str}".encode("utf-8")
    return hmac.new(key, msg, hashlib.sha256).hexdigest()

def verify_credits_signature(credits_data: Dict[str, Any]) -> bool:
    """Verify that credits_data has not been tampered with offline."""
    if not isinstance(credits_data, dict):
        return False
    sig = credits_data.get("signature")
    if not sig or not isinstance(sig, str):
        return False
    expected = generate_credits_signature(credits_data)
    return hmac.compare_digest(sig, expected)

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


def _parse_credit_transaction_time(value: Any) -> Optional[datetime]:
    timestamp = str(value or "").strip()
    if not timestamp:
        return None
    for date_format in ("%Y-%m-%d %I:%M %p", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %I:%M:%S %p"):
        try:
            return datetime.strptime(timestamp, date_format)
        except ValueError:
            pass
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc).replace(tzinfo=None) if parsed.tzinfo else parsed
    except ValueError:
        return None


def _migrate_legacy_starter_credit(credits_data: Dict[str, Any]) -> bool:
    transactions = credits_data.get("transactions")
    if not isinstance(transactions, list):
        transactions = []

    starter_transactions = [
        tx for tx in transactions
        if isinstance(tx, dict)
        and str(tx.get("code") or "").strip().upper() == LEGACY_STARTER_CODE
    ]
    redeemed_codes = credits_data.get("redeemed_codes")
    if not isinstance(redeemed_codes, list):
        redeemed_codes = []
    has_starter_code = any(
        str(code).strip().upper() == LEGACY_STARTER_CODE
        for code in redeemed_codes
    )
    if not starter_transactions and not has_starter_code:
        return False

    remaining_transactions = [tx for tx in transactions if tx not in starter_transactions]
    timestamped = [
        (_parse_credit_transaction_time(tx.get("timestamp")), index, tx)
        for index, tx in enumerate(remaining_transactions)
        if isinstance(tx, dict)
    ]
    if len(timestamped) == len(remaining_transactions) and all(item[0] is not None for item in timestamped):
        ordered_transactions = [
            item[2] for item in sorted(timestamped, key=lambda item: (item[0], -item[1]))
        ]
    else:
        ordered_transactions = list(reversed(remaining_transactions))

    if starter_transactions:
        balance = 0.0
        for tx in ordered_transactions:
            if not isinstance(tx, dict):
                continue
            try:
                amount = abs(float(tx.get("amount", 0.0)))
            except (TypeError, ValueError):
                continue
            if not math.isfinite(amount):
                continue
            if tx.get("type") == "credit":
                balance = round(balance + amount, 2)
            elif tx.get("type") == "debit":
                balance = max(0.0, round(balance - amount, 2))
            else:
                continue
            tx["balance_after"] = balance
    else:
        try:
            current_balance = float(credits_data.get("balance", 0.0))
        except (TypeError, ValueError):
            current_balance = 0.0
        balance = max(0.0, round(current_balance - 100.0, 2))

    credits_data["balance"] = balance
    credits_data["transactions"] = remaining_transactions
    credits_data["redeemed_codes"] = [
        code for code in redeemed_codes
        if str(code).strip().upper() != LEGACY_STARTER_CODE
    ]
    return True


def load_app_credits() -> Dict[str, Any]:
    try:
        if os.path.exists(CREDITS_PATH):
            with open(CREDITS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and "balance" in data and "transactions" in data:
                    if not verify_credits_signature(data):
                        logger.warning("HMAC signature verification failed for credits.json! Potential tampering detected. Resetting balance to 0.")
                        data["balance"] = 0.00
                        save_app_credits(data)
                        return data

                    changed = _migrate_legacy_starter_credit(data)
                    if changed:
                        logger.info("Removed the legacy 100-point local starter credit.")
                    for tx in data.get("transactions", []):
                        desc = tx.get("description", "")
                        if "referral" in desc.lower():
                            continue
                        if tx.get("type") == "credit":
                            if "voucher" in desc.lower() or "starter" in desc.lower() or "bonus" in desc.lower() or "(" in desc:
                                tx["description"] = "Credit Points Added"
                                changed = True
                        elif tx.get("type") == "debit":
                            if ("voucher" in desc.lower() or "ai q" in desc.lower() or "(" in desc) and "copilot session" not in desc.lower():
                                tx["description"] = "Credit Points Used"
                                changed = True
                    if changed:
                        save_app_credits(data)
                    return data
    except Exception as exc:
        logger.warning("Could not read credits data: %s", exc)

    starter_data = {
        "balance": 0.0,
        "redeemed_codes": [],
        "transactions": []
    }
    save_app_credits(starter_data)
    return starter_data

def save_app_credits(credits_data: Dict[str, Any]) -> None:
    try:
        os.makedirs(APP_DATA_DIR, exist_ok=True)
        credits_data["signature"] = generate_credits_signature(credits_data)
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

def _get_dashboard_headers() -> Dict[str, str]:
    """Build authentication headers for Central Dashboard internal API requests."""
    secret = os.getenv("DASHBOARD_APP_SECRET", "").strip()
    return {"X-App-Secret": secret} if secret else {}

def redeem_credit_code(
    raw_code: str,
    user_name: str = "",
    user_email: str = "",
    user_phone: str = "",
    dashboard_url: Optional[str] = None
) -> Dict[str, Any]:
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

    url = (dashboard_url or os.getenv("DASHBOARD_API_URL", "http://localhost:5000")).rstrip("/")
    endpoint = f"{url}/api/credits/redeem"
    payload = {
        "code": formatted_code,
        "uuid": get_user_uuid(),
        "machine_id": get_machine_id(),
        "name": user_name or current_state.get("profile_name", ""),
        "email": user_email or current_state.get("profile_email", ""),
        "phone": user_phone or current_state.get("profile_phone", "")
    }

    headers = _get_dashboard_headers()

    try:
        import httpx
        resp = httpx.post(endpoint, json=payload, headers=headers, timeout=5.0)
        try:
            data = resp.json()
        except Exception:
            data = {}
        if resp.status_code == 200 and (data.get("success") or data.get("status") == "success"):
            amount = float(data.get("amount", 0))
            new_balance = round(float(credits_data.get("balance", 0.0)) + amount, 2)
            credits_data["balance"] = new_balance
            if "redeemed_codes" not in credits_data:
                credits_data["redeemed_codes"] = []
            credits_data["redeemed_codes"].append(formatted_code)

            txn_id = f"TXN-{secrets.randbelow(90000) + 10000}"
            tx = {
                "id": txn_id,
                "type": "credit",
                "amount": amount,
                "balance_after": new_balance,
                "timestamp": datetime.now().strftime("%Y-%m-%d %I:%M %p"),
                "code": formatted_code,
                "expiry_date": (datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d"),
                "description": "Credit Points Added",
                "user_name": (user_name or "").strip() or current_state.get("profile_name") or "User",
                "user_email": (user_email or "").strip() or current_state.get("profile_email") or "user@example.com",
                "user_phone": (user_phone or "").strip() or current_state.get("profile_phone") or "N/A"
            }
            if "transactions" not in credits_data:
                credits_data["transactions"] = []
            credits_data["transactions"].insert(0, tx)
            save_app_credits(credits_data)

            return {
                "success": True,
                "amount": amount,
                "balance": new_balance,
                "code": formatted_code,
                "message": data.get("message", f"Successfully recharged +{amount} credit points!"),
                "transaction": tx
            }
        else:
            err_msg = data.get("message") or data.get("error") or f"Unable to redeem voucher (code {resp.status_code})"
            return {
                "success": False,
                "error": err_msg
            }
    except Exception as exc:
        logger.warning(f"Failed to connect to credit server ({endpoint}): {exc}")
        return {
            "success": False,
            "error": "Oops, unable to connect to the server. Please check your connection."
        }

def redeem_referral_code(
    raw_code: str,
    user_name: str = "",
    user_email: str = "",
    user_phone: str = "",
    dashboard_url: Optional[str] = None
) -> Dict[str, Any]:
    """Redeem a referral code for referee user, adding 10 credits and recording 1-time claim."""
    cleaned = (raw_code or "").strip().upper()
    if not cleaned:
        return {
            "success": False,
            "error": "Referral code is required."
        }

    credits_data = load_app_credits()
    if credits_data.get("has_redeemed_referral"):
        return {
            "success": False,
            "error": "You have already redeemed a referral code. Only one redemption is allowed per account/device."
        }

    url = (dashboard_url or os.getenv("DASHBOARD_API_URL", "http://localhost:5000")).rstrip("/")
    endpoint = f"{url}/api/referrals/redeem"
    payload = {
        "code": cleaned,
        "uuid": get_user_uuid(),
        "machine_id": get_machine_id(),
        "name": user_name or current_state.get("profile_name", ""),
        "email": user_email or current_state.get("profile_email", ""),
        "phone": user_phone or current_state.get("profile_phone", "")
    }

    headers = _get_dashboard_headers()
    try:
        import httpx
        resp = httpx.post(endpoint, json=payload, headers=headers, timeout=5.0)
        try:
            data = resp.json()
        except Exception:
            data = {}
        if resp.status_code == 200 and (data.get("success") or data.get("status") == "success"):
            reward = float(data.get("reward", 10.0))
            new_balance = round(float(credits_data.get("balance", 0.0)) + reward, 2)
            credits_data["balance"] = new_balance
            credits_data["has_redeemed_referral"] = True
            credits_data["applied_referral_code"] = cleaned

            txn_id = f"TXN-REF-{secrets.randbelow(90000) + 10000}"
            tx = {
                "id": txn_id,
                "type": "credit",
                "amount": reward,
                "balance_after": new_balance,
                "timestamp": datetime.now().strftime("%Y-%m-%d %I:%M %p"),
                "code": cleaned,
                "expiry_date": (datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d"),
                "description": f"Referral Bonus (+{int(reward)} pts)",
                "user_name": (user_name or "").strip() or current_state.get("profile_name") or "User",
                "user_email": (user_email or "").strip() or current_state.get("profile_email") or "user@example.com",
                "user_phone": (user_phone or "").strip() or current_state.get("profile_phone") or "N/A"
            }
            if "transactions" not in credits_data:
                credits_data["transactions"] = []
            credits_data["transactions"].insert(0, tx)
            save_app_credits(credits_data)

            return {
                "success": True,
                "reward": reward,
                "balance": new_balance,
                "code": cleaned,
                "message": data.get("message", f"Referral code applied! You received +{reward} credit points."),
                "transaction": tx
            }
        else:
            err_msg = data.get("message") or data.get("error") or f"Unable to redeem referral code (code {resp.status_code})"
            return {
                "success": False,
                "error": err_msg
            }
    except Exception as exc:
        logger.warning(f"Failed to connect to referral server ({endpoint}): {exc}")
        return {
            "success": False,
            "error": "Oops, unable to connect to the server. Please check your connection."
        }

def sync_startup_handshake(dashboard_url: Optional[str] = None) -> Dict[str, Any]:
    """Startup handshake with central dashboard: validates machine ID, gets rates, or falls back to offline grace mode."""
    url = (dashboard_url or os.getenv("DASHBOARD_API_URL", "http://localhost:5000")).rstrip("/")
    endpoint = f"{url}/api/app/startup-check"

    machine_id = get_machine_id()
    user_uuid = get_user_uuid()
    profile_name = current_state.get("profile_name", "")
    profile_email = current_state.get("profile_email", "")
    profile_phone = current_state.get("profile_phone", "")

    credits_data = load_app_credits()
    current_bal = float(credits_data.get("balance", 0.0) or 0.0)
    txns = credits_data.get("transactions", [])

    payload = {
        "uuid": user_uuid,
        "machine_id": machine_id,
        "name": profile_name,
        "email": profile_email,
        "phone": profile_phone,
        "balance": current_bal,
        "transactions": txns
    }

    headers = _get_dashboard_headers()

    try:
        import httpx
        with httpx.Client(timeout=3.5) as client:
            resp = client.post(endpoint, json=payload, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "error" and data.get("error_code") == "device_mismatch":
                    logger.warning(f"Device mismatch detected: {data.get('message')}")
                    return {
                        "status": "device_mismatch",
                        "offline": False,
                        "message": data.get("message", "Device mismatch detected.")
                    }

                rates = data.get("rates")
                if rates and isinstance(rates, dict):
                    set_billing_rates(rates)

                terms_data = data.get("terms")
                if isinstance(terms_data, dict) and terms_data.get("content"):
                    set_terms_conditions(terms_data, persist=True)

                contact_data = data.get("contact")
                if isinstance(contact_data, dict) and contact_data:
                    set_contact_info(contact_data, persist=True)

                groq_key = (data.get("groq_api") or "").strip()
                if groq_key:
                    ai_engine.update_groq_key(groq_key)
                    current_state["has_groq_key"] = True
                    current_state["has_api_key"] = True
                    logger.info("Managed Groq API key synced from Central Dashboard.")

                genai_key = (data.get("genai_api") or "").strip()
                if genai_key:
                    ai_engine.update_api_key(genai_key)
                    current_state["has_gemini_key"] = True
                    current_state["has_api_key"] = True
                    logger.info("Managed Gemini API key synced from Central Dashboard.")

                credits_data = load_app_credits()

                # Sync static referral code and status from dashboard
                remote_ref_code = data.get("referral_code")
                if remote_ref_code:
                    credits_data["referral_code"] = remote_ref_code
                    current_state["referral_code"] = remote_ref_code

                if data.get("has_redeemed_referral") is not None:
                    credits_data["has_redeemed_referral"] = bool(data.get("has_redeemed_referral"))

                # Asynchronous reward processing for referrer
                pending_referral = float(data.get("pending_referral_credits", 0.0) or 0.0)
                if pending_referral > 0:
                    cur_bal = round(float(credits_data.get("balance", 0.0)), 2)
                    new_bal = round(cur_bal + pending_referral, 2)
                    credits_data["balance"] = new_bal
                    ref_txn = {
                        "id": f"TXN-RWD-{secrets.randbelow(90000) + 10000}",
                        "type": "credit",
                        "amount": pending_referral,
                        "balance_after": new_bal,
                        "timestamp": datetime.now().strftime("%Y-%m-%d %I:%M %p"),
                        "code": "REFERRAL-REWARD",
                        "expiry_date": (datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d"),
                        "description": f"Referral Reward (+{int(pending_referral)} pts) - Friends joined",
                        "user_name": current_state.get("profile_name", "User"),
                        "user_email": current_state.get("profile_email", "user@example.com"),
                        "user_phone": current_state.get("profile_phone", "N/A"),
                    }
                    if "transactions" not in credits_data:
                        credits_data["transactions"] = []
                    credits_data["transactions"].insert(0, ref_txn)
                    save_app_credits(credits_data)
                    logger.info(f"Synced +{pending_referral} referral reward points from Central Dashboard! New balance: {new_bal}")

                # 1. Primary Ledger-based sync: Sync any remote voucher codes assigned to this user that are not yet recorded locally
                remote_codes = data.get("redeemed_codes")
                credits_data = load_app_credits()
                codes_applied = 0
                if isinstance(remote_codes, list) and remote_codes:
                    local_redeemed_set = set(credits_data.get("redeemed_codes", []))
                    for rc in remote_codes:
                        c_code = str(rc.get("code") or "").strip().upper()
                        c_amt = float(rc.get("amount") or 0.0)
                        if c_code and c_amt > 0 and c_code not in local_redeemed_set:
                            cur_bal = round(float(credits_data.get("balance", 0.0)), 2)
                            new_bal = round(cur_bal + c_amt, 2)
                            credits_data["balance"] = new_bal
                            if "redeemed_codes" not in credits_data:
                                credits_data["redeemed_codes"] = []
                            credits_data["redeemed_codes"].append(c_code)
                            local_redeemed_set.add(c_code)

                            sync_txn = {
                                "id": f"TXN-DASH-{secrets.randbelow(90000) + 10000}",
                                "type": "credit",
                                "amount": c_amt,
                                "balance_after": new_bal,
                                "timestamp": datetime.now().strftime("%Y-%m-%d %I:%M %p"),
                                "code": c_code,
                                "expiry_date": (datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d"),
                                "description": f"Credit Points Added via Dashboard ({c_code})",
                                "user_name": current_state.get("profile_name", "User"),
                                "user_email": current_state.get("profile_email", "user@example.com"),
                                "user_phone": current_state.get("profile_phone", "N/A"),
                            }
                            if "transactions" not in credits_data:
                                credits_data["transactions"] = []
                            credits_data["transactions"].insert(0, sync_txn)
                            codes_applied += 1
                            logger.info(f"Synced dashboard voucher {c_code} (+{c_amt} pts). New balance: {new_bal}")

                    if codes_applied > 0:
                        save_app_credits(credits_data)
                        logger.info(f"Applied {codes_applied} new dashboard vouchers. Final balance: {credits_data['balance']}")

                # 2. Fallback gross sync if redeemed_codes is absent (legacy backend support)
                if codes_applied == 0 and not remote_codes:
                    remote_total = float(data.get("total_redeemed") or 0.0)
                    if remote_total > 0:
                        local_redeemed_total = sum(
                            float(tx.get("amount", 0)) for tx in credits_data.get("transactions", [])
                            if tx.get("type") == "credit" and "starter" not in str(tx.get("code", "")).lower()
                        )
                        diff = round(remote_total - local_redeemed_total, 2)
                        if diff > 0:
                            cur_bal = round(float(credits_data.get("balance", 0.0)), 2)
                            new_bal = round(cur_bal + diff, 2)
                            credits_data["balance"] = new_bal
                            sync_txn = {
                                "id": f"TXN-DASH-{secrets.randbelow(90000) + 10000}",
                                "type": "credit",
                                "amount": diff,
                                "balance_after": new_bal,
                                "timestamp": datetime.now().strftime("%Y-%m-%d %I:%M %p"),
                                "code": "DASHBOARD-RECHARGE",
                                "expiry_date": (datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d"),
                                "description": "Credit Points Added via Dashboard",
                                "user_name": current_state.get("profile_name", "User"),
                                "user_email": current_state.get("profile_email", "user@example.com"),
                                "user_phone": current_state.get("profile_phone", "N/A"),
                            }
                            if "transactions" not in credits_data:
                                credits_data["transactions"] = []
                            credits_data["transactions"].insert(0, sync_txn)
                            save_app_credits(credits_data)
                            logger.info(f"Synced +{diff} credits from Central Dashboard! New balance: {new_bal}")

                # 3. Synchronize remote transactions from Central Dashboard into local ledger
                remote_txns = data.get("transactions")
                if isinstance(remote_txns, list) and remote_txns:
                    credits_data = load_app_credits()
                    local_txns = credits_data.get("transactions", [])
                    existing_tx_ids = set()
                    for t in local_txns:
                        tid = t.get("id") or t.get("txn_id")
                        if tid:
                            existing_tx_ids.add(str(tid).strip())

                    added_txns = 0
                    for rtx in remote_txns:
                        rtid = str(rtx.get("id") or rtx.get("txn_id") or "").strip()
                        if rtid and rtid not in existing_tx_ids:
                            local_txns.append(rtx)
                            existing_tx_ids.add(rtid)
                            added_txns += 1

                    if added_txns > 0:
                        credits_data["transactions"] = local_txns
                        save_app_credits(credits_data)
                        logger.info(f"Merged {added_txns} remote transactions from dashboard into local ledger.")

                return {
                    "success": True,
                    "status": "success",
                    "offline": False,
                    "data": data
                }
            else:
                logger.warning(f"Dashboard startup check returned status {resp.status_code}")
    except Exception as exc:
        logger.info(f"Dashboard startup check unreachable ({exc}). Entering offline grace mode.")

    return {
        "success": False,
        "status": "offline_grace",
        "offline": True,
        "balance": get_credits_balance()
    }

async def sync_user_profile_to_dashboard(dashboard_url: Optional[str] = None) -> bool:
    """Asynchronously sync candidate profile details to central dashboard database."""
    url = (dashboard_url or os.getenv("DASHBOARD_API_URL", "http://localhost:5000")).rstrip("/")
    endpoint = f"{url}/api/user/sync"
    payload = {
        "uuid": get_user_uuid(),
        "machine_id": get_machine_id(),
        "name": current_state.get("profile_name", ""),
        "email": current_state.get("profile_email", ""),
        "phone": current_state.get("profile_phone", ""),
        "groq_api": ai_engine.groq_api_key if hasattr(ai_engine, "groq_api_key") else None,
        "genai_api": ai_engine.api_key if hasattr(ai_engine, "api_key") else None
    }
    headers = _get_dashboard_headers()
    try:
        import httpx
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.post(endpoint, json=payload, headers=headers)
            return resp.status_code == 200
    except Exception as exc:
        logger.debug(f"User sync to dashboard skipped: {exc}")
        return False

DEFAULT_BILLING_RATES: Dict[str, Any] = {
    "call_per_minute": 2.50,
    "snap_per_count": 5.00,
    "note_per_count": 2.00,
    "note_max_chars": 500,
    "referral_reward": 10.00,
}

current_billing_rates: Dict[str, Any] = DEFAULT_BILLING_RATES.copy()

def get_billing_rate(key: str) -> Any:
    return current_billing_rates.get(key, DEFAULT_BILLING_RATES.get(key))

def set_billing_rates(new_rates: Dict[str, Any]) -> None:
    for key, val in new_rates.items():
        if key in DEFAULT_BILLING_RATES:
            try:
                if key == "note_max_chars":
                    current_billing_rates[key] = int(val)
                else:
                    current_billing_rates[key] = round(float(val), 2)
            except (ValueError, TypeError):
                pass
    logger.info(f"Billing rates updated: {current_billing_rates}")

async def sync_billing_rates_from_remote(remote_url: Optional[str] = None) -> bool:
    """Fetch remote billing rates on startup. Fallback gracefully to default rates without crash."""
    url = remote_url or os.getenv("REMOTE_BILLING_RATES_URL", "").strip()
    if not url:
        return False
    try:
        import httpx
        user_email = current_state.get("profile_email", "")
        params = {"email": user_email} if user_email else {}
        async with httpx.AsyncClient(timeout=httpx.Timeout(2.0, connect=0.8)) as client:
            resp = await client.get(url, params=params)
            if resp.status_code == 200:
                data = resp.json()
                rates = data.get("rates") if isinstance(data, dict) else None
                if rates and isinstance(rates, dict):
                    set_billing_rates(rates)
                    return True
    except Exception as exc:
        logger.warning(f"Could not sync billing rates from remote ({url}): {exc}. Using default rates.")
    return False


def _load_default_terms_content() -> str:
    txt_path = os.path.join(BASE_DIR, "TERMS_AND_CONDITIONS.txt")
    try:
        if os.path.exists(txt_path):
            with open(txt_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    return content
    except Exception:
        pass
    return (
        "TERMS AND CONDITIONS - INTERVIEW COPILOT SOFTWARE\n\n"
        "By installing, launching, or using this Software, you agree to be bound by the Terms & Conditions "
        "covering single-device license binding, credit point consumption, fair use, and privacy policies."
    )


DEFAULT_TERMS_CONDITIONS: Dict[str, Any] = {
    "title": "Terms & Conditions",
    "content": _load_default_terms_content(),
    "version": 1,
    "published_on": "",
}

current_terms_conditions: Dict[str, Any] = dict(DEFAULT_TERMS_CONDITIONS)


def get_terms_conditions() -> Dict[str, Any]:
    """Return active Terms & Conditions (preferring latest synced cache over built-in fallback)."""
    cached = current_state.get("terms_cache")
    if isinstance(cached, dict) and cached.get("content"):
        if int(cached.get("version") or 1) >= int(current_terms_conditions.get("version") or 1):
            return {
                "title": str(cached.get("title") or "Terms & Conditions"),
                "content": str(cached.get("content") or ""),
                "version": int(cached.get("version") or 1),
                "published_on": str(cached.get("published_on") or ""),
            }
    return dict(current_terms_conditions)


def set_terms_conditions(new_terms: Dict[str, Any], persist: bool = True) -> Dict[str, Any]:
    """Update active Terms & Conditions in memory and optionally persist to preferences.json."""
    global current_terms_conditions
    if not isinstance(new_terms, dict) or not str(new_terms.get("content") or "").strip():
        return get_terms_conditions()
    clean_terms = {
        "title": str(new_terms.get("title") or "Terms & Conditions").strip() or "Terms & Conditions",
        "content": str(new_terms.get("content") or "").strip(),
        "version": int(new_terms.get("version") or 1),
        "published_on": str(new_terms.get("published_on") or ""),
    }
    current_terms_conditions = clean_terms
    current_state["terms_cache"] = clean_terms
    if persist:
        prefs = load_app_preferences()
        prefs["terms_cache"] = clean_terms
        save_app_preferences(prefs)
    logger.info(f"Terms & Conditions updated to v{clean_terms['version']}.")
    return dict(clean_terms)


def sync_terms_from_remote(dashboard_url: Optional[str] = None) -> Dict[str, Any]:
    """Fetch latest published Terms & Conditions directly from backend API."""
    url = (dashboard_url or os.getenv("DASHBOARD_API_URL", "http://localhost:5000")).rstrip("/")
    endpoint = f"{url}/api/terms-conditions"
    try:
        import httpx
        with httpx.Client(timeout=2.5) as client:
            resp = client.get(endpoint)
            if resp.status_code == 200:
                payload = resp.json()
                terms_data = payload.get("terms") if isinstance(payload, dict) else None
                if isinstance(terms_data, dict) and terms_data.get("content"):
                    return set_terms_conditions(terms_data, persist=True)
    except Exception as exc:
        logger.debug(f"Remote terms fetch skipped ({endpoint}): {exc}")
    return get_terms_conditions()


def accept_terms_conditions(version: Optional[int] = None) -> Dict[str, Any]:
    """Record user acceptance of the specified (or active) Terms & Conditions version."""
    terms = get_terms_conditions()
    accepted_ver = int(version if version is not None else terms.get("version", 1))
    accepted_ts = datetime.now().strftime("%d-%m-%Y %I:%M %p")
    current_state["accepted_terms_version"] = accepted_ver
    current_state["accepted_terms_on"] = accepted_ts
    prefs = load_app_preferences()
    prefs["accepted_terms_version"] = accepted_ver
    prefs["accepted_terms_on"] = accepted_ts
    save_app_preferences(prefs)
    return {
        "accepted_version": accepted_ver,
        "accepted_on": accepted_ts,
    }


DEFAULT_CONTACT_INFO: Dict[str, Any] = {
    "support_email": "admin@avintrax.com",
    "support_phone": "+91-8723969733",
    "company_name": "Avintrax",
    "software_version": "v1.0.0",
    "copyright_text": "© 2026 Avintrax. All rights reserved.",
    "website_url": "https://avintrax.com",
}

_cached_contact_info: Optional[Dict[str, Any]] = None


def get_contact_info() -> Dict[str, Any]:
    """Return active contact, support & software information."""
    global _cached_contact_info
    if _cached_contact_info is not None:
        return dict(_cached_contact_info)

    cached = current_state.get("contact_cache")
    if isinstance(cached, dict) and cached.get("support_email"):
        _cached_contact_info = dict(cached)
        return dict(_cached_contact_info)

    try:
        prefs = load_app_preferences()
        saved_contact = prefs.get("contact_cache")
        if isinstance(saved_contact, dict) and saved_contact:
            merged = DEFAULT_CONTACT_INFO.copy()
            merged.update(saved_contact)
            _cached_contact_info = merged
            current_state["contact_cache"] = merged
            return dict(merged)
    except Exception:
        pass

    return dict(DEFAULT_CONTACT_INFO)


def set_contact_info(new_contact: Dict[str, Any], persist: bool = True) -> Dict[str, Any]:
    """Update active contact info in memory and optionally persist to preferences.json."""
    global _cached_contact_info
    if not isinstance(new_contact, dict) or not new_contact:
        return get_contact_info()
    merged = DEFAULT_CONTACT_INFO.copy()
    for k in ["support_email", "support_phone", "company_name", "software_version", "copyright_text", "website_url"]:
        v = new_contact.get(k)
        if v is not None and str(v).strip():
            merged[k] = str(v).strip()
    _cached_contact_info = merged
    current_state["contact_cache"] = merged
    if persist:
        try:
            prefs = load_app_preferences()
            prefs["contact_cache"] = merged
            save_app_preferences(prefs)
        except Exception:
            pass
    logger.info("Contact & Support information updated.")
    return dict(merged)


def sync_contact_from_remote(dashboard_url: Optional[str] = None) -> Dict[str, Any]:
    """Fetch latest contact information directly from backend API."""
    url = (dashboard_url or os.getenv("DASHBOARD_API_URL", "http://localhost:5000")).rstrip("/")
    endpoint = f"{url}/api/contact"
    try:
        import httpx
        with httpx.Client(timeout=2.5) as client:
            resp = client.get(endpoint)
            if resp.status_code == 200:
                payload = resp.json()
                contact_data = payload.get("contact") if isinstance(payload, dict) else None
                if isinstance(contact_data, dict) and contact_data:
                    return set_contact_info(contact_data, persist=True)
    except Exception as exc:
        logger.debug(f"Remote contact fetch skipped ({endpoint}): {exc}")
    return get_contact_info()

# Live Call Billing Worker
live_call_billing_task: Optional[asyncio.Task] = None

def get_credits_balance() -> float:
    try:
        data = load_app_credits()
        return round(float(data.get("balance", 0.0)), 2)
    except Exception:
        return 0.0


def sync_usage_balance_to_dashboard(transaction: Dict[str, Any], balance: float, dashboard_url: Optional[str] = None) -> bool:
    """Synchronize local deduction transaction and updated balance to central dashboard."""
    url = (dashboard_url or os.getenv("DASHBOARD_API_URL", "http://localhost:5000")).rstrip("/")
    endpoint = f"{url}/api/user/sync-balance"
    payload = {
        "uuid": get_user_uuid(),
        "machine_id": get_machine_id(),
        "balance": balance,
        "transaction": transaction
    }
    headers = _get_dashboard_headers()
    try:
        import httpx
        with httpx.Client(timeout=3.0) as client:
            resp = client.post(endpoint, json=payload, headers=headers)
            return resp.status_code == 200
    except Exception as exc:
        logger.debug(f"Could not sync usage balance to dashboard: {exc}")
        return False


def lookup_and_restore_user_account(email: str, dashboard_url: Optional[str] = None) -> Dict[str, Any]:
    """Look up registered user account by email and restore UUID, balance, and transaction history."""
    cleaned_email = (email or "").strip().lower()
    if not cleaned_email:
        return {"success": False, "found": False, "error": "Email is required."}

    url = (dashboard_url or os.getenv("DASHBOARD_API_URL", "http://localhost:5000")).rstrip("/")
    endpoint = f"{url}/api/user/restore"
    payload = {
        "email": cleaned_email,
        "machine_id": get_machine_id()
    }
    headers = _get_dashboard_headers()
    try:
        import httpx
        with httpx.Client(timeout=4.0) as client:
            resp = client.post(endpoint, json=payload, headers=headers)
            if resp.status_code == 403:
                err = resp.json().get("message", "Device binding mismatch.")
                return {"success": False, "found": True, "error": err}
            if resp.status_code == 200:
                data = resp.json()
                if not data.get("found"):
                    return {"success": True, "found": False}

                user_data = data.get("user") or {}
                remote_uuid = user_data.get("uuid")
                if remote_uuid:
                    global _cached_user_uuid
                    _cached_user_uuid = remote_uuid
                    prefs = load_app_preferences()
                    prefs["user_uuid"] = remote_uuid
                    if user_data.get("name"):
                        prefs["profile_name"] = user_data["name"]
                        current_state["profile_name"] = user_data["name"]
                    if user_data.get("phone"):
                        prefs["profile_phone"] = user_data["phone"]
                        current_state["profile_phone"] = user_data["phone"]
                    prefs["profile_email"] = cleaned_email
                    current_state["profile_email"] = cleaned_email
                    save_app_preferences(prefs)

                # Restore credits & transactions
                credits_data = load_app_credits()
                restored_balance = float(user_data.get("current_balance", credits_data.get("balance", 0.0)))
                credits_data["balance"] = restored_balance
                if user_data.get("referral_code"):
                    credits_data["referral_code"] = user_data["referral_code"]
                    current_state["referral_code"] = user_data["referral_code"]
                if "has_redeemed_referral" in user_data:
                    credits_data["has_redeemed_referral"] = bool(user_data["has_redeemed_referral"])

                remote_txs = data.get("transactions") or []
                if remote_txs:
                    existing_ids = {tx.get("id") for tx in credits_data.get("transactions", []) if tx.get("id")}
                    merged_txs = list(credits_data.get("transactions", []))
                    for r_tx in remote_txs:
                        if r_tx.get("id") not in existing_ids:
                            merged_txs.append(r_tx)
                            existing_ids.add(r_tx.get("id"))
                    credits_data["transactions"] = merged_txs

                save_app_credits(credits_data)
                logger.info(f"User account restored successfully for {cleaned_email}! Restored balance: {restored_balance}")
                return {"success": True, "found": True, "user": user_data, "transactions": credits_data.get("transactions", [])}
    except Exception as exc:
        logger.warning(f"Error restoring user account ({endpoint}): {exc}")
        return {"success": False, "found": False, "error": f"Server unreachable: {exc}"}

    return {"success": False, "found": False, "error": "Could not restore user account."}


def deduct_credit_usage(
    amount: float,
    user_name: str,
    user_email: str,
    user_phone: str,
    description: str = "",
    duration: str = "",
    total_snaps: int = 0,
    count: int = 0,
    session_id: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    credits_data = load_app_credits()
    cur_bal = round(float(credits_data.get("balance", 0.0)), 2)
    amount_float = round(float(amount), 2)
    new_bal = max(0.0, round(cur_bal - amount_float, 2))
    credits_data["balance"] = new_bal

    now = datetime.now()
    tx_id = f"TXN-{int(now.timestamp()) % 1000000:06d}"

    # Check if this active session already has a transaction in history
    existing_tx = None
    if session_id and "transactions" in credits_data:
        for tx in credits_data["transactions"]:
            if tx.get("session_id") == session_id:
                existing_tx = tx
                break

    if existing_tx:
        # In-place update of existing session transaction to avoid cluttering history
        existing_tx["amount"] = round(float(existing_tx.get("amount", 0.0)) - amount_float, 2)
        existing_tx["balance_after"] = new_bal
        existing_tx["timestamp"] = now.strftime("%Y-%m-%d %I:%M %p")
        if duration:
            existing_tx["duration"] = duration
        if total_snaps is not None:
            existing_tx["total_snaps"] = total_snaps
        if count is not None:
            existing_tx["count"] = count
        if description and not existing_tx.get("finalized"):
            existing_tx["description"] = description
        save_app_credits(credits_data)
        try:
            threading.Thread(target=sync_usage_balance_to_dashboard, args=(existing_tx, new_bal), daemon=True).start()
        except Exception:
            pass
        return existing_tx

    transaction = {
        "id": tx_id,
        "type": "debit",
        "amount": -amount_float,
        "balance_after": new_bal,
        "timestamp": now.strftime("%Y-%m-%d %I:%M %p"),
        "code": "",
        "expiry_date": "",
        "description": description or ("Copilot Session (In Progress)" if session_id else "Credit Points Used"),
        "duration": duration or "N/A",
        "total_snaps": total_snaps,
        "count": count,
        "session_id": session_id,
        "user_name": (user_name or "").strip() or current_state.get("profile_name") or "User",
        "user_email": (user_email or "").strip() or current_state.get("profile_email") or "user@example.com",
        "user_phone": (user_phone or "").strip() or current_state.get("profile_phone") or "N/A"
    }

    if "transactions" not in credits_data:
        credits_data["transactions"] = []
    credits_data["transactions"].insert(0, transaction)

    save_app_credits(credits_data)
    try:
        threading.Thread(target=sync_usage_balance_to_dashboard, args=(transaction, new_bal), daemon=True).start()
    except Exception:
        pass
    return transaction


def finalize_session_transaction(
    session_id: str,
    duration: Optional[str] = None,
    total_snaps: Optional[int] = None
) -> Optional[Dict[str, Any]]:
    """
    Finalize an active session's consolidated transaction upon call completion.
    Formats description cleanly: 'Copilot Session (<duration>, <total_snaps> snaps)'.
    """
    if not session_id:
        return None
    credits_data = load_app_credits()
    target_tx = None
    if "transactions" in credits_data:
        for tx in credits_data["transactions"]:
            if tx.get("session_id") == session_id:
                target_tx = tx
                break
    if not target_tx:
        return None

    dur = duration or target_tx.get("duration", "1m")
    snaps = total_snaps if total_snaps is not None else target_tx.get("total_snaps", 0)
    target_tx["duration"] = dur
    target_tx["total_snaps"] = snaps
    target_tx["description"] = f"Copilot Session ({dur}, {snaps} snaps)"
    target_tx["finalized"] = True
    target_tx["timestamp"] = datetime.now().strftime("%Y-%m-%d %I:%M %p")
    save_app_credits(credits_data)
    return target_tx


async def _call_billing_ticker():
    """Background ticker that deducts call_per_minute at every 60s boundary and terminates if insufficient."""
    logger.info("Call billing ticker started.")
    minute_counter = 1
    try:
        while copilot_session_state.get("is_active"):
            await asyncio.sleep(60)
            if not copilot_session_state.get("is_active"):
                break
            minute_counter += 1
            call_rate = get_billing_rate("call_per_minute")
            current_bal = get_credits_balance()
            active_session_id = copilot_session_state.get("session_id")

            if current_bal < call_rate:
                logger.warning(f"Balance {current_bal} is insufficient for minute {minute_counter} ({call_rate}). Terminating call.")
                session_history.end_session()
                copilot_session_state["is_active"] = False
                copilot_session_state["started_at"] = None
                if active_session_id:
                    finalize_session_transaction(
                        active_session_id,
                        duration=f"{minute_counter - 1}m",
                        total_snaps=session_metrics.get("total_snaps", 0)
                    )
                copilot_session_state["session_id"] = None
                await manager.broadcast({
                    "type": "copilot_ended",
                    "reason": "insufficient_credits",
                    "message": f"Session auto-terminated: Insufficient credits to continue call ({current_bal:.2f} pts available, {call_rate:.2f} pts required)."
                })
                break

            # Deduct for this minute block - consolidated into existing session card
            tx = deduct_credit_usage(
                amount=call_rate,
                description="Copilot Session (In Progress)",
                user_name=current_state.get("profile_name", ""),
                user_email=current_state.get("profile_email", ""),
                user_phone=current_state.get("profile_phone", ""),
                duration=f"{minute_counter}m",
                total_snaps=session_metrics.get("total_snaps", 0),
                count=session_metrics.get("qa_count", 0),
                session_id=active_session_id
            )
            if tx:
                await manager.broadcast({
                    "type": "credits_updated",
                    "balance": tx["balance_after"],
                    "transaction": tx
                })
    except asyncio.CancelledError:
        logger.info("Call billing ticker stopped.")
        raise
    except Exception as exc:
        logger.error(f"Error in call billing ticker: {exc}")

def start_call_billing_ticker():
    global live_call_billing_task
    stop_call_billing_ticker()
    if main_event_loop and main_event_loop.is_running():
        try:
            running_loop = asyncio.get_running_loop()
            if running_loop is main_event_loop:
                live_call_billing_task = main_event_loop.create_task(_call_billing_ticker())
            else:
                live_call_billing_task = asyncio.run_coroutine_threadsafe(
                    _call_billing_ticker(),
                    main_event_loop
                )
        except RuntimeError:
            live_call_billing_task = asyncio.run_coroutine_threadsafe(
                _call_billing_ticker(),
                main_event_loop
            )

def stop_call_billing_ticker():
    global live_call_billing_task
    if live_call_billing_task:
        try:
            live_call_billing_task.cancel()
        except Exception:
            pass
        live_call_billing_task = None

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

    # Update session metrics
    try:
        session_metrics["qa_count"] += 1
    except Exception:
        pass

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
    "session_id": None,
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
