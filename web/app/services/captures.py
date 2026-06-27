"""Pending voice captures ("clip that").

The bot writes a WAV to the shared audio volume under ``captures/`` and inserts a
``pending_clips`` doc; this service lets the web review them, then either promote
one into a real clip (reusing the normal upload pipeline, so it gets trimmed,
loudness-normalised and an identifier) or discard it.
"""

from pathlib import Path
from typing import List, Optional

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException

from app.database import get_db
from app.services.clips import AUDIO_DIR, ClipsService


class CapturesService:
    def __init__(self):
        self.db = get_db()

    def list_pending(self) -> List[dict]:
        docs = self.db.pending_clips.find(
            {"status": "pending"}, sort=[("created_at", -1)]
        )
        return [
            {
                "id": str(doc["_id"]),
                "target_voice": doc.get("target_voice"),
                "requested_by": doc.get("requested_by"),
                "duration_s": doc.get("duration_s"),
                "created_at": (
                    doc["created_at"].isoformat() + "Z"
                    if doc.get("created_at")
                    else None
                ),
            }
            for doc in docs
        ]

    def _get(self, capture_id: str) -> dict:
        try:
            oid = ObjectId(capture_id)
        except (InvalidId, TypeError):
            raise HTTPException(400, "Invalid capture id")
        doc = self.db.pending_clips.find_one({"_id": oid})
        if not doc:
            raise HTTPException(404, "Capture not found")
        return doc

    def get_audio_path(self, capture_id: str) -> Path:
        doc = self._get(capture_id)
        path = AUDIO_DIR / doc["file"]
        if not path.exists():
            raise HTTPException(404, "Capture audio missing")
        return path

    def promote(
        self,
        capture_id: str,
        name: str,
        tags: List[str],
        start: Optional[float],
        end: Optional[float],
        user: str,
        is_admin: bool,
    ) -> dict:
        doc = self._get(capture_id)
        self._authorize(doc, user, is_admin)

        path = AUDIO_DIR / doc["file"]
        if not path.exists():
            raise HTTPException(404, "Capture audio missing")
        contents = path.read_bytes()

        # Reuse the full clip pipeline (validation, trim, normalise, identifier).
        clip = ClipsService().upload_clip(
            name, ".wav", contents, tags, uploaded_by=user, start=start, end=end
        )

        # Keep the capture in the review list so several clips can be pulled from
        # one grab (different trims/names). It's only removed on explicit discard.
        return clip

    def discard(self, capture_id: str, user: str, is_admin: bool) -> None:
        doc = self._get(capture_id)
        self._authorize(doc, user, is_admin)
        self._unlink(AUDIO_DIR / doc["file"])
        self.db.pending_clips.delete_one({"_id": doc["_id"]})

    @staticmethod
    def _authorize(doc: dict, user: str, is_admin: bool) -> None:
        if not (is_admin or doc.get("requested_by") == user):
            raise HTTPException(403, "You can only manage captures you created")

    @staticmethod
    def _unlink(path: Path) -> None:
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass
