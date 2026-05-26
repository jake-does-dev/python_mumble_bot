import io
import os
import re
import wave
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import HTTPException

from app.database import get_db

AUDIO_DIR = Path(os.getenv("AUDIO_DIR", "/app/audio"))
MAX_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB
MAX_DURATION_SECONDS = 10
_NAME_RE = re.compile(r"^[a-zA-Z0-9_\-]+$")

_PREFIX_MAP = {
    "daryl_": "dm",
    "david_": "dg",
    "dom_": "dh",
    "jake_": "ja",
    "ollie_": "oy",
    "will_": "wt",
}


def _read_duration(contents: bytes, ext: str) -> float:
    if ext == ".wav":
        try:
            with wave.open(io.BytesIO(contents)) as f:
                return f.getnframes() / f.getframerate()
        except Exception:
            raise HTTPException(400, "Could not read WAV file")
    else:
        try:
            from mutagen.mp3 import MP3

            return MP3(fileobj=io.BytesIO(contents)).info.length
        except Exception:
            raise HTTPException(400, "Could not read MP3 file")


class ClipsService:
    def __init__(self):
        self.db = get_db()

    def get_clips(
        self,
        search: Optional[str] = None,
        tag: Optional[str] = None,
    ) -> List[dict]:
        query = {}
        if search:
            query["$or"] = [
                {"name": {"$regex": search, "$options": "i"}},
                {"identifier": {"$regex": search, "$options": "i"}},
            ]
        if tag:
            query["tags"] = tag

        return list(self.db.clips.find(query, {"_id": 0}))

    def get_clip_by_ref(self, ref: str) -> Optional[dict]:
        clip = self.db.clips.find_one({"identifier": ref}, {"_id": 0})
        if not clip:
            clip = self.db.clips.find_one({"name": ref}, {"_id": 0})
        return clip

    def get_all_tags(self) -> List[str]:
        tags = self.db.clips.distinct("tags")
        return sorted(tags)

    def upload_clip(
        self, name: str, ext: str, contents: bytes, tags: List[str]
    ) -> dict:
        if not _NAME_RE.match(name):
            raise HTTPException(
                400,
                "Name may only contain letters, numbers, underscores, and hyphens",
            )

        if len(contents) > MAX_SIZE_BYTES:
            raise HTTPException(
                413, f"File too large — max {MAX_SIZE_BYTES // (1024 * 1024)} MB"
            )

        duration = _read_duration(contents, ext)
        if duration > MAX_DURATION_SECONDS:
            raise HTTPException(
                400,
                f"Audio too long — max {MAX_DURATION_SECONDS} seconds",
            )

        if self.db.clips.find_one({"name": name}):
            raise HTTPException(409, f"A clip named '{name}' already exists")

        identifier = self._next_identifier(name)

        filename = f"{name}{ext}"
        AUDIO_DIR.mkdir(parents=True, exist_ok=True)
        dest = AUDIO_DIR / filename
        if dest.exists():
            raise HTTPException(409, f"File '{filename}' already exists on disk")
        dest.write_bytes(contents)

        doc = {
            "identifier": identifier,
            "name": name,
            "file": filename,
            "creation_time": datetime.utcnow(),
            "tags": tags,
        }
        self.db.clips.insert_one(doc)
        doc.pop("_id", None)

        return doc

    def delete_clip(self, identifier: str) -> None:
        clip = self.db.clips.find_one({"identifier": identifier})
        if not clip:
            raise HTTPException(404, f"Clip '{identifier}' not found")

        audio_file = AUDIO_DIR / clip["file"]
        if audio_file.exists():
            audio_file.unlink()

        self.db.clips.delete_one({"identifier": identifier})
        self.db.favourites.update_many({}, {"$pull": {"clips": identifier}})

    def _next_identifier(self, name: str) -> str:
        file_prefix = "generic"
        id_prefix = ""
        for fp, ip in _PREFIX_MAP.items():
            if name.startswith(fp):
                file_prefix = fp
                id_prefix = ip
                break

        doc = self.db.identifiers.find_one_and_update(
            {"file_prefix": file_prefix},
            {"$inc": {"next_id": 1}},
        )
        if doc is None:
            return f"u{int(datetime.utcnow().timestamp())}"

        return f"{id_prefix}{doc['next_id']}"
