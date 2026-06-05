import time

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.auth import get_current_user
from app.services.clips import ClipsService
from app.services.commands import CommandsService
from app.services.presence import enforce_presence
from app.services.songs import SongsService
from app.services.users import UsersService

router = APIRouter(prefix="/api/songs", tags=["songs"])

# Per-user cooldown between song plays (a song is a heavier render than a clip).
SONG_COOLDOWN_SECONDS = 10
_last_song_play = {}


class RenameSongRequest(BaseModel):
    name: str


class PlaySongRequest(BaseModel):
    clip_ref: str
    clip_name: str = ""
    transpose: int = Field(default=0, ge=-24, le=24)
    speed: float = Field(default=1.0, ge=0.25, le=4.0)
    gain: float = Field(default=0.0, ge=-30.0, le=30.0)
    max_seconds: float = Field(default=0.0, ge=0.0, le=600.0)  # 0 = full song


@router.get("/")
def list_songs(current_user: str = Depends(get_current_user)):
    return SongsService().list_songs()


@router.get("/history")
def song_history(current_user: str = Depends(get_current_user)):
    return SongsService().get_history()


@router.post("/upload")
async def upload_song(
    file: UploadFile = File(...),
    current_user: str = Depends(get_current_user),
):
    contents = await file.read()
    return SongsService().upload_song(file.filename, contents, uploaded_by=current_user)


@router.patch("/{song_id}")
def rename_song(
    song_id: str,
    body: RenameSongRequest,
    current_user: str = Depends(get_current_user),
):
    is_admin = UsersService().is_admin(current_user)
    return SongsService().rename_song(
        song_id, body.name, requested_by=current_user, is_admin=is_admin
    )


@router.delete("/{song_id}")
def delete_song(song_id: str, current_user: str = Depends(get_current_user)):
    is_admin = UsersService().is_admin(current_user)
    SongsService().delete_song(song_id, requested_by=current_user, is_admin=is_admin)
    return {"message": f"Deleted {song_id}"}


@router.post("/{song_id}/play")
def play_song(
    song_id: str,
    body: PlaySongRequest,
    current_user: str = Depends(get_current_user),
):
    enforce_presence(current_user, "song")
    now = time.monotonic()
    elapsed = now - _last_song_play.get(current_user, 0)
    if elapsed < SONG_COOLDOWN_SECONDS:
        remaining = int(SONG_COOLDOWN_SECONDS - elapsed) + 1
        raise HTTPException(429, f"Wait {remaining}s before playing another song")

    song = SongsService().get_song(song_id)
    if not song:
        raise HTTPException(404, f"Song '{song_id}' not found")

    clip = ClipsService().get_clip_by_ref(body.clip_ref)
    if not clip:
        raise HTTPException(404, f"Clip '{body.clip_ref}' not found")

    CommandsService().enqueue_song(
        song_id=song["id"],
        song_filename=song["filename"],
        song_name=song["name"],
        clip_ref=body.clip_ref,
        clip_name=body.clip_name or clip["name"],
        requested_by=current_user,
        transpose=body.transpose,
        speed=body.speed,
        gain=body.gain,
        max_seconds=body.max_seconds,
    )
    _last_song_play[current_user] = now
    return {"message": f"Playing {song['name']} on {clip['name']}"}
