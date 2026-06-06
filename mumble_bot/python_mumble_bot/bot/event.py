import os

from python_mumble_bot.bot.constants import ROOT_CHANNEL


class Event:
    def __init__(self, data):
        self.data = data

    def __eq__(self, other):
        return self.data == other.data


class AudioEvent(Event):
    def __init__(
        self,
        data,
        playback_speeds,
        semitone_shifts=None,
        voice_key=None,
        append=True,
    ):
        super().__init__(data)
        self.playback_speeds = playback_speeds
        self.semitone_shifts = semitone_shifts
        # Mixer routing: which "voice" this plays on, and whether it appends to
        # that voice (sequential) or replaces it (interrupt/restart). Web single
        # plays key by requester + replace; queues use a shared appending voice;
        # legacy in-channel events default to a shared appending "default" voice.
        self.voice_key = voice_key
        self.append = append


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


class MidiSongEvent(Event):
    """Play a MIDI song using a clip as the instrument (web-triggered)."""

    def __init__(self, clip_ref, song_file, transpose=0, speed=1.0, gain=0.0,
                 max_seconds=0.0, requested_by=None, song_name=None, clip_name=None):
        super().__init__(clip_ref)
        self.clip_ref = clip_ref
        self.song_file = song_file      # filename under audio/music, e.g. "foo.mid"
        self.transpose = transpose      # semitone offset on top of auto-centring
        self.speed = speed              # global tempo multiplier (onset spacing)
        self.gain = gain                # dB, applied to the whole render
        self.max_seconds = max_seconds  # 0 = full song
        self.requested_by = requested_by
        # Display names for the now-playing mini-player (fall back to file/ref).
        self.song_name = song_name or song_file
        self.clip_name = clip_name or clip_ref


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
