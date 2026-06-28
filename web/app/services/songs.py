"""MIDI song library — shareable .mid files played through a clip "instrument".

Parsing/metadata uses `mido` directly here (the web image does not bundle
pmb_core). The bots do the actual rendering; this service just stores the files
(in the shared audio volume, under music/) and their metadata.
"""

import io
import os
import re
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import mido
from fastapi import HTTPException

from app.database import get_db

AUDIO_DIR = Path(os.getenv("AUDIO_DIR", "/app/audio"))
SONGS_DIR = AUDIO_DIR / "music"
MAX_SIZE_BYTES = 2 * 1024 * 1024  # 2 MB — MIDI files are tiny
_NAME_RE = re.compile(r"[^a-z0-9_-]+")
DRUM_CHANNEL = 9


def _slugify(name: str) -> str:
    slug = _NAME_RE.sub("-", name.strip().lower()).strip("-")
    return slug or "song"


def _summarize(contents: bytes) -> dict:
    """Validate the upload is a real MIDI and pull out light metadata."""
    try:
        mid = mido.MidiFile(file=io.BytesIO(contents))
    except Exception:
        raise HTTPException(400, "Not a valid MIDI file")

    now = 0.0
    open_notes = {}
    note_count = 0
    duration = 0.0
    try:
        for msg in mid:
            now += msg.time
            if getattr(msg, "channel", 0) == DRUM_CHANNEL:
                continue
            if msg.type == "note_on" and msg.velocity > 0:
                open_notes[(msg.channel, msg.note)] = open_notes.get((msg.channel, msg.note), 0) + 1
            elif msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
                if open_notes.get((msg.channel, msg.note)):
                    open_notes[(msg.channel, msg.note)] -= 1
                    note_count += 1
                    duration = now
    except Exception:
        raise HTTPException(400, "Could not read MIDI file")

    if note_count == 0:
        raise HTTPException(400, "MIDI file has no playable (non-drum) notes")

    return {
        "duration_s": round(duration, 2),
        "note_count": note_count,
        "track_count": len(mid.tracks),
        # How many distinct instrument "lines" can be voiced separately.
        "instrument_count": len(_extract_lines(contents)),
    }


def _extract_lines(contents: bytes) -> list:
    """Group a song's notes into instrument "lines" by General MIDI program,
    merging channels that share a program (e.g. two Alto Sax channels → one
    line). Returns ``[{"program", "note_count", "channels"}]`` sorted busiest
    first. Program → friendly name is done client-side. No tempo maths needed —
    we only count note-ons and read the program active on each channel."""
    try:
        mid = mido.MidiFile(file=io.BytesIO(contents))
    except Exception:
        raise HTTPException(400, "Not a valid MIDI file")
    programs = {}
    lines = {}
    for msg in mid:
        if msg.type == "program_change":
            programs[msg.channel] = msg.program
        elif msg.type == "note_on" and msg.velocity > 0:
            if getattr(msg, "channel", 0) == DRUM_CHANNEL:
                continue
            prog = programs.get(msg.channel, 0)
            line = lines.setdefault(
                prog, {"program": prog, "note_count": 0, "channels": set()}
            )
            line["note_count"] += 1
            line["channels"].add(msg.channel)
    out = [
        {
            "program": ln["program"],
            "note_count": ln["note_count"],
            "channels": sorted(ln["channels"]),
        }
        for ln in lines.values()
    ]
    out.sort(key=lambda ln: ln["note_count"], reverse=True)
    return out


