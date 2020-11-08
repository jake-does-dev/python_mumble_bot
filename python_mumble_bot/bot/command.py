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
                    commands = ListCommand()
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
    def __init__(self):
        super().__init__()

    def generate_events(self, mongo_interface, user):
        clips = sorted([(c[NAME], c[IDENTIFIER]) for c in mongo_interface.get_clips()])
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

        return [UserTextEvent(html, user)]


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

        num_requested = int(self.data[0])
        args = parser.parse_args(self.data[1:])

        min_speed = args.minSpeed
        max_speed = args.maxSpeed

        if min_speed is None:
            min_speed = "1x"
        if max_speed is None:
            max_speed = "1x"

        file_names = mongo_interface.get_all_file_names()
        chosen = []
        speeds = []

        if 0 < num_requested < 10:
            for i in range(0, int(num_requested)):
                chosen.append(random.choice(file_names))
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


class TagCommand(Command):
    def __init__(self, data):
        super().__init__(data)

    def generate_events(self, mongo_interface, user):
        tag = self.data[0]
        files = self.data[1:]
        for f in files:
            mongo_interface.tag(f, tag)
        text_output = "".join(
            [
                'The following files have now been tagged with "',
                tag,
                '": ',
                ",".join(files),
            ]
        )
        return [UserTextEvent(text_output, user)]


class UntagCommand(Command):
    def __init__(self, data):
        super().__init__(data)

    def generate_events(self, mongo_interface, user):
        tag = self.data[0]
        files = self.data[1:]
        for f in files:
            mongo_interface.untag(f, tag)
        text_output = "".join(
            [
                'The following files have now been untagged with "',
                tag,
                '": ',
                ",".join(files),
            ]
        )
        return [UserTextEvent(text_output, user)]


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
