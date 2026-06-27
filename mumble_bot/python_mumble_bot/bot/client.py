import datetime as dt
import logging
import os
import re
import time

import pymumble_py3 as pymumble
from pmb_core.db.mongodb import MongoInterface

from python_mumble_bot.bot.api_wrapper import MumbleWrapper
from python_mumble_bot.bot.command import CommandResolver, RefreshCommand
from python_mumble_bot.bot.constants import (
    MUMBLE_HOSTNAME,
    MUMBLE_PASSWORD,
    MUMBLE_USERNAME,
    USER_GREETINGS_DICT,
    USERNAME_DICT,
)
from python_mumble_bot.bot.event import AudioEvent
from python_mumble_bot.bot.manager import (
    CaptureManager,
    CommandManager,
    PlaybackManager,
    StateManager,
    TextMessageManager,
    VoiceStateManager,
)

log = logging.getLogger("pmb.mumble.client")

# "Clip that" / instant replay keeps a rolling buffer of everyone's voice, which
# means receiving (and continuously decoding) all incoming audio. Off unless
# enabled, so non-capture deployments don't pay the cost or hold the audio.
CLIP_CAPTURE_ENABLED = os.getenv("CLIP_CAPTURE_ENABLED", "true").lower() in (
    "1",
    "true",
    "yes",
)


def connect():
    mumble = pymumble.Mumble(
        os.getenv(MUMBLE_HOSTNAME),
        os.getenv(MUMBLE_USERNAME),
        password=os.getenv(MUMBLE_PASSWORD),
    )
    # receive_sound gates whether pymumble decodes incoming audio at all.
    mumble.receive_sound = CLIP_CAPTURE_ENABLED

    client = Client(mumble)
    client.start()
    client.set_callbacks()
    client.loop()

    return client


