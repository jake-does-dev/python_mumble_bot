from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import get_current_user
from app.services.clips import ClipsService
from app.services.entrance import MAX_CLIPS, EntranceService
from app.services.users import UsersService

router = APIRouter(prefix="/api/entrance", tags=["entrance"])

_NOT_LINKED = "Link your account to a voice user first (ask an admin)."


class ClipSetting(BaseModel):
    clip_ref: str
    speed: float = 1.0
    pitch: int = 0


class EntranceRequest(BaseModel):
    clips: List[ClipSetting]


def _validate_clips(settings: List[ClipSetting]) -> List[dict]:
    """Resolve each ref to a real clip, clamp speed/pitch, cap the count."""
    clips_service = ClipsService()
    out = []
    for s in settings[:MAX_CLIPS]:
        clip = clips_service.get_clip_by_ref(s.clip_ref)
        if not clip:
            raise HTTPException(status_code=400, detail=f"Unknown clip: {s.clip_ref}")
        out.append(
            {
                "clip_ref": clip["identifier"],
                "clip_name": clip["name"],
                "speed": max(0.5, min(2.0, float(s.speed))),
                "pitch": max(-12, min(12, int(s.pitch))),
            }
        )
    return out


def _my_voice_id(username: str) -> str:
    user = UsersService().get_user(username) or {}
    return user.get("voice_id")


# -- self-service ------------------------------------------------------------


@router.get("/me")
def get_mine(current_user: str = Depends(get_current_user)):
    voice_id = _my_voice_id(current_user)
    if not voice_id:
        return {"voice_linked": False, "clips": []}
    doc = EntranceService().get_for_voice(voice_id) or {}
    return {"voice_linked": True, "voice_id": voice_id, "clips": doc.get("clips", [])}


@router.put("/me")
def set_mine(body: EntranceRequest, current_user: str = Depends(get_current_user)):
    voice_id = _my_voice_id(current_user)
    if not voice_id:
        raise HTTPException(status_code=403, detail=_NOT_LINKED)
    clips = _validate_clips(body.clips)
    EntranceService().set_for_voice(voice_id, clips, updated_by=current_user)
    return {"clips": clips}


@router.delete("/me")
def clear_mine(current_user: str = Depends(get_current_user)):
    voice_id = _my_voice_id(current_user)
    if voice_id:
        EntranceService().clear(voice_id)
    return {"message": "cleared"}


# -- admin: manage anyone's --------------------------------------------------


def _require_admin(current_user: str):
    if not UsersService().is_admin(current_user):
        raise HTTPException(status_code=403, detail="Admins only")


@router.get("/")
def list_all(current_user: str = Depends(get_current_user)):
    _require_admin(current_user)
    return {"entrances": EntranceService().get_all()}


@router.put("/{voice_id}")
def set_for(
    voice_id: str, body: EntranceRequest, current_user: str = Depends(get_current_user)
):
    _require_admin(current_user)
    clips = _validate_clips(body.clips)
    EntranceService().set_for_voice(voice_id, clips, updated_by=current_user)
    return {"voice_id": voice_id, "clips": clips}


@router.delete("/{voice_id}")
def clear_for(voice_id: str, current_user: str = Depends(get_current_user)):
    _require_admin(current_user)
    EntranceService().clear(voice_id)
    return {"message": "cleared"}
