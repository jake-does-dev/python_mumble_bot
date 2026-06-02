import time
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth import get_current_user
from app.services.clips import ClipsService
from app.services.commands import CommandsService
from app.services.presence import enforce_presence
from app.services.users import UsersService

router = APIRouter(prefix="/api/commands", tags=["commands"])

# Per-user cooldown between queue plays (in-process; single uvicorn worker).
QUEUE_COOLDOWN_SECONDS = 30
_last_queue_play = {}

# Per-user burst limit on single plays (anti-spam for held/mashed pad keys).
PLAY_RATE_MAX = 10
PLAY_RATE_WINDOW = 30  # seconds
_play_times = {}  # username -> list[monotonic timestamps within the window]


def _check_play_rate(user: str) -> None:
    now = time.monotonic()
    times = [t for t in _play_times.get(user, []) if now - t < PLAY_RATE_WINDOW]
    if len(times) >= PLAY_RATE_MAX:
        retry = int(PLAY_RATE_WINDOW - (now - times[0])) + 1
        _play_times[user] = times
        raise HTTPException(
            status_code=429,
            detail=f"Slow down — max {PLAY_RATE_MAX} plays per {PLAY_RATE_WINDOW}s (wait {retry}s)",
        )
    times.append(now)
    _play_times[user] = times


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
    enforce_presence(current_user, "play")
    _check_play_rate(current_user)
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


@router.get("/last-stop")
def last_stop(current_user: str = Depends(get_current_user)):
    # Lets every client detect a stop (broadcast a toast to all users).
    return CommandsService().last_stop()


@router.post("/stop")
def stop_playback(current_user: str = Depends(get_current_user)):
    # Emergency stop is admin-only.
    if not UsersService().is_admin(current_user):
        raise HTTPException(status_code=403, detail="Admin access required")
    CommandsService().enqueue_stop(requested_by=current_user)
    return {"message": "Playback stopped"}


@router.post("/play-queue")
def play_queue(body: PlayQueueRequest, current_user: str = Depends(get_current_user)):
    enforce_presence(current_user, "queue")
    now = time.monotonic()
    elapsed = now - _last_queue_play.get(current_user, 0)
    if elapsed < QUEUE_COOLDOWN_SECONDS:
        remaining = int(QUEUE_COOLDOWN_SECONDS - elapsed) + 1
        raise HTTPException(
            status_code=429,
            detail=f"Wait {remaining}s before playing another queue",
        )

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
    _last_queue_play[current_user] = now
    return {"message": f"Queued {len(resolved)} clips"}