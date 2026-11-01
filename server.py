import os
import sys
import logging
import asyncio
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends
from fastapi.staticfiles import StaticFiles

import core.state as state
from core.state import (
    STATIC_DIR,
    TEMPLATES_DIR,
    logger,
    manager,
    current_state,
    ai_engine,
    screen_snipper,
    loopback_listener,
    hotkey_manager,
    session_history,
    copilot_session_state,
    companion_state,
    reset_companion_state,
    verify_pairing_token,
    session_metrics,
    record_session_qa,
    load_app_notes,
    load_app_credits,
    DEFAULT_PREFERENCES,
    LOCAL_IP,
    verify_ws_auth,
    ptt_pause_loopback,
    ptt_resume_loopback,
    stop_desktop_overlay,
    regenerate_pairing_token,
    get_pairing_token,
    get_mobile_url,
    get_billing_rate,
    get_credits_balance,
    deduct_credit_usage,
    sync_billing_rates_from_remote,
)

from routers.pages import router as pages_router
from routers.copilot import router as copilot_router
from routers.history import router as history_router
from routers.notes import router as notes_router
from routers.settings import router as settings_router

# Lifespan: Server startup and graceful shutdown
@asynccontextmanager
async def lifespan(app: FastAPI):
    state.main_event_loop = asyncio.get_running_loop()
    session_history.start_session()
    logger.info("Realtek HD Audio Universal Service started.")
    # Startup check: Non-blocking sync of remote billing rates
    asyncio.create_task(sync_billing_rates_from_remote())
    hotkey_manager.start()
    try:
        if current_state["vad_mode"] == "smart":
            threading.Thread(target=loopback_listener.start, name="loopback-starter", daemon=True).start()
        logger.info("🎧 System Loopback Listener initializing in background thread.")
    except Exception as e:
        logger.warning(f"Could not auto-start loopback listener: {e}")
    yield
    # Shutdown
    hotkey_manager.stop()
    loopback_listener.stop()
    stop_desktop_overlay()
    logger.info("Server shutdown complete.")

app = FastAPI(title="Realtek HD Audio Universal Service", lifespan=lifespan)

