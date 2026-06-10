import asyncio
import audioop
import datetime
import logging
import random
import re
import threading
import time
import wave
from collections import deque

import discord
from discord import app_commands
from discord.ext import commands, tasks, voice_recv
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
    bot = interaction.client
    voice_client = interaction.guild.voice_client
    if voice_client is None:
        return await bot._connect_voice(channel)
    if voice_client.channel != channel:
        await voice_client.move_to(channel)
    bot._start_listening(voice_client)
    return voice_client


def _patch_voice_recv_decode():
    """Two fixes to discord-ext-voice-recv so it can capture E2EE voice:

    1. **DAVE (E2EE).** Discord voice is end-to-end encrypted by default — the
       opus payload is MLS-encrypted *inside* the transport encryption, and
       voice-recv only strips the transport layer (leaving opus as noise). We
       MLS-decrypt each sender's frame using the session discord.py already
       maintains (the bot is a real group member), keeping E2EE intact.

       Crucially this is done **in network-arrival order**, inside the socket
       callback's transport-decrypt step (``decrypt_rtp``), *before* voice-recv's
       jitter buffer reorders packets. The MLS media ratchet is order-sensitive,
       so decrypting after reordering corrupts ~3% of frames. Passthrough mode is
       kept on (discord.py only enables it transiently) so davey decrypts the
       encrypted frames and passes Discord's occasional un-E2EE frames through.
    2. **Resilience.** voice-recv tears down the *entire* receive loop on a single
       decode error. We skip a bad packet (opus PLC conceals the gap) instead.
    """
    from discord.ext.voice_recv import opus as _vr_opus
    from discord.ext.voice_recv import reader as _vr_reader

    if getattr(_vr_opus.PacketDecoder, "_pmb_patched", False):
        return

    try:
        import davey
    except Exception:  # noqa: BLE001
        davey = None

    stats = {"dave_ok": 0, "dave_skip": 0, "dave_fail": 0, "ok": 0, "opus_fail": 0}
    pt = {"sess": None, "t": 0.0}
    # Sentinel for "this frame is lost/undecryptable" — conceal it downstream
    # rather than feeding opus ciphertext (which decodes into static).
    LOST = b"\x00LOST"

    # --- 1. DAVE-decrypt in arrival order, wrapping each reader's decrypt_rtp ---
    _orig_reader_init = _vr_reader.AudioReader.__init__

    def _reader_init(self, sink, voice_client, **kwargs):
        _orig_reader_init(self, sink, voice_client, **kwargs)
        if davey is None:
            return
        decryptor = self.decryptor
        _orig_decrypt_rtp = decryptor.decrypt_rtp

        def _decrypt_rtp(packet):
            data = _orig_decrypt_rtp(packet)  # transport decryption (unchanged)
            # Strip RTP padding (RFC3550 §5.1) — Discord sets the padding bit and
            # voice_recv doesn't remove it, so the trailing padding bytes corrupt
            # the DAVE-decrypt input → static. The P bit is in the cleartext
            # header; the final decrypted byte is the padding length.
            # (Mirrors discord.js fix discordjs/discord.js#11449.)
            if data and getattr(packet, "padding", False):
                pad = data[-1]
                if 0 < pad <= len(data):
                    data = data[:-pad]
            conn = getattr(voice_client, "_connection", None)
            sess = getattr(conn, "dave_session", None)
            if sess is None or getattr(conn, "dave_protocol_version", 0) <= 0:
                return data  # E2EE not active — plain opus already
            uid = voice_client._get_id_from_ssrc(packet.ssrc)
            if uid is None:
                stats["dave_skip"] += 1
                return LOST  # sender unmapped yet — conceal, don't leak ciphertext
            # Keep passthrough on (discord.py only enables it transiently) so davey
            # returns Discord's occasional un-E2EE frames as plain opus instead of
            # erroring. Re-assert often, since it lapses.
            now = time.monotonic()
            if sess is not pt["sess"] or now - pt["t"] > 1:
                try:
                    sess.set_passthrough_mode(True)
                except Exception:  # noqa: BLE001
                    pass
                pt["sess"], pt["t"] = sess, now
            try:
                out = sess.decrypt(int(uid), davey.MediaType.audio, bytes(data))
                stats["dave_ok"] += 1
                if not pt.get("logged_e2ee"):
                    pt["logged_e2ee"] = True
                    log.info(
                        "E2EE voice active: DAVE protocol v%s, outgoing-encrypted=%s",
                        getattr(conn, "dave_protocol_version", 0),
                        getattr(conn, "can_encrypt", False),
                    )
                return out
            except Exception as e:  # noqa: BLE001
                stats["dave_fail"] += 1
                if stats["dave_fail"] <= 5:
                    log.info("DAVE decrypt fail #%d: %r", stats["dave_fail"], e)
                return LOST  # undecryptable — conceal (NOT ciphertext → no static)

        decryptor.decrypt_rtp = _decrypt_rtp

    _vr_reader.AudioReader.__init__ = _reader_init

    # --- 2. Resilient opus decode (data is already DAVE-decrypted by now) ------
    _orig_decode = _vr_opus.PacketDecoder._decode_packet

    def _plc(self):
        try:
            return self._decoder.decode(None, fec=False)
        except Exception:  # noqa: BLE001
            return b""

    def _decode_packet(self, packet):
        # A frame we couldn't decrypt → conceal with PLC, never decode ciphertext.
        if packet and getattr(packet, "decrypted_data", None) in (LOST, b""):
            stats["opus_fail"] += 1
            return packet, _plc(self)
        try:
            result = _orig_decode(self, packet)
            if packet:
                stats["ok"] += 1
            return result
        except Exception:  # noqa: BLE001
            stats["opus_fail"] += 1
            return packet, _plc(self)

    _vr_opus.PacketDecoder._decode_packet = _decode_packet
    _vr_opus.PacketDecoder._pmb_patched = True


