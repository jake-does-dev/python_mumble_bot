"""Tests for SongsService MIDI "lines" extraction — the data behind assigning a
different clip per instrument. Builds tiny in-memory MIDIs with mido so no
fixture files are needed."""

import io

import mido

from app.services.commands import CommandsService
from app.services.songs import SongsService, _extract_lines, _summarize


def _midi(tracks):
    """tracks: list of (program, channel, n_notes). Returns MIDI file bytes."""
    mid = mido.MidiFile()
    tr = mido.MidiTrack()
    mid.tracks.append(tr)
    for program, channel, n in tracks:
        tr.append(mido.Message("program_change", program=program, channel=channel, time=0))
        for _ in range(n):
            tr.append(mido.Message("note_on", note=60, velocity=80, channel=channel, time=0))
            tr.append(mido.Message("note_off", note=60, velocity=0, channel=channel, time=120))
    buf = io.BytesIO()
    mid.save(file=buf)
    return buf.getvalue()


def test_lines_group_by_instrument_merging_channels():
    # Two channels share program 65 (Alto Sax) → one merged line; trumpet (56)
    # and bass (32) are their own. Drums (channel 9) are excluded entirely.
    data = _midi([
        (56, 0, 5),    # Trumpet, 5 notes
        (65, 1, 4),    # Alto Sax, ch1
        (65, 2, 3),    # Alto Sax, ch2  -> merges with the above into 7
        (32, 3, 8),    # Acoustic Bass
        (0, 9, 10),    # drums -> ignored
    ])
    lines = _extract_lines(data)

    by_prog = {ln["program"]: ln for ln in lines}
    assert set(by_prog) == {56, 65, 32}  # no drum line
    assert by_prog[65]["note_count"] == 7
    assert by_prog[65]["channels"] == [1, 2]
    assert by_prog[56]["note_count"] == 5
    # sorted busiest first
    assert [ln["program"] for ln in lines] == [32, 65, 56]


def test_single_instrument_song_is_one_line():
    lines = _extract_lines(_midi([(0, 0, 6)]))
    assert len(lines) == 1
    assert lines[0]["program"] == 0 and lines[0]["note_count"] == 6


def test_summarize_reports_instrument_count():
    meta = _summarize(_midi([(56, 0, 3), (65, 1, 2), (65, 2, 2), (0, 9, 4)]))
    # two melodic programs (drums excluded) → 2 instruments
    assert meta["instrument_count"] == 2
    assert meta["note_count"] == 7  # drums not counted


def test_history_remembers_per_line_instruments(db):
    # A play with per-line instruments must round-trip through history so it can
    # be replayed with the exact same clips + volumes.
    instruments = [
        {"program": 56, "clip_ref": "honk", "clip_name": "honk", "gain": -3},
        {"program": 32, "clip_ref": "bark", "clip_name": "bark", "gain": 2},
    ]
    CommandsService().enqueue_song(
        song_filename="moon.mid", song_name="Fly Me to the Moon",
        clip_ref="meow", clip_name="meow", requested_by="winneh",
        song_id="moon", gain=-6, instruments=instruments,
    )
    hist = SongsService().get_history()
    assert len(hist) == 1
    assert hist[0]["instruments"] == instruments
    assert hist[0]["gain"] == -6
