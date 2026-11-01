from typing import Optional, Dict, Any
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request

from core.state import (
    verify_pairing_token,
    session_history,
    reset_session_metrics,
    copilot_session_state,
    companion_state,
    manager,
    get_billing_rate,
    get_credits_balance,
    deduct_credit_usage,
    start_call_billing_ticker,
    stop_call_billing_ticker,
    current_state,
)

router = APIRouter(prefix="/api/history", tags=["history"])

@router.get("", dependencies=[Depends(verify_pairing_token)])
async def api_get_session_history():
    return {"sessions": session_history.list_sessions()}

@router.delete("/{session_id}", dependencies=[Depends(verify_pairing_token)])
async def api_delete_session_history(session_id: str):
    if not session_history.delete_session(session_id):
        raise HTTPException(status_code=404, detail="Session history was not found.")
    await manager.broadcast({"type": "session_history_deleted", "session_id": session_id})
    return {"success": True}

@router.post("/session/start", dependencies=[Depends(verify_pairing_token)])
async def api_start_session_history(request: Request):
    source = request.headers.get("x-device", "").lower().strip()
    if not source:
        source = request.query_params.get("source", "desktop").lower().strip()

    # Protection: Disconnected mobile companion cannot start a session
    if source == "mobile" and not companion_state.get("mobile_connected"):
        raise HTTPException(status_code=403, detail="Mobile companion is disconnected. Scan QR code to pair.")

    # Billing Pre-check: Check if user has enough balance for at least 1 minute
    call_rate = get_billing_rate("call_per_minute")
    current_balance = get_credits_balance()
    if current_balance < call_rate:
        raise HTTPException(
            status_code=402,
            detail=f"Insufficient credit points to start Copilot session. ({current_balance:.2f} available, {call_rate:.2f} points required for 1 min call)."
        )

    # Upfront deduction for minute 1
    tx = deduct_credit_usage(
        amount=call_rate,
        description=f"Call Minute 1 (-{call_rate:.2f} pts)",
        user_name=current_state.get("profile_name", ""),
        user_email=current_state.get("profile_email", ""),
        user_phone=current_state.get("profile_phone", ""),
        duration="1m",
        total_snaps=0,
        count=0
    )
    if tx:
        await manager.broadcast({
            "type": "credits_updated",
            "balance": tx["balance_after"],
            "transaction": tx
        })

    session_history.start_session()
    reset_session_metrics()
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    copilot_session_state["is_active"] = True
    copilot_session_state["started_at"] = now_ms

    # Start live 60-second background billing ticker
    start_call_billing_ticker()

    await manager.broadcast({
        "type": "copilot_started",
        "start_time": now_ms,
        "source": source
    })
    return {"success": True, "start_time": now_ms, "source": source}

@router.post("/session/end", dependencies=[Depends(verify_pairing_token)])
async def api_end_session_history():
    stop_call_billing_ticker()
    session_history.end_session()
    copilot_session_state["is_active"] = False
    copilot_session_state["started_at"] = None
    await manager.broadcast({
        "type": "copilot_ended"
    })
    return {"success": True}
