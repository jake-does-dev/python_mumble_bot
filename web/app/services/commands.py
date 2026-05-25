from datetime import datetime
from typing import Optional
from app.database import get_db


class CommandsService:
    def __init__(self):
        self.db = get_db()

    def enqueue_play(self, clip_ref: str, requested_by: str) -> dict:
        command = {
            "clip_ref": clip_ref,
            "requested_by": requested_by,
            "status": "pending",
            "created_at": datetime.utcnow()
        }
        self.db.pending_commands.insert_one(command)
        return command

    def get_next_pending(self) -> Optional[dict]:
        return self.db.pending_commands.find_one({"status": "pending"})

    def mark_done(self, command_id) -> None:
        self.db.pending_commands.update_one(
            {"_id": command_id},
            {"$set": {"status": "done"}}
        )