import asyncio
import audioop
import logging
import os
import threading
import time
from pathlib import Path

import discord
from pmb_core.audio import transform

log = logging.getLogger("pmb.discord.playback")

AUDIO_DIR = Path(os.getenv("AUDIO_DIR", "audio"))

# 20ms of 48kHz 16-bit stereo silence (discord.py reads 3840-byte PCM frames).
SILENCE_FRAME = b"\x00" * 3840

QUEUE_VOICE = "__queue__"


def build_source(file_name, speed, shift, volume):
    """Build a Discord audio source for a clip, applying speed/pitch/volume.

    Discord consumes a true 48kHz stereo stream, so we use the standard
    (asetrate-based) filter rather than the Mumble reinterpret-rate filter.
    """
    path = AUDIO_DIR.joinpath(file_name)
    audio_filter = transform.generate_standard_filter(volume, speed, shift)
    return discord.FFmpegPCMAudio(
        str(path),
        options='-af "{0}"'.format(audio_filter),
    )


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

    def play_now(self, voice_key, source):
        """Play a single clip on this user's voice — overlaps other users,
        restarts if they were already playing something."""
        self._begin_stream()
        self._log_start(time.monotonic())
        self._mixer.set_voice(voice_key, source, None)

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
