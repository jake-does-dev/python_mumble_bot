import os
import sys

sys.path.append(os.path.realpath("/home/winneh/dev/python_mumble_bot/src"))

import bot.record as record


def test_record_for_one_user(tmp_path):
    user = "MY_USER"
    users = [{"name": user}]

    manager = record.RecordingManager(users, recording_dir=tmp_path)

    manager.start_recording()
    manager.write(
        user, b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    )
    manager.stop_recording()

    assert len(os.listdir(tmp_path)) == 1


def test_record_for_multiple_users(tmp_path):
    users = [{"name": v} for v in ["1", "2", "3"]]

    manager = record.RecordingManager(users, recording_dir=tmp_path)

    manager.start_recording()
    for user in users:
        manager.write(
            user["name"],
            b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00",
        )
    manager.stop_recording()

    assert len(os.listdir(tmp_path)) == 3
