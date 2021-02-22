import argparse
import os
import random

from python_mumble_bot.bot.constants import IDENTIFIER, NAME, ROOT_CHANNEL
from python_mumble_bot.bot.event import (
    AudioEvent,
    ChannelTextEvent,
    RecordEvent,
    UserTextEvent,
)


class CommandResolver:
    def resolve(self, incoming):
        parts = incoming.message.split()
        if len(parts) < 2:
            return InvalidCommand()

        if parts[0] == "/pp":
            commands = PlayCommand(parts[1:])
        else:
            for_bot = parts[0]
            if for_bot != "/pmb":
                return IgnoreCommand()
            else:
                action = parts[1]
                if action == "list":
                    if len(parts) == 2:
                        commands = ListCommand(None)
                    else:
                        commands = ListCommand(parts[2])
                elif action == "play":
                    commands = PlayCommand(parts[2:])
                elif action == "random":
                    commands = RandomCommand(parts[2:])
                elif action == "record":
                    commands = RecordCommand(parts[2])
                elif action == "dota":
                    commands = DotaCommand()
                elif action == "tag":
                    commands = TagCommand(parts[2:])
                elif action == "untag":
                    commands = UntagCommand(parts[2:])
                elif action == "load":
                    commands = LoadClipsCommand()
                elif action == "volume":
                    commands = VolumeCommand(parts[2])
                else:
                    commands = InvalidCommand()

        return commands


class Command:
    def __init__(self, data=None):
        self.data = data

    def __eq__(self, other):
        return self.data == other.data

    def generate_events(self, mongo_interface, user):
        return None


class RefreshCommand(Command):
    def __init__(self):
        super().__init__()


class ListCommand(RefreshCommand):
    def __init__(self, tag):
        super().__init__()
        self.tag = tag

    def generate_events(self, mongo_interface, user):
        clips = sorted(
            [(c[NAME], c[IDENTIFIER]) for c in mongo_interface.get_clips(self.tag)]
        )
        names = []
        ids = []

        for name, identifier in clips:
            names.append(name)
            ids.append(identifier)

        starting_char = [n[0] for n in names]

        elems_map = dict()
        for i in range(0, len(starting_char)):
            elems = elems_map.get(starting_char[i], [])
            elem = "".join(["(", ids[i], "): ", names[i]])
            elems.append(elem)
            elems_map[starting_char[i]] = elems

        tables_map = dict()
        for k in elems_map:
            table = "<table><tr>"
            elems = elems_map.get(k)
            for i, elem in enumerate(elems):
                if (i + 1) % 5 == 0:
                    table = table + "</tr><tr>"
                table = table + "".join(["<td>", elem, "</td>"])
            table = table + "</tr></table>"
            tables_map[k] = table

        html = ""
        for k in tables_map:
            table = tables_map[k]
            html = html + "".join(["<h4>", k, "</h4>", "<ul>", table, "</ul>"])

        event = [UserTextEvent(html, user)]
        if html == "":
            if self.tag is None:
                event = [ChannelTextEvent("No clips found in Mongo!!!")]
            else:
                event = [
                    UserTextEvent(
                        "".join(["No clips found with tag: ", self.tag]), user
                    )
                ]

        return event


class DotaCommand(Command):
    GAME_MODES = ["diretide", "turbo", "allpick"]

    def generate_events(self, mongo_interface, user):
        chosen = random.choice(self.GAME_MODES)
        return [ChannelTextEvent(chosen, channel_name=os.getenv(ROOT_CHANNEL))]


