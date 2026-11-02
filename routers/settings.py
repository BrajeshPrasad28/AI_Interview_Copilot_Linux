import asyncio
import logging
from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File

from core.state import (
    verify_pairing_token,
    current_state,
    DEFAULT_PREFERENCES,
    save_app_preferences,
    ai_engine,
    loopback_listener,
    save_saved_resume,
    delete_saved_resume,
    load_app_credits,
    redeem_credit_code,
    get_machine_id,
    get_user_uuid,
    sync_user_profile_to_dashboard,
    manager,
)
from document_processor import extract_text_from_document

logger = logging.getLogger("server")

router = APIRouter(tags=["settings"])

@router.get("/api/settings", dependencies=[Depends(verify_pairing_token)])
async def api_get_settings():
    """Retrieve current non-sensitive settings (including texts for editing/clearing)."""
    masked_key = ""
    if ai_engine.api_key:
        masked_key = ai_engine.api_key[:4] + "..." + ai_engine.api_key[-4:] if len(ai_engine.api_key) > 8 else "***"

    masked_groq = ""
    if ai_engine.groq_api_key:
        masked_groq = ai_engine.groq_api_key[:6] + "..." + ai_engine.groq_api_key[-4:] if len(ai_engine.groq_api_key) > 10 else "***"

    return {
        "has_api_key": bool(ai_engine.api_key or ai_engine.groq_api_key),
        "has_gemini_key": bool(ai_engine.api_key),
        "has_groq_key": bool(ai_engine.groq_api_key),
        "masked_key": masked_key,
        "masked_groq_key": masked_groq,
        "language": current_state["language"],
        "mode": current_state["mode"],
        "has_resume": bool(ai_engine.resume_text),
        "resume_filename": current_state.get("resume_filename", ""),
        "has_jd": bool(ai_engine.job_description),
        "resume": ai_engine.resume_text,
        "jd": ai_engine.job_description,
        "loopback_active": loopback_listener.is_running,
        "machine_id": get_machine_id(),
        "user_uuid": get_user_uuid(),
        **{key: current_state[key] for key in DEFAULT_PREFERENCES}
    }

@router.post("/api/settings", dependencies=[Depends(verify_pairing_token)])
async def api_update_settings(payload: Dict[str, Any]):
    """Update provider, profile, and interface settings."""
    if payload.get("google_search_enabled") and not ai_engine.api_key:
        raise HTTPException(status_code=400, detail="Google Search grounding requires a Gemini API key.")
    profile_name = payload.get("profile_name")
    if profile_name is not None and (not isinstance(profile_name, str) or len(profile_name) > 100):
        raise HTTPException(status_code=400, detail="Profile name must be 100 characters or fewer.")

    profile_email = payload.get("profile_email")
    if profile_email is not None and (not isinstance(profile_email, str) or len(profile_email) > 120):
        raise HTTPException(status_code=400, detail="Profile email must be 120 characters or fewer.")

    profile_phone = payload.get("profile_phone")
    if profile_phone is not None and (not isinstance(profile_phone, str) or len(profile_phone) > 50):
        raise HTTPException(status_code=400, detail="Profile phone must be 50 characters or fewer.")

    api_key = payload.get("api_key")
    if api_key is not None and api_key.strip():
        ai_engine.update_api_key(api_key.strip())
        current_state["has_gemini_key"] = True

    groq_key = payload.get("groq_api_key")
    if groq_key is not None and groq_key.strip():
        ai_engine.update_groq_key(groq_key.strip())
        current_state["has_groq_key"] = True

    current_state["has_api_key"] = bool(ai_engine.api_key or ai_engine.groq_api_key)

    resume = payload.get("resume")
    jd = payload.get("jd")
    lang = payload.get("language")
    mode = payload.get("mode")
    custom_instructions = payload.get("custom_instructions")

    if profile_name is not None:
        current_state["profile_name"] = profile_name.strip()
    if profile_email is not None:
        current_state["profile_email"] = profile_email.strip()
    if profile_phone is not None:
        current_state["profile_phone"] = profile_phone.strip()

    if lang:
        current_state["language"] = lang.lower()
    if mode:
        current_state["mode"] = mode.lower()

    # Pass resume and jd directly; empty string clears them in ai_engine.update_profile
    ai_engine.update_profile(
        resume=resume,
        jd=jd,
        preferred_language=current_state["language"],
        custom_instructions=custom_instructions,
        candidate_name=current_state.get("profile_name"),
        candidate_email=current_state.get("profile_email"),
        candidate_phone=current_state.get("profile_phone"),
    )
    if resume is not None:
        clean_resume = str(resume).strip()
        if clean_resume:
            fn = current_state.get("resume_filename") or "resume.pdf"
            save_saved_resume(fn, clean_resume)
            current_state["resume_filename"] = fn
            current_state["has_resume"] = True
        else:
            delete_saved_resume()
            current_state["resume_filename"] = ""
            current_state["has_resume"] = False

    if custom_instructions is not None:
        current_state["custom_instructions"] = ai_engine.custom_instructions

    int_settings = {
        "background_opacity": (0, 100),
        "font_opacity": (10, 100),
        "response_font_size": (12, 32),
    }
    for key, (minimum, maximum) in int_settings.items():
        if key in payload:
            try:
                current_state[key] = max(minimum, min(maximum, int(payload[key])))
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail=f"Invalid {key} value.")

    if "show_screen_capture_button" in payload:
        current_state["show_screen_capture_button"] = bool(payload["show_screen_capture_button"])
    if "neural_vad_enabled" in payload:
        current_state["neural_vad_enabled"] = bool(payload["neural_vad_enabled"])
        loopback_listener.use_neural_vad = current_state["neural_vad_enabled"]
    if "google_search_enabled" in payload:
        current_state["google_search_enabled"] = bool(payload["google_search_enabled"])
        ai_engine.google_search_enabled = current_state["google_search_enabled"]
    if "screen_quality" in payload:
        try:
            quality = int(payload["screen_quality"])
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid screen quality.")
        if quality not in (50, 75, 90):
            raise HTTPException(status_code=400, detail="Screen quality must be 50, 75, or 90.")
        current_state["screen_quality"] = quality
    if "vad_mode" in payload:
        vad_mode = str(payload["vad_mode"]).lower()
        if vad_mode not in ("smart", "manual"):
            raise HTTPException(status_code=400, detail="VAD mode must be smart or manual.")
        current_state["vad_mode"] = vad_mode
        if vad_mode == "manual":
            loopback_listener.stop()
        elif not loopback_listener.is_running:
            try:
                loopback_listener.start()
            except Exception as exc:
                raise HTTPException(status_code=500, detail=f"Could not start audio listener: {exc}")

    save_app_preferences({key: current_state[key] for key in DEFAULT_PREFERENCES})

    # Trigger background sync to Central Dashboard if profile changed
    if profile_name is not None or profile_email is not None or profile_phone is not None:
        asyncio.create_task(sync_user_profile_to_dashboard())

    # Broadcast updated state
    await manager.broadcast({
        "type": "settings_updated",
        "mode": current_state["mode"],
        "language": current_state["language"],
        "has_api_key": current_state["has_api_key"],
        "has_gemini_key": current_state["has_gemini_key"],
        "has_groq_key": current_state["has_groq_key"],
        "has_resume": bool(ai_engine.resume_text),
        "resume_filename": current_state.get("resume_filename", ""),
        **{key: current_state[key] for key in DEFAULT_PREFERENCES}
    })

    return {
        "success": True,
        "message": "Settings saved successfully.",
        "loopback_active": loopback_listener.is_running,
    }

