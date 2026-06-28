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

# General MIDI program (instrument) names, indexed by program number 0-127. Used
# to label a song's separate "lines" so the UI can offer a clip per instrument.
GM_INSTRUMENTS = [
    "Acoustic Grand Piano",
    "Bright Acoustic Piano",
    "Electric Grand Piano",
    "Honky-tonk Piano",
    "Electric Piano 1",
    "Electric Piano 2",
    "Harpsichord",
    "Clavi",
    "Celesta",
    "Glockenspiel",
    "Music Box",
    "Vibraphone",
    "Marimba",
    "Xylophone",
    "Tubular Bells",
    "Dulcimer",
    "Drawbar Organ",
    "Percussive Organ",
    "Rock Organ",
    "Church Organ",
    "Reed Organ",
    "Accordion",
    "Harmonica",
    "Tango Accordion",
    "Acoustic Guitar (nylon)",
    "Acoustic Guitar (steel)",
    "Electric Guitar (jazz)",
    "Electric Guitar (clean)",
    "Electric Guitar (muted)",
    "Overdriven Guitar",
    "Distortion Guitar",
    "Guitar Harmonics",
    "Acoustic Bass",
    "Electric Bass (finger)",
    "Electric Bass (pick)",
    "Fretless Bass",
    "Slap Bass 1",
    "Slap Bass 2",
    "Synth Bass 1",
    "Synth Bass 2",
    "Violin",
    "Viola",
    "Cello",
    "Contrabass",
    "Tremolo Strings",
    "Pizzicato Strings",
    "Orchestral Harp",
    "Timpani",
    "String Ensemble 1",
    "String Ensemble 2",
    "Synth Strings 1",
    "Synth Strings 2",
    "Choir Aahs",
    "Voice Oohs",
    "Synth Voice",
    "Orchestra Hit",
    "Trumpet",
    "Trombone",
    "Tuba",
    "Muted Trumpet",
    "French Horn",
    "Brass Section",
    "Synth Brass 1",
    "Synth Brass 2",
    "Soprano Sax",
    "Alto Sax",
    "Tenor Sax",
    "Baritone Sax",
    "Oboe",
    "English Horn",
    "Bassoon",
    "Clarinet",
    "Piccolo",
    "Flute",
    "Recorder",
    "Pan Flute",
    "Blown Bottle",
    "Shakuhachi",
    "Whistle",
    "Ocarina",
    "Lead 1 (square)",
    "Lead 2 (sawtooth)",
    "Lead 3 (calliope)",
    "Lead 4 (chiff)",
    "Lead 5 (charang)",
    "Lead 6 (voice)",
    "Lead 7 (fifths)",
    "Lead 8 (bass + lead)",
    "Pad 1 (new age)",
    "Pad 2 (warm)",
    "Pad 3 (polysynth)",
    "Pad 4 (choir)",
    "Pad 5 (bowed)",
    "Pad 6 (metallic)",
    "Pad 7 (halo)",
    "Pad 8 (sweep)",
    "FX 1 (rain)",
    "FX 2 (soundtrack)",
    "FX 3 (crystal)",
    "FX 4 (atmosphere)",
    "FX 5 (brightness)",
    "FX 6 (goblins)",
    "FX 7 (echoes)",
    "FX 8 (sci-fi)",
    "Sitar",
    "Banjo",
    "Shamisen",
    "Koto",
    "Kalimba",
    "Bagpipe",
    "Fiddle",
    "Shanai",
    "Tinkle Bell",
    "Agogo",
    "Steel Drums",
    "Woodblock",
    "Taiko Drum",
    "Melodic Tom",
    "Synth Drum",
    "Reverse Cymbal",
    "Guitar Fret Noise",
    "Breath Noise",
    "Seashore",
    "Bird Tweet",
    "Telephone Ring",
    "Helicopter",
    "Applause",
    "Gunshot",
]