# Ensure static & template directories exist and mount
os.makedirs(os.path.join(STATIC_DIR, "css"), exist_ok=True)
os.makedirs(os.path.join(STATIC_DIR, "js"), exist_ok=True)
os.makedirs(TEMPLATES_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Register Modular Routers
app.include_router(pages_router)
app.include_router(copilot_router)
app.include_router(history_router)
app.include_router(notes_router)
app.include_router(settings_router)

# Real-time WebSocket Endpoint
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    if not verify_ws_auth(websocket):
        logger.warning(f"Rejecting unauthorized WebSocket connection from {websocket.client}")
        await websocket.close(code=1008, reason="Unauthorized: Missing or invalid pairing token")
        return

    is_mobile = websocket.query_params.get("client") == "mobile" or websocket.query_params.get("device") == "mobile"
    if is_mobile:
        companion_state["mobile_connected"] = True
        companion_state["mobile_client_ip"] = websocket.client.host if websocket.client else "unknown"
        await manager.broadcast({
            "type": "companion_status",
            "connected": True,
            "device": "mobile"
        })

    await manager.connect(websocket, is_mobile=is_mobile)
    # Send initial state to syncing clients
    await websocket.send_json({
        "type": "init",
        "mode": current_state["mode"],
        "language": current_state["language"],
        "has_api_key": bool(ai_engine.api_key or ai_engine.groq_api_key),
        "has_gemini_key": bool(ai_engine.api_key),
        "has_groq_key": bool(ai_engine.groq_api_key),
        "has_resume": bool(ai_engine.resume_text),
        "resume_filename": current_state.get("resume_filename", ""),
        "copilot_active": copilot_session_state["is_active"],
        "copilot_start_time": copilot_session_state["started_at"],
        "companion_connected": companion_state["mobile_connected"],
        "local_ip": LOCAL_IP,
        "loopback_active": loopback_listener.is_running,
        "notes": load_app_notes(),
        "credits_balance": load_app_credits().get("balance", 0),
        **{key: current_state[key] for key in DEFAULT_PREFERENCES}
    })

    try:
        while True:
            data = await websocket.receive_json()
            action = data.get("action")

            if action == "mobile_connected":
                is_mobile = True
                if websocket not in manager.mobile_connections:
                    manager.mobile_connections.append(websocket)
                companion_state["mobile_connected"] = True
                await manager.broadcast({
                    "type": "companion_status",
                    "connected": True,
                    "device": "mobile"
                })

            elif action == "speech_interim":
                await manager.broadcast({
                    "type": "speech_interim",
                    "text": data.get("text", "")
                })

            elif action == "speech_final":
                text = data.get("text", "").strip()
                if text:
                    mode = data.get("mode", current_state["mode"])
                    speaker = data.get("speaker", "Candidate")
                    await manager.broadcast({"type": "status", "status": "thinking", "question": text, "speaker": speaker})
                    result = await asyncio.to_thread(ai_engine.ask_question, text, mode=mode, speaker=speaker)
                    record_session_qa(result, text)
                    await manager.broadcast({
                        "type": "new_answer",
                        "data": result
                    })

            elif action == "ask":
                question = data.get("question", "").strip()
                mode = data.get("mode", current_state["mode"])
                speaker = data.get("speaker", "Candidate")
                if question:
                    await manager.broadcast({"type": "status", "status": "thinking", "question": question, "speaker": speaker})
                    result = await asyncio.to_thread(ai_engine.ask_question, question, mode=mode, speaker=speaker)
                    record_session_qa(result, question)
                    await manager.broadcast({
                        "type": "new_answer",
                        "data": result
                    })

            elif action == "toggle_loopback":
                enable = data.get("enable", not loopback_listener.is_running)
                if enable:
                    loopback_listener.start()
                else:
                    loopback_listener.stop()
                await manager.broadcast({
                    "type": "loopback_status",
                    "is_active": loopback_listener.is_running
                })

            elif action == "ptt_start":
                ptt_pause_loopback()
                await manager.broadcast({"type": "ptt_state", "is_recording": True, "loopback_active": False})
                await manager.broadcast({"type": "loopback_status", "is_active": False})

            elif action == "ptt_end":
                is_active = ptt_resume_loopback()
                await manager.broadcast({"type": "ptt_state", "is_recording": False, "loopback_active": is_active})
                await manager.broadcast({"type": "loopback_status", "is_active": is_active})

            elif action == "trigger_snip":
                snap_rate = get_billing_rate("snap_per_count")
                current_balance = get_credits_balance()
                if current_balance < snap_rate:
                    err_msg = f"Insufficient credit points to take screen snap. ({current_balance:.2f} available, {snap_rate:.2f} required)."
                    await manager.broadcast({"type": "status", "status": "error", "message": err_msg})
                    continue

                await manager.broadcast({"type": "status", "status": "capturing_screen", "speaker": "Screen Vision"})
                try:
                    img_bytes = await asyncio.to_thread(screen_snipper.capture_primary_screen, current_state["screen_quality"])
                    session_metrics["total_snaps"] += 1
                    result = await asyncio.to_thread(
                        ai_engine.solve_screen_snip, img_bytes, mode=data.get("mode", current_state["mode"])
                    )
                    record_session_qa(result, data.get("prompt") or "Screen question (screenshot)")
                    
                    # Deduct snap credits
                    tx = deduct_credit_usage(
                        amount=snap_rate,
                        description=f"Screen Snap Solution (-{snap_rate:.2f} pts)",
                        user_name=current_state.get("profile_name", ""),
                        user_email=current_state.get("profile_email", ""),
                        user_phone=current_state.get("profile_phone", ""),
                        total_snaps=session_metrics.get("total_snaps", 1),
                        count=session_metrics.get("qa_count", 0)
                    )
                    if tx:
                        await manager.broadcast({
                            "type": "credits_updated",
                            "balance": tx["balance_after"],
                            "transaction": tx
                        })

                    await manager.broadcast({
                        "type": "new_answer",
                        "data": result
                    })
                except Exception as e:
                    await manager.broadcast({
                        "type": "status",
                        "status": "error",
                        "message": f"Screen snip error: {str(e)}"
                    })

            elif action == "change_mode":
                new_mode = data.get("mode", "coding")
                current_state["mode"] = new_mode
                await manager.broadcast({
                    "type": "mode_changed",
                    "mode": new_mode
                })

            elif action == "clear_history":
                ai_engine.clear_history()
                await manager.broadcast({"type": "history_cleared"})

            elif action == "panic":
                ai_engine.clear_history()
                await manager.broadcast({"type": "panic_clear"})

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket handler error: {e}")
        manager.disconnect(websocket)
    finally:
        if is_mobile:
            reset_companion_state()
            await manager.broadcast({
                "type": "companion_status",
                "connected": False
            })

@app.post("/api/companion/disconnect", dependencies=[Depends(verify_pairing_token)])
async def api_disconnect_companion():
    reset_companion_state()
    await manager.disconnect_mobile_clients()
    new_token = regenerate_pairing_token()
    await manager.broadcast({
        "type": "companion_status",
        "connected": False
    })
    await manager.broadcast({
        "type": "pairing_token_updated",
        "token": new_token,
        "mobile_url": get_mobile_url()
    })
    return {"success": True, "token": new_token, "mobile_url": get_mobile_url()}

@app.post("/api/companion/takeover", dependencies=[Depends(verify_pairing_token)])
async def api_takeover_companion():
    # 1. Stop any active copilot session that was running
    if copilot_session_state.get("is_active"):
        session_history.end_session()
        copilot_session_state["is_active"] = False
        copilot_session_state["started_at"] = None
        await manager.broadcast({
            "type": "copilot_ended"
        })

    # 2. Reset companion and forcefully disconnect mobile clients
    reset_companion_state()
    await manager.disconnect_mobile_clients()
    new_token = regenerate_pairing_token()

    # 3. Broadcast status updates
    await manager.broadcast({
        "type": "companion_status",
        "connected": False
    })
    await manager.broadcast({
        "type": "pairing_token_updated",
        "token": new_token,
        "mobile_url": get_mobile_url()
    })
    return {"success": True, "token": new_token, "mobile_url": get_mobile_url()}
