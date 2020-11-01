import os
import sys
from test.mocks import MockMumbleWrapper, MockSound, MockUserWrapper

from bot.event import Event, RecordEvent
from bot.manager import RecordingManager

sys.path.append(os.path.relpath("./python_mumble_bot"))

START = RecordEvent("start")
STOP = RecordEvent("stop")
DATA = b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"


def test_record_for_one_user(tmp_path):
    user = MockUserWrapper("USER", MockSound(DATA))

    mumble = MockMumbleWrapper([user], None)
    manager = RecordingManager(mumble, recording_dir=tmp_path)

    manager.dispatch(START)
    manager.loop()
    manager.dispatch(STOP)

    assert len(os.listdir(tmp_path)) == 1


def test_record_for_multiple_users(tmp_path):
    users = [MockUserWrapper(v, MockSound(DATA)) for v in ["1", "2", "3"]]

    mumble = MockMumbleWrapper(users, None)

    manager = RecordingManager(mumble, recording_dir=tmp_path)

    manager.dispatch(START)
    manager.loop()
    manager.dispatch(STOP)

    assert len(os.listdir(tmp_path)) == 3


def test_event_acceptance():
    manager = RecordingManager(None, None)

    assert manager.accept(RecordEvent(None))
    assert not manager.accept(Event(None))
