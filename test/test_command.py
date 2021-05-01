import os
import sys
from unittest import mock

from python_mumble_bot.db.mongodb import MongoInterface

sys.path.append(os.path.relpath("./python_mumble_bot"))

from python_mumble_bot.bot.command import (
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
from python_mumble_bot.bot.constants import (
    H4,
    H4_END,
    IDENTIFIER,
    NAME,
    TABLE,
    TABLE_END,
    TD,
    TD_END,
    TR,
    TR_END,
    UL,
    UL_END,
)
from python_mumble_bot.bot.event import (
    AudioEvent,
    ChannelTextEvent,
    RecordEvent,
    UserTextEvent,
)
from python_mumble_bot.bot.message import Message

command_resolver = CommandResolver()


def test_resolve_play_by_name():
    incoming = Message("/pmb play this thing")
    command = command_resolver.resolve(incoming)

    assert command == PlayCommand(["this", "thing"])


def test_resolve_play_by_id():
    incoming = Message("/pmb play 0 1")
    command = command_resolver.resolve(incoming)

    assert command == PlayCommand(["0", "1"])


def test_resolve_dota():
    incoming = Message("/pmb dota")
    command = command_resolver.resolve(incoming)

    assert command == DotaCommand()


def test_resolve_random():
    incoming = Message("/pmb random 4")
    command = command_resolver.resolve(incoming)

    assert command == RandomCommand(["4"])


def test_resolve_record():
    incoming = Message("/pmb record start")
    command = command_resolver.resolve(incoming)

    assert command == RecordCommand("start")


def test_resolve_list():
    incoming = Message("/pmb list")
    command = command_resolver.resolve(incoming)

    assert command == ListCommand(None)


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
    mock_mongo_interface = mock.create_autospec(MongoInterface)
    mock_mongo_interface.get_clips.return_value = [
        {IDENTIFIER: "0", NAME: "awesome"},
        {IDENTIFIER: "1", NAME: "bingo"},
    ]

    command = ListCommand(None)
    event = command.generate_events(mock_mongo_interface, None)

    expected_html = "".join(
        [
            H4,
            "a",
            H4_END,
            UL,
            TABLE,
            TR,
            TD,
            "(0): awesome",
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
            "(1): bingo",
            TD_END,
            TR_END,
            TABLE_END,
            UL_END,
        ]
    )
    expected_event = [UserTextEvent(expected_html, None)]

    assert event == expected_event


def test_event_from_dota_command():
    command = DotaCommand()
    events = command.generate_events(None, None)

    assert isinstance(events[0], ChannelTextEvent)
    assert events[0].data in ["turbo", "diretide", "allpick"]


def test_event_from_invalid_command():
    command = InvalidCommand()
    events = command.generate_events(None, None)

    assert events == [UserTextEvent(None, None)]


def test_event_from_ignore_command():
    command = IgnoreCommand()
    events = command.generate_events(None, None)

    assert events == [UserTextEvent(None, None)]


def test_event_from_play_command_by_name():
    command = PlayCommand(["first", "second"])
    events = command.generate_events(None, None)

    assert events == [AudioEvent(["first", "second"], ["1x", "1x"])]


def test_event_from_play_command_by_id():
    command = PlayCommand(["0", "1"])
    events = command.generate_events(None, None)

    assert events == [AudioEvent(["0", "1"], ["1x", "1x"])]


def test_event_from_random_command():
    mock_mongo_interface = mock.create_autospec(MongoInterface)

    names = ["awesome", "bingo", "charlie", "delta"]
    mock_mongo_interface.get_all_file_names.return_value = names

    command = RandomCommand("3")
    events = command.generate_events(mock_mongo_interface, None)

    assert isinstance(events[0], UserTextEvent)
    assert isinstance(events[1], AudioEvent)
    assert set(events[1].data).issubset(set(names))


def test_event_from_record_command():
    command = RecordCommand("start")
    events = command.generate_events(None, None)

    assert events == [RecordEvent("start")]


def test_unimplemented_command():
    command = Command()
    events = command.generate_events(None, None)

    assert events is None