def gm_instrument_name(program):
    """Friendly General MIDI instrument name for a program number (0-127)."""
    if 0 <= program < len(GM_INSTRUMENTS):
        return GM_INSTRUMENTS[program]
    return "Program {0}".format(program)


class MidiNote:
    __slots__ = ("pitch", "start", "duration", "velocity", "channel", "program")

    def __init__(self, pitch, start, duration, velocity, channel=0, program=0):
        self.pitch = pitch  # MIDI note number 0-127 (60 = middle C)
        self.start = start  # seconds from song start
        self.duration = duration  # seconds
        self.velocity = velocity  # 1-127
        self.channel = channel  # MIDI channel 0-15 (the "line" it's part of)
        self.program = program  # General MIDI program active at note-on

    def __repr__(self):
        return (
            "MidiNote(pitch={0}, start={1:.3f}, dur={2:.3f}, vel={3}, "
            "ch={4}, prog={5})".format(
                self.pitch,
                self.start,
                self.duration,
                self.velocity,
                self.channel,
                self.program,
            )
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
    # Current GM program per channel (program_change updates it; default 0). Each
    # note records the program active on its channel so the renderer can group
    # notes into instrument "lines".
    programs = {}

    for msg in mid:
        now += msg.time
        if msg.type == "program_change":
            programs[msg.channel] = msg.program
            continue
        is_note_on = msg.type == "note_on" and msg.velocity > 0
        is_note_off = msg.type == "note_off" or (
            msg.type == "note_on" and msg.velocity == 0
        )
        if not (is_note_on or is_note_off):
            continue
        if not include_drums and getattr(msg, "channel", 0) == DRUM_CHANNEL:
            continue
        if is_note_on:
            open_notes.setdefault((msg.channel, msg.note), []).append(
                (now, msg.velocity, programs.get(msg.channel, 0))
            )
        else:
            stack = open_notes.get((msg.channel, msg.note))
            if stack:
                start, velocity, program = stack.pop()
                duration = now - start
                if duration > 0:
                    notes.append(
                        MidiNote(
                            msg.note, start, duration, velocity, msg.channel, program
                        )
                    )

    # Close any notes left hanging at end-of-file (malformed/truncated MIDI).
    for (channel, pitch), stack in open_notes.items():
        for start, velocity, program in stack:
            if now - start > 0:
                notes.append(
                    MidiNote(pitch, start, now - start, velocity, channel, program)
                )

    notes.sort(key=lambda n: (n.start, n.pitch))
    duration = max((n.start + n.duration for n in notes), default=0.0)
    return notes, duration


def song_lines(path):
    """Group a song's notes into instrument "lines" so each can be played by a
    different clip. Channels sharing a GM instrument are merged into one line
    (e.g. two "Alto Sax" channels → one line). Returns a list of dicts sorted by
    note count (busiest first):

        {"program": int, "instrument": str, "note_count": int, "channels": [..]}
    """
    notes, _duration = parse_midi(path)
    lines = {}
    for n in notes:
        line = lines.get(n.program)
        if line is None:
            line = {
                "program": n.program,
                "instrument": gm_instrument_name(n.program),
                "note_count": 0,
                "channels": set(),
            }
            lines[n.program] = line
        line["note_count"] += 1
        line["channels"].add(n.channel)
    out = [
        {
            "program": ln["program"],
            "instrument": ln["instrument"],
            "note_count": ln["note_count"],
            "channels": sorted(ln["channels"]),
        }
        for ln in lines.values()
    ]
    out.sort(key=lambda ln: ln["note_count"], reverse=True)
    return out


def summarize_midi(path):
    """Lightweight metadata for the library (used at upload time)."""
    mid = mido.MidiFile(path)
    notes, duration = parse_midi(path)
    return {
        "duration_s": round(duration, 2),
        "note_count": len(notes),
        "track_count": len(mid.tracks),
    }
