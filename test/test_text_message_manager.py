from test.mocks import MockChannelWrapper, MockMumbleWrapper, MockUserWrapper

from bot.event import ChannelTextEvent, Event, UserTextEvent
from bot.manager import TextMessageManager


def test_accept_events():
    mumble = MockMumbleWrapper(None, None)
    manager = TextMessageManager(mumble)

    assert manager.accept(UserTextEvent(None, None))
    assert manager.accept(ChannelTextEvent(None, None))
    assert not manager.accept(Event("data"))


def test_process_channel_text_event():
    channels = {"channel": MockChannelWrapper()}
    mumble = MockMumbleWrapper(None, channels)
    manager = TextMessageManager(mumble)
    event = ChannelTextEvent("MyMessage", "channel")

    manager.process(event)

    assert channels["channel"].data == "MyMessage"


def test_process_user_text_event():
    user = MockUserWrapper("USER")
    mumble = MockMumbleWrapper(user, None)
    manager = TextMessageManager(mumble)
    event = UserTextEvent("MyMessage", user)

    manager.process(event)

    assert user.text_data == "MyMessage"
