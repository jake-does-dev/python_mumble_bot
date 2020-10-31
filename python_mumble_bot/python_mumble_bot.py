import os
import random
import subprocess as sp
import wave
from datetime import datetime

import pymumble_py3 as pymumble

AUDIO_DIR = "../audio/"
RECORDING_DIR = "/mnt/f/Users/Jake/Documents/MumbleRecordings/"
BITRATE = 48000
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
    def __init__(self, mumble):
        self.mumble = mumble

    def start(self):
        self.mumble.start()
        self.mumble.is_ready()
        self.channel = self.mumble.channels.find_by_name(os.getenv(ROOT_CHANNEL))
        self.myself = self.mumble.users.myself
        self.recording_manager = RecordingManager(list(self.mumble.users.values()))
        self.file_map = self.refresh_map()

        self.loop()

    def loop(self):
        while self.mumble.is_alive():
            if self.recording_manager.is_recording:
                for user in self.mumble.users.values():
                    if user.sound.is_sound():
                        user_name = user["name"]
                        sound = user.sound.get_sound()
                        self.recording_manager.write(user_name, sound.pcm)

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
            elif action == "dota":
                chosen = random.randint(0, 3)
                if chosen == 1:
                    self.channel.send_text_message("turbo")
                elif chosen == 2:
                    self.channel.send_text_message("all pick")
                elif chosen == 3:
                    self.channel.send_text_message("diretide")
            else:
                self.channel.send_text_message(
                    "Unknown command '{0}'. Check and try again.".format(action)
                )

    def list_files(self):
        self.refresh_map()

        self.channel.send_text_message(
            ", ".join(sorted([k for k in self.mapping.keys()]))
        )

    def refresh_map(self):
        (_, _, file_paths) = next(os.walk(AUDIO_DIR))
        names = [f.split(".")[0] for f in file_paths]
        self.mapping = dict(
            zip(names, ["{0}{1}".format(AUDIO_DIR, f) for f in file_paths])
        )

    def play_files(self, file_names):
        for name in file_names:
            file = self.mapping.get(name)

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
    def __init__(self, users):
        self.is_recording = False
        self.users = users
        self.files = dict()

    def start_recording(self):
        now = datetime.now()
        format = "%Y%m%d%H%M%S"

        for user in self.users:
            user_name = user["name"]
            file_name = "{0}{1}-mumble-{2}.wav".format(
                RECORDING_DIR, user_name, now.strftime(format)
            )

            file = wave.open(file_name, "wb")
            file.setparams((1, 2, BITRATE, 0, "NONE", "not compressed"))
            self.files[user_name] = file

        self.is_recording = True

    def stop_recording(self):
        for file in self.files.values():
            file.close()

        self.is_recording = False
        self.files = dict()

    def write(self, name, data):
        self.files[name].writeframes(data)
