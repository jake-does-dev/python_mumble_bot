import os

from python_mumble_bot.bot.constants import ROOT_CHANNEL


class Event:
    def __init__(self, data):
        self.data = data

    def __eq__(self, other):
        return self.data == other.data


class AudioEvent(Event):
    def __init__(self, data, playback_speeds, semitone_shifts=None):
        super().__init__(data)
        self.playback_speeds = playback_speeds
        self.semitone_shifts = semitone_shifts

class VocodeEvent(Event):
    def __init__(self, speaker, words):
        self.speaker = speaker
        self.words = words

class MusicEvent(Event):
    def __init__(self, data, piece, speed, root_pitch, measure_limit, volume):
        super().__init__(data)
        self.speed = speed
        self.piece = piece
        self.root_pitch = root_pitch
        self.measure_limit = measure_limit
        self.volume = volume


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


class ListMusicEvent(TextEvent):
    def __init__(self, data):
        super().__init__(data)
