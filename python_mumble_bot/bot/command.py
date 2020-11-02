import os
import random

from bot.constants import AUDIO_CLIPS_MAPPING, ROOT_CHANNEL
from bot.event import AudioEvent, ChannelTextEvent, RecordEvent, UserTextEvent


class CommandResolver:
    def resolve(self, incoming):
        parts = incoming.message.split()
        if len(parts) < 2:
            return InvalidCommand()

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
                commands = RandomCommand(parts[2])
            elif action == "record":
                commands = RecordCommand(parts[2])
            elif action == "dota":
                commands = DotaCommand()
            else:
                commands = InvalidCommand()

        return commands


class Command:
    def __init__(self, data=None):
        self.data = data

    def __eq__(self, other):
        return self.data == other.data

    def generate_events(self, state, user):
        return None


class RefreshCommand(Command):
    def __init__(self):
        super().__init__()


class ListCommand(RefreshCommand):
    def __init__(self):
        super().__init__()

    def generate_events(self, state, user):
        sorted_names = sorted([k for k in state[AUDIO_CLIPS_MAPPING].keys()])
        starting_char = [n[0] for n in sorted_names]

        elems_map = dict()
        for i in range(0, len(starting_char)):
            names = elems_map.get(starting_char[i], [])
            names.append(sorted_names[i])
            elems_map[starting_char[i]] = names

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

    def generate_events(self, state, user):
        chosen = random.choice(self.GAME_MODES)
        return [ChannelTextEvent(chosen, channel_name=os.getenv(ROOT_CHANNEL))]


class RandomCommand(Command):
    def __init__(self, number):
        super().__init__(number)

    def generate_events(self, state, user):
        file_names = list(state[AUDIO_CLIPS_MAPPING].keys())
        chosen = []

        for i in range(0, int(self.data)):
            chosen.append(random.choice(file_names))

        command = ["To repeat this random selection:", "/pmb"]
        for selected in chosen:
            command.append(selected)

        repeat = " ".join(command)
        return [UserTextEvent(repeat, user), AudioEvent(chosen)]


class RecordCommand(Command):
    def __init__(self, command):
        super().__init__(command)

    def generate_events(self, state, user):
        return [RecordEvent(self.data)]


class PlayCommand(Command):
    def __init__(self, file_names):
        super().__init__(file_names)

    def generate_events(self, state, user):
        return [AudioEvent(self.data)]


class InvalidCommand(Command):
    def __init__(self):
        super().__init__("Unrecognised command.")

    def generate_events(self, state, user):
        return [UserTextEvent(self.data, user)]


class IgnoreCommand(Command):
    def __init__(self):
        super().__init__("Ignoring command.")

    def generate_events(self, state, user):
        return [UserTextEvent(self.data, user)]
