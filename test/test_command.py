import os
import sys

sys.path.append(os.path.relpath("./python_mumble_bot"))

from bot.command import (
    Command,
    CommandResolver,
    DotaCommand,
    IgnoreCommand,
    InvalidCommand,
    ListCommand,
    PlayCommand,
    RandomCommand,
    RecordCommand,
)
from bot.constants import (
    AUDIO_CLIPS_MAPPING,
    H4,
    H4_END,
    TABLE,
    TABLE_END,
    TD,
    TD_END,
    TR,
    TR_END,
    UL,
    UL_END,
)
from bot.event import AudioEvent, RecordEvent, TextEvent
from bot.message import Message

command_resolver = CommandResolver()


def test_resolve_play():
    incoming = Message("/pmb play this thing")
    command = command_resolver.resolve(incoming)

    assert command == PlayCommand(["this", "thing"])


def test_resolve_dota():
    incoming = Message("/pmb dota")
    command = command_resolver.resolve(incoming)

    assert command == DotaCommand()


def test_resolve_random():
    incoming = Message("/pmb random 4")
    command = command_resolver.resolve(incoming)

    assert command == RandomCommand("4")


def test_resolve_record():
    incoming = Message("/pmb record start")
    command = command_resolver.resolve(incoming)

    assert command == RecordCommand("start")


def test_resolve_list():
    incoming = Message("/pmb list")
    command = command_resolver.resolve(incoming)

    assert command == ListCommand()


def test_ignore():
    incoming = Message("/thisisnotforpmb command")
    command = command_resolver.resolve(incoming)

    assert command == IgnoreCommand()


def test_invalid_not_enough_args():
    incoming = Message("/onlyoneparameter")
    command = command_resolver.resolve(incoming)
    assert isinstance(command, InvalidCommand)


def test_invalid_unknown_command():
    incoming = Message("/pmb unknown_command")
    command = command_resolver.resolve(incoming)
    assert isinstance(command, InvalidCommand)


def test_event_from_list_command():
    state = dict()
    state[AUDIO_CLIPS_MAPPING] = {"awesome": "a.wav", "bingo": "b.wav"}

    command = ListCommand()
    event = command.generate_events(state)

    expected_html = "".join(
        [
            H4,
            "a",
            H4_END,
            UL,
            TABLE,
            TR,
            TD,
            "awesome",
            TD_END,
            TR_END,
            TABLE_END,
            UL_END,
            H4,
            "b",
            H4_END,
            UL,
            TABLE,
            TR,
            TD,
            "bingo",
            TD_END,
            TR_END,
            TABLE_END,
            UL_END,
        ]
    )
    expected_event = [TextEvent(expected_html)]

    assert event == expected_event


def test_event_from_dota_command():
    command = DotaCommand()
    events = command.generate_events(None)

    assert isinstance(events[0], TextEvent)
    assert events[0].data in ["turbo", "diretide", "allpick"]


def test_event_from_invalid_command():
    command = InvalidCommand()
    events = command.generate_events(None)

    assert events == [TextEvent("Unrecognised command.")]


def test_event_from_ignore_command():
    command = IgnoreCommand()
    events = command.generate_events(None)

    assert events == [TextEvent("Ignoring command.")]


def test_event_from_play_command():
    command = PlayCommand(["first", "second"])
    events = command.generate_events(None)

    assert events == [AudioEvent(["first", "second"])]


def test_event_from_random_command():
    state = dict()
    state[AUDIO_CLIPS_MAPPING] = {
        "awesome": "a.wav",
        "bingo": "b.wav",
        "charlie": "c.wav",
        "delta": "d.wav",
    }

    command = RandomCommand("3")
    events = command.generate_events(state)

    assert isinstance(events[0], TextEvent)
    assert isinstance(events[1], AudioEvent)
    assert set(events[1].data).issubset(state[AUDIO_CLIPS_MAPPING].keys())


def test_event_from_record_command():
    command = RecordCommand("start")
    events = command.generate_events(None)

    assert events == [RecordEvent("start")]


def test_unimplemented_command():
    command = Command()
    events = command.generate_events(None)

    assert events is None
