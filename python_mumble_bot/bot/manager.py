import datetime as dt
import math
import os
import subprocess as sp
import wave
from pathlib import Path

from bot.constants import (
    AUDIO_CLIPS_BY_ID,
    AUDIO_CLIPS_BY_NAME,
    BITRATE,
    DEFAULT_RECORDING_DIR,
)
from bot.event import (
    AudioEvent,
    ChannelTextEvent,
    RecordEvent,
    TextEvent,
    UserTextEvent,
)


class EventManager:
    def process(self, event):
        if self.accept(event):
            self.dispatch(event)

    def accept(self, event):
        pass

    def dispatch(self, event):
        pass

    def loop(self):
        pass


class PlaybackManager(EventManager):
    def __init__(self, mumble, state_manager):
        self.mumble = mumble
        self.state_manager = state_manager

    def accept(self, event):
        return isinstance(event, AudioEvent)

    def dispatch(self, event):
        for ref, speed in zip(event.data, event.playback_speed):
            if ref.isnumeric():
                file_resolver = self.state_manager.find_audio_clip_by_id
            else:
                file_resolver = self.state_manager.find_audio_clip_by_name

            file = file_resolver(ref)
            desired_speed = float(speed[:-1])

            # Api limitations for speed change in range (0.5, 2).
            # Can work around by concatenating speeds together, e.g, atempo=2.0,atempo=2.0 for 4x speed
            if desired_speed < 0.5:
                num_required = 1
                while desired_speed < 0.5:
                    num_required = num_required * 2
                    desired_speed = math.sqrt(desired_speed)

                desired_speed = round(desired_speed, 2)
                tempo_command = ",".join(
                    ["atempo=" + str(desired_speed) for i in range(0, num_required)]
                )
            elif desired_speed > 2:
                num_required = 1
                while desired_speed > 2:
                    num_required = num_required * 2
                    desired_speed = math.sqrt(desired_speed)

                desired_speed = round(desired_speed, 2)
                tempo_command = ",".join(
                    ["atempo=" + str(desired_speed) for i in range(0, num_required)]
                )
            else:
                tempo_command = "".join(["atempo=", str(desired_speed)])

            encode_command = [
                "ffmpeg",
                "-i",
                file,
                "-filter:a",
                tempo_command,
                "-ac",
                "1",
                "-f",
                "s16le",
                "-",
            ]
            print(encode_command)
            pcm = sp.Popen(
                encode_command, stdout=sp.PIPE, stderr=sp.DEVNULL
            ).stdout.read()
            self.mumble.sound_output.add_sound(pcm)


class TextMessageManager(EventManager):
    def __init__(self, mumble_wrapper):
        self.mumble_wrapper = mumble_wrapper
        self.channel_wrapper = None

    def accept(self, event):
        return isinstance(event, TextEvent)

    def dispatch(self, event):
        if isinstance(event, ChannelTextEvent):
            if self.channel_wrapper is None:
                self.channel_wrapper = self.mumble_wrapper.get_channel(
                    event.channel_name
                )
            self.channel_wrapper.send(event.data)

        elif isinstance(event, UserTextEvent):
            event.user.send_text_message(event.data)


class RecordingManager(EventManager):
    def __init__(self, mumble_wrapper, recording_dir=Path(DEFAULT_RECORDING_DIR)):
        self.mumble_wrapper = mumble_wrapper
        self.recording_dir = recording_dir
        self.is_recording = False
        self.files = dict()

    def accept(self, event):
        return isinstance(event, RecordEvent)

    def dispatch(self, event):
        if event.data == "start":
            self._start_recording()
        else:
            self._stop_recording()

    def _start_recording(self):
        now = dt.datetime.now()
        date_format = "%Y%m%d%H%M%S"

        for user_wrapper in self.mumble_wrapper.get_users():
            user_name = user_wrapper.get_name()

            file_name = "".join(
                [user_name, "-mumble-", now.strftime(date_format), ".wav"]
            )
            path = self.recording_dir.joinpath(file_name)

            file = wave.open(path.as_posix(), "wb")
            file.setparams((1, 2, BITRATE, 0, "NONE", "not compressed"))
            self.files[user_name] = file

        self.is_recording = True
        self.mumble_wrapper.set_receive_sound(True)
        self.mumble_wrapper.start_recording()

    def _stop_recording(self):
        self.mumble_wrapper.stop_recording()
        self.mumble_wrapper.set_receive_sound(False)
        self.is_recording = False

        for file in self.files.values():
            file.close()

        self.files = dict()

    def _write(self, name, data):
        self.files[name].writeframes(data)

    def loop(self):
        if self.is_recording:
            for user_wrapper in self.mumble_wrapper.get_users():
                if user_wrapper.is_sound():
                    user_name = user_wrapper.get_name()
                    sound = user_wrapper.get_sound()
                    self._write(user_name, sound.pcm)


class StateManager(EventManager):
    def __init__(self, audio_clips_dir=Path("../audio/")):
        self.audio_clips_dir = audio_clips_dir
        self.state = dict()

    def refresh_state(self):
        self._refresh_audio_clips()

    def _refresh_audio_clips(self):
        audio_dir = self.audio_clips_dir

        (_, _, file_paths) = next(os.walk(audio_dir))

        file_paths = sorted(file_paths)
        names = [f.split(".")[0] for f in file_paths]

        files = [audio_dir.joinpath(f) for f in file_paths]

        clips_by_name = dict()
        clips_by_id = dict()
        for i, name in enumerate(names):
            clips_by_name[name] = files[i]
            clips_by_id[str(i)] = files[i]

        self.state[AUDIO_CLIPS_BY_NAME] = clips_by_name
        self.state[AUDIO_CLIPS_BY_ID] = clips_by_id

    def get_audio_clips_by_id(self):
        return self.state[AUDIO_CLIPS_BY_ID]

    def get_audio_clips_by_name(self):
        return self.state[AUDIO_CLIPS_BY_NAME]

    def find_audio_clip_by_id(self, identifier):
        audio_clips_map = self.get_audio_clips_by_id()
        return audio_clips_map.get(identifier)

    def find_audio_clip_by_name(self, name):
        audio_clips_map = self.get_audio_clips_by_name()
        return audio_clips_map.get(name)
