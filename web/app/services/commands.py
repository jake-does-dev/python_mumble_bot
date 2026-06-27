from datetime import datetime, timedelta
from typing import List, Optional

import pymongo

from app.database import get_db

HISTORY_LIMIT = 250


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
                "pitch": e.get("pitch", 0),
                "speed": e.get("speed", 1.0),
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

    def enqueue_play(self, clip_ref: str, clip_name: str, requested_by: str, pitch: int = 0, speed: float = 1.0, reverse: bool = False) -> dict:
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
            "reverse": reverse,
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
                "reverse": item.get("reverse", False),
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

    def enqueue_song(
        self,
        song_filename: str,
        song_name: str,
        clip_ref: str,
        clip_name: str,
        requested_by: str,
        transpose: int = 0,
        speed: float = 1.0,
        gain: float = 0.0,
        max_seconds: float = 0.0,
        song_id: str = None,
    ) -> None:
        now = datetime.utcnow()
        # Durable, append-only record of song plays (its own log, separate from
        # the per-clip play_log).
        self.db.song_log.insert_one(
            {
                "song_id": song_id,
                "song_name": song_name,
                "clip_ref": clip_ref,
                "clip_name": clip_name,
                "requested_by": requested_by,
                "transpose": transpose,
                "speed": speed,
                "gain": gain,
                "max_seconds": max_seconds,
                "played_at": now,
            }
        )
        self.db.pending_commands.insert_many([
            {
                "type": "announce",
                "message": f"<b>{requested_by}</b> queued 🎵 {song_name} on {clip_name}",
                "status": "pending",
                "created_at": now,
            },
            {
                "type": "play_song",
                "song": song_filename,
                "song_name": song_name,
                "clip_ref": clip_ref,
                "clip_name": clip_name,
                "requested_by": requested_by,
                "transpose": transpose,
                "speed": speed,
                "gain": gain,
                "max_seconds": max_seconds,
                "status": "pending",
                "created_at": now + timedelta(microseconds=1),
            },
        ])

    def enqueue_skip_song(self, requested_by: str) -> None:
        self.db.pending_commands.insert_one(
            {
                "type": "skip_song",
                "requested_by": requested_by,
                "status": "pending",
                "created_at": datetime.utcnow(),
            }
        )

    def enqueue_capture(
        self, target_voice: str, duration: float, requested_by: str
    ) -> None:
        # "Clip that": ask the bot to dump the last `duration` seconds of
        # `target_voice`'s rolling buffer into a pending capture for review. The
        # bot announces success/failure itself, so there's no announce doc here.
        self.db.pending_commands.insert_one(
            {
                "type": "clip_capture",
                "target_voice": target_voice,
                "duration": duration,
                "requested_by": requested_by,
                "status": "pending",
                "created_at": datetime.utcnow(),
            }
        )

    def get_song_state(self) -> dict:
        """Current song + upcoming queue, as mirrored by the bot."""
        doc = self.db.song_state.find_one({"_id": "singleton"})
        if not doc:
            return {"current": None, "queue": []}
        current = doc.get("current")
        if current and current.get("started_at"):
            current = {**current, "started_at": current["started_at"].isoformat() + "Z"}
        return {"current": current, "queue": doc.get("queue", [])}

    def last_stop(self) -> dict:
        doc = self.db.pending_commands.find_one(
            {"type": "stop"}, sort=[("created_at", pymongo.DESCENDING)]
        )
        if not doc:
            return {"at": None, "by": None}
        return {
            "at": doc["created_at"].isoformat() + "Z",
            "by": doc.get("requested_by"),
        }

    def enqueue_stop(self, requested_by: str) -> None:
        # Cancel anything still queued so it won't start, then tell the bot to
        # clear whatever is currently playing.
        self.db.pending_commands.update_many(
            {
                "status": "pending",
                "type": {"$in": ["play", "queue_play", "play_song", "clip_capture"]},
            },
            {"$set": {"status": "done"}},
        )
        self.db.pending_commands.insert_one(
            {
                "type": "stop",
                "requested_by": requested_by,
                "status": "pending",
                "created_at": datetime.utcnow(),
            }
        )

    def last_restart(self) -> dict:
        doc = self.db.pending_commands.find_one(
            {"type": "restart"}, sort=[("created_at", pymongo.DESCENDING)]
        )
        if not doc:
            return {"at": None, "by": None}
        return {
            "at": doc["created_at"].isoformat() + "Z",
            "by": doc.get("requested_by"),
        }

    def enqueue_restart(self, requested_by: str) -> None:
        # Cancel anything still queued (it shouldn't fire on a freshly-restarted
        # bot), then ask the bot to exit so Docker restarts it and it rejoins.
        self.db.pending_commands.update_many(
            {
                "status": "pending",
                "type": {"$in": ["play", "queue_play", "play_song", "clip_capture"]},
            },
            {"$set": {"status": "done"}},
        )
        self.db.pending_commands.insert_one(
            {
                "type": "restart",
                "requested_by": requested_by,
                "status": "pending",
                "created_at": datetime.utcnow(),
            }
        )

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