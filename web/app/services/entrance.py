from datetime import datetime
from typing import List, Optional

from app.database import get_db

# Keep entrance sequences short — they play before the person can do anything.
MAX_CLIPS = 3


class EntranceService:
    """Per-voice-identity entrance sounds: clips the bot plays when that user
    joins its channel. Keyed by `voice_id` (Mumble username / Discord user id),
    the same identity the presence (`voice_state`) uses."""

    def __init__(self):
        self.db = get_db()

    def get_for_voice(self, voice_id: str) -> Optional[dict]:
        return self.db.entrance_sounds.find_one({"_id": voice_id}, {"_id": 0})

    def get_all(self) -> List[dict]:
        return list(self.db.entrance_sounds.find({}, {"_id": 0}))

    def set_for_voice(self, voice_id: str, clips: List[dict], updated_by: str) -> dict:
        doc = {
            "voice_id": voice_id,
            "clips": clips[:MAX_CLIPS],
            "updated_by": updated_by,
            "updated_at": datetime.utcnow(),
        }
        self.db.entrance_sounds.replace_one(
            {"_id": voice_id}, {"_id": voice_id, **doc}, upsert=True
        )
        return doc

    def clear(self, voice_id: str) -> None:
        self.db.entrance_sounds.delete_one({"_id": voice_id})
