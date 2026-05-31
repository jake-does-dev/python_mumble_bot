import asyncio
import logging
import os
from pathlib import Path

import discord
from pmb_core.audio import transform

log = logging.getLogger("pmb.discord.playback")

AUDIO_DIR = Path(os.getenv("AUDIO_DIR", "audio"))


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


class GuildPlayer:
    """Plays queued audio sources one at a time for a single guild."""

    def __init__(self, voice_client):
        self.voice_client = voice_client
        self.queue = asyncio.Queue()
        self._task = None

    def start(self, loop):
        if self._task is None or self._task.done():
            self._task = loop.create_task(self._run())

    async def enqueue(self, source):
        await self.queue.put(source)

    async def _run(self):
        while True:
            source = await self.queue.get()
            try:
                if not self.voice_client.is_connected():
                    continue
                finished = asyncio.Event()

                def _after(error, event=finished):
                    if error:
                        log.warning("Playback error: %s", error)
                    self.voice_client.loop.call_soon_threadsafe(event.set)

                self.voice_client.play(source, after=_after)
                await finished.wait()
            except Exception:
                log.exception("Failed to play queued source")
            finally:
                self.queue.task_done()
