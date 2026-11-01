import secrets
import datetime
from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException

from core.state import (
    verify_pairing_token,
    load_app_notes,
    save_app_notes,
    manager,
    get_billing_rate,
    get_credits_balance,
    deduct_credit_usage,
    current_state,
)

router = APIRouter(prefix="/api/notes", tags=["notes"])

@router.get("", dependencies=[Depends(verify_pairing_token)])
async def api_get_notes():
    """Retrieve saved notebook and cheat-sheet notes."""
    return {"success": True, "notes": load_app_notes()}

@router.post("", dependencies=[Depends(verify_pairing_token)])
async def api_save_note(payload: Dict[str, Any]):
    """Create a new note or update an existing one."""
    title = (payload.get("title") or "").strip()
    content = (payload.get("content") or "").strip()
    note_id = payload.get("id")

    if not title and not content:
        raise HTTPException(status_code=400, detail="Note must have a title or content.")

    # Strict Backend Title Length Validation (Max 50 chars)
    if len(title) > 50:
        raise HTTPException(
            status_code=400,
            detail=f"Note title exceeds maximum allowed limit of 50 characters ({len(title)}/50 entered)."
        )

    # Strict Backend Character Length Validation (Max 500 chars)
    max_chars = get_billing_rate("note_max_chars")
    if len(content) > max_chars:
        raise HTTPException(
            status_code=400,
            detail=f"Note content exceeds maximum allowed limit of {max_chars} characters ({len(content)}/{max_chars} entered)."
        )

    # Billing Deduction: Only charged when creating a NEW note
    is_new_note = not bool(note_id)
    if is_new_note:
        note_rate = get_billing_rate("note_per_count")
        current_balance = get_credits_balance()
        if current_balance < note_rate:
            raise HTTPException(
                status_code=402,
                detail=f"Insufficient credit points to create a new note. ({current_balance:.2f} available, {note_rate:.2f} points required)."
            )

    if not title:
        first_line = content.split("\n")[0].strip()
        title = first_line[:50] if first_line else "Untitled Note"

    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    notes = load_app_notes()

    target_note = None
    if note_id:
        for note in notes:
            if note.get("id") == note_id:
                note["title"] = title
                note["content"] = content
                note["updated_at"] = now_str
                target_note = note
                break

    if not target_note:
        note_id = f"note_{int(datetime.datetime.now().timestamp())}_{secrets.token_hex(3)}"
        target_note = {
            "id": note_id,
            "title": title,
            "content": content,
            "created_at": now_str,
            "updated_at": now_str
        }
        notes.insert(0, target_note)

        # Deduct note_per_count credits for new note
        note_rate = get_billing_rate("note_per_count")
        tx = deduct_credit_usage(
            amount=note_rate,
            description=f"Quick Note Created (-{note_rate:.2f} pts)",
            user_name=current_state.get("profile_name", ""),
            user_email=current_state.get("profile_email", ""),
            user_phone=current_state.get("profile_phone", ""),
            total_snaps=0,
            count=0
        )
        if tx:
            await manager.broadcast({
                "type": "credits_updated",
                "balance": tx["balance_after"],
                "transaction": tx
            })

    notes.sort(key=lambda n: n.get("updated_at", ""), reverse=True)
    save_app_notes(notes)

    await manager.broadcast({
        "type": "notes_updated",
        "notes": notes
    })
    return {"success": True, "note": target_note, "notes": notes}

@router.delete("/{note_id}", dependencies=[Depends(verify_pairing_token)])
async def api_delete_note(note_id: str):
    """Delete a note by its unique ID."""
    notes = load_app_notes()
    new_notes = [n for n in notes if n.get("id") != note_id]
    if len(new_notes) == len(notes):
        raise HTTPException(status_code=404, detail="Note was not found.")

    save_app_notes(new_notes)
    await manager.broadcast({
        "type": "notes_updated",
        "notes": new_notes
    })
    return {"success": True, "notes": new_notes}
