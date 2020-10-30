import os
import subprocess as sp
import wave
from datetime import datetime

import pymumble_py3 as pymumble

AUDIO_DIR = "../audio/"
RECORDING_DIR = "/mnt/f/Users/Jake/Documents/MumbleRecordings/"
BITRATE = 24000
HOSTNAME = "MUMBLE_SERVER_HOSTNAME"
PASSWORD = "MUMBLE_SERVER_PASSWORD"
ROOT_CHANNEL = "MUMBLE_SERVER_ROOT_CHANNEL"


def connect():
    mumble = pymumble.Mumble(
        os.getenv(HOSTNAME), "PythonMumbleBot", password=os.getenv(PASSWORD)
    )
    client = Client(mumble)

    client.set_callbacks()
    client.start()

    return client


class Client:
    def __init__(self, mumble):
        self.mumble = mumble

    def start(self):
        self.mumble.start()
        self.mumble.is_ready()
        self.channel = self.mumble.channels.find_by_name(os.getenv(ROOT_CHANNEL))
        self.myself = self.mumble.users.myself
        self.recording_manager = RecordingManager()

        self.loop()

    def loop(self):
        while self.mumble.is_alive():
            if self.recording_manager.is_recording:
                for user in self.mumble.users.values():
                    if user.sound.is_sound():
                        sound = user.sound.get_sound()
                        self.recording_manager.write(sound.pcm)

    def set_callbacks(self):
        self.mumble.callbacks.set_callback(
            pymumble.constants.PYMUMBLE_CLBK_TEXTMESSAGERECEIVED, self.interpret_command
        )

    def interpret_command(self, command):
        print(command.message)
        parts = command.message.split()
        if len(parts) < 2:
            self.channel.send_text_message(
                "Badly formatted command. Check and try again."
            )

        for_bot = parts[0]
        if for_bot == "/pmb":
            action = parts[1]

            if action == "list":
                self.list_files()
            elif action == "play":
                self.play_files(parts[2:])
            elif action == "record":
                if len(parts) != 3:
                    self.channel.send_text_message(
                        "The 'record' command needs to be followed by 'start' or 'stop'. Check and try again."
                    )
                else:
                    self.record(parts[2])
            else:
                self.channel.send_text_message(
                    "Unknown command '{0}'. Check and try again.".format(action)
                )

    def list_files(self):
        (_, _, filenames) = next(os.walk(AUDIO_DIR))
        formatted = sorted([f.split(".")[0] for f in filenames])
        self.channel.send_text_message(
            "Here are the available audio files: {0}".format(formatted)
        )
        self.channel.send_text_message("Usage: /pmb play file1 file2 ...")

    def play_files(self, file_names):
        for name in file_names:
            file = "../audio/{0}.wav".format(name)
            encode_command = ["ffmpeg", "-i", file, "-ac", "1", "-f", "s16le", "-"]
            print(encode_command)
            pcm = sp.Popen(
                encode_command, stdout=sp.PIPE, stderr=sp.DEVNULL
            ).stdout.read()
            self.mumble.sound_output.add_sound(pcm)

    def record(self, state):
        if state == "start":
            self.recording_manager.start_recording()
            self.mumble.set_receive_sound(True)
            self.myself.mumble_object.users.myself.recording = True
        else:
            self.myself.mumble_object.users.myself.recording = False
            self.mumble.set_receive_sound(False)
            self.recording_manager.stop_recording()


class RecordingManager:
    def __init__(self):
        self.is_recording = False
        self.file = None

    def start_recording(self):
        now = datetime.now()
        format = "%Y%m%d%H%M%S"
        name = "{0}mumble-{1}.wav".format(RECORDING_DIR, now.strftime(format))

        self.file = wave.open(name, "wb")
        self.file.setparams((2, 2, BITRATE, 0, "NONE", "not compressed"))
        self.is_recording = True

    def stop_recording(self):
        self.is_recording = False
        self.file.close()
        self.file = None

    def write(self, data):
        self.file.writeframes(data)
