import os
import sys

sys.path.append(os.path.relpath("./python_mumble_bot"))

from python_mumble_bot.bot.manager import VoiceStateManager


class FakeCollection:
    def __init__(self):
        self.last_set = None

    def update_one(self, flt, update, upsert=False):
        self.last_set = update["$set"]


class FakeDB:
    def __init__(self):
        self.voice_state = FakeCollection()


class FakeMongo:
    def __init__(self):
        self.db = FakeDB()


class FakeMumble:
    def __init__(self, users):
        self.users = users

    def my_channel(self):
        return {"channel_id": 1, "name": "General"}


def _publish(monkeypatch, users):
    monkeypatch.setenv("MUMBLE_SERVER_USERNAME", "thebot")
    mongo = FakeMongo()
    VoiceStateManager(FakeMumble(users), mongo)._publish()
    return mongo.db.voice_state.last_set


def test_present_excludes_bot_and_other_channels(monkeypatch):
    state = _publish(monkeypatch, {
        1: {"channel_id": 1, "name": "alice", "self_mute": False, "self_deaf": False},
        2: {"channel_id": 1, "name": "thebot"},          # the bot itself
        3: {"channel_id": 2, "name": "carol"},           # different channel
    })
    present = {m["name"] for m in state["present"]}
    assert present == {"alice"}
    # the gate keys the web reads
    assert state["current_channel_id"] == "1"


def test_self_mute_and_deaf_propagate(monkeypatch):
    state = _publish(monkeypatch, {
        1: {"channel_id": 1, "name": "alice", "self_mute": True, "self_deaf": False},
        2: {"channel_id": 1, "name": "bob", "self_mute": False, "self_deaf": True},
    })
    present = {m["name"]: m for m in state["present"]}
    assert present["alice"]["mute"] is True and present["alice"]["deaf"] is False
    assert present["bob"]["mute"] is False and present["bob"]["deaf"] is True
    # mumble identity is the username
    assert present["alice"]["id"] == "alice"


def test_server_mute_and_deaf_also_count(monkeypatch):
    state = _publish(monkeypatch, {
        1: {"channel_id": 1, "name": "alice", "mute": True, "deaf": False},
        2: {"channel_id": 1, "name": "bob", "mute": False, "deaf": True},
    })
    present = {m["name"]: m for m in state["present"]}
    assert present["alice"]["mute"] is True
    assert present["bob"]["deaf"] is True


def test_missing_flags_default_to_false(monkeypatch):
    state = _publish(monkeypatch, {
        1: {"channel_id": 1, "name": "alice"},
    })
    alice = state["present"][0]
    assert alice["mute"] is False and alice["deaf"] is False
