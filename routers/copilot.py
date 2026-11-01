import asyncio
import logging
from typing import Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form

from core.state import (
    verify_pairing_token,
    current_state,
    ai_engine,
    screen_snipper,
    loopback_listener,
    manager,
    record_session_qa,
    reset_session_metrics,
    session_metrics,
    LOCAL_IP,
    get_mobile_url,
    ptt_pause_loopback,
    ptt_resume_loopback,
    launch_desktop_overlay,
    copilot_session_state,
)

logger = logging.getLogger("server")

router = APIRouter(tags=["copilot"])

@router.get("/api/status", dependencies=[Depends(verify_pairing_token)])
async def get_status():
    """Get system and pairing status."""
    return {
        "success": True,
        "has_api_key": bool(ai_engine.api_key or ai_engine.groq_api_key),
        "has_gemini_key": bool(ai_engine.api_key),
        "has_groq_key": bool(ai_engine.groq_api_key),
        "local_ip": LOCAL_IP,
        "mobile_url": get_mobile_url(),
        "mode": current_state["mode"],
        "language": current_state["language"],
        "loopback_active": loopback_listener.is_running
    }

@router.post("/api/desktop-overlay", dependencies=[Depends(verify_pairing_token)])
async def api_launch_desktop_overlay():
    """Launch the native desktop overlay window on this PC."""
    return launch_desktop_overlay()

@router.post("/api/loopback/toggle", dependencies=[Depends(verify_pairing_token)])
async def toggle_loopback(payload: Optional[Dict[str, Any]] = None):
    """Toggle the Windows System Audio Loopback listener (Interviewer voice only)."""
    enable = (payload or {}).get("enable", not loopback_listener.is_running)
    if enable:
        loopback_listener.start()
    else:
        loopback_listener.stop()

    is_active = loopback_listener.is_running
    await manager.broadcast({
        "type": "loopback_status",
        "is_active": is_active
    })
    return {"success": True, "is_active": is_active}

@router.get("/api/loopback/status", dependencies=[Depends(verify_pairing_token)])
async def get_loopback_status():
    return {"is_active": loopback_listener.is_running}

@router.post("/api/ask", dependencies=[Depends(verify_pairing_token)])
async def api_ask_question(payload: Dict[str, Any]):
    """Process a typed or transcribed question (offloaded from asyncio event loop)."""
    question = payload.get("question", "").strip()
    mode = payload.get("mode", current_state["mode"])
    speaker = payload.get("speaker", "Candidate")

    if not question:
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    await manager.broadcast({"type": "status", "status": "thinking", "question": question, "speaker": speaker})

    result = await asyncio.to_thread(ai_engine.ask_question, question, mode=mode, speaker=speaker)
    record_session_qa(result, question)

    await manager.broadcast({
        "type": "new_answer",
        "data": result
    })

    return result

@router.post("/api/snip", dependencies=[Depends(verify_pairing_token)])
async def api_trigger_snip(payload: Optional[Dict[str, Any]] = None):
    """Trigger screen snip on host PC and solve with vision (offloaded to thread)."""
    mode = (payload or {}).get("mode", current_state["mode"])
    prompt = (payload or {}).get("prompt", "")

    await manager.broadcast({"type": "status", "status": "capturing_screen"})

    try:
        img_bytes = await asyncio.to_thread(screen_snipper.capture_primary_screen, current_state["screen_quality"])
        session_metrics["total_snaps"] += 1
    except Exception as e:
        err_msg = f"Screen capture failed: {str(e)}"
        await manager.broadcast({"type": "status", "status": "error", "message": err_msg})
        return {"success": False, "error": err_msg}

    await manager.broadcast({"type": "status", "status": "thinking", "is_snip": True})

    result = await asyncio.to_thread(ai_engine.solve_screen_snip, img_bytes, user_prompt=prompt, mode=mode)
    record_session_qa(result, prompt or "Screen question (screenshot)")

    await manager.broadcast({
        "type": "new_answer",
        "data": result
    })

    return result

@router.post("/api/upload-image", dependencies=[Depends(verify_pairing_token)])
async def api_upload_image(file: UploadFile = File(...), mode: str = Form("coding"), prompt: str = Form("")):
    """Analyze an uploaded screenshot / image taken with mobile phone (offloaded to thread)."""
    img_bytes = await file.read()
    await manager.broadcast({"type": "status", "status": "thinking", "is_snip": True})

    result = await asyncio.to_thread(ai_engine.solve_screen_snip, img_bytes, user_prompt=prompt, mode=mode)
    record_session_qa(result, prompt or "Screen question (uploaded image)")

    await manager.broadcast({
        "type": "new_answer",
        "data": result
    })

    return result

@router.post("/api/process-audio", dependencies=[Depends(verify_pairing_token)])
async def api_process_audio(file: UploadFile = File(...), mode: str = Form("coding"), speaker: str = Form("Candidate")):
    """Process a recorded audio clip from candidate (PTT) or loopback."""
    audio_bytes = await file.read()
    mime_type = file.content_type or "audio/webm"
    await manager.broadcast({
        "type": "status",
        "status": "thinking",
        "is_audio": True,
        "speaker": speaker,
        "message": f"🎙️ Transcribing {speaker.lower()} audio..."
    })

    result = await asyncio.to_thread(ai_engine.solve_audio, audio_bytes, mime_type=mime_type, mode=mode, speaker=speaker)
    record_session_qa(result)

    await manager.broadcast({
        "type": "new_answer",
        "data": result
    })

    return result

@router.post("/api/ptt/start", dependencies=[Depends(verify_pairing_token)])
async def api_ptt_start():
    ptt_pause_loopback()
    await manager.broadcast({"type": "ptt_state", "is_recording": True, "loopback_active": False})
    await manager.broadcast({"type": "loopback_status", "is_active": False})
    return {"success": True, "loopback_active": False}

@router.post("/api/ptt/end", dependencies=[Depends(verify_pairing_token)])
async def api_ptt_end():
    is_active = ptt_resume_loopback()
    await manager.broadcast({"type": "ptt_state", "is_recording": False, "loopback_active": is_active})
    await manager.broadcast({"type": "loopback_status", "is_active": is_active})
    return {"success": True, "loopback_active": is_active}

@router.post("/api/clear-history", dependencies=[Depends(verify_pairing_token)])
async def api_clear_history():
    """Clear conversation memory / context window."""
    ai_engine.clear_history()
    reset_session_metrics()
    await manager.broadcast({"type": "history_cleared"})
    return {"success": True, "message": "Conversation context cleared."}

@router.get("/api/copilot/status", dependencies=[Depends(verify_pairing_token)])
async def api_get_copilot_status():
    return {
        "is_active": copilot_session_state["is_active"],
        "started_at": copilot_session_state["started_at"]
    }
