import os
import sys

sys.path.append(os.path.relpath("./python_mumble_bot"))

from bot.command import (
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

command_resolver = CommandResolver()


class Message:
    def __init__(self, message):
        self.message = message


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
    event = command.generate_event(state)

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
    expected_event = TextEvent(expected_html)

    assert event == expected_event


def test_event_from_dota_command():
    command = DotaCommand()
    event = command.generate_event(None)

    assert isinstance(event, TextEvent)
    assert event.data in ["turbo", "diretide", "allpick"]


def test_event_from_invalid_command():
    command = InvalidCommand()
    event = command.generate_event(None)

    assert event == TextEvent("Unrecognised command.")


def test_event_from_ignore_command():
    command = IgnoreCommand()
    event = command.generate_event(None)

    assert event == TextEvent("Ignoring command.")


def test_event_from_play_command():
    command = PlayCommand(["first", "second"])
    event = command.generate_event(None)

    assert event == AudioEvent(["first", "second"])


def test_event_from_random_command():
    state = dict()
    state[AUDIO_CLIPS_MAPPING] = {
        "awesome": "a.wav",
        "bingo": "b.wav",
        "charlie": "c.wav",
        "delta": "d.wav",
    }

    command = RandomCommand("3")
    event = command.generate_event(state)

    assert isinstance(event, AudioEvent)
    assert set(event.data).issubset(state[AUDIO_CLIPS_MAPPING].keys())


def test_event_from_record_command():
    command = RecordCommand("start")
    event = command.generate_event(None)

    assert event == RecordEvent("start")
