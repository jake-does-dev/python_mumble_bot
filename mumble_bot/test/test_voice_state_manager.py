import os
import sys

sys.path.append(os.path.relpath("./python_mumble_bot"))

from python_mumble_bot.bot.manager import PlaybackManager, VoiceStateManager


class FakeCollection:
    def __init__(self):
        self.last_set = None

    def update_one(self, flt, update, upsert=False):
        self.last_set = update["$set"]


class FakeMongo:
    def __init__(self):
        self.db = type("DB", (), {"voice_state": FakeCollection()})()


class FakeChannel(dict):
    def __init__(self, cid, name):
        super().__init__(channel_id=cid, name=name)
        self.moved_in = False

    def move_in(self):
        self.moved_in = True


class FakeChannels(dict):
    """int channel_id -> FakeChannel, plus pymumble's find_by_name."""

    def find_by_name(self, name):
        for ch in self.values():
            if ch["name"] == name:
                return ch
        raise KeyError(name)


def _default_channels():
    return FakeChannels(
        {
            0: FakeChannel(0, "Root"),
            1: FakeChannel(1, "General"),
            2: FakeChannel(2, "AFK"),
        }
    )


class FakeMumble:
    def __init__(self, users, channels=None, current_id=1):
        self.users = users
        self.channels = channels if channels is not None else _default_channels()
        self._current_id = current_id

    def my_channel(self):
        return {"channel_id": self._current_id}


def _publish(monkeypatch, users, channels=None, current_id=1):
    monkeypatch.setenv("MUMBLE_SERVER_USERNAME", "thebot")
    mongo = FakeMongo()
    mumble = FakeMumble(users, channels=channels, current_id=current_id)
    VoiceStateManager(mumble, mongo)._publish()
    return mongo.db.voice_state.last_set


# --- voice_state publishing -------------------------------------------------


def test_present_excludes_bot_and_other_channels(monkeypatch):
    state = _publish(
        monkeypatch,
        {
            1: {
                "channel_id": 1,
                "name": "alice",
                "self_mute": False,
                "self_deaf": False,
            },
            2: {"channel_id": 1, "name": "thebot"},  # the bot itself
            3: {"channel_id": 2, "name": "carol"},  # different channel
        },
    )
    present = {m["name"] for m in state["present"]}
    assert present == {"alice"}  # only the bot's channel, bot excluded
    assert state["current_channel_id"] == "1"


def test_all_channels_published_with_counts_sorted(monkeypatch):
    state = _publish(
        monkeypatch,
        {
            1: {"channel_id": 1, "name": "alice"},
            2: {"channel_id": 2, "name": "carol"},
            3: {"channel_id": 2, "name": "dave"},
            4: {"channel_id": 1, "name": "thebot"},
        },
    )
    chans = {c["name"]: c for c in state["channels"]}
    # every server channel is listed, not just the bot's
    assert set(chans) == {"Root", "General", "AFK"}
    assert chans["General"]["users"] == 1  # alice (bot excluded)
    assert chans["AFK"]["users"] == 2  # carol + dave
    assert chans["Root"]["users"] == 0
    # stable order by channel id so the dropdown doesn't jump around
    assert [c["id"] for c in state["channels"]] == ["0", "1", "2"]


def test_self_mute_and_deaf_propagate(monkeypatch):
    state = _publish(
        monkeypatch,
        {
            1: {
                "channel_id": 1,
                "name": "alice",
                "self_mute": True,
                "self_deaf": False,
            },
            2: {"channel_id": 1, "name": "bob", "self_mute": False, "self_deaf": True},
        },
    )
    present = {m["name"]: m for m in state["present"]}
    assert present["alice"]["mute"] is True and present["alice"]["deaf"] is False
    assert present["bob"]["mute"] is False and present["bob"]["deaf"] is True
    assert present["alice"]["id"] == "alice"  # mumble identity is the username


def test_server_mute_and_deaf_also_count(monkeypatch):
    state = _publish(
        monkeypatch,
        {
            1: {"channel_id": 1, "name": "alice", "mute": True, "deaf": False},
            2: {"channel_id": 1, "name": "bob", "mute": False, "deaf": True},
        },
    )
    present = {m["name"]: m for m in state["present"]}
    assert present["alice"]["mute"] is True
    assert present["bob"]["deaf"] is True


def test_missing_flags_default_to_false(monkeypatch):
    state = _publish(monkeypatch, {1: {"channel_id": 1, "name": "alice"}})
    alice = state["present"][0]
    assert alice["mute"] is False and alice["deaf"] is False


# --- channel move (join / leave) -------------------------------------------


def _playback_with(mumble):
    m = PlaybackManager.__new__(PlaybackManager)
    m.mumble = mumble
    return m


def test_join_channel_moves_into_target():
    mumble = FakeMumble({})
    _playback_with(mumble).join_channel("2")
    assert mumble.channels[2].moved_in is True
    assert mumble.channels[1].moved_in is False


def test_join_channel_none_is_noop():
    mumble = FakeMumble({})
    _playback_with(mumble).join_channel(None)
    assert all(not ch.moved_in for ch in mumble.channels.values())


def test_leave_uses_root_channel_env(monkeypatch):
    monkeypatch.setenv("MUMBLE_SERVER_ROOT_CHANNEL", "General")
    mumble = FakeMumble({})
    _playback_with(mumble).leave_channel()
    assert mumble.channels[1].moved_in is True  # "General"


def test_leave_falls_back_to_root_id_zero(monkeypatch):
    monkeypatch.delenv("MUMBLE_SERVER_ROOT_CHANNEL", raising=False)
    mumble = FakeMumble({})
    _playback_with(mumble).leave_channel()
    assert mumble.channels[0].moved_in is True  # server root
