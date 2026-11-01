"""Persistent, bounded history of completed interview sessions."""

import json
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


class SessionHistory:
    """Store the five most recent Q&A sessions independently from AI context."""

    def __init__(self, path: str, max_sessions: int = 5):
        self.path = path
        self.max_sessions = max_sessions
        self._lock = threading.RLock()
        self._sessions: List[Dict[str, Any]] = self._load()
        self._active_session: Optional[Dict[str, Any]] = None

    def _load(self) -> List[Dict[str, Any]]:
        try:
            with open(self.path, "r", encoding="utf-8") as history_file:
                data = json.load(history_file)
            sessions = data.get("sessions", []) if isinstance(data, dict) else []
            if not isinstance(sessions, list):
                return []
            valid = [session for session in sessions if isinstance(session, dict) and isinstance(session.get("id"), str)]
            return valid[-self.max_sessions:]
        except (OSError, ValueError, TypeError, AttributeError):
            return []

    def _save(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        temporary_path = self.path + ".tmp"
        with open(temporary_path, "w", encoding="utf-8") as history_file:
            json.dump({"sessions": self._sessions}, history_file, ensure_ascii=False, indent=2)
        os.replace(temporary_path, self.path)

    def start_session(self) -> None:
        """Begin a fresh session; it is persisted when the first answer is recorded."""
        with self._lock:
            self._active_session = None

    def end_session(self) -> None:
        with self._lock:
            self._active_session = None

    def add_qa(self, question: str, answer: str, user_name: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        question = (question or "").strip()
        answer = (answer or "").strip()
        if not question or not answer:
            return

        with self._lock:
            timestamp = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
            if self._active_session is None:
                self._active_session = {
                    "id": uuid.uuid4().hex,
                    "started_at": timestamp,
                    "user_name": (user_name or "").strip() or "User",
                    "items": [],
                }
                self._sessions.append(self._active_session)

            entry: Dict[str, Any] = {"timestamp": timestamp, "question": question, "answer": answer}
            if metadata:
                for key in ("mode", "speaker", "model_used", "is_audio", "is_screenshot"):
                    value = metadata.get(key)
                    if value is not None:
                        entry[key] = value
            self._active_session["items"].append(entry)
            self._sessions = self._sessions[-self.max_sessions:]
            self._save()

    def list_sessions(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(session, items=[dict(item) for item in session.get("items", [])]) for session in reversed(self._sessions)]

    def delete_session(self, session_id: str) -> bool:
        with self._lock:
            original_count = len(self._sessions)
            self._sessions = [session for session in self._sessions if session.get("id") != session_id]
            if len(self._sessions) == original_count:
                return False
            if self._active_session and self._active_session.get("id") == session_id:
                self._active_session = None
            self._save()
            return True


def question_from_result(result: Dict[str, Any], fallback: str = "") -> str:
    """Find the question text for text, transcribed audio, or direct audio answers."""
    question = result.get("question") or result.get("transcribed_question") or fallback
    if question:
        return str(question).strip()

    answer = str(result.get("answer") or "")
    match = re.match(r'^Question:\s*["“]?(.*?)["”]?\s*(?:\r?\n|$)', answer, re.IGNORECASE)
    return match.group(1).strip() if match else "Interviewer audio question"
