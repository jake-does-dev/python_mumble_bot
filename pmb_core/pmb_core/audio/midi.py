"""Minimal MIDI reader for the "play a clip as an instrument" feature.

MIDI is the only song format the bots play (the old MusicXML path is dormant).
We flatten a Standard MIDI File into a simple list of notes on an absolute
seconds timeline; each bot then renders it by pitch-shifting an instrument clip
onto a PCM canvas (mono for Mumble, stereo for Discord).

``mido`` does the heavy lifting: iterating a ``MidiFile`` yields messages whose
``.time`` is already in seconds (tempo-adjusted), so we just accumulate it.
"""

import mido

# General MIDI percussion lives on channel 9 (0-indexed). Its "pitches" are drum
# voices, not a melody, so rendering them as pitched clips sounds wrong — skip.
DRUM_CHANNEL = 9


class MidiNote:
    __slots__ = ("pitch", "start", "duration", "velocity")

    def __init__(self, pitch, start, duration, velocity):
        self.pitch = pitch          # MIDI note number 0-127 (60 = middle C)
        self.start = start          # seconds from song start
        self.duration = duration    # seconds
        self.velocity = velocity    # 1-127

    def __repr__(self):
        return "MidiNote(pitch={0}, start={1:.3f}, dur={2:.3f}, vel={3})".format(
            self.pitch, self.start, self.duration, self.velocity
        )


def parse_midi(path, include_drums=False):
    """Parse a .mid file into a flat, time-sorted list of MidiNote.

    Returns ``(notes, duration_seconds)``. Notes from all tracks are merged onto
    one timeline (polyphony is fine — the renderer mixes overlaps).
    """
    mid = mido.MidiFile(path)

    now = 0.0
    # open_notes[(channel, pitch)] = [(start, velocity), ...] (a stack, so
    # repeated note-ons on the same pitch pair with note-offs in LIFO order).
    open_notes = {}
    notes = []

    for msg in mid:
        now += msg.time
        is_note_on = msg.type == "note_on" and msg.velocity > 0
        is_note_off = msg.type == "note_off" or (
            msg.type == "note_on" and msg.velocity == 0
        )
        if not (is_note_on or is_note_off):
            continue
        if not include_drums and getattr(msg, "channel", 0) == DRUM_CHANNEL:
            continue
        if is_note_on:
            open_notes.setdefault((msg.channel, msg.note), []).append((now, msg.velocity))
        else:
            stack = open_notes.get((msg.channel, msg.note))
            if stack:
                start, velocity = stack.pop()
                duration = now - start
                if duration > 0:
                    notes.append(MidiNote(msg.note, start, duration, velocity))

    # Close any notes left hanging at end-of-file (malformed/truncated MIDI).
    for (_channel, pitch), stack in open_notes.items():
        for start, velocity in stack:
            if now - start > 0:
                notes.append(MidiNote(pitch, start, now - start, velocity))

    notes.sort(key=lambda n: (n.start, n.pitch))
    duration = max((n.start + n.duration for n in notes), default=0.0)
    return notes, duration


def summarize_midi(path):
    """Lightweight metadata for the library (used at upload time)."""
    mid = mido.MidiFile(path)
    notes, duration = parse_midi(path)
    return {
        "duration_s": round(duration, 2),
        "note_count": len(notes),
        "track_count": len(mid.tracks),
    }