class Client:
    STATE_MANAGER = "STATE_MANAGER"
    PLAYBACK_MANAGER = "PLAYBACK_MANAGER"
    CAPTURE_MANAGER = "CAPTURE_MANAGER"
    TEXT_MESSAGE_MANAGER = "TEXT_MESSAGE_MANAGER"
    COMMAND_MANAGER = "COMMAND_MANAGER"
    VOICE_STATE_MANAGER = "VOICE_STATE_MANAGER"

    # Don't replay someone's entrance sound if they bounce in and out quickly.
    ENTRANCE_COOLDOWN_SECS = 30

    def __init__(
        self,
        mumble,
        state_manager=None,
        playback_manager=None,
        capture_manager=None,
        text_message_manager=None,
    ):
        self.mumble = mumble
        self.command_resolver = CommandResolver()
        self.managers = dict()
        self._entrance_cooldown = {}  # voice name -> last-played monotonic time

        state_manager = (
            StateManager(MongoInterface()) if state_manager is None else state_manager
        )
        state_manager.connect()
        playback_manager = (
            PlaybackManager(self.mumble, state_manager)
            if playback_manager is None
            else playback_manager
        )
        text_message_manager = (
            TextMessageManager(MumbleWrapper(self.mumble))
            if text_message_manager is None
            else text_message_manager
        )
        capture_manager = (
            CaptureManager(
                MumbleWrapper(self.mumble),
                state_manager.mongo_interface,
                text_message_manager,
            )
            if capture_manager is None
            else capture_manager
        )

        command_manager = CommandManager(
            state_manager.mongo_interface,
            playback_manager,
            text_message_manager,
            capture_manager,
        )

        voice_state_manager = VoiceStateManager(
            self.mumble, state_manager.mongo_interface
        )

        self.managers[self.STATE_MANAGER] = state_manager
        self.managers[self.PLAYBACK_MANAGER] = playback_manager
        self.managers[self.CAPTURE_MANAGER] = capture_manager
        self.managers[self.TEXT_MESSAGE_MANAGER] = text_message_manager
        self.managers[self.COMMAND_MANAGER] = command_manager
        self.managers[self.VOICE_STATE_MANAGER] = voice_state_manager

    # noinspection PyUnresolvedReferences
    def set_callbacks(self):
        self.mumble.callbacks.set_callback(
            pymumble.constants.PYMUMBLE_CLBK_TEXTMESSAGERECEIVED,
            self.interpret_command,
        )

        self.mumble.callbacks.set_callback(
            pymumble.constants.PYMUMBLE_CLBK_USERUPDATED,
            self.user_updated_command,
        )

        self.mumble.callbacks.set_callback(
            pymumble.constants.PYMUMBLE_CLBK_USERCREATED,
            self.user_created_command,
        )

        # One sink for all received audio → the rolling buffer (+ recording).
        # Registering this stops pymumble queueing per-user sound, so nothing else
        # may consume it. Only when capture is enabled (else audio isn't received).
        if CLIP_CAPTURE_ENABLED:
            self.mumble.callbacks.set_callback(
                pymumble.constants.PYMUMBLE_CLBK_SOUNDRECEIVED,
                self.managers[self.CAPTURE_MANAGER].on_sound,
            )

    def interpret_command(self, incoming):
        command = self.command_resolver.resolve(incoming)

        if isinstance(command, RefreshCommand):
            self.managers[self.STATE_MANAGER].refresh_state()

        events = command.generate_events(
            self.managers[self.STATE_MANAGER].mongo_interface,
            self.mumble.users.get(incoming.actor),
        )
        for event in events:
            for manager in self.managers.values():
                manager.process(event)

    def user_updated_command(self, user_event, incoming):
        # A user moved channel — play their entrance if they moved into ours.
        if {"actor", "channel_id"} == incoming.keys() and self.mumble.my_channel()[
            "channel_id"
        ] == user_event.get("channel_id"):
            self._play_entrance(user_event.get("name"))

    def user_created_command(self, user_event):
        # A user connected — play their entrance only if they landed in our channel.
        try:
            in_our_channel = self.mumble.my_channel()["channel_id"] == user_event.get(
                "channel_id"
            )
        except Exception:
            in_our_channel = False
        if in_our_channel:
            self._play_entrance(user_event.get("name"))

    def _play_entrance(self, user):
        """Play the user's configured entrance sound (from `entrance_sounds`)
        when they join the bot's channel. Replaces the old hardcoded greeting
        dicts; debounced so quick rejoins don't spam."""
        if not user:
            return
        now = time.monotonic()
        if now - self._entrance_cooldown.get(user, 0) < self.ENTRANCE_COOLDOWN_SECS:
            return
        try:
            doc = self.managers[
                self.STATE_MANAGER
            ].mongo_interface.db.entrance_sounds.find_one({"_id": user})
        except Exception:
            doc = None
        clips = (doc or {}).get("clips") or []
        if not clips:
            return
        self._entrance_cooldown[user] = now
        refs = [c["clip_ref"] for c in clips]
        speeds = ["{0}x".format(c.get("speed", 1.0)) for c in clips]
        shifts = ["{0}s".format(int(c.get("pitch", 0))) for c in clips]
        event = AudioEvent(
            refs, speeds, shifts, voice_key="entrance-{0}".format(user), append=False
        )
        self.managers[self.PLAYBACK_MANAGER].process(event)

    def _seed_entrance_from_legacy(self):
        """One-off, idempotent migration of the old hardcoded greeting dicts
        into `entrance_sounds`. Only fills users with no doc yet, so it never
        clobbers a web-configured entrance."""
        try:
            db = self.managers[self.STATE_MANAGER].mongo_interface.db
        except Exception:
            return
        for mumble_name, key in USERNAME_DICT.items():
            try:
                if db.entrance_sounds.find_one({"_id": mumble_name}):
                    continue
                clips = []
                for greeting in USER_GREETINGS_DICT.get(key) or []:
                    parsed = self._parse_legacy_greeting(db, greeting)
                    if parsed:
                        clips.append(parsed)
                if clips:
                    db.entrance_sounds.replace_one(
                        {"_id": mumble_name},
                        {
                            "_id": mumble_name,
                            "voice_id": mumble_name,
                            "clips": clips,
                            "updated_by": "migration",
                            "updated_at": dt.datetime.utcnow(),
                        },
                        upsert=True,
                    )
                    log.info(
                        "Seeded entrance for %s (%d clips)", mumble_name, len(clips)
                    )
            except Exception:
                log.exception("entrance seed failed for %s", mumble_name)

    @staticmethod
    def _parse_legacy_greeting(db, text):
        """Parse a legacy greeting string like "0.8x dg15" or "bot_hello_jake"
        into {clip_ref, clip_name, speed, pitch}, resolving names to refs."""
        speed, pitch, clip_token = 1.0, 0, None
        for tok in text.split():
            if re.fullmatch(r"\d+(\.\d+)?x", tok):
                speed = float(tok[:-1])
            elif re.fullmatch(r"-?\d+s", tok):
                pitch = int(tok[:-1])
            else:
                clip_token = tok
        if not clip_token:
            return None
        clip = db.clips.find_one({"identifier": clip_token}) or db.clips.find_one(
            {"name": clip_token}
        )
        if not clip:
            return None
        return {
            "clip_ref": clip["identifier"],
            "clip_name": clip["name"],
            "speed": speed,
            "pitch": pitch,
        }

    def start(self):
        self.mumble.start()
        self.mumble.is_ready()
        self.managers[self.STATE_MANAGER].refresh_state()
        self._seed_entrance_from_legacy()
        # Capture consent is session-scoped: a fresh process starts with everyone
        # opted out, so they must opt in again for this session.
        if CLIP_CAPTURE_ENABLED and self.managers[self.CAPTURE_MANAGER] is not None:
            self.managers[self.CAPTURE_MANAGER].clear_optin()

    def loop(self):
        while self.mumble.is_alive():
            for manager in self.managers.values():
                manager.loop()

            # allow available callbacks to jump into the tight loop
            time.sleep(0.01)


class Greeting:
    def __init__(self, actor, message):
        self.actor = actor
        self.message = message


if __name__ == "__main__":
    connect()
