import datetime as dt
import math
import subprocess as sp
import os
import wave
from pathlib import Path

from python_mumble_bot.musicxml.parser import parse_musicxml
from python_mumble_bot.music.piece import Note
from python_mumble_bot.bot.constants import BITRATE, DEFAULT_RECORDING_DIR
from python_mumble_bot.bot.event import (
    AudioEvent,
    MusicEvent,
    ChannelTextEvent,
    RecordEvent,
    TextEvent,
    UserTextEvent,
)


class EventManager:
    def process(self, event):
        if self.accept(event):
            self.dispatch(event)

    def accept(self, event):
        pass

    def dispatch(self, event):
        pass

    def loop(self):
        pass


class PlaybackManager(EventManager):
    NOTES_TO_SEMITONES = {'C': 0,
         'D': 2,
         'E': 4,
         'F': 5,
         'G': 7,
         'A': 9,
         'B': 11}

    RESAMPLE_FILTER = "aresample=48000*"
    SETRATE_FILTER = "asetrate=48000/"

    def __init__(self, mumble, state_manager):
        self.mumble = mumble
        self.state_manager = state_manager

    def accept(self, event):
        return isinstance(event, AudioEvent) or isinstance(event, MusicEvent)

    def dispatch(self, event):
        if isinstance(event, AudioEvent):
            self._play_clips(event, self.RESAMPLE_FILTER)
        elif isinstance(event, MusicEvent):
            self._play_music(event)

    def _play_clips(self, event, pitch_filter):
        for ref, speed, shift in zip(event.data, event.playback_speeds, event.semitone_shifts):
            file = self.state_manager.find_audio_clip(ref)
            pcm = self._transform_audio(file, pitch_filter, self.state_manager.get_volume(), float(speed[:-1]), float(shift[:-1]), desired_output='pcm')
            self.mumble.sound_output.add_sound(pcm)
            
    def _play_music(self, event):
        piece = "audio/music/{0}".format(event.piece)
        processing_dir = "audio/music_processing/{0}".format(event.piece)
        clip = event.data
        base_speed = event.speed
        root_pitch = event.root_pitch

        # music_to_process = self.data
        # piece = '/tmp/Bach_Minuet_in_G_Major_BWV_Anh._114'
        # piece = '/tmp/Sea_Shanty_2'
        file = self.state_manager.find_audio_clip(clip)

        # measures = parse_musicxml(music_to_process)
        measures = parse_musicxml('{0}.xml'.format(piece))

        measure_duration = measures['measure_length']

        # Now, in each measures, concatenate the pcm data for
        # each voice. If there are rests for the voices,
        # then these must be filled in with blank data.
        measure_voice_note_wav_file_format = "{0}_measure{1}_voice{2}_note{3}.wav"
        measure_voice_wav_file_format = "{0}_measure{1}_voice{2}.wav"
        measure_wav_file_format = "{0}_measure{1}.wav"

        measure_files = []
        root_octave = None

        for measure_number, measure in enumerate(measures['measures']):
            voices = list(measure.keys())
            voice_to_note_numbers = {}

            voice_pcm_data = []

            # Extract each voiceline as its own set of audio data
            for voice, notes in measure.items():
                for note_number, note in enumerate(notes):
                    octave = note.octave
                    if root_octave is None:
                        root_octave = octave

                    octave_shift = octave - root_octave
                    octave_semitone_shift = 12 * octave_shift

                    alter = note.alter
                    pitch = root_pitch + self.NOTES_TO_SEMITONES[note.note_name] + octave_semitone_shift + note.alter
                    speed = base_speed * (measure_duration / note.duration) / 10
                    
                    file_name = measure_voice_note_wav_file_format.format(processing_dir, measure_number, voice, note_number)
                    self._transform_audio(file, self.SETRATE_FILTER, self.state_manager.get_volume(), speed, pitch, desired_output='wav', output_file=file_name)

                voice_to_note_numbers[voice] = len(notes)

            # Now, concatenate each voice into one file
            for voice, num_notes in voice_to_note_numbers.items():
                files = [measure_voice_note_wav_file_format.format(processing_dir, measure_number, voice, n) for n in range(0, num_notes)]
                command = ["sox"]
                [command.append(f) for f in files]
                command.append(measure_voice_wav_file_format.format(processing_dir, measure_number, voice))

                sp.Popen(command)

            measure_voice_files = [measure_voice_wav_file_format.format(processing_dir, measure_number, v) for v in list(voice_to_note_numbers.keys())]

            amix_command = ["ffmpeg"]
            for mvf in measure_voice_files:
                amix_command.append("-i")
                amix_command.append(mvf)
            amix_command.append("-y")
            amix_command.append("-filter_complex")
            amix_command.append("amix=inputs={0}:duration=longest".format(len(measure_voice_files)))

            measure_file = measure_wav_file_format.format(processing_dir, measure_number)
            amix_command.append(measure_file)
            sp.Popen(amix_command)
            measure_files.append(measure_file)

        for mf in measure_files:
            pcm = self._transform_audio(mf, self.RESAMPLE_FILTER, 1, 1, 1, desired_output='pcm')
            self.mumble.sound_output.add_sound(pcm)

    def _transform_audio(self, file, pitch_filter, volume, speed, shift, desired_output='pcm', output_file=None):
        filter = self._generate_filter(pitch_filter, volume, speed, shift)

        if desired_output == 'pcm':
            return self._transform_as_pcm_data(file, filter)
        elif desired_output == 'wav':
            return self._transform_as_wav(file, filter, output_file)

    def _generate_filter(self, pitch_filter, volume, speed, shift):
        shift_resample_multiplier = 2 ** (-shift / 12)
        required_tempo = speed / 2 ** (shift / 12)

        # Api limitations for speed change in range (0.5, 2).
        # Can work around by concatenating speeds together, e.g, atempo=2.0,atempo=2.0 for 4x speed

        if required_tempo < 0.5:
            num_required = 1
            while required_tempo < 0.5:
                num_required = num_required * 2
                required_tempo = math.sqrt(required_tempo)
            required_tempo = round(required_tempo, 2)
            tempo_filter = ",".join(
                ["atempo=" + str(required_tempo) for i in range(0, num_required)]
            )
        elif required_tempo > 2:
            num_required = 1
            while required_tempo > 2:
                num_required = num_required * 2
                required_tempo = math.sqrt(required_tempo)
            required_tempo = round(required_tempo, 2)
            tempo_filter = ",".join(
                ["atempo=" + str(required_tempo) for i in range(0, num_required)]
            )
        else:
            tempo_filter = "".join(["atempo=", str(required_tempo)])

        
        pitch_filter = "".join([pitch_filter, str(shift_resample_multiplier)])
        volume_filter = "".join(["volume=", str(volume)])
        filter = ",".join([tempo_filter, volume_filter, pitch_filter])

        return filter

    def _transform_as_pcm_data(self, file, filter):
        encode_command = "ffmpeg -i {0} -filter_complex {1} -ac 1 -f s16le -".format(file, filter)

        print(encode_command)
        pcm = sp.Popen(
            encode_command.split(" "), stdout=sp.PIPE, stderr=sp.DEVNULL
        ).stdout.read()
        
        return pcm

    def _transform_as_wav(self, input, filter, output):
        filter = "{0},{1}".format(filter, "aresample=48000")
        encode_command = "ffmpeg -i {0} -filter_complex {1} -y {2}".format(input, filter, output)

        p = sp.Popen(encode_command.split(" "))
        p.communicate()


