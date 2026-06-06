"""Tests for the Mumble song queue (now-playing / upcoming / skip).

These lock the `song_state` doc the shared web reads to render the now-playing
mini-player, plus the enqueue / skip / stop transitions. The audio render and
mixer threads aren't exercised here — we build the manager via __new__ and test
the pure queue/state logic directly.
"""

import os
import sys
import threading

sys.path.append(os.path.relpath("./python_mumble_bot"))

from python_mumble_bot.bot.event import MidiSongEvent
from python_mumble_bot.bot.manager import PlaybackManager


class FakeColl:
    def __init__(self):
        self.doc = None

    def replace_one(self, flt, doc, upsert=False):
        self.doc = doc


class FakeMongo:
    def __init__(self):
        self.db = type("DB", (), {"song_state": FakeColl()})()


class FakeState:
    def __init__(self):
        self.mongo_interface = FakeMongo()


class FakeMumble:
    def __init__(self):
        self.sound_output = type("SO", (), {"clear_buffer": lambda self: None})()


def _mgr():
    """A PlaybackManager with just the song-queue state wired (no threads)."""
    m = PlaybackManager.__new__(PlaybackManager)
    m._song_pending = []
    m._song_current = None
    m._song_lock = threading.Lock()
    m._skip_flag = threading.Event()
    m._voices = {}
    m._mix_lock = threading.Lock()
    m.state_manager = FakeState()
    m.mumble = FakeMumble()
    return m


def _state(m):
    return m.state_manager.mongo_interface.db.song_state.doc


def _event(song="gstq.mid", clip="dm0", **kw):
    return MidiSongEvent(clip_ref=clip, song_file=song, **kw)


def test_event_display_names_default_to_file_and_ref():
    e = MidiSongEvent(clip_ref="dm0", song_file="gstq.mid")
    assert e.song_name == "gstq.mid" and e.clip_name == "dm0"
    e2 = MidiSongEvent(
        clip_ref="dm0",
        song_file="gstq.mid",
        song_name="God Save the Queen",
        clip_name="dry_fart",
    )
    assert e2.song_name == "God Save the Queen" and e2.clip_name == "dry_fart"


def test_enqueue_publishes_upcoming_queue():
    m = _mgr()
    m.enqueue_song(
        _event(
            song="a.mid",
            clip="c1",
            song_name="Alpha",
            clip_name="one",
            requested_by="winneh",
        )
    )
    m.enqueue_song(
        _event(
            song="b.mid",
            clip="c2",
            song_name="Bravo",
            clip_name="two",
            requested_by="bob",
        )
    )

    doc = _state(m)
    assert doc["_id"] == "singleton"
    assert doc["current"] is None
    assert [q["song_name"] for q in doc["queue"]] == ["Alpha", "Bravo"]
    assert doc["queue"][0]["clip_name"] == "one"
    assert doc["queue"][1]["requested_by"] == "bob"


def test_publish_serialises_current_song():
    m = _mgr()
    import datetime as dt

    m._song_current = {
        "song_name": "Alpha",
        "clip_name": "one",
        "requested_by": "winneh",
        "started_at": dt.datetime(2026, 6, 6, 12, 0, 0),
        "duration_s": 12.5,
    }
    m._publish_song_state()
    cur = _state(m)["current"]
    assert cur["song_name"] == "Alpha"
    assert cur["duration_s"] == 12.5


def test_skip_sets_flag():
    m = _mgr()
    assert not m._skip_flag.is_set()
    m.skip_song()
    assert m._skip_flag.is_set()


def test_stop_clears_queue_and_current_and_signals_skip():
    m = _mgr()
    m.enqueue_song(_event(song_name="Alpha"))
    m.enqueue_song(_event(song_name="Bravo"))
    m._song_current = {
        "song_name": "Alpha",
        "clip_name": "one",
        "requested_by": "w",
        "started_at": None,
        "duration_s": 5,
    }

    m.stop()

    assert m._song_pending == []
    assert m._song_current is None
    assert m._skip_flag.is_set()  # so the worker's wait loop breaks promptly
    doc = _state(m)
    assert doc["current"] is None and doc["queue"] == []


def test_publish_is_noop_when_mongo_unavailable():
    # Before mongo connects, replace_one raises -> _publish must swallow it.
    m = _mgr()

    def boom(*a, **k):
        raise RuntimeError("not connected")

    m.state_manager.mongo_interface.db.song_state.replace_one = boom
    assert m._publish_song_state() is False  # no crash
