from datetime import datetime
from typing import Optional
import pymongo
from app.database import get_db

HISTORY_LIMIT = 50


class CommandsService:
    def __init__(self):
        self.db = get_db()

    def get_history(self) -> list:
        commands = list(
            self.db.pending_commands.find(
                {"status": "done"},
                sort=[("created_at", pymongo.DESCENDING)],
                limit=HISTORY_LIMIT,
            )
        )
        clip_refs = [c["clip_ref"] for c in commands]
        clips = {
            c["identifier"]: c["name"]
            for c in self.db.clips.find({"identifier": {"$in": clip_refs}})
        }
        return [
            {
                "clip_ref": c["clip_ref"],
                "clip_name": clips.get(c["clip_ref"], c["clip_ref"]),
                "requested_by": c["requested_by"],
                "played_at": c["created_at"].isoformat() + "Z",
            }
            for c in commands
        ]

    def enqueue_play(self, clip_ref: str, requested_by: str, pitch: int = 0, speed: float = 1.0) -> dict:
        command = {
            "clip_ref": clip_ref,
            "requested_by": requested_by,
            "status": "pending",
            "created_at": datetime.utcnow(),
            "pitch": pitch,
            "speed": speed,
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