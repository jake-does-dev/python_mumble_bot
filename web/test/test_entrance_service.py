"""Tests for EntranceService + the router's clip validation.

Entrance sounds are keyed by voice_id (Mumble username / Discord id) and read by
both bots on join, so the stored shape matters.
"""

import pytest

from app.routers.entrance import ClipSetting, _validate_clips
from app.services.entrance import MAX_CLIPS, EntranceService


def test_set_and_get_roundtrip(db):
    svc = EntranceService()
    clips = [{"clip_ref": "a0", "clip_name": "alpha", "speed": 1.0, "pitch": 0}]
    svc.set_for_voice("winneh", clips, updated_by="winneh")

    doc = svc.get_for_voice("winneh")
    assert doc["voice_id"] == "winneh"
    assert doc["clips"] == clips
    assert doc["updated_by"] == "winneh"


def test_get_missing_returns_none(db):
    assert EntranceService().get_for_voice("nobody") is None


def test_caps_clip_count(db):
    svc = EntranceService()
    many = [{"clip_ref": f"r{i}", "clip_name": f"n{i}", "speed": 1.0, "pitch": 0} for i in range(10)]
    svc.set_for_voice("bob", many, updated_by="bob")
    assert len(svc.get_for_voice("bob")["clips"]) == MAX_CLIPS


def test_get_all_and_clear(db):
    svc = EntranceService()
    svc.set_for_voice("a", [{"clip_ref": "x", "clip_name": "x", "speed": 1, "pitch": 0}], "a")
    svc.set_for_voice("b", [{"clip_ref": "y", "clip_name": "y", "speed": 1, "pitch": 0}], "b")
    assert {e["voice_id"] for e in svc.get_all()} == {"a", "b"}

    svc.clear("a")
    assert svc.get_for_voice("a") is None
    assert {e["voice_id"] for e in svc.get_all()} == {"b"}


def test_validate_resolves_ref_and_clamps(db):
    db.clips.insert_one({"identifier": "dm0", "name": "dry_fart"})
    out = _validate_clips([ClipSetting(clip_ref="dm0", speed=9.0, pitch=99)])
    assert out == [
        {"clip_ref": "dm0", "clip_name": "dry_fart", "speed": 2.0, "pitch": 12}
    ]


def test_validate_resolves_by_name(db):
    db.clips.insert_one({"identifier": "dm0", "name": "dry_fart"})
    out = _validate_clips([ClipSetting(clip_ref="dry_fart")])
    assert out[0]["clip_ref"] == "dm0"  # stored as the identifier, not the name


def test_validate_rejects_unknown_clip(db):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        _validate_clips([ClipSetting(clip_ref="nope")])
    assert exc.value.status_code == 400
