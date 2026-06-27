import asyncio
import audioop
import io
import logging
import os
import statistics
import subprocess as sp
import threading
import time
from pathlib import Path

import discord
from pmb_core.audio import transform
from pmb_core.audio.midi import parse_midi

log = logging.getLogger("pmb.discord.playback")

AUDIO_DIR = Path(os.getenv("AUDIO_DIR", "audio"))
SONGS_DIR = AUDIO_DIR / "music"

# 20ms of 48kHz 16-bit stereo silence (discord.py reads 3840-byte PCM frames).
SILENCE_FRAME = b"\x00" * 3840
FRAME_BYTES = 3840

# Mixer voice key for sequential queue playback (one shared lane, plays in order).
QUEUE_VOICE = "__queue__"

# Song render constants. Discord wants 48kHz 16-bit STEREO (4 bytes/frame).
SR = 48000
BYTES_PER_FRAME = 4  # 2 channels * 2 bytes
# Don't pitch-shift the instrument absurdly far — a ±2 octave window keeps it
# musical-ish; out-of-range notes clamp (octave folding is deferred).
MAX_SEMITONE_SHIFT = 24
# Floor each note's audio so very short notes still pop rather than click out.
MIN_NOTE_SECONDS = 0.08
SONG_LOUDNORM = "loudnorm=I=-16:TP=-1.5:LRA=11"


def build_source(file_name, speed, shift, volume, reverse=False):
    """Build a Discord audio source for a clip, applying speed/pitch/volume
    (and optionally playing it backwards).

    Discord consumes a true 48kHz stereo stream, so we use the standard
    (asetrate-based) filter rather than the Mumble reinterpret-rate filter.
    """
    path = AUDIO_DIR.joinpath(file_name)
    audio_filter = transform.generate_standard_filter(volume, speed, shift, reverse)
    return discord.FFmpegPCMAudio(
        str(path),
        options='-af "{0}"'.format(audio_filter),
    )


def _render_clip_pcm(clip_path, shift):
    """Render one clip, pitch-shifted by `shift` semitones, to 48kHz stereo
    s16le PCM bytes (volume 1.0 — overall level is set once at the end)."""
    audio_filter = transform.generate_standard_filter(1.0, 1.0, shift)
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-i", str(clip_path),
        "-af", audio_filter,
        "-ar", str(SR), "-ac", "2", "-f", "s16le", "pipe:1",
    ]
    proc = sp.run(cmd, stdout=sp.PIPE, stderr=sp.PIPE)
    if proc.returncode != 0:
        log.warning("song: ffmpeg shift %s failed: %s", shift, proc.stderr.decode()[:200])
    return proc.stdout


