from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth import get_current_user
from app.services.clips import ClipsService
from app.services.commands import CommandsService

router = APIRouter(prefix="/api/commands", tags=["commands"])


class PlayOptions(BaseModel):
    pitch: int = Field(default=0, ge=-12, le=12)
    speed: float = Field(default=1.0, ge=0.5, le=4.0)  # 0.5x minimum playback speed


class QueueItem(BaseModel):
    clip_ref: str
    clip_name: str = ""
    pitch: int = Field(default=0, ge=-12, le=12)
    speed: float = Field(default=1.0, ge=0.5, le=4.0)


class PlayQueueRequest(BaseModel):
    queue_name: str = "Queue"
    items: List[QueueItem]


@router.get("/history")
def get_history(current_user: str = Depends(get_current_user)):
    return CommandsService().get_history()


@router.post("/play/{clip_ref}")
def play_clip(
    clip_ref: str,
    options: PlayOptions = PlayOptions(),
    current_user: str = Depends(get_current_user),
):
    clip = ClipsService().get_clip_by_ref(clip_ref)
    if not clip:
        raise HTTPException(status_code=404, detail=f"Clip '{clip_ref}' not found")

    CommandsService().enqueue_play(
        clip_ref,
        clip_name=clip["name"],
        requested_by=current_user,
        pitch=options.pitch,
        speed=options.speed,
    )
    return {"message": f"Playing {clip_ref}"}


@router.post("/play-queue")
def play_queue(body: PlayQueueRequest, current_user: str = Depends(get_current_user)):
    if not body.items:
        raise HTTPException(status_code=400, detail="Queue is empty")

    clips_service = ClipsService()
    resolved = []
    for item in body.items:
        clip = clips_service.get_clip_by_ref(item.clip_ref)
        if not clip:
            raise HTTPException(
                status_code=404, detail=f"Clip '{item.clip_ref}' not found"
            )
        resolved.append(
            {
                "clip_ref": item.clip_ref,
                "clip_name": item.clip_name or clip["name"],
                "pitch": item.pitch,
                "speed": item.speed,
            }
        )

    CommandsService().enqueue_queue(resolved, current_user, body.queue_name)
    return {"message": f"Queued {len(resolved)} clips"}