class TextMessageManager(EventManager):
    def __init__(self, mumble_wrapper):
        self.mumble_wrapper = mumble_wrapper
        self.channel_wrapper = None

    def accept(self, event):
        return isinstance(event, TextEvent)

    def dispatch(self, event):
        if isinstance(event, ChannelTextEvent):
            if self.channel_wrapper is None:
                self.channel_wrapper = self.mumble_wrapper.get_channel(
                    event.channel_name
                )
            self.channel_wrapper.send(event.data)

        elif isinstance(event, UserTextEvent):
            event.user.send_text_message(event.data)


class RecordingManager(EventManager):
    def __init__(self, mumble_wrapper, recording_dir=Path(DEFAULT_RECORDING_DIR)):
        self.mumble_wrapper = mumble_wrapper
        self.recording_dir = recording_dir
        self.is_recording = False
        self.files = dict()

    def accept(self, event):
        return isinstance(event, RecordEvent)

    def dispatch(self, event):
        if event.data == "start":
            self._start_recording()
        else:
            self._stop_recording()

    def _start_recording(self):
        now = dt.datetime.now()
        date_format = "%Y%m%d%H%M%S"

        for user_wrapper in self.mumble_wrapper.get_users():
            user_name = user_wrapper.get_name()

            file_name = "".join(
                [user_name, "-mumble-", now.strftime(date_format), ".wav"]
            )
            path = self.recording_dir.joinpath(file_name)

            file = wave.open(path.as_posix(), "wb")
            file.setparams((1, 2, BITRATE, 0, "NONE", "not compressed"))
            self.files[user_name] = file

        self.is_recording = True
        self.mumble_wrapper.set_receive_sound(True)
        self.mumble_wrapper.start_recording()

    def _stop_recording(self):
        self.mumble_wrapper.stop_recording()
        self.mumble_wrapper.set_receive_sound(False)
        self.is_recording = False

        for file in self.files.values():
            file.close()

        self.files = dict()

    def _write(self, name, data):
        self.files[name].writeframes(data)

    def loop(self):
        if self.is_recording:
            for user_wrapper in self.mumble_wrapper.get_users():
                if user_wrapper.is_sound():
                    user_name = user_wrapper.get_name()
                    sound = user_wrapper.get_sound()
                    self._write(user_name, sound.pcm)


class StateManager(EventManager):
    def __init__(self, mongo_interface, audio_clips_dir=Path("audio/")):
        self.mongo_interface = mongo_interface
        self.audio_clips_dir = audio_clips_dir

    def connect(self):
        self.mongo_interface.connect()

    def refresh_state(self):
        self.mongo_interface.refresh()

    def find_audio_clip(self, ref):
        return self.audio_clips_dir.joinpath(self.mongo_interface.get_file_by_ref(ref))

    def get_volume(self):
        return self.mongo_interface.get_volume()
