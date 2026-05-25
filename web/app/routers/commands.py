from fastapi import APIRouter, Depends, HTTPException
from app.auth import get_current_user
from app.services.commands import CommandsService
from app.services.clips import ClipsService

router = APIRouter(prefix="/api/commands", tags=["commands"])

@router.get("/history")
def get_history(current_user: str = Depends(get_current_user)):
    return CommandsService().get_history()

@router.post("/play/{clip_ref}")
def play_clip(clip_ref: str, current_user: str = Depends(get_current_user)):
    clip = ClipsService().get_clip_by_ref(clip_ref)
    if not clip:
        raise HTTPException(status_code=404, detail=f"Clip '{clip_ref}' not found")

    CommandsService().enqueue_play(clip_ref, requested_by=current_user)
    return {"message": f"Playing {clip_ref}"}