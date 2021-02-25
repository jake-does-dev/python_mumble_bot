import argparse
import os
import random

from python_mumble_bot.bot.constants import IDENTIFIER, NAME, ROOT_CHANNEL
from python_mumble_bot.bot.event import (
    AudioEvent,
    ChannelTextEvent,
    RecordEvent,
    UserTextEvent,
    MusicEvent,
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
                elif action == "music":
                    commands = MusicCommand(parts[2:])
                elif action == "help":
                    if len(parts) == 2:
                        commands = HelpCommand(None)
                    else:
                        commands = HelpCommand(parts[2])
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

    @staticmethod
    def help():
        return ""


class RefreshCommand(Command):
    def __init__(self):
        super().__init__()


class ListCommand(RefreshCommand):
    def __init__(self, tag):
        super().__init__()
        self.tag = tag

    @staticmethod
    def help():
        return "<br>".join(
            ["Example call: /pmb list",
            "This shows all available clips",
            "Example call: /pmb list chicken",
            "This shows all available clips with tag chicken"])

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

    @staticmethod
    def help():
        return "<br>".join(
            ["Example call: /pmb dota",
            "This chooses which Dota game mode to play"])


class RandomCommand(Command):
    def __init__(self, data):
        super().__init__(data)

    @staticmethod
    def help():
        return "<br>".join(
            ["Example call: /pmb random 10",
            "This plays 10 random clips",
            "Example call: /pmb random 10 @minSpeed 0.5x @maxSpeed 2x @pitchDownLimit -6s @pitchUpLimit 6s @clips oy17,oy77",
            "This plays 10 random clips, with a min speed of 0.5x, max speed of 2x, within the pitch range of 6 semitones below and 6 semitones above, choosing from the clips oy17 and oy77. All modifiers are optional"])

    def generate_events(self, mongo_interface, user):
        parser = argparse.ArgumentParser(prefix_chars="@")
        parser.add_argument("@minSpeed")
        parser.add_argument("@maxSpeed")
        parser.add_argument("@clips")
        parser.add_argument("@pitchDownLimit")
        parser.add_argument("@pitchUpLimit")

        num_requested = int(self.data[0])
        args = parser.parse_args(self.data[1:])

        min_speed = args.minSpeed
        max_speed = args.maxSpeed
        clips_csv = args.clips
        pitch_down_limit = args.pitchDownLimit
        pitch_up_limit = args.pitchUpLimit

        if min_speed is None:
            min_speed = "1x"
        if max_speed is None:
            max_speed = "1x"
        if pitch_down_limit is None:
            pitch_down_limit = "0s"
        if pitch_up_limit is None:
            pitch_up_limit = "0s"

        if clips_csv is None:
            clips = mongo_interface.get_all_file_names()
        else:
            clips = clips_csv.split(",")

        chosen = []
        speeds = []
        semitone_shifts = []

        if 0 < num_requested < 26:
            for i in range(0, int(num_requested)):
                chosen.append(random.choice(clips))

                speed = round(random.uniform(float(min_speed[:-1]), float(max_speed[:-1])), 2)
                speeds.append("".join([str(speed), "x"]))

                pitch_shift = random.randint(int(pitch_down_limit[:-1]), int(pitch_up_limit[:-1]))
                semitone_shifts.append("".join([str(pitch_shift), "s"]))

            command = ["To repeat this random selection:", "/pmb"]
            for sp, shift, selected in zip(speeds, semitone_shifts, chosen):
                command.append("".join([str(round(float(sp[:-1]), 2)), "x"]))
                command.append("".join([str(shift[:-1]), "s"]))
                command.append(selected)

            text_output = " ".join(command)
        else:
            text_output = "".join(
                [
                    str(num_requested),
                    " is not in the range (0, 10). Request a number in that range.",
                ]
            )

        print("".join(["files:{", str(chosen), "}\nspeeds:{", str(speeds), "}\nshifts:{", str(semitone_shifts), "}"]))

        return [UserTextEvent(text_output, user), AudioEvent(chosen, speeds, semitone_shifts)]


class RecordCommand(Command):
    def __init__(self, command):
        super().__init__(command)

    @staticmethod
    def help():
        return "<br>".join(
            ["Example call: /pmb record [start|stop]",
             "Starts/stops recording voice data from all users"])

    def generate_events(self, mongo_interface, user):
        return [RecordEvent(self.data)]

class MusicCommand(Command):
    def __init__(self, data):
        super().__init__(data)
    
    def generate_events(self, mongo_interface, user):
        piece = self.data[0]
        clip = self.data[1]
        speed = float(self.data[2][:-1])
        pitch = int(self.data[3][:-1])

        return [MusicEvent(clip, piece, speed, pitch)]

    @staticmethod
    def help():
        return "<br>".join(
            ["Example call: /pmb music Sea_Shanty_2 oy61 1.3x 4s",
             "Plays the song sea-shanty-2 using the sound clip oy61, at an increased speed of 1.3x and a root pitch of 4 semitones above oy61",
             "AVAILABLE PIECES: [bach-minuet-in-g, coffin-dance, mario-bros-theme, sea-shanty-2]"])

class PlayCommand(Command):
    def __init__(self, data):
        forward_filled_speeds = self.do_forward_fill(data, self.is_speed, "1x")
        forward_filled_semitone_shifts = self.do_forward_fill(data, self.is_semitone_shift, "0s")

        files = []
        speeds = []
        shifts = []

        i = 0
        while i < len(data):
            incoming = data[i]
            speed = forward_filled_speeds[i]
            shift = forward_filled_semitone_shifts[i]

            if self.is_riser(incoming):
                print("startShift" + data[i+1])
                print("endShift" + data[i+2])
                print("clipShift" + data[i+3])

                startShift = int(data[i+1][:-1])
                endShift = int(data[i+2][:-1])
                clip = data[i+3]

                for s in range(startShift, endShift):
                    files.append(clip)
                    speeds.append(speed)
                    shifts.append("".join([str(s), "s"]))

                i += 3
  
            elif not self.is_speed(incoming) and not self.is_semitone_shift(incoming):
                files.append(incoming)
                speeds.append(speed)
                shifts.append(shift)
                print(i)

            i += 1
            print(i)

        self.data = files
        self.playback_speeds = speeds
        self.semitone_shifts = shifts

        print("".join(["files:{", str(self.data), "}\nspeeds:{", str(self.playback_speeds), "}\nshifts:{", str(self.semitone_shifts), "}"]))

    @staticmethod
    def help():
        return "<br>".join(
            ["Example call: /pp oy17",
            "Plays the clip with id oy17",
            "Example call: /pp ollie_raspberry",
            "Plays the clip with name ollie_raspberry",
            "Example call: /pp 2x 3s oy17",
            "Plays the clip oy17 at 2x speed, at 3 semitones pitch shifted up. If speeds and pitch shifts are ignored, then the defaults of 1x and 0s are used.",
            ])


    def generate_events(self, mongo_interface, user):
        return [AudioEvent(self.data, self.playback_speeds, self.semitone_shifts)]

    @staticmethod
    def do_forward_fill(data, checking_function, default):
        forward_filled = []
        if checking_function(data[0]):
            forward_filled.append(data[0])
        else:
            forward_filled.append(default)

        for i in range(1, len(data)):
            if checking_function(data[i]):
                forward_filled.append(data[i])
            else:
                forward_filled.append(forward_filled[i - 1])

        return forward_filled

    @staticmethod
    def is_riser(riser):
        return riser.endswith("riser")

    @staticmethod
    def is_speed(speed):
        return speed.endswith("x")

    @staticmethod
    def is_semitone_shift(semitone_shift):
        return semitone_shift.endswith("s")


class AbstractTagCommand(Command):
    def __init__(self, data):
        super().__init__(data)

    @staticmethod
    def help():
        return "<br>".join(
            ["Example call: /pmb tag chicken oy45",
            "This tags the clip oy45 with the tag chicken. See /pmb list [tag] for further use"])

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

    @staticmethod
    def help():
        return "<br>".join(
            ["Example: /pmb volume 0.5",
            "Plays all clips at half their original volume."]
        )

    def generate_events(self, mongo_interface, user):
        volume = float(self.data)

        mongo_interface.set_volume(volume)
        return [ChannelTextEvent("".join(["The bot's volume has been set to: ", self.data]))]


class HelpCommand(Command):
    def __init__(self, data):
        super().__init__(data)
    
    def generate_events(self, mongo_interface, user):
        subclasses = Command.__subclasses__()

        text = "<br>" + "<br><br>".join([x.help() for x in subclasses])

        print(text)
        # return [UserTextEvent(text, user)]
        return [UserTextEvent(text, user)]