class RandomCommand(Command):
    def __init__(self, data):
        super().__init__(data)

    def generate_events(self, mongo_interface, user):
        parser = argparse.ArgumentParser()
        parser.add_argument("--minSpeed")
        parser.add_argument("--maxSpeed")
        parser.add_argument("--clips")

        num_requested = int(self.data[0])
        args = parser.parse_args(self.data[1:])

        min_speed = args.minSpeed
        max_speed = args.maxSpeed
        clips_csv = args.clips

        if min_speed is None:
            min_speed = "1x"
        if max_speed is None:
            max_speed = "1x"

        if clips_csv is None:
            clips = mongo_interface.get_all_file_names()
        else:
            clips = clips_csv.split(",")

        print(clips)

        chosen = []
        speeds = []

        if 0 < num_requested < 26:
            for i in range(0, int(num_requested)):
                chosen.append(random.choice(clips))
                speed = random.uniform(float(min_speed[:-1]), float(max_speed[:-1]))
                speeds.append("".join([str(speed), "x"]))

            command = ["To repeat this random selection:", "/pmb"]
            for sp, selected in zip(speeds, chosen):
                command.append("".join([str(round(float(sp[:-1]), 2)), "x"]))
                command.append(selected)

            text_output = " ".join(command)
        else:
            text_output = "".join(
                [
                    str(num_requested),
                    " is not in the range (0, 10). Request a number in that range.",
                ]
            )

        return [UserTextEvent(text_output, user), AudioEvent(chosen, speeds)]


class RecordCommand(Command):
    def __init__(self, command):
        super().__init__(command)

    def generate_events(self, mongo_interface, user):
        return [RecordEvent(self.data)]


class PlayCommand(Command):
    def __init__(self, data):
        forward_filled_speeds = []
        if self.is_speed(data[0]):
            forward_filled_speeds.append(data[0])
        else:
            forward_filled_speeds.append("1x")

        for i in range(1, len(data)):
            if self.is_speed(data[i]):
                forward_filled_speeds.append(data[i])
            else:
                forward_filled_speeds.append(forward_filled_speeds[i - 1])

        files = []
        speeds = []

        for i in range(0, len(data)):
            f = data[i]
            s = forward_filled_speeds[i]

            if not self.is_speed(f):
                files.append(f)
                speeds.append(s)

        self.playback_speeds = speeds
        self.data = files

    def generate_events(self, mongo_interface, user):
        return [AudioEvent(self.data, self.playback_speeds)]

    @staticmethod
    def is_speed(speed):
        return speed.endswith("x")


class AbstractTagCommand(Command):
    def __init__(self, data):
        super().__init__(data)

    def generate_events(self, mongo_interface, user):
        if isinstance(self, TagCommand):
            tagging_function = mongo_interface.tag
            output_start = 'The following files have now been tagged with "'
        elif isinstance(self, UntagCommand):
            tagging_function = mongo_interface.untag
            output_start = 'The following files have now been untagged with "'
        else:
            raise TypeError("AbstractTagCommand is not of a known subclass")

        tag = self.data[0]
        files = self.data[1:]
        tagging_function(files, tag)

        text_output = "".join(
            [
                output_start,
                tag,
                '": ',
                ",".join(files),
            ]
        )
        return [ChannelTextEvent(text_output)]


class TagCommand(AbstractTagCommand):
    def __init__(self, data):
        super().__init__(data)


class UntagCommand(AbstractTagCommand):
    def __init__(self, data):
        super().__init__(data)


class LoadClipsCommand(Command):
    def __init__(self):
        super().__init__()

    def generate_events(self, mongo_interface, user):
        new_clips = mongo_interface.add_new_clips()

        print("loaded")

        clips_formatted = []
        for identifier, name in new_clips:
            clips_formatted.append(" -> ".join([identifier, name]))

        text_output = ", ".join(clips_formatted)

        return [
            ChannelTextEvent(
                "".join(["The following clips have been loaded: ", text_output])
            )
        ]


class InvalidCommand(Command):
    def __init__(self):
        super().__init__()

    def generate_events(self, mongo_interface, user):
        return [UserTextEvent(self.data, user)]


class IgnoreCommand(Command):
    def __init__(self):
        super().__init__()

    def generate_events(self, mongo_interface, user):
        return [UserTextEvent(self.data, user)]


class VolumeCommand(Command):
    def __init__(self, data):
        super().__init__(data)

    def generate_events(self, mongo_interface, user):
        volume = float(self.data)

        mongo_interface.set_volume(volume)
        return [ChannelTextEvent("".join(["The bot's volume has been set to: ", self.data]))]