def build_song_source(clip_file, song_file, transpose, speed, gain_db, base_volume, max_seconds=0):
    """Render a whole MIDI song into one stereo PCM source, using `clip_file` as
    the instrument. Returns (discord.PCMAudio, duration_seconds), or (None, 0.0)
    if there's nothing to play. The duration lets the caller time the song queue.

    Each note triggers the clip pitch-shifted to that note's pitch (relative to
    the song's median pitch, so shifts stay small), laid onto a silent canvas at
    the note's onset and capped to its duration. Overlapping notes (chords) mix
    via audioop.add. A final loudnorm tames peaks and sets the level.

    `max_seconds` (0 = no limit) caps the rendered output length: notes starting
    after it are dropped and the canvas is truncated to it.
    Blocking (spawns ffmpeg) — call via asyncio.to_thread.
    """
    song_path = SONGS_DIR.joinpath(song_file)
    clip_path = AUDIO_DIR.joinpath(clip_file)
    notes, _duration = parse_midi(str(song_path))
    if not notes:
        return None, 0.0

    speed = max(0.25, min(4.0, float(speed or 1.0)))
    transpose = int(transpose or 0)
    root = int(statistics.median(n.pitch for n in notes))
    limit_bytes = int(max(0, max_seconds) * SR) * BYTES_PER_FRAME  # 0 = no limit

    def shift_for(note):
        return max(-MAX_SEMITONE_SHIFT, min(MAX_SEMITONE_SHIFT, note.pitch - root + transpose))

    # Render each distinct pitch-shift once (a tune uses only a handful).
    shift_pcm = {}
    for n in notes:
        if limit_bytes and int((n.start / speed) * SR) * BYTES_PER_FRAME >= limit_bytes:
            continue
        shift = shift_for(n)
        if shift not in shift_pcm:
            shift_pcm[shift] = _render_clip_pcm(clip_path, shift)

    min_note_bytes = int(MIN_NOTE_SECONDS * SR) * BYTES_PER_FRAME
    placements = []
    max_end = 0
    for n in notes:
        offset = int((n.start / speed) * SR) * BYTES_PER_FRAME
        if limit_bytes and offset >= limit_bytes:
            continue
        pcm = shift_pcm.get(shift_for(n)) or b""
        if not pcm:
            continue
        cap = max(min_note_bytes, int((n.duration / speed) * SR) * BYTES_PER_FRAME)
        seg = pcm[:cap]
        if limit_bytes:
            seg = seg[:limit_bytes - offset]  # don't ring past the cap
        if not seg:
            continue
        placements.append((offset, seg))
        max_end = max(max_end, offset + len(seg))

    if max_end == 0:
        return None, 0.0

    canvas = bytearray(max_end)
    for i, (offset, seg) in enumerate(placements):
        region = bytes(canvas[offset:offset + len(seg)])
        if len(region) < len(seg):
            seg = seg[:len(region)]
        if not seg:
            continue
        mixed = audioop.add(region, seg, 2)
        canvas[offset:offset + len(mixed)] = mixed
        # audioop holds the GIL; without periodic yields this tight mix loop
        # starves discord.py's realtime audio thread (20ms/frame) and the
        # gateway heartbeat → stutter. Sleep briefly every few notes so they
        # always get a slice. (This runs in a worker thread, not the loop.)
        if i % 8 == 7:
            time.sleep(0.001)

    pcm_out = _finalize_song(bytes(canvas), base_volume * transform.gain_db_to_multiplier(gain_db))

    # discord.PCMAudio drops a trailing partial frame, so pad to a frame boundary.
    if len(pcm_out) % FRAME_BYTES:
        pcm_out += b"\x00" * (FRAME_BYTES - len(pcm_out) % FRAME_BYTES)
    duration_s = len(pcm_out) / (SR * BYTES_PER_FRAME)
    return discord.PCMAudio(io.BytesIO(pcm_out)), duration_s


def _finalize_song(pcm, volume):
    """Loudness-normalise the assembled canvas, apply the overall volume, and
    fade the last 30ms out (clean ending, no click when the cap truncates a
    sound mid-way). Falls back to a plain volume scale if ffmpeg fails."""
    dur = len(pcm) / (SR * BYTES_PER_FRAME)
    fade = min(0.03, dur)
    audio_filter = "{0},volume={1},afade=t=out:st={2:.3f}:d={3:.3f}".format(
        SONG_LOUDNORM, volume, max(0.0, dur - fade), fade
    )
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-f", "s16le", "-ar", str(SR), "-ac", "2", "-i", "pipe:0",
        "-af", audio_filter,
        "-f", "s16le", "-ar", str(SR), "-ac", "2", "pipe:1",
    ]
    proc = sp.run(cmd, input=pcm, stdout=sp.PIPE, stderr=sp.PIPE)
    if proc.returncode == 0 and proc.stdout:
        return proc.stdout
    log.warning("song: finalize loudnorm failed, using raw mix")
    return audioop.mul(pcm, 2, volume)


