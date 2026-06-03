import io
import os
import re
import shutil
import subprocess
import wave
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import pymongo
from fastapi import HTTPException

from app.database import get_db

AUDIO_DIR = Path(os.getenv("AUDIO_DIR", "/app/audio"))
MAX_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB
MAX_DURATION_SECONDS = 10
_NAME_RE = re.compile(r"^[a-zA-Z0-9_\-]+$")

# "prefix" (default) keeps the Mumble-style prefixed IDs (oy69, ja12, ...).
# "integer" generates plain incrementing integers (1, 2, 3, ...) — used by the
# Discord stack for short, easy-to-type IDs.
CLIP_ID_MODE = os.getenv("CLIP_ID_MODE", "prefix")

# When enabled, uploaded clips are loudness-normalised once (EBU R128) so no
# single clip can be wildly louder than the rest. Done at upload so playback
# stays instant (no per-play processing).
NORMALIZE_UPLOADS = os.getenv("NORMALIZE_UPLOADS", "").lower() in ("1", "true", "yes")
# Trim leading silence (so clips start right on the sound), then
# loudness-normalise. Applied once at upload — keeps playback instant.
_AUDIO_FILTER = (
    "silenceremove=start_periods=1:start_duration=0:start_threshold=-50dB,"
    "loudnorm=I=-16:TP=-1.5:LRA=11"
)
# Re-normalise after a manual trim (no silence-removal — the user chose the cut).
_LOUDNORM_FILTER = "loudnorm=I=-16:TP=-1.5:LRA=11"


