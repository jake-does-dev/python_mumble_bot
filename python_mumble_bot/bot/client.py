import os
import subprocess as sp

import bot.record as record
import pymumble_py3 as pymumble
from bot.command import CommandResolver, RefreshCommand
from bot.event import AudioEvent, RecordEvent, TextEvent
from bot.manager import StateManager

AUDIO_DIR = "audio/"
HOSTNAME = "MUMBLE_SERVER_HOSTNAME"
PASSWORD = "MUMBLE_SERVER_PASSWORD"
ROOT_CHANNEL = "MUMBLE_SERVER_ROOT_CHANNEL"
VALID_AUDIO_FORMATS = [".wav", ".mp3"]


def connect():
    mumble = pymumble.Mumble(
        os.getenv(HOSTNAME), "PythonMumbleBot", password=os.getenv(PASSWORD)
    )

    client = Client(mumble)
    client.set_callbacks()
    client.start()

    return client


class Client:
    def __init__(
        self, mumble, state_manager=StateManager(), command_resolver=CommandResolver()
    ):
        self.mumble = mumble
        self.state_manager = state_manager
        self.command_resolver = command_resolver

    # noinspection PyUnresolvedReferences
    def set_callbacks(self):
        self.mumble.callbacks.set_callback(
            pymumble.constants.PYMUMBLE_CLBK_TEXTMESSAGERECEIVED, self.interpret_command
        )

    def interpret_command(self, incoming):
        command = self.command_resolver.resolve(incoming)

        if isinstance(command, RefreshCommand):
            self.state_manager.refresh_state()

        event = command.generate_event(self.state_manager.state)

        if isinstance(event, TextEvent):
            self.send_text(event)
        elif isinstance(event, AudioEvent):
            self.send_audio(event)
        elif isinstance(event, RecordEvent):
            self.record(event)

    def send_text(self, event):
        channel = self.mumble.channels.find_by_name(os.getenv(ROOT_CHANNEL))
        channel.send_text_message(event.data)

    def send_audio(self, event):
        file_mapping = self.state_manager.get_audio_clips()
        for name in event.data:
            file = file_mapping[name]
            encode_command = ["ffmpeg", "-i", file, "-ac", "1", "-f", "s16le", "-"]
            print(encode_command)
            pcm = sp.Popen(
                encode_command, stdout=sp.PIPE, stderr=sp.DEVNULL
            ).stdout.read()
            self.mumble.sound_output.add_sound(pcm)

    def start(self):
        self.mumble.start()
        self.mumble.is_ready()
        self.myself = self.mumble.users.myself
        self.recording_manager = record.RecordingManager(
            list(self.mumble.users.values())
        )

        self.loop()

    def loop(self):
        while self.mumble.is_alive():
            if self.recording_manager.is_recording:
                for user in self.mumble.users.values():
                    if user.sound.is_sound():
                        user_name = user["name"]
                        sound = user.sound.get_sound()
                        self.recording_manager.write(user_name, sound.pcm)

    def record(self, event):
        if event.data == "start":
            self.recording_manager.start_recording()
            self.mumble.set_receive_sound(True)
            self.myself.recording()
        else:
            self.myself.unrecording()
            self.mumble.set_receive_sound(False)
            self.recording_manager.stop_recording()


if __name__ == "__main__":
    connect()
