import secrets
import datetime
from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException

from core.state import (
    verify_pairing_token,
    load_app_notes,
    save_app_notes,
    manager,
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

    if not title:
        first_line = content.split("\n")[0].strip()
        title = first_line[:40] if first_line else "Untitled Note"

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