class SongsService:
    def __init__(self):
        self.db = get_db()

    def list_songs(self) -> List[dict]:
        songs = list(self.db.songs.find({}, {"_id": 0}))
        # Backfill instrument_count for songs uploaded before it was tracked, so
        # the library card can show how many lines a song has (one-off per song).
        for song in songs:
            if song.get("instrument_count") is None:
                path = SONGS_DIR / song["filename"]
                try:
                    count = len(_extract_lines(path.read_bytes())) if path.exists() else 0
                except Exception:
                    count = 0
                self.db.songs.update_one(
                    {"id": song["id"]}, {"$set": {"instrument_count": count}}
                )
                song["instrument_count"] = count
        return songs

    def get_song(self, song_id: str) -> Optional[dict]:
        return self.db.songs.find_one({"id": song_id}, {"_id": 0})

    def get_lines(self, song_id: str) -> List[dict]:
        """Instrument lines for a song (for per-line clip assignment), read from
        the stored .mid on demand. A single-instrument song returns one line."""
        song = self.db.songs.find_one({"id": song_id}, {"_id": 0})
        if not song:
            raise HTTPException(404, f"Song '{song_id}' not found")
        path = SONGS_DIR / song["filename"]
        if not path.exists():
            raise HTTPException(404, "Song file missing")
        return _extract_lines(path.read_bytes())

    def upload_song(self, filename: str, contents: bytes, uploaded_by: str) -> dict:
        ext = Path(filename).suffix.lower()
        if ext not in (".mid", ".midi"):
            raise HTTPException(400, "Only .mid / .midi files are supported")
        if len(contents) > MAX_SIZE_BYTES:
            raise HTTPException(413, f"File too large — max {MAX_SIZE_BYTES // (1024 * 1024)} MB")

        meta = _summarize(contents)

        name = Path(filename).stem
        song_id = _slugify(name)
        if self.db.songs.find_one({"id": song_id}):
            raise HTTPException(409, f"A song named '{song_id}' already exists")

        SONGS_DIR.mkdir(parents=True, exist_ok=True)
        stored_filename = f"{song_id}.mid"
        dest = SONGS_DIR / stored_filename
        if dest.exists():
            raise HTTPException(409, f"File '{stored_filename}' already exists on disk")
        dest.write_bytes(contents)

        doc = {
            "id": song_id,
            "name": name,
            "filename": stored_filename,
            "uploaded_by": uploaded_by,
            "duration_s": meta["duration_s"],
            "note_count": meta["note_count"],
            "track_count": meta["track_count"],
            "instrument_count": meta["instrument_count"],
            "created_at": datetime.utcnow(),
        }
        self.db.songs.insert_one(doc)
        doc.pop("_id", None)
        return doc

    def rename_song(self, song_id: str, new_name: str, requested_by: str, is_admin: bool) -> dict:
        song = self.db.songs.find_one({"id": song_id})
        if not song:
            raise HTTPException(404, f"Song '{song_id}' not found")
        if not is_admin and song.get("uploaded_by") != requested_by:
            raise HTTPException(403, "You can only rename songs you uploaded")
        name = (new_name or "").strip()
        if not name:
            raise HTTPException(400, "Name cannot be empty")
        if len(name) > 80:
            raise HTTPException(400, "Name too long (max 80 chars)")
        # Only the display name changes; id/filename stay stable so the stored
        # file and play references don't break.
        self.db.songs.update_one({"id": song_id}, {"$set": {"name": name}})
        song["name"] = name
        song.pop("_id", None)
        return song

    def delete_song(self, song_id: str, requested_by: str, is_admin: bool) -> None:
        song = self.db.songs.find_one({"id": song_id})
        if not song:
            raise HTTPException(404, f"Song '{song_id}' not found")
        if not is_admin and song.get("uploaded_by") != requested_by:
            raise HTTPException(403, "You can only delete songs you uploaded")
        path = SONGS_DIR / song["filename"]
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        self.db.songs.delete_one({"id": song_id})

    def get_history(self, limit: int = 100) -> List[dict]:
        import pymongo
        entries = list(
            self.db.song_log.find(
                {}, sort=[("played_at", pymongo.DESCENDING)], limit=limit
            )
        )
        return [
            {
                "song_id": e.get("song_id"),
                "song_name": e.get("song_name"),
                "clip_ref": e.get("clip_ref"),
                "clip_name": e.get("clip_name"),
                "requested_by": e.get("requested_by"),
                "transpose": e.get("transpose", 0),
                "speed": e.get("speed", 1.0),
                "gain": e.get("gain", 0),
                "max_seconds": e.get("max_seconds", 0),
                "instruments": e.get("instruments", []),
                "played_at": e["played_at"].isoformat() + "Z",
            }
            for e in entries
        ]
