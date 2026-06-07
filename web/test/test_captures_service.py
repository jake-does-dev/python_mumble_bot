"""Tests for the "clip that" review pipeline: CapturesService + enqueue_capture.

The bot writes a WAV under AUDIO_DIR/captures/ and a `pending_clips` doc; the web
reviews them and either promotes one into a real clip (reusing the clip upload
pipeline) or discards it. Auth is owner-or-admin.
"""

import io
import wave

import pytest

from app.services.captures import CapturesService
from app.services.commands import CommandsService


def _wav_bytes(seconds=1.0, rate=48000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        w.writeframes(b"\x01\x02" * int(rate * seconds))
    return buf.getvalue()


@pytest.fixture
def audio_dir(tmp_path, monkeypatch):
    """Point both clips and captures at a writable temp audio dir."""
    import app.services.captures as captures_mod
    import app.services.clips as clips_mod

    monkeypatch.setattr(clips_mod, "AUDIO_DIR", tmp_path)
    monkeypatch.setattr(captures_mod, "AUDIO_DIR", tmp_path)
    (tmp_path / "captures").mkdir()
    return tmp_path


def _seed_capture(db, audio_dir, requested_by="alice", name="cap_x.wav"):
    (audio_dir / "captures" / name).write_bytes(_wav_bytes())
    res = db.pending_clips.insert_one(
        {
            "target_voice": "dave",
            "requested_by": requested_by,
            "duration_s": 1.0,
            "file": "captures/" + name,
            "status": "pending",
            "created_at": __import__("datetime").datetime.utcnow(),
        }
    )
    return str(res.inserted_id)


def test_enqueue_capture_writes_command(db):
    CommandsService().enqueue_capture("dave", 30, "alice")
    doc = db.pending_commands.find_one({"type": "clip_capture"})
    assert doc["target_voice"] == "dave"
    assert doc["duration"] == 30
    assert doc["requested_by"] == "alice"
    assert doc["status"] == "pending"


def test_list_pending(db, audio_dir):
    _seed_capture(db, audio_dir, name="a.wav")
    _seed_capture(db, audio_dir, name="b.wav")
    pending = CapturesService().list_pending()
    assert len(pending) == 2
    assert {p["target_voice"] for p in pending} == {"dave"}
    assert all("id" in p for p in pending)


def test_promote_creates_clip_and_removes_capture(db, audio_dir):
    cid = _seed_capture(db, audio_dir)
    clip = CapturesService().promote(
        cid, "daves_gem", ["funny"], None, None, user="alice", is_admin=False
    )
    assert clip["name"] == "daves_gem"
    # the clip file now exists, the capture is gone (doc + temp file)
    assert (audio_dir / clip["file"]).exists()
    assert db.pending_clips.find_one({"target_voice": "dave"}) is None
    assert not (audio_dir / "captures" / "cap_x.wav").exists()


def test_promote_rejects_non_owner(db, audio_dir):
    from fastapi import HTTPException

    cid = _seed_capture(db, audio_dir, requested_by="alice")
    with pytest.raises(HTTPException) as exc:
        CapturesService().promote(cid, "x", [], None, None, user="bob", is_admin=False)
    assert exc.value.status_code == 403
    # nothing consumed
    assert db.pending_clips.find_one({"target_voice": "dave"}) is not None


def test_discard_owner_and_admin(db, audio_dir):
    from fastapi import HTTPException

    cid = _seed_capture(db, audio_dir, requested_by="alice", name="a.wav")
    with pytest.raises(HTTPException):
        CapturesService().discard(cid, user="bob", is_admin=False)

    # owner can discard
    CapturesService().discard(cid, user="alice", is_admin=False)
    assert db.pending_clips.find_one({"_id": __import__("bson").ObjectId(cid)}) is None
    assert not (audio_dir / "captures" / "a.wav").exists()

    # admin can discard someone else's
    cid2 = _seed_capture(db, audio_dir, requested_by="alice", name="b.wav")
    CapturesService().discard(cid2, user="winneh", is_admin=True)
    assert db.pending_clips.find_one({"target_voice": "dave"}) is None


def test_bad_id_is_400(db, audio_dir):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        CapturesService().discard("not-an-objectid", user="alice", is_admin=True)
    assert exc.value.status_code == 400
