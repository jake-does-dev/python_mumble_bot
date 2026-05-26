from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from app.auth import get_current_user
from app.services.commands import CommandsService
from app.services.clips import ClipsService

router = APIRouter(prefix="/api/commands", tags=["commands"])

class PlayOptions(BaseModel):
    pitch: int = Field(default=0, ge=-12, le=12)
    speed: float = Field(default=1.0, ge=0.05, le=4.0)  # 0.05 is ffmpeg's lower limit

@router.get("/history")
def get_history(current_user: str = Depends(get_current_user)):
    return CommandsService().get_history()

@router.post("/play/{clip_ref}")
def play_clip(clip_ref: str, options: PlayOptions = PlayOptions(), current_user: str = Depends(get_current_user)):
    clip = ClipsService().get_clip_by_ref(clip_ref)
    if not clip:
        raise HTTPException(status_code=404, detail=f"Clip '{clip_ref}' not found")

    CommandsService().enqueue_play(clip_ref, clip_name=clip["name"], requested_by=current_user, pitch=options.pitch, speed=options.speed)
    return {"message": f"Playing {clip_ref}"}