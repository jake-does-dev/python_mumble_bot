import os
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.security import OAuth2PasswordRequestForm
from app.auth import create_access_token, get_current_user
from app.services.users import UsersService
from app.models.users import Token, UserCreate
from app.limiter import limiter
from pydantic import BaseModel

VOICE_CONTROL_ENABLED = os.getenv("VOICE_CONTROL_ENABLED", "").lower() in (
    "1",
    "true",
    "yes",
)
PLAY_REQUIRES_PRESENCE = os.getenv("PLAY_REQUIRES_PRESENCE", "").lower() in (
    "1",
    "true",
    "yes",
)
# "Clip that" capture: only the Mumble stack runs a bot that buffers audio, so
# gate the UI tab on this flag (the shared web image also serves the Discord stack).
CLIP_CAPTURE_ENABLED = os.getenv("CLIP_CAPTURE_ENABLED", "").lower() in (
    "1",
    "true",
    "yes",
)

router = APIRouter(prefix="/api/users", tags=["users"])

class ChangePassword(BaseModel):
    current_password: str
    new_password: str

class VoiceLink(BaseModel):
    voice_id: Optional[str] = None
    voice_name: Optional[str] = None

class CaptureOptin(BaseModel):
    opt_in: bool

@router.post("/login", response_model=Token)
@limiter.limit("5/minute")
def login(request: Request, form_data: OAuth2PasswordRequestForm = Depends()):
    if not UsersService().authenticate(form_data.username, form_data.password):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token = create_access_token({"sub": form_data.username})
    return {"access_token": token, "token_type": "bearer"}

@router.post("/register")
def register(user: UserCreate, current_user: str = Depends(get_current_user)):
    users_service = UsersService()
    if not users_service.is_admin(current_user):
        raise HTTPException(status_code=403, detail="Only admins can register new users")
    if not users_service.create_user(user.username, user.password):
        raise HTTPException(status_code=400, detail="Username already exists")
    return {"message": "User created successfully"}

@router.get("/me")
def me(current_user: str = Depends(get_current_user)):
    users_service = UsersService()
    user = users_service.get_user(current_user) or {}
    return {
        "username": current_user,
        "is_admin": users_service.is_admin(current_user),
        "voice_control": VOICE_CONTROL_ENABLED,
        "clip_capture": CLIP_CAPTURE_ENABLED,
        "presence_required": PLAY_REQUIRES_PRESENCE,
        "voice_linked": bool(user.get("voice_id")),
        "voice_name": user.get("voice_name"),
        "capture_optin": bool(user.get("capture_optin")),
    }

@router.get("/")
def list_users(current_user: str = Depends(get_current_user)):
    users_service = UsersService()
    if not users_service.is_admin(current_user):
        raise HTTPException(status_code=403, detail="Admin access required")
    return users_service.list_users()

@router.patch("/{username}/voice")
def set_voice_link(
    username: str, body: VoiceLink, current_user: str = Depends(get_current_user)
):
    users_service = UsersService()
    if not users_service.is_admin(current_user):
        raise HTTPException(status_code=403, detail="Admin access required")
    if not users_service.set_voice_link(username, body.voice_id, body.voice_name):
        raise HTTPException(status_code=404, detail="User not found")
    return {"message": "Voice link updated"}

@router.put("/me/capture-optin")
def set_capture_optin(
    body: CaptureOptin, current_user: str = Depends(get_current_user)
):
    # Self-service consent to being clipped. Until you opt in, the bot drops your
    # audio and never buffers it, so there's nothing anyone could clip.
    if not UsersService().set_capture_optin(current_user, body.opt_in):
        raise HTTPException(status_code=404, detail="User not found")
    return {"capture_optin": body.opt_in}

@router.post("/change-password")
def change_password(body: ChangePassword, current_user: str = Depends(get_current_user)):
    users_service = UsersService()
    if not users_service.authenticate(current_user, body.current_password):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    users_service.change_password(current_user, body.new_password)
    return {"message": "Password changed successfully"}