def _normalize_loudness(path: Path) -> None:
    tmp = path.with_name(".norm_" + path.name)
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", str(path), "-af", _AUDIO_FILTER, "-ar", "48000", str(tmp)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if result.returncode == 0 and tmp.exists():
        os.replace(tmp, path)
    elif tmp.exists():
        tmp.unlink()

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
                {"tags": {"$regex": search, "$options": "i"}},
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
        self,
        name: str,
        ext: str,
        contents: bytes,
        tags: List[str],
        uploaded_by: Optional[str] = None,
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

        if NORMALIZE_UPLOADS:
            _normalize_loudness(dest)

        doc = {
            "identifier": identifier,
            "name": name,
            "file": filename,
            "creation_time": datetime.utcnow(),
            "tags": tags,
            "uploaded_by": uploaded_by,
        }
        self.db.clips.insert_one(doc)
        doc.pop("_id", None)

        return doc

    def update_clip(
        self,
        identifier: str,
        current_user: str,
        is_admin: bool,
        name: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> dict:
        clip = self.db.clips.find_one({"identifier": identifier})
        if not clip:
            raise HTTPException(404, f"Clip '{identifier}' not found")
        if not (is_admin or clip.get("uploaded_by") == current_user):
            raise HTTPException(403, "You can only edit clips you uploaded")

        updates = {}

        if tags is not None:
            updates["tags"] = sorted({t.strip() for t in tags if t.strip()})

        if name is not None and name != clip["name"]:
            if not _NAME_RE.match(name):
                raise HTTPException(
                    400,
                    "Name may only contain letters, numbers, underscores, and hyphens",
                )
            if self.db.clips.find_one(
                {"name": name, "identifier": {"$ne": identifier}}
            ):
                raise HTTPException(409, f"A clip named '{name}' already exists")

            ext = Path(clip["file"]).suffix
            new_filename = f"{name}{ext}"
            new_path = AUDIO_DIR / new_filename
            if new_path.exists():
                raise HTTPException(
                    409, f"File '{new_filename}' already exists on disk"
                )
            old_path = AUDIO_DIR / clip["file"]
            if old_path.exists():
                old_path.rename(new_path)
            updates["name"] = name
            updates["file"] = new_filename

        if updates:
            self.db.clips.update_one(
                {"identifier": identifier}, {"$set": updates}
            )

        return self.db.clips.find_one({"identifier": identifier}, {"_id": 0})

    def _authorize_edit(self, clip, current_user, is_admin):
        if not (is_admin or clip.get("uploaded_by") == current_user):
            raise HTTPException(403, "You can only edit clips you uploaded")

    def trim_clip(
        self,
        identifier: str,
        current_user: str,
        is_admin: bool,
        start: float,
        end: float,
    ) -> dict:
        clip = self.db.clips.find_one({"identifier": identifier})
        if not clip:
            raise HTTPException(404, f"Clip '{identifier}' not found")
        self._authorize_edit(clip, current_user, is_admin)

        if start < 0 or end <= start or (end - start) < 0.1:
            raise HTTPException(400, "Invalid trim selection")

        path = AUDIO_DIR / clip["file"]
        if not path.exists():
            raise HTTPException(404, "Audio file not found")

        # Keep a one-time backup of the very first original so trims are revertable.
        original_file = clip.get("original_file")
        if not original_file:
            original_file = ".orig_" + clip["file"]
            backup = AUDIO_DIR / original_file
            if not backup.exists():
                shutil.copy2(path, backup)

        tmp = path.with_name(".trim_" + path.name)
        result = subprocess.run(
            [
                "ffmpeg", "-y", "-i", str(path),
                "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
                "-af", _LOUDNORM_FILTER, "-ar", "48000", str(tmp),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if result.returncode != 0 or not tmp.exists():
            if tmp.exists():
                tmp.unlink()
            raise HTTPException(500, "Trim failed")
        os.replace(tmp, path)

        self.db.clips.update_one(
            {"identifier": identifier}, {"$set": {"original_file": original_file}}
        )
        return self.db.clips.find_one({"identifier": identifier}, {"_id": 0})

    def revert_clip(
        self, identifier: str, current_user: str, is_admin: bool
    ) -> dict:
        clip = self.db.clips.find_one({"identifier": identifier})
        if not clip:
            raise HTTPException(404, f"Clip '{identifier}' not found")
        self._authorize_edit(clip, current_user, is_admin)

        original_file = clip.get("original_file")
        if not original_file:
            raise HTTPException(400, "This clip has no original to revert to")
        backup = AUDIO_DIR / original_file
        if not backup.exists():
            raise HTTPException(404, "Original backup is missing")

        shutil.copy2(backup, AUDIO_DIR / clip["file"])
        return self.db.clips.find_one({"identifier": identifier}, {"_id": 0})

    def set_gain(self, identifier: str, gain_db: float) -> dict:
        # Per-clip volume trim in dB on top of the loudness baseline. Stored as
        # metadata and applied by the bots at playback — non-destructive, so it
        # can be re-adjusted any time without touching the file.
        clip = self.db.clips.find_one({"identifier": identifier})
        if not clip:
            raise HTTPException(404, f"Clip '{identifier}' not found")
        if gain_db < -20 or gain_db > 20:
            raise HTTPException(400, "Gain must be between -20 and +20 dB")

        gain_db = round(float(gain_db), 1)
        self.db.clips.update_one(
            {"identifier": identifier}, {"$set": {"gain_db": gain_db}}
        )
        return self.db.clips.find_one({"identifier": identifier}, {"_id": 0})

    def delete_clip(self, identifier: str) -> None:
        clip = self.db.clips.find_one({"identifier": identifier})
        if not clip:
            raise HTTPException(404, f"Clip '{identifier}' not found")

        audio_file = AUDIO_DIR / clip["file"]
        if audio_file.exists():
            audio_file.unlink()
        if clip.get("original_file"):
            backup = AUDIO_DIR / clip["original_file"]
            if backup.exists():
                backup.unlink()

        self.db.clips.delete_one({"identifier": identifier})
        self.db.favourites.update_many({}, {"$pull": {"clips": identifier}})

    def _next_identifier(self, name: str) -> str:
        if CLIP_ID_MODE == "integer":
            doc = self.db.counters.find_one_and_update(
                {"_id": "clip_id"},
                {"$inc": {"seq": 1}},
                upsert=True,
                return_document=pymongo.ReturnDocument.AFTER,
            )
            return str(doc["seq"])

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
