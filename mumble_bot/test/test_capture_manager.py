"""Tests for CaptureManager — the single received-audio sink.

It feeds two things from one ``on_sound(user, chunk)`` callback: a rolling per-user
PCM buffer (for "clip that", **opted-in users only**) and, while recording, per-user
WAV files (``/record``, everyone). The window maths and the opt-in gate are the
parts most likely to break a future change, so they're covered directly with
synthetic chunks — no live Mumble needed.
"""

import os
import wave

from python_mumble_bot.bot.constants import NAME
from python_mumble_bot.bot.event import CaptureEvent, Event, RecordEvent
from python_mumble_bot.bot.manager import CaptureManager

SR = CaptureManager.SAMPLE_RATE


class FakeChunk:
    """Stands in for a pymumble SoundChunk (48 kHz mono int16)."""

    def __init__(self, time, pcm):
        self.time = time
        self.pcm = pcm


class FakeWrapper:
    def __init__(self):
        self.recording = False

    def start_recording(self):
        self.recording = True

    def stop_recording(self):
        self.recording = False


class FakeColl:
    def __init__(self):
        self.docs = []

    def insert_one(self, doc):
        self.docs.append(doc)


class FakeUsers:
    def __init__(self, docs=None):
        self.docs = docs or []

    def find(self, query=None, projection=None):
        # Mirrors the bot's query: opted-in users with a linked voice_id.
        return [d for d in self.docs if d.get("capture_optin") and d.get("voice_id")]

    def update_many(self, query, update):
        # Enough of pymongo's update_many for clear_optin: match on the query and
        # apply $set, counting docs that actually changed.
        set_fields = update.get("$set", {})
        modified = 0
        for d in self.docs:
            if all(d.get(k) == v for k, v in query.items()):
                if any(d.get(k) != v for k, v in set_fields.items()):
                    d.update(set_fields)
                    modified += 1
        return type("R", (), {"modified_count": modified})()


class FakeMongo:
    def __init__(self, users=None):
        self.db = type(
            "DB",
            (),
            {"pending_clips": FakeColl(), "users": FakeUsers(users)},
        )()


def _user(name):
    return {NAME: name}


def _tone(samples):
    # 0x0201 per sample — non-zero in both bytes so silence-trimming can't eat it.
    return b"\x01\x02" * samples


def _wav_seconds(path):
    with wave.open(path) as w:
        return w.getnframes() / w.getframerate()


def _optin(mgr, *names):
    mgr._optin = set(names)
    return mgr


def test_event_acceptance():
    mgr = CaptureManager(FakeWrapper(), FakeMongo())
    assert mgr.accept(RecordEvent("start"))
    assert mgr.accept(CaptureEvent("bob", 5))
    assert not mgr.accept(Event(None))


def test_record_captures_everyone_regardless_of_optin(tmp_path):
    # /record is a deliberate action and is NOT gated on opt-in.
    wrapper = FakeWrapper()
    mgr = CaptureManager(wrapper, FakeMongo(), recording_dir=tmp_path)

    mgr.dispatch(RecordEvent("start"))
    assert wrapper.recording is True
    for name in ["1", "2", "3"]:  # none opted in
        mgr.on_sound(_user(name), FakeChunk(0.0, _tone(480)))
    mgr.dispatch(RecordEvent("stop"))
    assert wrapper.recording is False

    assert len(os.listdir(tmp_path)) == 3


def test_buffer_only_holds_opted_in_users():
    mgr = _optin(CaptureManager(FakeWrapper(), FakeMongo()), "dave")
    mgr.on_sound(_user("dave"), FakeChunk(0.0, _tone(100)))
    mgr.on_sound(_user("nope"), FakeChunk(0.0, _tone(100)))
    assert "dave" in mgr._buffers
    assert "nope" not in mgr._buffers  # dropped, never stored


