import asyncio
import datetime
import logging
import random
import time

import discord
from discord import app_commands
from discord.ext import commands, tasks
from pmb_core.audio import transform
from pmb_core.db.mongodb import MongoInterface

from python_discord_bot import config, playback

log = logging.getLogger("pmb.discord")


def parse_speed(value):
    value = value.strip().lower().rstrip("x")
    try:
        speed = float(value)
    except ValueError:
        speed = 1.0
    return min(max(speed, 0.5), 4.0)


def parse_pitch(value):
    value = value.strip().lower().rstrip("s")
    try:
        pitch = int(round(float(value)))
    except ValueError:
        pitch = 0
    return min(max(pitch, -12), 12)


async def ensure_voice(interaction):
    """Connect to (or move to) the caller's voice channel; None if they aren't in one."""
    voice_state = interaction.user.voice
    if voice_state is None or voice_state.channel is None:
        return None
    channel = voice_state.channel
    voice_client = interaction.guild.voice_client
    if voice_client is None:
        return await channel.connect()
    if voice_client.channel != channel:
        await voice_client.move_to(channel)
    return voice_client


def _chunk_lines(lines, limit):
    buffer = []
    length = 0
    for line in lines:
        if buffer and length + len(line) + 1 > limit:
            yield "\n".join(buffer)
            buffer, length = [], 0
        buffer.append(line)
        length += len(line) + 1
    if buffer:
        yield "\n".join(buffer)


class DiscordBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(command_prefix="!pmb ", intents=intents)
        self.mongo = MongoInterface()
        self.players = {}
        # Songs play one-at-a-time: a worker drains this pending list, and the
        # current + upcoming state is mirrored to the `song_state` doc so the web
        # can show a "now playing" mini-player. See _song_worker.
        self._song_pending = []
        self._song_current = None
        self._song_signal = asyncio.Event()
        self._skip_event = asyncio.Event()
        self._song_worker_task = None

    async def setup_hook(self):
        await asyncio.to_thread(self.mongo.connect)
        await asyncio.to_thread(self.mongo.refresh)
        register_commands(self)
        if config.GUILD_ID:
            guild = discord.Object(id=config.GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()
        # Clear any stale "now playing" left over from a previous run.
        await asyncio.to_thread(self._write_song_state)
        self._song_worker_task = self.loop.create_task(self._song_worker())
        self.poll_commands.start()
        self.publish_voice_state.start()

    def get_player(self, voice_client):
        player = self.players.get(voice_client.guild.id)
        if player is None or player.voice_client is not voice_client:
            if player is not None:
                player.stop()
            player = playback.GuildPlayer(voice_client)
            self.players[voice_client.guild.id] = player
        player.start(self.loop)
        return player

    def resolve_clip(self, ref):
        collection = self.mongo.clips_collection
        return collection.find_one({"identifier": ref}) or collection.find_one(
            {"name": ref}
        )

    async def play_file(
        self, voice_client, file_name, speed, shift, interrupt=False,
        voice_key=None, gain_db=0,
    ):
        volume = await asyncio.to_thread(self.mongo.get_volume)
        volume = volume * transform.gain_db_to_multiplier(gain_db)
        t = time.monotonic()
        source = playback.build_source(file_name, speed, shift, volume)
        log.info(
            "[timing] ffmpeg spawn for %s: %.0fms",
            file_name,
            (time.monotonic() - t) * 1000,
        )
        player = self.get_player(voice_client)
        if interrupt:
            player.play_now(voice_key, source)
        else:
            await player.enqueue(source)

    def active_voice_client(self):
        for voice_client in self.voice_clients:
            if voice_client.is_connected():
                return voice_client
        return None

    def _target_guild(self):
        if config.GUILD_ID:
            return self.get_guild(config.GUILD_ID)
        return self.guilds[0] if self.guilds else None

    def _channel_has_humans(self, channel):
        # Use voice_states (populated straight from Discord's voice events, so
        # reliable WITHOUT the privileged members intent) rather than
        # channel.members, which reads the member cache and can come back empty
        # for a busy channel — that bug made the bot disconnect itself thinking
        # a full channel was abandoned. Errs toward "occupied" when a member
        # isn't cached, so we never wrongly leave.
        for user_id in channel.voice_states:
            if user_id == self.user.id:
                continue
            member = channel.guild.get_member(user_id)
            if member is None or not member.bot:
                return True
        return False

    async def join_channel(self, channel_id):
        if not channel_id:
            return
        channel = self.get_channel(int(channel_id))
        if not isinstance(channel, discord.VoiceChannel):
            log.warning("Join: %s is not a voice channel", channel_id)
            return
        # The bot must never sit in a channel alone — refuse to join one with
        # no human members (on_voice_state_update only handles people leaving).
        if not self._channel_has_humans(channel):
            log.info("Join: %s has no human members; not joining", channel.name)
            return
        voice_client = channel.guild.voice_client
        if voice_client is None:
            voice_client = await channel.connect()
        elif voice_client.channel != channel:
            await voice_client.move_to(channel)
        self.get_player(voice_client)
        # Remember where to rejoin after a restart (manual or the twice-daily one).
        await self._set_rejoin(str(channel.id))

    async def _set_rejoin(self, channel_id):
        await asyncio.to_thread(
            lambda: self.mongo.db.voice_state.update_one(
                {"_id": "state"},
                {"$set": {"rejoin_channel_id": channel_id}},
                upsert=True,
            )
        )

    async def _rejoin_last_channel(self):
        # On startup, rejoin the channel the bot was last in so a restart is
        # seamless. join_channel() still refuses an empty channel.
        try:
            state = await asyncio.to_thread(
                lambda: self.mongo.db.voice_state.find_one({"_id": "state"})
            )
            channel_id = state.get("rejoin_channel_id") if state else None
            if channel_id:
                log.info("Rejoining last channel %s on startup", channel_id)
                await self.join_channel(channel_id)
                if self.active_voice_client() is None:
                    # Target was empty/gone — don't leave a ghost behind.
                    await self._clear_voice_ghost()
                await self._publish_voice_state()
            else:
                # Nothing to rejoin — clear any stale voice session a previous
                # unclean shutdown (hard exit / SIGKILL / crash) may have left, so
                # we don't show as a "ghost" sitting in a channel.
                await self._clear_voice_ghost()
        except Exception:
            log.exception("Rejoin on startup failed")

    async def _clear_voice_ghost(self):
        guild = self._target_guild()
        if guild is None:
            return
        # A bot has a single voice state per guild; setting channel=None forces
        # Discord to drop any connection it still thinks we have, even though
        # this fresh process has no VoiceClient of its own.
        try:
            await guild.change_voice_state(channel=None)
        except Exception:
            log.exception("Clearing stale voice state on startup failed")

    async def _publish_voice_state(self):
        guild = self._target_guild()
        if guild is None:
            return
        channels = [
            {
                "id": str(c.id),
                "name": c.name,
                "users": sum(1 for m in c.members if not m.bot),
                "members": [
                    {"id": str(m.id), "name": m.display_name}
                    for m in c.members
                    if not m.bot
                ],
            }
            for c in guild.voice_channels
        ]
        voice_client = self.active_voice_client()
        current = str(voice_client.channel.id) if voice_client else None
        # Members of the bot's current channel — the presence-gate set.
        present = []
        if voice_client is not None:
            present = [
                {"id": str(m.id), "name": m.display_name}
                for m in voice_client.channel.members
                if not m.bot
            ]
        await asyncio.to_thread(
            lambda: self.mongo.db.voice_state.update_one(
                {"_id": "state"},
                {
                    "$set": {
                        "channels": channels,
                        "current_channel_id": current,
                        "present": present,
                    }
                },
                upsert=True,
            )
        )

    @tasks.loop(seconds=10)
    async def publish_voice_state(self):
        await self._publish_voice_state()

    @publish_voice_state.before_loop
    async def _before_publish(self):
        await self.wait_until_ready()

    async def announce(self, message):
        if not config.ANNOUNCE_CHANNEL_ID or not message:
            return
        channel = self.get_channel(config.ANNOUNCE_CHANNEL_ID)
        if channel is not None:
            text = message.replace("<b>", "**").replace("</b>", "**")
            await channel.send(text)

    async def on_voice_state_update(self, member, before, after):
        # When a human's voice state changes: leave if the bot is now alone in
        # its channel, then republish so per-channel user counts stay fresh.
        if member.bot:
            return
        voice_client = member.guild.voice_client
        if voice_client is not None and voice_client.is_connected():
            if not self._channel_has_humans(voice_client.channel):
                log.info(
                    "Auto-leave: %s has no humans left; disconnecting",
                    voice_client.channel.name,
                )
                await voice_client.disconnect()
                await self._set_rejoin(None)  # don't rejoin an abandoned channel
        await self._publish_voice_state()

    @tasks.loop(seconds=0.1)
    async def poll_commands(self):
        for _ in range(20):
            command = await asyncio.to_thread(self.mongo.get_next_pending_command)
            if command is None:
                return
            try:
                await self._handle_pending(command)
            finally:
                await asyncio.to_thread(self.mongo.mark_command_done, command["_id"])

    @poll_commands.before_loop
    async def _before_poll(self):
        await self.wait_until_ready()
        await self._rejoin_last_channel()

    async def _handle_pending(self, command):
        cmd_type = command.get("type", "play")
        if cmd_type == "announce":
            await self.announce(command.get("message", ""))
            return
        if cmd_type == "join":
            await self.join_channel(command.get("channel_id"))
            await self._publish_voice_state()
            return
        if cmd_type == "leave":
            voice_client = self.active_voice_client()
            if voice_client is not None:
                await voice_client.disconnect()
            await self._set_rejoin(None)
            await self._publish_voice_state()
            return
        if cmd_type == "restart":
            # A fast in-process reconnect, NOT a process restart: a full exit +
            # Docker relaunch meant a ~75s blackout. Instead we just drop the
            # (possibly laggy) warm voice connection, tear down the player so the
            # mixer stream is rebuilt fresh, and rejoin the same channel — a few
            # seconds, no downtime. The twice-daily cron still does a real
            # `docker restart` for a genuine clean slate.
            requested_by = command.get("requested_by", "web")
            voice_client = self.active_voice_client()
            if voice_client is None:
                log.info(
                    "Reconnect requested by %s, but not in a voice channel — nothing to do",
                    requested_by,
                )
                return
            channel_id = str(voice_client.channel.id)
            guild_id = voice_client.guild.id
            await self.announce(
                "♻ **{0}** reconnected the bot".format(requested_by)
            )
            log.info(
                "Reconnect requested by %s; dropping voice and rejoining %s",
                requested_by,
                channel_id,
            )
            try:
                await asyncio.wait_for(voice_client.disconnect(force=True), timeout=5)
            except Exception:
                log.exception("Voice disconnect during reconnect failed")
            player = self.players.pop(guild_id, None)
            if player is not None:
                try:
                    player.stop()  # discard the stale warm mixer stream
                except Exception:
                    log.exception("Stopping old player during reconnect failed")
            await asyncio.sleep(1)  # let Discord register the disconnect first
            await self.join_channel(channel_id)
            await self._publish_voice_state()
            return
        if cmd_type == "stop":
            # Clear the song queue + current song too, then panic the mixer.
            self._song_pending.clear()
            self._skip_event.set()
            await asyncio.to_thread(self._write_song_state)
            voice_client = self.active_voice_client()
            if voice_client is not None:
                player = self.players.get(voice_client.guild.id)
                if player is not None:
                    player.panic()
            return

        if cmd_type == "play_song":
            # Don't play inline (that would block the command loop); hand off to
            # the song worker, which serialises playback one song at a time.
            self._song_pending.append(command)
            self._song_signal.set()
            await asyncio.to_thread(self._write_song_state)
            return

        if cmd_type == "skip_song":
            self._skip_event.set()
            return

        voice_client = self.active_voice_client()
        if voice_client is None:
            log.warning(
                "No active voice channel; skipping clip %s", command.get("clip_ref")
            )
            return

        speed = float(command.get("speed", 1.0))
        pitch = float(command.get("pitch", 0))

        created = command.get("created_at")
        if isinstance(created, datetime.datetime):
            waited = (datetime.datetime.utcnow() - created).total_seconds() * 1000
            log.info(
                "[timing] %s waited %.0fms in pending queue",
                command.get("clip_ref"),
                waited,
            )

        if cmd_type == "play":
            name = command.get("clip_name") or command.get("clip_ref")
            await self.announce(
                "**{0}** played: /pp {1:g}x {2}s {3}".format(
                    command.get("requested_by", "web"), speed, int(pitch), name
                )
            )

        t0 = time.monotonic()
        doc = await asyncio.to_thread(self.resolve_clip, command["clip_ref"])
        if doc is None:
            log.warning("Clip not found: %s", command.get("clip_ref"))
            return
        # A single play gets its own per-user voice (overlaps others, restarts
        # on repeat); queue items play sequentially on the shared queue voice.
        await self.play_file(
            voice_client,
            doc["file"],
            speed,
            pitch,
            interrupt=(cmd_type == "play"),
            voice_key=command.get("requested_by") or "web",
            gain_db=doc.get("gain_db", 0),
        )
        log.info(
            "[timing] %s resolve+build+enqueue %.0fms",
            command["clip_ref"],
            (time.monotonic() - t0) * 1000,
        )

    def _write_song_state(self):
        """Mirror the current song + upcoming queue to the `song_state` singleton
        so the web can render the now-playing mini-player. Blocking (pymongo)."""
        queue = [
            {
                "song_name": c.get("song_name") or c.get("song"),
                "clip_name": c.get("clip_name") or c.get("clip_ref"),
                "requested_by": c.get("requested_by"),
            }
            for c in self._song_pending
        ]
        self.mongo.db.song_state.replace_one(
            {"_id": "singleton"},
            {"_id": "singleton", "current": self._song_current, "queue": queue,
             "updated_at": datetime.datetime.utcnow()},
            upsert=True,
        )

    async def _song_worker(self):
        """Play queued songs one at a time. Each waits for the previous to finish
        (or be skipped) before starting."""
        while True:
            if not self._song_pending:
                self._song_current = None
                await asyncio.to_thread(self._write_song_state)
                self._song_signal.clear()
                await self._song_signal.wait()
                continue
            command = self._song_pending.pop(0)
            try:
                await self._play_one_song(command)
            except Exception:
                log.exception("song worker: failed to play %s", command.get("song"))
            finally:
                self._song_current = None
                await asyncio.to_thread(self._write_song_state)

    async def _play_one_song(self, command):
        """Render one MIDI song with a clip as the instrument and play it to
        completion (or until skipped)."""
        voice_client = self.active_voice_client()
        if voice_client is None:
            log.warning("play_song: not in a voice channel; dropping %s", command.get("song"))
            return
        song_file = command.get("song")
        clip_ref = command.get("clip_ref")
        if not song_file or not clip_ref:
            log.warning("play_song: missing song or clip_ref")
            return
        doc = await asyncio.to_thread(self.resolve_clip, clip_ref)
        if doc is None:
            log.warning("play_song: clip not found: %s", clip_ref)
            return

        transpose = int(command.get("transpose", 0))
        speed = float(command.get("speed", 1.0))
        gain_db = float(command.get("gain", 0)) + float(doc.get("gain_db", 0))
        max_seconds = float(command.get("max_seconds", 0) or 0)
        base_volume = await asyncio.to_thread(self.mongo.get_volume)

        t0 = time.monotonic()
        source, duration = await asyncio.to_thread(
            playback.build_song_source,
            doc["file"], song_file, transpose, speed, gain_db, base_volume, max_seconds,
        )
        log.info(
            "[timing] song render %s on %s: %.0fms (%.1fs)",
            song_file, clip_ref, (time.monotonic() - t0) * 1000, duration,
        )
        if source is None:
            log.warning("play_song: nothing to render for %s", song_file)
            return

        song_name = command.get("song_name") or song_file
        clip_name = command.get("clip_name") or clip_ref
        requested_by = command.get("requested_by", "web")
        self._song_current = {
            "song_name": song_name,
            "clip_name": clip_name,
            "requested_by": requested_by,
            "started_at": datetime.datetime.utcnow(),
            "duration_s": round(duration, 2),
        }
        await asyncio.to_thread(self._write_song_state)

        player = self.get_player(voice_client)
        self._skip_event.clear()
        done = asyncio.Event()
        player.play_now("__song__", source, lambda: self.loop.call_soon_threadsafe(done.set))

        # Wait for the song to finish naturally, be skipped, or a safety timeout.
        skip_wait = asyncio.ensure_future(self._skip_event.wait())
        done_wait = asyncio.ensure_future(done.wait())
        try:
            await asyncio.wait(
                {skip_wait, done_wait}, timeout=duration + 5.0,
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            skip_wait.cancel()
            done_wait.cancel()
            if self._skip_event.is_set():
                log.info("song skipped: %s", song_name)
                player.stop_voice("__song__")
                self._skip_event.clear()


def register_commands(bot):
    @bot.tree.command(name="play", description="Play a clip in your voice channel")
    @app_commands.describe(
        clip="Clip name or id",
        speed="Playback speed, e.g. 2x (default 1x)",
        pitch="Pitch shift in semitones, e.g. 3s (default 0s)",
    )
    async def play(interaction, clip: str, speed: str = "1x", pitch: str = "0s"):
        await interaction.response.defer(thinking=True)
        voice_client = await ensure_voice(interaction)
        if voice_client is None:
            await interaction.followup.send(
                "Join a voice channel first.", ephemeral=True
            )
            return
        doc = await asyncio.to_thread(bot.resolve_clip, clip)
        if doc is None:
            await interaction.followup.send(
                "No clip found: `{0}`".format(clip), ephemeral=True
            )
            return
        speed_value = parse_speed(speed)
        pitch_value = parse_pitch(pitch)
        await bot.play_file(
            voice_client,
            doc["file"],
            speed_value,
            pitch_value,
            interrupt=True,
            voice_key=str(interaction.user.id),
            gain_db=doc.get("gain_db", 0),
        )
        await interaction.followup.send(
            "▶ Playing **{0}** ({1:g}x, {2}s)".format(
                doc["name"], speed_value, pitch_value
            )
        )

    @bot.tree.command(name="list", description="List available clips")
    @app_commands.describe(tag="Optional tag to filter by")
    async def list_clips(interaction, tag: str = None):
        await interaction.response.defer(ephemeral=True)
        pairs = await asyncio.to_thread(
            lambda: sorted(
                (c["name"], c["identifier"]) for c in bot.mongo.get_clips(tag)
            )
        )
        if not pairs:
            await interaction.followup.send("No clips found.", ephemeral=True)
            return
        lines = ["`{1}` {0}".format(name, ident) for name, ident in pairs]
        for chunk in _chunk_lines(lines, 1900):
            await interaction.followup.send(chunk, ephemeral=True)

    @bot.tree.command(name="random", description="Play random clips")
    @app_commands.describe(count="How many clips (1-10)")
    async def random_clips(interaction, count: int = 1):
        await interaction.response.defer(thinking=True)
        voice_client = await ensure_voice(interaction)
        if voice_client is None:
            await interaction.followup.send(
                "Join a voice channel first.", ephemeral=True
            )
            return
        count = min(max(count, 1), 10)
        docs = await asyncio.to_thread(lambda: list(bot.mongo.get_clips()))
        if not docs:
            await interaction.followup.send("No clips available.", ephemeral=True)
            return
        for doc in (random.choice(docs) for _ in range(count)):
            await bot.play_file(voice_client, doc["file"], 1.0, 0)
        await interaction.followup.send("🎲 Queued {0} random clip(s).".format(count))

    @bot.tree.command(name="volume", description="Set playback volume (0-5)")
    @app_commands.describe(level="Volume multiplier, e.g. 0.5")
    async def volume(interaction, level: float):
        if not 0 < level <= 5:
            await interaction.response.send_message(
                "Volume must be in (0, 5].", ephemeral=True
            )
            return
        await asyncio.to_thread(bot.mongo.set_volume, level)
        await interaction.response.send_message("🔊 Volume set to {0}".format(level))


bot = DiscordBot()


def run():
    bot.run(config.TOKEN)
