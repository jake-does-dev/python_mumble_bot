from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth import get_current_user
from app.database import get_db
from app.services.commands import CommandsService
from app.services.presence import enforce_presence

router = APIRouter(prefix="/api/voice", tags=["voice"])


class JoinRequest(BaseModel):
    channel_id: str


@router.get("/channels")
def list_channels(current_user: str = Depends(get_current_user)):
    db = get_db()
    state = db.voice_state.find_one({"_id": "state"}, {"_id": 0}) or {}

    # Mark who has consented to "clip that" so the UI only offers it for them.
    opted_in = {
        u["voice_id"]
        for u in db.users.find(
            {"capture_optin": True, "voice_id": {"$ne": None}}, {"voice_id": 1}
        )
        if u.get("voice_id")
    }
    present = [
        {**p, "opted_in": p.get("id") in opted_in}
        for p in state.get("present", [])
    ]
    return {
        "channels": state.get("channels", []),
        "current_channel_id": state.get("current_channel_id"),
        # Who's in the bot's channel right now — the "clip that" target list.
        "present": present,
    }


@router.post("/join")
def join(body: JoinRequest, current_user: str = Depends(get_current_user)):
    enforce_presence(current_user, "join", body.channel_id)
    CommandsService().enqueue_join(body.channel_id, requested_by=current_user)
    return {"message": "join requested"}


@router.post("/leave")
def leave(current_user: str = Depends(get_current_user)):
    enforce_presence(current_user, "leave")
    CommandsService().enqueue_leave(requested_by=current_user)
    return {"message": "leave requested"}
