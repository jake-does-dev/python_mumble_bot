import os
import random
import subprocess as sp

import pymumble_py3 as pymumble

import python_mumble_bot.bot.record as record

AUDIO_DIR = "audio/"
HOSTNAME = "MUMBLE_SERVER_HOSTNAME"
PASSWORD = "MUMBLE_SERVER_PASSWORD"
ROOT_CHANNEL = "MUMBLE_SERVER_ROOT_CHANNEL"
VALID_AUDIO_FORMATS = [".wav", ".mp3"]


def connect():
    mumble = pymumble.Mumble(
        os.getenv(HOSTNAME), "PythonMumbleBot", password=os.getenv(PASSWORD)
    )
    client = Client(mumble)

    client.set_callbacks()
    client.start()

    return client


class Client:
    def __init__(self, mumble):
        self.mumble = mumble

    def start(self):
        self.mumble.start()
        self.mumble.is_ready()
        self.channel = self.mumble.channels.find_by_name(os.getenv(ROOT_CHANNEL))
        self.myself = self.mumble.users.myself
        self.recording_manager = record.RecordingManager(
            list(self.mumble.users.values())
        )
        self.file_map = self.refresh_map()

        self.loop()

    def loop(self):
        while self.mumble.is_alive():
            if self.recording_manager.is_recording:
                for user in self.mumble.users.values():
                    if user.sound.is_sound():
                        user_name = user["name"]
                        sound = user.sound.get_sound()
                        self.recording_manager.write(user_name, sound.pcm)

    def set_callbacks(self):
        self.mumble.callbacks.set_callback(
            pymumble.constants.PYMUMBLE_CLBK_TEXTMESSAGERECEIVED, self.interpret_command
        )

    def interpret_command(self, command):
        print(command.message)
        parts = command.message.split()
        if len(parts) < 2:
            self.channel.send_text_message(
                "Badly formatted command. Check and try again."
            )

        for_bot = parts[0]
        if for_bot == "/pmb":
            action = parts[1]

            if action == "list":
                self.list_files()
            elif action == "play":
                self.play_files(parts[2:])
            elif action == "record":
                if len(parts) != 3:
                    self.channel.send_text_message(
                        "The 'record' command needs to be followed by 'start' or 'stop'. Check and try again."
                    )
                else:
                    self.record(parts[2])
            elif action == "dota":
                chosen = random.randint(0, 3)
                if chosen == 1:
                    self.channel.send_text_message("turbo")
                elif chosen == 2:
                    self.channel.send_text_message("all pick")
                elif chosen == 3:
                    self.channel.send_text_message("diretide")
            else:
                self.channel.send_text_message(
                    "Unknown command '{0}'. Check and try again.".format(action)
                )

    def list_files(self):
        self.refresh_map()

        sorted_names = sorted([k for k in self.mapping.keys()])
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

        print(html)
        self.channel.send_text_message(html)

    def refresh_map(self):
        (_, _, file_paths) = next(os.walk(AUDIO_DIR))
        names = [f.split(".")[0] for f in file_paths]
        self.mapping = dict(
            zip(names, ["{0}{1}".format(AUDIO_DIR, f) for f in file_paths])
        )

    def play_files(self, file_names):
        if len(file_names) == 2 and file_names[0] == "random":
            number = int(file_names[1])
            values = list(self.mapping.values())

            if number > 0 and number < 11:
                for _ in range(0, number):
                    file = random.choice(values)
                    self.send_audio(file)
            else:
                self.channel.send_text_message(
                    "I will only play between 1 and 10 clips."
                )

        else:
            for name in file_names:
                file = self.mapping.get(name)
                self.send_audio(file)

    def send_audio(self, file):
        encode_command = ["ffmpeg", "-i", file, "-ac", "1", "-f", "s16le", "-"]
        print(encode_command)
        pcm = sp.Popen(encode_command, stdout=sp.PIPE, stderr=sp.DEVNULL).stdout.read()
        self.mumble.sound_output.add_sound(pcm)

    def record(self, state):
        if state == "start":
            self.recording_manager.start_recording()
            self.mumble.set_receive_sound(True)
            self.myself.mumble_object.users.myself.recording = True
        else:
            self.myself.mumble_object.users.myself.recording = False
            self.mumble.set_receive_sound(False)
            self.recording_manager.stop_recording()


if __name__ == "__main__":
    connect()
