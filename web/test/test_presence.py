"""Tests for the presence gate (`enforce_presence`).

Covers the original "must be in the channel" rule and the newer rule that
sound-producing actions (play / queue / song) require both mic and audio on —
i.e. you can't play while muted or deafened.
"""

import pytest
from fastapi import HTTPException

import app.services.presence as presence
from app.services.presence import enforce_presence


@pytest.fixture
def gate_on(monkeypatch):
    # The flag is read from env at import; force it on for these tests.
    monkeypatch.setattr(presence, "PLAY_REQUIRES_PRESENCE", True)


def _link(db, username, voice_id, is_admin=False):
    db.users.insert_one(
        {"username": username, "voice_id": voice_id, "is_admin": is_admin, "password": "x"}
    )


def _set_present(db, members, channels=None):
    db.voice_state.update_one(
        {"_id": "state"},
        {"$set": {"present": members, "channels": channels or []}},
        upsert=True,
    )


def test_noop_when_gate_disabled(db, monkeypatch):
    monkeypatch.setattr(presence, "PLAY_REQUIRES_PRESENCE", False)
    # No user, no voice state, even no link — must not raise.
    enforce_presence("nobody", "play")


def test_admin_is_exempt(db, gate_on):
    _link(db, "winneh", voice_id=None, is_admin=True)
    # Admin with no link and not present still passes (bootstrap path).
    enforce_presence("winneh", "play")


def test_unlinked_user_rejected(db, gate_on):
    _link(db, "bob", voice_id=None)
    with pytest.raises(HTTPException) as exc:
        enforce_presence("bob", "play")
    assert exc.value.status_code == 403
    assert "linked" in exc.value.detail.lower()


def test_present_unmuted_user_can_play(db, gate_on):
    _link(db, "bob", voice_id="42")
    _set_present(db, [{"id": "42", "name": "bob", "mute": False, "deaf": False}])
    enforce_presence("bob", "play")  # no raise


def test_absent_user_rejected(db, gate_on):
    _link(db, "bob", voice_id="42")
    _set_present(db, [{"id": "99", "name": "someone-else"}])
    with pytest.raises(HTTPException) as exc:
        enforce_presence("bob", "play")
    assert exc.value.status_code == 403
    assert "voice channel" in exc.value.detail.lower()


@pytest.mark.parametrize("action", ["play", "queue", "song"])
def test_muted_user_cannot_produce_sound(db, gate_on, action):
    _link(db, "bob", voice_id="42")
    _set_present(db, [{"id": "42", "name": "bob", "mute": True, "deaf": False}])
    with pytest.raises(HTTPException) as exc:
        enforce_presence("bob", action)
    assert exc.value.status_code == 403
    assert "mic" in exc.value.detail.lower() or "unmute" in exc.value.detail.lower()


@pytest.mark.parametrize("action", ["play", "queue", "song"])
def test_deafened_user_cannot_produce_sound(db, gate_on, action):
    _link(db, "bob", voice_id="42")
    _set_present(db, [{"id": "42", "name": "bob", "mute": False, "deaf": True}])
    with pytest.raises(HTTPException) as exc:
        enforce_presence("bob", action)
    assert exc.value.status_code == 403


@pytest.mark.parametrize("action", ["skip", "stop", "leave"])
def test_muted_user_can_still_use_control_actions(db, gate_on, action):
    # Being muted must NOT block stop/skip/leave — only sound-producing actions.
    _link(db, "bob", voice_id="42")
    _set_present(db, [{"id": "42", "name": "bob", "mute": True, "deaf": True}])
    enforce_presence("bob", action)  # no raise


def test_join_checks_target_channel_membership(db, gate_on):
    _link(db, "bob", voice_id="42")
    _set_present(
        db,
        members=[],
        channels=[{"id": "7", "name": "General", "members": [{"id": "42", "name": "bob"}]}],
    )
    # bob is in channel 7 -> may summon the bot there
    enforce_presence("bob", "join", channel_id="7")
    # ...but not to channel 8 where he isn't
    with pytest.raises(HTTPException) as exc:
        enforce_presence("bob", "join", channel_id="8")
    assert exc.value.status_code == 403


def test_missing_mute_deaf_flags_treated_as_allowed(db, gate_on):
    # Older voice_state docs (pre-feature) have no mute/deaf keys -> not blocked.
    _link(db, "bob", voice_id="42")
    _set_present(db, [{"id": "42", "name": "bob"}])
    enforce_presence("bob", "play")  # no raise
