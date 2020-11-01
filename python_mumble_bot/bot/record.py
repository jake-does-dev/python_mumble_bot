import datetime as dt
import wave
from pathlib import Path

BITRATE = 48000
DEFAULT_RECORDING_DIR = Path("/mnt/f/Users/Jake/Documents/MumbleRecordings/")


class RecordingManager:
    def __init__(self, users, recording_dir=DEFAULT_RECORDING_DIR):
        self.is_recording = False
        self.users = users
        self.recording_dir = recording_dir
        self.files = dict()

    def start_recording(self):
        now = dt.datetime.now()
        format = "%Y%m%d%H%M%S"

        for user in self.users:
            user_name = user["name"]

            file_name = "".join([user_name, "-mumble-", now.strftime(format), ".wav"])
            path = self.recording_dir.joinpath(file_name)

            file = wave.open(path.as_posix(), "wb")
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
