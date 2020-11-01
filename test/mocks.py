from bot.api_wrapper import ChannelWrapper, MumbleWrapper, UserWrapper


class MockMumbleWrapper(MumbleWrapper):
    def __init__(self, users, channels):
        self.users = users
        self.channels = channels
        self.is_recording = False
        self.receiving_sound = False
        self.is_alive = True

    def get_users(self):
        return self.users

    def start_recording(self):
        self.is_recording = True

    def stop_recording(self):
        self.is_recording = False

    def set_receive_sound(self, option):
        self.receiving_sound = option

    def get_channel(self, name):
        return self.channels[name]

    def is_alive(self):
        return self.mumble.is_alive()


class MockChannelWrapper(ChannelWrapper):
    def __init__(self):
        self.data = None

    def send(self, data):
        self.data = data


class MockUserWrapper(UserWrapper):
    def __init__(self, name, data):
        self.name = name
        self.data = data
        self.sound = True

    def get_name(self):
        return self.name

    def is_sound(self):
        return self.sound

    def get_sound(self):
        return self.data


class MockSound:
    def __init__(self, pcm):
        self.pcm = pcm