def test_capture_requires_optin(tmp_path):
    mongo = FakeMongo()
    mgr = CaptureManager(FakeWrapper(), mongo, captures_dir=tmp_path)
    # no opt-in: even if we somehow had audio, capture refuses
    mgr.dispatch(CaptureEvent("dave", 5))
    assert mongo.db.pending_clips.docs == []
    assert os.listdir(tmp_path) == []


def test_capture_writes_wav_and_pending_doc(tmp_path):
    mongo = FakeMongo()
    mgr = _optin(CaptureManager(FakeWrapper(), mongo, captures_dir=tmp_path), "dave")

    mgr.on_sound(_user("dave"), FakeChunk(10.0, _tone(SR // 2)))  # 0.5s at t=10
    mgr.dispatch(CaptureEvent("dave", 5))

    assert len(mongo.db.pending_clips.docs) == 1
    doc = mongo.db.pending_clips.docs[0]
    assert doc["target_voice"] == "dave"
    assert doc["status"] == "pending"
    assert doc["file"].startswith("captures/")

    wavs = [f for f in os.listdir(tmp_path) if f.endswith(".wav")]
    assert len(wavs) == 1
    assert 0.3 < _wav_seconds(os.path.join(tmp_path, wavs[0])) < 0.7


def test_capture_preserves_gap_keeps_inner_silence(tmp_path):
    mongo = FakeMongo()
    mgr = _optin(CaptureManager(FakeWrapper(), mongo, captures_dir=tmp_path), "dave")

    # Two 0.5s bursts separated by a 1s gap (speech spans 0.0 → 2.0s).
    mgr.on_sound(_user("dave"), FakeChunk(0.0, _tone(SR // 2)))
    mgr.on_sound(_user("dave"), FakeChunk(1.5, _tone(SR // 2)))
    mgr.dispatch(CaptureEvent("dave", 10))

    wav = [f for f in os.listdir(tmp_path) if f.endswith(".wav")][0]
    assert 1.9 < _wav_seconds(os.path.join(tmp_path, wav)) < 2.1


def test_capture_opted_in_but_no_audio_is_noop(tmp_path):
    mongo = FakeMongo()
    mgr = _optin(CaptureManager(FakeWrapper(), mongo, captures_dir=tmp_path), "ghost")

    mgr.dispatch(CaptureEvent("ghost", 5))

    assert mongo.db.pending_clips.docs == []
    assert os.listdir(tmp_path) == []


def test_refresh_optin_reads_db_and_purges_on_optout():
    mongo = FakeMongo(users=[{"voice_id": "dave", "capture_optin": True}])
    mgr = CaptureManager(FakeWrapper(), mongo)

    mgr._refresh_optin()
    assert mgr._optin == {"dave"}

    mgr.on_sound(_user("dave"), FakeChunk(0.0, _tone(100)))
    assert "dave" in mgr._buffers

    # dave opts out — next refresh drops them from the set and purges their buffer
    mongo.db.users.docs = []
    mgr._refresh_optin()
    assert mgr._optin == set()
    assert "dave" not in mgr._buffers


def test_clear_optin_wipes_consent_set_buffers_and_db():
    mongo = FakeMongo(
        users=[
            {"voice_id": "dave", "capture_optin": True},
            {"voice_id": "sam", "capture_optin": True},
        ]
    )
    mgr = CaptureManager(FakeWrapper(), mongo)
    mgr._refresh_optin()
    mgr.on_sound(_user("dave"), FakeChunk(0.0, _tone(100)))
    assert mgr._optin == {"dave", "sam"} and "dave" in mgr._buffers

    cleared = mgr.clear_optin()

    assert cleared == 2
    assert mgr._optin == set()
    assert mgr._buffers == {}
    # DB reflects everyone opted out, so a later refresh stays empty.
    assert all(d["capture_optin"] is False for d in mongo.db.users.docs)
    mgr._refresh_optin()
    assert mgr._optin == set()
