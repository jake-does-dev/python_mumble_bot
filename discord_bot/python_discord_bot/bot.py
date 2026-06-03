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

    async def join_channel(self, channel_id):
        if not channel_id:
            return
        channel = self.get_channel(int(channel_id))
        if not isinstance(channel, discord.VoiceChannel):
            log.warning("Join: %s is not a voice channel", channel_id)
            return
        # The bot must never sit in a channel alone — refuse to join one with
        # no human members (on_voice_state_update only handles people leaving).
        if not any(not m.bot for m in channel.members):
            log.info("Join: %s has no human members; not joining", channel.name)
            return
        voice_client = channel.guild.voice_client
        if voice_client is None:
            voice_client = await channel.connect()
        elif voice_client.channel != channel:
            await voice_client.move_to(channel)
        self.get_player(voice_client)

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
            if not any(not m.bot for m in voice_client.channel.members):
                await voice_client.disconnect()
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
            await self._publish_voice_state()
            return
        if cmd_type == "stop":
            voice_client = self.active_voice_client()
            if voice_client is not None:
                player = self.players.get(voice_client.guild.id)
                if player is not None:
                    player.panic()
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
