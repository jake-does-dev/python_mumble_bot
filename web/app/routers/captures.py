from typing import List, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.auth import get_current_user
from app.services.captures import CapturesService
from app.services.commands import CommandsService
from app.services.presence import enforce_presence
from app.services.users import UsersService

router = APIRouter(prefix="/api/captures", tags=["captures"])

MAX_DURATION = 30


class CaptureRequest(BaseModel):
    target_voice: str
    duration: float = MAX_DURATION


class SaveRequest(BaseModel):
    name: str
    tags: List[str] = []
    start: Optional[float] = None
    end: Optional[float] = None


@router.post("/")
def trigger_capture(
    body: CaptureRequest, current_user: str = Depends(get_current_user)
):
    # Capturing makes the bot grab recent audio on your behalf, so require the
    # same presence as playing (but not mic/audio-on — you can clip while muted).
    enforce_presence(current_user, "capture")
    duration = max(1.0, min(float(body.duration or MAX_DURATION), MAX_DURATION))
    CommandsService().enqueue_capture(body.target_voice, duration, current_user)
    return {
        "status": "queued",
        "target_voice": body.target_voice,
        "duration": duration,
    }


@router.get("/pending")
def list_pending(current_user: str = Depends(get_current_user)):
    return CapturesService().list_pending()


@router.get("/{capture_id}/audio")
def capture_audio(capture_id: str, current_user: str = Depends(get_current_user)):
    path = CapturesService().get_audio_path(capture_id)
    return FileResponse(path, media_type="audio/wav")


@router.post("/{capture_id}/save")
def save_capture(
    capture_id: str,
    body: SaveRequest,
    current_user: str = Depends(get_current_user),
):
    is_admin = UsersService().is_admin(current_user)
    return CapturesService().promote(
        capture_id,
        body.name.strip(),
        [t.strip() for t in body.tags if t.strip()],
        body.start,
        body.end,
        current_user,
        is_admin,
    )


@router.delete("/{capture_id}")
def discard_capture(capture_id: str, current_user: str = Depends(get_current_user)):
    is_admin = UsersService().is_admin(current_user)
    CapturesService().discard(capture_id, current_user, is_admin)
    return {"message": "Capture discarded"}
