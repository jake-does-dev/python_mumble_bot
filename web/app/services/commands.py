from datetime import datetime, timedelta
from typing import List, Optional

import pymongo

from app.database import get_db

HISTORY_LIMIT = 50


class CommandsService:
    def __init__(self):
        self.db = get_db()

    def get_history(self) -> list:
        entries = list(
            self.db.play_log.find(
                {},
                sort=[("played_at", pymongo.DESCENDING)],
                limit=HISTORY_LIMIT,
            )
        )
        clip_refs = [e["clip_ref"] for e in entries]
        clips = {
            c["identifier"]: c["name"]
            for c in self.db.clips.find({"identifier": {"$in": clip_refs}})
        }
        return [
            {
                "clip_ref": e["clip_ref"],
                "clip_name": clips.get(e["clip_ref"]) or e.get("clip_name") or e["clip_ref"],
                "requested_by": e["requested_by"],
                "played_at": e["played_at"].isoformat() + "Z",
            }
            for e in entries
        ]

    def _log_play(self, clip_ref, clip_name, requested_by, pitch, speed, played_at):
        # Durable, append-only record for stats (pending_commands is TTL'd).
        self.db.play_log.insert_one(
            {
                "clip_ref": clip_ref,
                "clip_name": clip_name,
                "requested_by": requested_by,
                "pitch": pitch,
                "speed": speed,
                "played_at": played_at,
            }
        )

    def enqueue_play(self, clip_ref: str, clip_name: str, requested_by: str, pitch: int = 0, speed: float = 1.0) -> dict:
        now = datetime.utcnow()
        command = {
            "type": "play",
            "clip_ref": clip_ref,
            "clip_name": clip_name,
            "requested_by": requested_by,
            "status": "pending",
            "created_at": now,
            "pitch": pitch,
            "speed": speed,
        }
        self.db.pending_commands.insert_one(command)
        self._log_play(clip_ref, clip_name, requested_by, pitch, speed, now)
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
        log_docs = []
        for i, item in enumerate(items, start=1):
            played_at = base_time + timedelta(microseconds=i)
            docs.append({
                "type": "queue_play",
                "clip_ref": item["clip_ref"],
                "clip_name": item.get("clip_name") or item["clip_ref"],
                "requested_by": requested_by,
                "status": "pending",
                "created_at": played_at,
                "pitch": item.get("pitch", 0),
                "speed": item.get("speed", 1.0),
            })
            log_docs.append({
                "clip_ref": item["clip_ref"],
                "clip_name": item.get("clip_name") or item["clip_ref"],
                "requested_by": requested_by,
                "pitch": item.get("pitch", 0),
                "speed": item.get("speed", 1.0),
                "played_at": played_at,
            })
        self.db.pending_commands.insert_many(docs)
        if log_docs:
            self.db.play_log.insert_many(log_docs)

    def enqueue_join(self, channel_id: str, requested_by: str) -> None:
        self.db.pending_commands.insert_one(
            {
                "type": "join",
                "channel_id": channel_id,
                "requested_by": requested_by,
                "status": "pending",
                "created_at": datetime.utcnow(),
            }
        )

    def enqueue_leave(self, requested_by: str) -> None:
        self.db.pending_commands.insert_one(
            {
                "type": "leave",
                "requested_by": requested_by,
                "status": "pending",
                "created_at": datetime.utcnow(),
            }
        )

    def get_next_pending(self) -> Optional[dict]:
        return self.db.pending_commands.find_one({"status": "pending"})

    def mark_done(self, command_id) -> None:
        self.db.pending_commands.update_one(
            {"_id": command_id},
            {"$set": {"status": "done"}}
        )