import os

from bot.constants import ROOT_CHANNEL


class Event:
    def __init__(self, data):
        self.data = data

    def __eq__(self, other):
        return self.data == other.data


class AudioEvent(Event):
    def __init__(self, data, playback_speeds):
        super().__init__(data)
        self.playback_speed = playback_speeds


class RecordEvent(Event):
    def __init__(self, data):
        super().__init__(data)


class TextEvent(Event):
    def __init__(self, data):
        super().__init__(data)


class ChannelTextEvent(TextEvent):
    def __init__(self, data, channel_name=os.getenv(ROOT_CHANNEL)):
        super().__init__(data)
        self.channel_name = channel_name

    def __eq__(self, other):
        return self.data == other.data and self.channel_name == other.channel_name


class UserTextEvent(TextEvent):
    def __init__(self, data, user):
        super().__init__(data)
        self.user = user

    def __eq__(self, other):
        return self.data == other.data and self.user == other.user