_patch_voice_recv_decode()


class _CaptureSink(voice_recv.AudioSink):
    """Feeds the bot's rolling per-user buffer from received voice.

    discord.py can't receive voice on its own — this uses discord-ext-voice-recv,
    which decodes each speaker's Opus into 20ms 48kHz **stereo** PCM frames. We
    downmix to mono (to match the clip pipeline) and hand them to the bot, which
    keeps only opted-in users' audio. Runs on the library's receive thread.
    """

    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    def wants_opus(self):
        return False  # give us decoded PCM, not raw Opus

    def write(self, user, data):
        if user is None or getattr(user, "bot", False):
            return
        pcm = data.pcm
        if not pcm:
            return
        # RTP timestamp (48kHz sample clock) is the true audio timeline. The
        # library delivers frames in bursts, so arrival time would pile them up.
        ts = getattr(data.packet, "timestamp", None)
        self.bot._capture_write(str(user.id), ts, audioop.tomono(pcm, 2, 0.5, 0.5))

    def cleanup(self):
        pass


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
        # Entrance sounds: play a user's configured clip when they join the
        # bot's channel, debounced per user so quick rejoins don't spam.
        self._entrance_cooldown = {}
        # "Clip that" rolling buffers: voice_id (str(member.id)) -> deque of
        # (monotonic time, mono 48kHz PCM). Only opted-in users are held; the
        # sink runs on a receive thread, so guard with a lock.
        self._capture_buffers = {}
        self._capture_optin = set()
        self._capture_lock = threading.Lock()

    ENTRANCE_COOLDOWN_SECS = 30
    # Wait this long after someone joins before playing, so their client's audio
    # is up and they hear the clip from the start (not just the tail).
    ENTRANCE_DELAY_SECS = 2.0

    CAPTURE_BUFFER_SECONDS = 30
    CAPTURE_SAMPLE_RATE = 48000  # discord-ext-voice-recv decodes to 48kHz
    CAPTURE_ALL = "__all__"  # sentinel target: mix everyone opted-in

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
        if config.CLIP_CAPTURE_ENABLED:
            self.refresh_capture_optin.start()

    def get_player(self, voice_client):
        player = self.players.get(voice_client.guild.id)
        if player is None or player.voice_client is not voice_client:
            if player is not None:
                player.stop()
            player = playback.GuildPlayer(voice_client)
            self.players[voice_client.guild.id] = player
        player.start(self.loop)
        return player

    # ---- voice connect + receive ------------------------------------------
    async def _connect_voice(self, channel):
        """Connect to a voice channel. With capture on, use the receive-capable
        client (a VoiceClient superset, so playback is unaffected) and start the
        rolling-buffer listener."""
        cls = (
            voice_recv.VoiceRecvClient
            if config.CLIP_CAPTURE_ENABLED
            else discord.VoiceClient
        )
        voice_client = await channel.connect(cls=cls)
        self._start_listening(voice_client)
        return voice_client

    def _start_listening(self, voice_client):
        if not config.CLIP_CAPTURE_ENABLED or voice_client is None:
            return
        try:
            if not voice_client.is_listening():
                voice_client.listen(_CaptureSink(self))
        except Exception:
            log.exception("Failed to start voice capture listener")

    # ---- "clip that" rolling buffer ---------------------------------------
    def _capture_write(self, name, ts, mono_pcm):
        """Append a mono PCM frame to a user's rolling buffer (opted-in only).
        Stored as (arrival_monotonic, audio_time_seconds, pcm): we evict by
        arrival time (a true wall-clock window, wrap-safe) but place frames by the
        RTP audio time. Called from the receive thread."""
        if ts is None:
            return
        now = time.monotonic()
        audio_t = ts / float(self.CAPTURE_SAMPLE_RATE)
        with self._capture_lock:
            if name not in self._capture_optin:
                return  # not consented — dropped, never stored
            buf = self._capture_buffers.get(name)
            if buf is None:
                buf = deque()
                self._capture_buffers[name] = buf
                log.info("capture: receiving audio for %s", name)
            buf.append((now, audio_t, mono_pcm))
            cutoff = now - self.CAPTURE_BUFFER_SECONDS
            while buf and buf[0][0] < cutoff:
                buf.popleft()

    @tasks.loop(seconds=5)
    async def refresh_capture_optin(self):
        docs = await asyncio.to_thread(
            lambda: list(
                self.mongo.db.users.find(
                    {"capture_optin": True, "voice_id": {"$ne": None}},
                    {"voice_id": 1},
                )
            )
        )
        optin = {d.get("voice_id") for d in docs if d.get("voice_id")}
        with self._capture_lock:
            self._capture_optin = optin
            # Purge buffers for anyone who just opted out (don't keep their audio).
            for name in [n for n in self._capture_buffers if n not in optin]:
                del self._capture_buffers[name]

    @refresh_capture_optin.before_loop
    async def _before_optin(self):
        await self.wait_until_ready()

    async def _capture_clip(self, command):
        target = command.get("target_voice")
        requested_by = command.get("requested_by")
        duration = max(
            1.0,
            min(
                float(command.get("duration") or self.CAPTURE_BUFFER_SECONDS),
                self.CAPTURE_BUFFER_SECONDS,
            ),
        )

        if target == self.CAPTURE_ALL:
            # Mix everyone opted-in (buffers only ever hold opted-in users).
            with self._capture_lock:
                buffers = {
                    uid: list(buf)
                    for uid, buf in self._capture_buffers.items()
                    if uid in self._capture_optin and buf
                }
            pcm = self._render_capture_mix(buffers, duration) if buffers else b""
            label = "everyone"
        else:
            with self._capture_lock:
                opted = target in self._capture_optin
                # Render on the audio timeline (2nd tuple element), not arrival.
                chunks = (
                    [
                        (audio_t, pcm)
                        for (_now, audio_t, pcm) in self._capture_buffers.get(
                            target, ()
                        )
                    ]
                    if opted
                    else []
                )
            if not opted:
                await self.announce(
                    "<b>{0}</b> hasn't opted in to being clipped.".format(target)
                )
                return
            pcm = self._render_capture_window(chunks, duration) if chunks else b""
            label = target

        if not pcm:
            await self.announce(
                "Nothing to clip for <b>{0}</b> (no recent audio).".format(label)
            )
            return
        info = await asyncio.to_thread(self._write_capture, target, pcm, requested_by)
        await self.announce(
            "<b>{0}</b> clipped the last {1:g}s of <b>{2}</b> — review it in the "
            "web UI".format(requested_by or "web", info["duration_s"], label)
        )

    # Concatenate frames back-to-back; only insert real silence for genuine
    # pauses (a timestamp gap bigger than this). Smaller gaps come from the
    # occasional short (10ms) opus frame in a 20ms slot — concatenating those
    # contiguously avoids the silent slivers that click.
    CAPTURE_PAUSE_GAP = 0.12
    CAPTURE_MAX_PAUSE = 1.5

    def _render_capture_window(self, chunks, duration):
        """Rebuild the last ``duration`` seconds by concatenating the frames in
        order, inserting silence only for real pauses. Returns 48kHz mono int16
        PCM bytes."""
        sr = self.CAPTURE_SAMPLE_RATE
        chunks = sorted(chunks, key=lambda c: c[0])
        end = chunks[-1][0] + len(chunks[-1][1]) / 2 / sr
        start = end - duration

        out = bytearray()
        prev_end = None
        for ctime, pcm in chunks:
            frame_end = ctime + len(pcm) / 2 / sr
            if frame_end <= start:
                continue  # entirely before the window
            if ctime < start:  # straddles the window start — trim its lead-in
                drop = int(round((start - ctime) * sr)) * 2
                pcm = pcm[drop:]
                ctime = start
            if not pcm:
                continue
            if prev_end is not None:
                gap = ctime - prev_end
                if gap > self.CAPTURE_PAUSE_GAP:
                    pad = int(round(min(gap, self.CAPTURE_MAX_PAUSE) * sr)) * 2
                    out += b"\x00" * pad
            out += pcm
            prev_end = ctime + len(pcm) / 2 / sr

        # Trim outer silence (sample-aligned).
        left = len(out) - len(out.lstrip(b"\x00"))
        out = out[left - (left % 2) :]
        right = len(out) - len(out.rstrip(b"\x00"))
        right -= right % 2
        if right:
            out = out[:-right]
        return bytes(out)

    def _render_capture_mix(self, buffers, duration):
        """Mix every opted-in user's last ``duration`` seconds into one track.

        Each Discord speaker's RTP clock is independent, so we map each user's
        audio time onto the shared arrival clock via their median (arrival −
        audio) offset — this lines speakers up with each other. Within a user,
        frames are laid in contiguous runs (split only on real pauses) to avoid
        the short-frame slivers that click. Overlapping speech sums (audioop.add
        saturates, so it won't wrap). Returns 48kHz mono int16 PCM."""
        sr = self.CAPTURE_SAMPLE_RATE
        runs = []  # (canvas_start_seconds, pcm bytes)
        global_end = None
        for chunks in buffers.values():
            if not chunks:
                continue
            offs = sorted(now - at for (now, at, _pcm) in chunks)
            offset = offs[len(offs) // 2]  # audio-clock → arrival-clock
            cur = bytearray()
            cur_start = None
            prev_end = None
            for _now, at, pcm in chunks:
                ct = at + offset
                if prev_end is None or (ct - prev_end) > self.CAPTURE_PAUSE_GAP:
                    if cur:
                        runs.append((cur_start, bytes(cur)))
                    cur = bytearray(pcm)
                    cur_start = ct
                else:
                    cur += pcm
                prev_end = ct + len(pcm) / 2 / sr
            if cur:
                runs.append((cur_start, bytes(cur)))
            if prev_end is not None:
                global_end = (
                    prev_end if global_end is None else max(global_end, prev_end)
                )

        if global_end is None or not runs:
            return b""
        start = global_end - duration
        canvas = bytearray(int(round(duration * sr)) * 2)
        for cstart, pcm in runs:
            off = int(round((cstart - start) * sr))
            if off < 0:  # run straddles the window start — trim its lead-in
                pcm = pcm[(-off) * 2 :]
                off = 0
            byte_off = off * 2
            if byte_off >= len(canvas) or not pcm:
                continue
            seg = pcm[: len(canvas) - byte_off]
            end_b = byte_off + len(seg)
            canvas[byte_off:end_b] = audioop.add(bytes(canvas[byte_off:end_b]), seg, 2)

        left = len(canvas) - len(canvas.lstrip(b"\x00"))
        canvas = canvas[left - (left % 2) :]
        right = len(canvas) - len(canvas.rstrip(b"\x00"))
        right -= right % 2
        if right:
            canvas = canvas[:-right]
        return bytes(canvas)

    def _write_capture(self, target, pcm, requested_by):
        captures_dir = playback.AUDIO_DIR / "captures"
        captures_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.utcnow().strftime("%Y%m%d%H%M%S")
        safe = re.sub(r"[^A-Za-z0-9_-]", "_", str(target)) or "user"
        filename = "cap_{0}_{1}.wav".format(stamp, safe)
        path = captures_dir / filename
        with wave.open(str(path), "wb") as f:
            f.setparams((1, 2, self.CAPTURE_SAMPLE_RATE, 0, "NONE", "not compressed"))
            f.writeframes(pcm)
        duration_s = round(len(pcm) / 2 / self.CAPTURE_SAMPLE_RATE, 2)
        self.mongo.db.pending_clips.insert_one(
            {
                "target_voice": target,
                "requested_by": requested_by,
                "duration_s": duration_s,
                "file": "captures/" + filename,
                "created_at": datetime.datetime.utcnow(),
                "status": "pending",
            }
        )
        return {"duration_s": duration_s}

    def resolve_clip(self, ref):
        collection = self.mongo.clips_collection
        return collection.find_one({"identifier": ref}) or collection.find_one(
            {"name": ref}
        )

    async def play_file(
        self,
        voice_client,
        file_name,
        speed,
        shift,
        interrupt=False,
        voice_key=None,
        gain_db=0,
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
            voice_client = await self._connect_voice(channel)
        elif voice_client.channel != channel:
            await voice_client.move_to(channel)
        self._start_listening(voice_client)
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
                {
                    "id": str(m.id),
                    "name": m.display_name,
                    # A user must have both mic and audio on to play; capture
                    # self- and server-applied mute/deaf so the web can gate it.
                    "mute": bool(m.voice and (m.voice.mute or m.voice.self_mute)),
                    "deaf": bool(m.voice and (m.voice.deaf or m.voice.self_deaf)),
                }
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
        # When a human's voice state changes: play their entrance sound if they
        # joined the bot's channel, leave if the bot is now alone, then republish
        # so per-channel user counts stay fresh.
        if member.bot:
            return
        voice_client = member.guild.voice_client
        if voice_client is not None and voice_client.is_connected():
            bot_channel = voice_client.channel
            joined_us = (
                after.channel is not None
                and after.channel.id == bot_channel.id
                and (before.channel is None or before.channel.id != bot_channel.id)
            )
            if joined_us:
                await self._maybe_play_entrance(member, voice_client)
            if not self._channel_has_humans(bot_channel):
                log.info(
                    "Auto-leave: %s has no humans left; disconnecting",
                    bot_channel.name,
                )
                await voice_client.disconnect()
                await self._set_rejoin(None)  # don't rejoin an abandoned channel
        await self._publish_voice_state()

    async def _maybe_play_entrance(self, member, voice_client):
        if not config.ENTRANCE_ENABLED:
            return  # entrance sounds disabled on this bot
        now = time.monotonic()
        if (
            now - self._entrance_cooldown.get(member.id, 0)
            < self.ENTRANCE_COOLDOWN_SECS
        ):
            return
        doc = await asyncio.to_thread(
            lambda: self.mongo.db.entrance_sounds.find_one({"_id": str(member.id)})
        )
        clips = (doc or {}).get("clips") or []
        if not clips:
            return
        self._entrance_cooldown[member.id] = now
        # Give the joiner's client a moment to finish setting up its audio
        # receive stream, otherwise they miss the first second of the clip.
        await asyncio.sleep(self.ENTRANCE_DELAY_SECS)
        # They may have bounced straight back out, or the bot moved/left.
        if not voice_client.is_connected():
            return
        if member.voice is None or member.voice.channel != voice_client.channel:
            return
        log.info("Playing entrance for %s (%d clips)", member.display_name, len(clips))
        player = self.get_player(voice_client)
        voice_key = "entrance-{0}".format(member.id)
        base_volume = await asyncio.to_thread(self.mongo.get_volume)
        for c in clips:
            doc = await asyncio.to_thread(self.resolve_clip, c["clip_ref"])
            if doc is None:
                continue
            volume = base_volume * transform.gain_db_to_multiplier(
                doc.get("gain_db", 0)
            )
            source = playback.build_source(
                doc["file"],
                float(c.get("speed", 1.0)),
                float(c.get("pitch", 0)),
                volume,
            )
            done = asyncio.Event()
            player.play_now(
                voice_key, source, lambda: self.loop.call_soon_threadsafe(done.set)
            )
            try:
                await asyncio.wait_for(done.wait(), timeout=30.0)
            except asyncio.TimeoutError:
                pass

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
            await self.announce("♻ **{0}** reconnected the bot".format(requested_by))
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

        if cmd_type == "clip_capture":
            await self._capture_clip(command)
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
            {
                "_id": "singleton",
                "current": self._song_current,
                "queue": queue,
                "updated_at": datetime.datetime.utcnow(),
            },
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
            log.warning(
                "play_song: not in a voice channel; dropping %s", command.get("song")
            )
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
            doc["file"],
            song_file,
            transpose,
            speed,
            gain_db,
            base_volume,
            max_seconds,
        )
        log.info(
            "[timing] song render %s on %s: %.0fms (%.1fs)",
            song_file,
            clip_ref,
            (time.monotonic() - t0) * 1000,
            duration,
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
        player.play_now(
            "__song__", source, lambda: self.loop.call_soon_threadsafe(done.set)
        )

        # Wait for the song to finish naturally, be skipped, or a safety timeout.
        skip_wait = asyncio.ensure_future(self._skip_event.wait())
        done_wait = asyncio.ensure_future(done.wait())
        try:
            await asyncio.wait(
                {skip_wait, done_wait},
                timeout=duration + 5.0,
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
