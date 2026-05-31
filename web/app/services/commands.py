from datetime import datetime, timedelta
from typing import List, Optional

import pymongo

from app.database import get_db

HISTORY_LIMIT = 50


class CommandsService:
    def __init__(self):
        self.db = get_db()

    def get_history(self) -> list:
        commands = list(
            self.db.pending_commands.find(
                {"status": "done", "type": {"$ne": "announce"}},
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
                "clip_name": c.get("clip_name") or clips.get(c["clip_ref"], c["clip_ref"]),
                "requested_by": c["requested_by"],
                "played_at": c["created_at"].isoformat() + "Z",
            }
            for c in commands
        ]

    def enqueue_play(self, clip_ref: str, clip_name: str, requested_by: str, pitch: int = 0, speed: float = 1.0) -> dict:
        command = {
            "type": "play",
            "clip_ref": clip_ref,
            "clip_name": clip_name,
            "requested_by": requested_by,
            "status": "pending",
            "created_at": datetime.utcnow(),
            "pitch": pitch,
            "speed": speed,
        }
        self.db.pending_commands.insert_one(command)
        return command

    @staticmethod
    def _fmt_cmd(clip_name: str, pitch: int, speed: float) -> str:
        return f"/pp {speed:g}x {pitch}s {clip_name}"

    def enqueue_queue(self, items: List[dict], requested_by: str, queue_name: str) -> None:
        base_time = datetime.utcnow()
        chain = " ".join(
            f"{item.get('speed', 1.0):g}x {item.get('pitch', 0)}s {item.get('clip_name') or item['clip_ref']}"
            for item in items
        )
        label = f"/pp {chain}"
        docs = [
            {
                "type": "announce",
                "message": f"<b>{requested_by}</b> queued: {label}",
                "status": "pending",
                "created_at": base_time,
            }
        ]
        for i, item in enumerate(items, start=1):
            docs.append({
                "type": "queue_play",
                "clip_ref": item["clip_ref"],
                "clip_name": item.get("clip_name") or item["clip_ref"],
                "requested_by": requested_by,
                "status": "pending",
                "created_at": base_time + timedelta(microseconds=i),
                "pitch": item.get("pitch", 0),
                "speed": item.get("speed", 1.0),
            })
        self.db.pending_commands.insert_many(docs)

    def get_next_pending(self) -> Optional[dict]:
        return self.db.pending_commands.find_one({"status": "pending"})

    def mark_done(self, command_id) -> None:
        self.db.pending_commands.update_one(
            {"_id": command_id},
            {"$set": {"status": "done"}}
        )