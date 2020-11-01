import os
import sys

sys.path.append(os.path.relpath("./python_mumble_bot"))

from bot.manager import StateManager


def test_refresh_audio_files_mapping(tmp_path):
    audio_dir = tmp_path / "audio/"
    f1 = audio_dir / "sound.wav"
    f2 = audio_dir / "other.mp3"
    f3 = audio_dir / "music.wav"

    audio_dir.mkdir()
    f1.touch()
    f2.touch()
    f3.touch()

    manager = StateManager(audio_clips_dir=audio_dir)
    manager.refresh_state()
    audio_clips = manager.get_audio_clips()

    assert audio_clips["sound"] == f1
    assert audio_clips["other"] == f2
    assert audio_clips["music"] == f3
