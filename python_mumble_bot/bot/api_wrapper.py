from python_mumble_bot.bot.constants import NAME


class UserWrapper:
    def __init__(self, user):
        self.user = user

    def get_name(self):
        return self.user[NAME]

    def is_sound(self):
        return self.user.sound.is_sound()

    def get_sound(self):
        return self.user.sound.get_sound()


class ChannelWrapper:
    def __init__(self, channel):
        self.channel = channel

    def send(self, data):
        self.channel.send_text_message(data)


class MumbleWrapper:
    def __init__(self, mumble):
        self.mumble = mumble

    def get_users(self):
        users = []
        for k in self.mumble.users:
            users.append(UserWrapper(self.mumble.users[k]))

        return users

    def get_channel(self, name):
        return ChannelWrapper(self.mumble.channels.find_by_name(name))

    def start_recording(self):
        self.mumble.users.myself.recording()

    def stop_recording(self):
        self.mumble.users.myself.unrecording()

    def set_receive_sound(self, option):
        self.mumble.set_receive_sound(option)

    def is_alive(self):
        return self.mumble.is_alive()
