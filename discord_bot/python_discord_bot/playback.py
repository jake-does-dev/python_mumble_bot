import asyncio
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


class _WarmStream(discord.AudioSource):
    """A single, never-ending 48kHz stereo PCM stream.

    It emits the current clip's audio when one is set, and silence otherwise.
    Played once via ``voice_client.play`` and never stopped, so the voice
    connection stays continuously active ("warm") and Discord's jitter buffer
    never drains between clips — which is what was delaying the first audio
    after idle gaps. read() runs in discord.py's player thread, so access to
    the current clip is guarded by a lock.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._current = None
        self._on_done = None

    def set_clip(self, source, on_done):
        with self._lock:
            old, self._current, self._on_done = self._current, source, on_done
        if old is not None:
            old.cleanup()

    def read(self):
        with self._lock:
            src = self._current
            on_done = self._on_done
        if src is not None:
            data = src.read()
            if data:
                return data
            with self._lock:
                if self._current is src:
                    self._current = None
                    self._on_done = None
            src.cleanup()
            if on_done is not None:
                on_done()
        return SILENCE_FRAME

    def is_opus(self):
        return False

    def cleanup(self):
        with self._lock:
            current, self._current, self._on_done = self._current, None, None
        if current is not None:
            current.cleanup()


class GuildPlayer:
    """Plays queued clips one at a time over a persistent, always-on stream."""

    def __init__(self, voice_client):
        self.voice_client = voice_client
        self.queue = asyncio.Queue()
        self._task = None
        self._stream = _WarmStream()
        self.created_at = time.monotonic()
        self.play_count = 0

    def start(self, loop):
        self._begin_stream()
        if self._task is None or self._task.done():
            self._task = loop.create_task(self._run())

    def stop(self):
        if self._task is not None:
            self._task.cancel()
        self._stream.cleanup()

    async def enqueue(self, source):
        await self.queue.put((source, time.monotonic()))

    def _begin_stream(self):
        # Start the warm (silence) stream if it isn't already running, so the
        # connection is kept active even while idle.
        if self.voice_client.is_connected() and not self.voice_client.is_playing():
            self.voice_client.play(self._stream, after=self._stream_ended)

    def _stream_ended(self, error):
        if error:
            log.warning("Warm stream stopped: %s", error)

    async def _run(self):
        while True:
            source, queued_at = await self.queue.get()
            try:
                if not self.voice_client.is_connected():
                    continue
                self._begin_stream()

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

                finished = asyncio.Event()

                def _done(event=finished):
                    self.voice_client.loop.call_soon_threadsafe(event.set)

                self._stream.set_clip(source, _done)
                await finished.wait()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Failed to play queued source")
            finally:
                self.queue.task_done()
