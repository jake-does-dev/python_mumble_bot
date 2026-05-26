from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.auth import get_current_user
from app.services.clips import ClipsService
from app.services.favourites import FavouritesService
from app.services.users import UsersService

router = APIRouter(prefix="/api/clips", tags=["clips"])

_VALID_EXTENSIONS = {".wav", ".mp3"}


@router.get("/")
def get_clips(
    search: Optional[str] = None,
    tag: Optional[str] = None,
    favourites_only: bool = False,
    current_user: str = Depends(get_current_user),
):
    clips_service = ClipsService()
    favourites_service = FavouritesService()

    clips = clips_service.get_clips(search=search, tag=tag)
    favourite_refs = set(favourites_service.get_favourites(current_user))

    for clip in clips:
        clip["is_favourite"] = clip["identifier"] in favourite_refs

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
    current_user: str = Depends(get_current_user),
):
    ext = Path(file.filename).suffix.lower()
    if ext not in _VALID_EXTENSIONS:
        raise HTTPException(400, "Only .wav and .mp3 files are accepted")

    contents = await file.read()
    clip_name = name.strip() or Path(file.filename).stem
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]

    return ClipsService().upload_clip(clip_name, ext, contents, tag_list)


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
