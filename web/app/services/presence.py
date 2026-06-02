import os

from fastapi import HTTPException

from app.database import get_db
from app.services.users import UsersService

# When enabled, a user must be present in the bot's voice channel (and linked to
# their in-channel identity) before they can play/queue clips or move the bot.
PLAY_REQUIRES_PRESENCE = os.getenv("PLAY_REQUIRES_PRESENCE", "").lower() in (
    "1",
    "true",
    "yes",
)

_NOT_LINKED = (
    "Your account isn't linked to a voice user — ask an admin to link you."
)
_NOT_PRESENT = "You must be in the voice channel to do that."
_NOT_IN_TARGET = "You can only summon the bot to a channel you're in."


def _voice_state() -> dict:
    return get_db().voice_state.find_one({"_id": "state"}) or {}


def enforce_presence(current_user: str, action: str, channel_id: str = None) -> None:
    """Raise 403 unless the user is allowed to perform `action`.

    Admins are always exempt (also required so linking can be bootstrapped).
    `action` is one of: play, queue, leave (gate on the bot's current channel)
    or join (gate on the target `channel_id`).
    """
    if not PLAY_REQUIRES_PRESENCE:
        return

    users = UsersService()
    if users.is_admin(current_user):
        return

    user = users.get_user(current_user)
    voice_id = (user or {}).get("voice_id")
    if not voice_id:
        raise HTTPException(status_code=403, detail=_NOT_LINKED)

    state = _voice_state()

    if action == "join":
        channel = next(
            (c for c in state.get("channels", []) if str(c.get("id")) == str(channel_id)),
            None,
        )
        member_ids = {m.get("id") for m in (channel or {}).get("members", [])}
        if voice_id not in member_ids:
            raise HTTPException(status_code=403, detail=_NOT_IN_TARGET)
        return

    present_ids = {m.get("id") for m in state.get("present", [])}
    if voice_id not in present_ids:
        raise HTTPException(status_code=403, detail=_NOT_PRESENT)
