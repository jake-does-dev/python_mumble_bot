from test.mocks import MockChannelWrapper, MockMumbleWrapper

from bot.event import Event, TextEvent
from bot.manager import TextMessageManager


def test_accept_events():
    mumble = MockMumbleWrapper(None, None)
    manager = TextMessageManager(mumble)

    assert manager.accept(TextEvent(None, None))
    assert not manager.accept(Event("data"))


def test_dispatch():
    channels = {"channel": MockChannelWrapper()}
    mumble = MockMumbleWrapper(None, channels)
    manager = TextMessageManager(mumble)
    event = TextEvent("MyMessage", "channel")

    manager.dispatch(event)

    assert channels["channel"].data == "MyMessage"


def test_process():
    channels = {"channel": MockChannelWrapper()}
    mumble = MockMumbleWrapper(None, channels)
    manager = TextMessageManager(mumble)
    event = TextEvent("MyMessage", "channel")

    manager.process(event)

    assert channels["channel"].data == "MyMessage"
