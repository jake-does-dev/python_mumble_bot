import random

from bot.constants import AUDIO_CLIPS_MAPPING
from bot.event import AudioEvent, RecordEvent, TextEvent


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
                # self.list_files()
            elif action == "play":
                commands = PlayCommand(parts[2:])
                # self.play_files(parts[2:])
            elif action == "random":
                commands = RandomCommand(parts[2])
            elif action == "record":
                commands = RecordCommand(parts[2])
                # if len(parts) != 3:
                #     self.channel.send_text_message(
                #         "The 'record' command needs to be followed by 'start' or 'stop'. Check and try again."
                #     )
                # else:
                #     self.record(parts[2])
            elif action == "dota":
                commands = DotaCommand()
                # chosen = random.randint(0, 3)
                # if chosen == 1:
                #     self.channel.send_text_message("turbo")
                # elif chosen == 2:
                #     self.channel.send_text_message("all pick")
                # elif chosen == 3:
                #     self.channel.send_text_message("diretide")
            else:
                commands = InvalidCommand()

        return commands


class Command:
    def __init__(self, data=None):
        self.data = data

    def __eq__(self, other):
        return self.data == other.data

    def generate_event(self, _):
        return None


class RefreshCommand(Command):
    def __init__(self):
        super().__init__()


class ListCommand(RefreshCommand):
    def __init__(self):
        super().__init__()

    def generate_event(self, state):
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

        return TextEvent(html)


class DotaCommand(Command):
    GAME_MODES = ["diretide", "turbo", "allpick"]

    def generate_event(self, _):
        chosen = random.choice(self.GAME_MODES)
        return TextEvent(chosen)


class RandomCommand(Command):
    def __init__(self, number):
        super().__init__(number)

    def generate_event(self, state):
        file_names = list(state[AUDIO_CLIPS_MAPPING].keys())
        chosen = []

        for i in range(0, int(self.data)):
            chosen.append(random.choice(file_names))

        return AudioEvent(chosen)


class RecordCommand(Command):
    def __init__(self, command):
        super().__init__(command)

    def generate_event(self, _):
        return RecordEvent(self.data)


class PlayCommand(Command):
    def __init__(self, file_names):
        super().__init__(file_names)

    def generate_event(self, _):
        return AudioEvent(self.data)


class InvalidCommand(Command):
    def __init__(self):
        super().__init__("Unrecognised command.")

    def generate_event(self, _):
        return TextEvent(self.data)


class IgnoreCommand(Command):
    def __init__(self):
        super().__init__("Ignoring command.")

    def generate_event(self, _):
        return TextEvent(self.data)