class _MixerStream(discord.AudioSource):
    """A single never-ending 48kHz stereo PCM stream that mixes any number of
    concurrent "voices" together.

    Each voice is keyed (e.g. by user) so different people's clips overlap, like
    Discord's native soundboard, while re-setting the same key interrupts and
    restarts just that voice. Played once and never stopped, so the connection
    stays warm. read() runs in discord.py's player thread; voices are guarded
    by a lock.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._voices = {}  # key -> (source, on_done)

    def set_voice(self, key, source, on_done=None):
        with self._lock:
            old = self._voices.get(key)
            self._voices[key] = (source, on_done)
        if old is not None:
            if old[0] is not None:
                old[0].cleanup()
            if old[1] is not None:
                old[1]()  # unblock whoever was waiting on the replaced voice

    def drop_voice(self, key):
        """Stop and remove a single voice (e.g. skip the song), firing its
        on_done so anyone awaiting it is unblocked."""
        with self._lock:
            old = self._voices.pop(key, None)
        if old is not None:
            if old[0] is not None:
                old[0].cleanup()
            if old[1] is not None:
                old[1]()

    def read(self):
        with self._lock:
            items = list(self._voices.items())
        if not items:
            return SILENCE_FRAME

        mixed = None
        ended = []
        for key, (src, on_done) in items:
            data = src.read()
            if not data:
                ended.append((key, src, on_done))
                continue
            mixed = data if mixed is None else audioop.add(mixed, data, 2)

        for key, src, on_done in ended:
            with self._lock:
                current = self._voices.get(key)
                if current is not None and current[0] is src:
                    del self._voices[key]
            src.cleanup()
            if on_done is not None:
                on_done()

        return mixed if mixed is not None else SILENCE_FRAME

    def is_opus(self):
        return False

    def clear(self):
        """Drop all active voices immediately (stop playback) but keep the
        stream alive (it just emits silence). on_done fires so anyone awaiting
        a queue voice is unblocked."""
        with self._lock:
            items = list(self._voices.items())
            self._voices.clear()
        for key, (src, on_done) in items:
            if src is not None:
                src.cleanup()
            if on_done is not None:
                on_done()

    def cleanup(self):
        with self._lock:
            voices = list(self._voices.values())
            self._voices.clear()
        for src, _ in voices:
            if src is not None:
                src.cleanup()


class GuildPlayer:
    """Mixes per-user single plays (overlapping, restartable) with one
    sequential queue voice, over a persistent always-on stream."""

    def __init__(self, voice_client):
        self.voice_client = voice_client
        self.queue = asyncio.Queue()
        self._task = None
        self._mixer = _MixerStream()
        self.created_at = time.monotonic()
        self.play_count = 0

    def start(self, loop):
        self._begin_stream()
        if self._task is None or self._task.done():
            self._task = loop.create_task(self._run())

    def stop(self):
        if self._task is not None:
            self._task.cancel()
        self._mixer.cleanup()

    def panic(self):
        """Stop everything now: drain queued items and clear all live voices.
        The warm stream keeps running (silence), so the connection stays warm."""
        drained = 0
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
                self.queue.task_done()
                drained += 1
            except Exception:
                break
        self._mixer.clear()
        log.info("Panic: cleared playback (%d queued dropped)", drained)

    def play_now(self, voice_key, source, on_done=None):
        """Play a single clip on this user's voice — overlaps other users,
        restarts if they were already playing something. `on_done` (if given)
        fires when the source ends, is replaced, or is dropped."""
        self._begin_stream()
        self._log_start(time.monotonic())
        self._mixer.set_voice(voice_key, source, on_done)

    def stop_voice(self, voice_key):
        """Stop a single voice immediately (used to skip the current song)."""
        self._mixer.drop_voice(voice_key)

    async def enqueue(self, source):
        """Queue a clip on the shared sequential queue voice."""
        await self.queue.put((source, time.monotonic()))

    def _begin_stream(self):
        if self.voice_client.is_connected() and not self.voice_client.is_playing():
            self.voice_client.play(self._mixer, after=self._stream_ended)

    def _stream_ended(self, error):
        if error:
            log.warning("Warm stream stopped: %s", error)

    def _log_start(self, queued_at):
        self.play_count += 1
        try:
            ws_latency = self.voice_client.average_latency * 1000
        except Exception:
            ws_latency = -1
        log.info(
            "[timing] player start: %.0fms after enqueue | conn_age=%.0fs plays=%d ws_latency=%.0fms",
            (time.monotonic() - queued_at) * 1000,
            time.monotonic() - self.created_at,
            self.play_count,
            ws_latency,
        )

    async def _run(self):
        while True:
            source, queued_at = await self.queue.get()
            try:
                if not self.voice_client.is_connected():
                    continue
                self._begin_stream()
                self._log_start(queued_at)
                finished = asyncio.Event()

                def _done(event=finished):
                    self.voice_client.loop.call_soon_threadsafe(event.set)

                self._mixer.set_voice(QUEUE_VOICE, source, _done)
                await finished.wait()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Failed to play queued source")
            finally:
                self.queue.task_done()
