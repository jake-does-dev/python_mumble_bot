"""Tests for the Discord bot's playback module.

The queue regression was a `NameError: QUEUE_VOICE is not defined` — a constant
got deleted, the module imported fine until the queue path ran, and queues went
silent. The import-smoke + constant tests here would have caught exactly that.
The mixer tests lock the PCM-mixing maths and the on_done callbacks the song
queue / skip logic depends on.
"""

import audioop
import shutil

import discord
import mido
import pytest

from python_discord_bot import playback

FRAME_LEN = len(playback.SILENCE_FRAME)  # one 20ms stereo frame, in bytes


# --- import smoke / constants (catches the deleted-constant class of bug) ----

def test_module_imports_and_bot_imports():
    # bot.py imports playback and references its constants at call time; importing
    # it exercises the module-level wiring that a stray NameError would break.
    from python_discord_bot import bot  # noqa: F401


def test_queue_voice_constant_present():
    assert playback.QUEUE_VOICE == "__queue__"


def test_expected_public_symbols_exist():
    for name in ("build_song_source", "build_source", "_MixerStream", "GuildPlayer"):
        assert hasattr(playback, name), name


# --- _MixerStream PCM mixing ------------------------------------------------

class FakeSource(discord.AudioSource):
    """Yields the given frames once each, then EOF (b'')."""

    def __init__(self, frames):
        self._frames = list(frames)
        self.cleaned = False

    def read(self):
        return self._frames.pop(0) if self._frames else b""

    def cleanup(self):
        self.cleaned = True

    def is_opus(self):
        return False


def _const_frame(sample_value):
    """A full stereo frame where every 16-bit sample equals `sample_value`."""
    return (sample_value & 0xFFFF).to_bytes(2, "little") * (FRAME_LEN // 2)


def test_empty_mixer_emits_silence():
    mixer = playback._MixerStream()
    assert mixer.read() == playback.SILENCE_FRAME


def test_single_voice_passes_through_then_ends_and_fires_on_done():
    mixer = playback._MixerStream()
    done = []
    src = FakeSource([_const_frame(7)])
    mixer.set_voice("u1", src, on_done=lambda: done.append(True))

    assert mixer.read() == _const_frame(7)   # the frame plays
    assert mixer.read() == playback.SILENCE_FRAME  # source exhausted -> silence
    assert done == [True]                    # on_done fired exactly once
    assert src.cleaned is True               # source cleaned up
    assert mixer.read() == playback.SILENCE_FRAME  # voice removed, still silent


def test_two_voices_are_summed():
    mixer = playback._MixerStream()
    mixer.set_voice("a", FakeSource([_const_frame(100)]))
    mixer.set_voice("b", FakeSource([_const_frame(200)]))

    mixed = mixer.read()
    assert mixed == audioop.add(_const_frame(100), _const_frame(200), 2)
    assert mixed == _const_frame(300)


def test_set_voice_same_key_replaces_and_unblocks_old():
    mixer = playback._MixerStream()
    done = []
    old = FakeSource([_const_frame(1)])
    mixer.set_voice("k", old, on_done=lambda: done.append("old"))
    # re-setting the same key interrupts the old voice
    mixer.set_voice("k", FakeSource([_const_frame(2)]), on_done=lambda: done.append("new"))

    assert done == ["old"]      # old voice's waiter was unblocked
    assert old.cleaned is True
    assert mixer.read() == _const_frame(2)  # the new voice is what plays


def test_drop_voice_stops_and_fires_on_done():
    mixer = playback._MixerStream()
    done = []
    src = FakeSource([_const_frame(5)] * 10)
    mixer.set_voice(playback.QUEUE_VOICE, src, on_done=lambda: done.append(True))

    mixer.drop_voice(playback.QUEUE_VOICE)
    assert done == [True]
    assert src.cleaned is True
    assert mixer.read() == playback.SILENCE_FRAME  # gone despite frames remaining


def test_clear_fires_all_on_done():
    mixer = playback._MixerStream()
    fired = []
    mixer.set_voice("a", FakeSource([_const_frame(1)] * 5), on_done=lambda: fired.append("a"))
    mixer.set_voice("b", FakeSource([_const_frame(1)] * 5), on_done=lambda: fired.append("b"))

    mixer.clear()
    assert set(fired) == {"a", "b"}
    assert mixer.read() == playback.SILENCE_FRAME


# --- build_song_source -------------------------------------------------------

def _write_midi(path, notes_ticks=480):
    mid = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    track.append(mido.Message("note_on", note=60, velocity=100, time=0))
    track.append(mido.Message("note_off", note=60, velocity=0, time=notes_ticks))
    track.append(mido.Message("note_on", note=64, velocity=100, time=0))
    track.append(mido.Message("note_off", note=64, velocity=0, time=notes_ticks))
    mid.tracks.append(track)
    mid.save(str(path))


def test_build_song_source_empty_midi_returns_none(tmp_path, monkeypatch):
    # An empty MIDI -> no notes -> (None, 0.0), and crucially no ffmpeg spawn.
    songs = tmp_path / "music"
    songs.mkdir()
    monkeypatch.setattr(playback, "AUDIO_DIR", tmp_path)
    monkeypatch.setattr(playback, "SONGS_DIR", songs)
    empty = songs / "empty.mid"
    mido.MidiFile(ticks_per_beat=480).save(str(empty))

    source, duration = playback.build_song_source(
        "clip.wav", "empty.mid", transpose=0, speed=1.0, gain_db=0.0, base_volume=1.0
    )
    assert source is None and duration == 0.0


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not available")
def test_build_song_source_renders_pcm(tmp_path, monkeypatch):
    import subprocess as sp

    songs = tmp_path / "music"
    songs.mkdir()
    monkeypatch.setattr(playback, "AUDIO_DIR", tmp_path)
    monkeypatch.setattr(playback, "SONGS_DIR", songs)

    # a real 0.5s tone clip for the instrument
    clip = tmp_path / "clip.wav"
    sp.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
         "-i", "sine=frequency=440:duration=0.5", "-ar", "48000", "-ac", "2", str(clip)],
        check=True,
    )
    _write_midi(songs / "tune.mid")

    source, duration = playback.build_song_source(
        "clip.wav", "tune.mid", transpose=0, speed=1.0, gain_db=0.0, base_volume=1.0
    )

    assert isinstance(source, discord.PCMAudio)
    assert duration > 0
    # the rendered PCM is frame-aligned (PCMAudio drops a trailing partial frame)
    pcm = source.stream.read()
    assert len(pcm) % playback.FRAME_BYTES == 0
    assert len(pcm) > 0
