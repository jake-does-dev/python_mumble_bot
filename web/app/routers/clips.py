from fastapi import APIRouter, Depends
from typing import List, Optional
from app.auth import get_current_user
from app.services.clips import ClipsService
from app.services.favourites import FavouritesService

router = APIRouter(prefix="/api/clips", tags=["clips"])

@router.get("/")
def get_clips(
    search: Optional[str] = None,
    tag: Optional[str] = None,
    favourites_only: bool = False,
    current_user: str = Depends(get_current_user)
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

@router.post("/{identifier}/favourite")
def toggle_favourite(identifier: str, current_user: str = Depends(get_current_user)):
    is_favourite = FavouritesService().toggle_favourite(current_user, identifier)
    return {"is_favourite": is_favourite}