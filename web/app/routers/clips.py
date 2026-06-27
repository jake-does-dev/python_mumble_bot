from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.auth import get_current_user
from app.services.clips import AUDIO_DIR, ClipsService
from app.services.favourites import FavouritesService
from app.services.users import UsersService
from app.services.votes import VotesService

router = APIRouter(prefix="/api/clips", tags=["clips"])

_VALID_EXTENSIONS = {".wav", ".mp3"}


class ClipUpdate(BaseModel):
    name: Optional[str] = None
    tags: Optional[List[str]] = None


class VoteRequest(BaseModel):
    value: int


class TrimRequest(BaseModel):
    start: float
    end: float


class GainRequest(BaseModel):
    gain_db: float


@router.get("/")
def get_clips(
    search: Optional[str] = None,
    tag: Optional[str] = None,
    favourites_only: bool = False,
    current_user: str = Depends(get_current_user),
):
    clips_service = ClipsService()
    favourites_service = FavouritesService()
    votes_service = VotesService()

    clips = clips_service.get_clips(search=search, tag=tag)
    favourite_refs = set(favourites_service.get_favourites(current_user))
    scores = votes_service.scores()
    my_votes = votes_service.user_votes(current_user)

    for clip in clips:
        clip["is_favourite"] = clip["identifier"] in favourite_refs
        clip["score"] = scores.get(clip["identifier"], 0)
        clip["my_vote"] = my_votes.get(clip["identifier"], 0)

    if favourites_only:
        clips = [c for c in clips if c["is_favourite"]]

    return clips


@router.get("/tags")
def get_tags(current_user: str = Depends(get_current_user)):
    return ClipsService().get_all_tags()


@router.post("/upload")
async def upload_clip(
    file: UploadFile = File(...),
    name: str = Form(default=""),
    tags: str = Form(default=""),
    start: Optional[float] = Form(default=None),
    end: Optional[float] = Form(default=None),
    current_user: str = Depends(get_current_user),
):
    ext = Path(file.filename).suffix.lower()
    if ext not in _VALID_EXTENSIONS:
        raise HTTPException(400, "Only .wav and .mp3 files are accepted")

    contents = await file.read()
    clip_name = name.strip() or Path(file.filename).stem
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]

    return ClipsService().upload_clip(
        clip_name, ext, contents, tag_list,
        uploaded_by=current_user, start=start, end=end,
    )


@router.patch("/{identifier}")
def edit_clip(
    identifier: str,
    body: ClipUpdate,
    current_user: str = Depends(get_current_user),
):
    is_admin = UsersService().is_admin(current_user)
    name = body.name.strip() if body.name is not None else None
    return ClipsService().update_clip(
        identifier, current_user, is_admin, name=name, tags=body.tags
    )


@router.post("/{identifier}/vote")
def vote_clip(
    identifier: str,
    body: VoteRequest,
    current_user: str = Depends(get_current_user),
):
    return VotesService().set_vote(current_user, identifier, body.value)


@router.post("/{identifier}/trim")
def trim_clip(
    identifier: str,
    body: TrimRequest,
    current_user: str = Depends(get_current_user),
):
    is_admin = UsersService().is_admin(current_user)
    return ClipsService().trim_clip(
        identifier, current_user, is_admin, body.start, body.end
    )


@router.patch("/{identifier}/gain")
def set_gain(
    identifier: str,
    body: GainRequest,
    current_user: str = Depends(get_current_user),
):
    if not UsersService().is_admin(current_user):
        raise HTTPException(403, "Admin access required")
    return ClipsService().set_gain(identifier, body.gain_db)


@router.post("/{identifier}/revert")
def revert_clip(identifier: str, current_user: str = Depends(get_current_user)):
    is_admin = UsersService().is_admin(current_user)
    return ClipsService().revert_clip(identifier, current_user, is_admin)


@router.get("/{identifier}/audio")
def clip_audio(
    identifier: str,
    pitch: int = 0,
    speed: float = 1.0,
    reverse: bool = False,
    current_user: str = Depends(get_current_user),
):
    clips_service = ClipsService()
    clip = clips_service.get_clip_by_ref(identifier)
    if not clip:
        raise HTTPException(404, f"Clip '{identifier}' not found")
    path = AUDIO_DIR / clip["file"]
    if not path.exists():
        raise HTTPException(404, "Audio file not found")

    # No transform at all → serve the raw file (waveform, download, plain preview).
    pitch = max(-12, min(12, pitch))
    speed = max(0.5, min(4.0, speed))
    if pitch == 0 and abs(speed - 1.0) < 1e-3 and not reverse:
        media_type = "audio/mpeg" if path.suffix.lower() == ".mp3" else "audio/wav"
        return FileResponse(path, media_type=media_type)

    # Otherwise render it exactly as the bot would play it.
    out = clips_service.render_preview(clip, pitch, speed, reverse)
    return FileResponse(out, media_type="audio/wav")


@router.delete("/{identifier}")
def delete_clip(identifier: str, current_user: str = Depends(get_current_user)):
    if not UsersService().is_admin(current_user):
        raise HTTPException(403, "Admin access required")
    ClipsService().delete_clip(identifier)
    return {"message": f"Clip '{identifier}' deleted"}


@router.post("/{identifier}/favourite")
def toggle_favourite(
    identifier: str, current_user: str = Depends(get_current_user)
):
    is_favourite = FavouritesService().toggle_favourite(current_user, identifier)
    return {"is_favourite": is_favourite}
