import os
from pathlib import Path

from bot.constants import AUDIO_CLIPS_MAPPING


class StateManager:
    def __init__(self, audio_clips_dir=Path("../audio/")):
        self.audio_clips_dir = audio_clips_dir
        self.state = dict()

    def refresh_state(self):
        self.refresh_audio_clips()

    def refresh_audio_clips(self):
        audio_dir = self.audio_clips_dir

        (_, _, file_paths) = next(os.walk(audio_dir))
        names = [f.split(".")[0] for f in file_paths]

        self.state[AUDIO_CLIPS_MAPPING] = dict(
            zip(names, [audio_dir.joinpath(f) for f in file_paths])
        )

    def get_audio_clips(self):
        return self.state[AUDIO_CLIPS_MAPPING]
