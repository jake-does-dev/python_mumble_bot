import os
import time

import pymumble_py3 as pymumble

from python_mumble_bot.bot.api_wrapper import MumbleWrapper
from python_mumble_bot.bot.command import CommandResolver, RefreshCommand
from python_mumble_bot.bot.constants import (
    MUMBLE_HOSTNAME,
    MUMBLE_PASSWORD,
    MUMBLE_USERNAME,
    USER_GREETINGS_DICT,
    USERNAME_DICT,
)
from python_mumble_bot.bot.manager import (
    PlaybackManager,
    RecordingManager,
    StateManager,
    TextMessageManager,
)
from python_mumble_bot.db.mongodb import MongoInterface


def connect():
    mumble = pymumble.Mumble(
        os.getenv(MUMBLE_HOSTNAME),
        os.getenv(MUMBLE_USERNAME),
        password=os.getenv(MUMBLE_PASSWORD),
    )
    mumble.set_receive_sound = False

    client = Client(mumble)
    client.start()
    client.set_callbacks()

    client.interpret_command(
        Greeting(os.getenv(MUMBLE_USERNAME), "/pmb play beep_boop")
    )

    client.loop()

    return client


class Client:
    STATE_MANAGER = "STATE_MANAGER"
    PLAYBACK_MANAGER = "PLAYBACK_MANAGER"
    RECORDING_MANAGER = "RECORDING_MANAGER"
    TEXT_MESSAGE_MANAGER = "TEXT_MESSAGE_MANAGER"

    def __init__(
        self,
        mumble,
        state_manager=None,
        playback_manager=None,
        recording_manager=None,
        text_message_manager=None,
    ):
        self.mumble = mumble
        self.command_resolver = CommandResolver()
        self.managers = dict()

        state_manager = (
            StateManager(MongoInterface()) if state_manager is None else state_manager
        )
        state_manager.connect()
        playback_manager = (
            PlaybackManager(self.mumble, state_manager)
            if playback_manager is None
            else playback_manager
        )
        recording_manager = (
            RecordingManager(MumbleWrapper(self.mumble))
            if recording_manager is None
            else recording_manager
        )
        text_message_manager = (
            TextMessageManager(MumbleWrapper(self.mumble))
            if text_message_manager is None
            else text_message_manager
        )

        self.managers[self.STATE_MANAGER] = state_manager
        self.managers[self.PLAYBACK_MANAGER] = playback_manager
        self.managers[self.RECORDING_MANAGER] = recording_manager
        self.managers[self.TEXT_MESSAGE_MANAGER] = text_message_manager

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
        if {"actor", "channel_id"} == incoming.keys() and self.mumble.my_channel()[
            "channel_id"
        ] == user_event.get("channel_id"):
            self._send_delayed_greeting(user_event.get("name"))

    def user_created_command(self, user_event):
        self._send_delayed_greeting(user_event.get("name"))

    def _send_delayed_greeting(self, user):
        if user in USERNAME_DICT.keys():
            greetings = USER_GREETINGS_DICT[USERNAME_DICT[user]]
            for greeting in greetings:
                self.interpret_command(Greeting(user, "/pmb play {0}".format(greeting)))

    def start(self):
        self.mumble.start()
        self.mumble.is_ready()
        self.managers[self.STATE_MANAGER].refresh_state()

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
