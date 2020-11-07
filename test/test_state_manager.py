import os
import sys

sys.path.append(os.path.relpath("./python_mumble_bot"))

from python_mumble_bot.bot.manager import StateManager


def test_refresh_audio_files_mapping(tmp_path):
    audio_dir = tmp_path / "audio/"
    f1 = audio_dir / "music.wav"
    f2 = audio_dir / "other.mp3"
    f3 = audio_dir / "sound.wav"

    audio_dir.mkdir()
    f1.touch()
    f2.touch()
    f3.touch()

    manager = StateManager(audio_clips_dir=audio_dir)
    manager.refresh_state()

    assert manager.find_audio_clip_by_id("0") == f1
    assert manager.find_audio_clip_by_name("music") == f1

    assert manager.find_audio_clip_by_id("1") == f2
    assert manager.find_audio_clip_by_name("other") == f2

    assert manager.find_audio_clip_by_id("2") == f3
    assert manager.find_audio_clip_by_name("sound") == f3