@router.post("/api/upload-resume", dependencies=[Depends(verify_pairing_token)])
async def api_upload_resume(file: UploadFile = File(...)):
    """Upload and extract text from a PDF resume no larger than 1 MB."""
    filename = file.filename or "resume.pdf"
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Please upload a PDF resume.")

    max_size = 1024 * 1024
    file_bytes = await file.read(max_size + 1)
    if len(file_bytes) > max_size:
        raise HTTPException(status_code=413, detail="Resume file must be 1 MB or smaller.")
    if b"%PDF-" not in file_bytes[:1024]:
        raise HTTPException(status_code=400, detail="The uploaded file is not a valid PDF.")

    try:
        extracted_text = await asyncio.to_thread(extract_text_from_document, file_bytes, filename)
        if not extracted_text:
            raise HTTPException(status_code=400, detail="Could not extract text from document.")

        ai_engine.update_profile(resume=extracted_text)
        current_state["resume_filename"] = filename
        current_state["has_resume"] = True
        save_saved_resume(filename, extracted_text)
        logger.info(f"Resume uploaded and updated: {filename} ({len(extracted_text)} chars)")
        await manager.broadcast({
            "type": "resume_updated",
            "filename": filename,
            "length": len(extracted_text)
        })
        return {
            "success": True,
            "message": f"Resume parsed successfully ({len(extracted_text)} characters extracted).",
            "filename": filename,
            "length": len(extracted_text),
            "text": extracted_text,
            "preview": extracted_text[:300]
        }
    except Exception as e:
        logger.error(f"Error parsing resume: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@router.delete("/api/resume", dependencies=[Depends(verify_pairing_token)])
@router.post("/api/resume/delete", dependencies=[Depends(verify_pairing_token)])
async def api_delete_resume():
    """Remove candidate resume from AI context and persistent storage."""
    ai_engine.update_profile(resume="")
    delete_saved_resume()
    current_state["resume_filename"] = ""
    current_state["has_resume"] = False
    logger.info("Resume deleted by user.")
    await manager.broadcast({
        "type": "resume_deleted"
    })
    return {"success": True, "message": "Resume deleted successfully."}

@router.get("/api/credits", dependencies=[Depends(verify_pairing_token)])
async def api_get_credits():
    credits_data = load_app_credits()
    return {
        "balance": credits_data.get("balance", 0),
        "transactions": credits_data.get("transactions", []),
        "user_name": current_state.get("profile_name", ""),
        "user_email": current_state.get("profile_email", ""),
        "user_phone": current_state.get("profile_phone", ""),
        "user_uuid": get_user_uuid(),
        "machine_id": get_machine_id()
    }

@router.post("/api/credits/redeem", dependencies=[Depends(verify_pairing_token)])
async def api_redeem_credits(payload: Dict[str, Any]):
    code = str(payload.get("code") or "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="Voucher code cannot be empty.")

    res = redeem_credit_code(
        raw_code=code,
        user_name=current_state.get("profile_name", ""),
        user_email=current_state.get("profile_email", ""),
        user_phone=current_state.get("profile_phone", "")
    )
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error", "Failed to redeem code."))

    await manager.broadcast({
        "type": "credits_updated",
        "balance": res["balance"],
        "transaction": res.get("transaction")
    })
    return res
