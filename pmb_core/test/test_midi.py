"""Tests for pmb_core.audio.midi.parse_midi / summarize_midi.

These guard the shared MIDI front-end that BOTH bots feed into their
clip-as-instrument renderers, so a parsing regression would silently break the
jukebox on Mumble and Discord at once.

We synthesise tiny Standard MIDI Files in a temp dir with mido (note_on /
note_off deltas in ticks). With the default tempo (500000 us/beat) and
ticks_per_beat=480, seconds = ticks / 960, i.e. 480 ticks == 0.5s.
"""

import mido
import pytest

from pmb_core.audio.midi import DRUM_CHANNEL, parse_midi, summarize_midi

TPB = 480  # ticks per beat -> 480 ticks == 0.5s at the default tempo


def _write_midi(tmp_path, messages, name="t.mid"):
    """messages: list of mido.Message with delta `time` in ticks."""
    mid = mido.MidiFile(ticks_per_beat=TPB)
    track = mido.MidiTrack()
    for msg in messages:
        track.append(msg)
    mid.tracks.append(track)
    path = tmp_path / name
    mid.save(str(path))
    return str(path)


def test_single_note(tmp_path):
    path = _write_midi(tmp_path, [
        mido.Message("note_on", note=60, velocity=100, time=0),
        mido.Message("note_off", note=60, velocity=0, time=TPB),  # +0.5s
    ])
    notes, duration = parse_midi(path)

    assert len(notes) == 1
    n = notes[0]
    assert n.pitch == 60
    assert n.velocity == 100
    assert n.start == pytest.approx(0.0, abs=1e-6)
    assert n.duration == pytest.approx(0.5, abs=1e-3)
    assert duration == pytest.approx(0.5, abs=1e-3)


def test_notes_sorted_by_start(tmp_path):
    # Emit a later note first in track order; parse must still sort by start.
    path = _write_midi(tmp_path, [
        mido.Message("note_on", note=64, velocity=80, time=0),
        mido.Message("note_off", note=64, velocity=0, time=TPB),       # 0.0 - 0.5
        mido.Message("note_on", note=67, velocity=80, time=0),
        mido.Message("note_off", note=67, velocity=0, time=TPB),       # 0.5 - 1.0
    ])
    notes, _ = parse_midi(path)

    starts = [round(n.start, 3) for n in notes]
    assert starts == sorted(starts)
    assert [n.pitch for n in notes] == [64, 67]


def test_chord_polyphony(tmp_path):
    # Two simultaneous note_ons -> two overlapping notes, both captured.
    path = _write_midi(tmp_path, [
        mido.Message("note_on", note=60, velocity=100, time=0),
        mido.Message("note_on", note=64, velocity=100, time=0),
        mido.Message("note_off", note=60, velocity=0, time=TPB),
        mido.Message("note_off", note=64, velocity=0, time=0),
    ])
    notes, _ = parse_midi(path)

    assert len(notes) == 2
    assert {n.pitch for n in notes} == {60, 64}
    assert all(n.start == pytest.approx(0.0, abs=1e-6) for n in notes)


def test_zero_velocity_note_on_is_note_off(tmp_path):
    # A note_on with velocity 0 is the common "running status" note-off.
    path = _write_midi(tmp_path, [
        mido.Message("note_on", note=72, velocity=90, time=0),
        mido.Message("note_on", note=72, velocity=0, time=TPB),
    ])
    notes, _ = parse_midi(path)

    assert len(notes) == 1
    assert notes[0].pitch == 72
    assert notes[0].duration == pytest.approx(0.5, abs=1e-3)


def test_drum_channel_skipped_by_default(tmp_path):
    path = _write_midi(tmp_path, [
        mido.Message("note_on", note=38, velocity=100, time=0, channel=DRUM_CHANNEL),
        mido.Message("note_off", note=38, velocity=0, time=TPB, channel=DRUM_CHANNEL),
    ])
    assert parse_midi(path)[0] == []
    # ...but available when explicitly requested.
    assert len(parse_midi(path, include_drums=True)[0]) == 1


def test_hanging_note_closed_at_eof(tmp_path):
    # note_on with no matching note_off -> closed at end of file.
    path = _write_midi(tmp_path, [
        mido.Message("note_on", note=60, velocity=100, time=0),
        mido.Message("note_on", note=62, velocity=100, time=TPB),  # advances clock
    ])
    notes, duration = parse_midi(path)

    pitches = {n.pitch for n in notes}
    assert 60 in pitches  # the hanging note survived
    assert duration > 0


def test_empty_midi(tmp_path):
    path = _write_midi(tmp_path, [])
    assert parse_midi(path) == ([], 0.0)


def test_summarize_midi_shape(tmp_path):
    path = _write_midi(tmp_path, [
        mido.Message("note_on", note=60, velocity=100, time=0),
        mido.Message("note_off", note=60, velocity=0, time=TPB),
    ])
    meta = summarize_midi(path)

    assert set(meta) == {"duration_s", "note_count", "track_count"}
    assert meta["note_count"] == 1
    assert meta["track_count"] == 1
    assert meta["duration_s"] == pytest.approx(0.5, abs=0.05)
