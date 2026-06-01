from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth import get_current_user
from app.database import get_db
from app.services.commands import CommandsService

router = APIRouter(prefix="/api/voice", tags=["voice"])


class JoinRequest(BaseModel):
    channel_id: str


@router.get("/channels")
def list_channels(current_user: str = Depends(get_current_user)):
    db = get_db()
    state = db.voice_state.find_one({"_id": "state"}, {"_id": 0}) or {}
    return {
        "channels": state.get("channels", []),
        "current_channel_id": state.get("current_channel_id"),
    }


@router.post("/join")
def join(body: JoinRequest, current_user: str = Depends(get_current_user)):
    CommandsService().enqueue_join(body.channel_id, requested_by=current_user)
    return {"message": "join requested"}


@router.post("/leave")
def leave(current_user: str = Depends(get_current_user)):
    CommandsService().enqueue_leave(requested_by=current_user)
    return {"message": "leave requested"}
