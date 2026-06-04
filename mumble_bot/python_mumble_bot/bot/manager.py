import audioop
import base64
import datetime as dt
import json
import logging
import os
import subprocess as sp
import threading
import time
import wave
from collections import OrderedDict
from pathlib import Path

import requests
from pmb_core.audio import transform

from python_mumble_bot.bot.constants import (
    BITRATE,
    DEFAULT_RECORDING_DIR,
    MUMBLE_USERNAME,
    NAME,
    ROOT_CHANNEL,
)
from python_mumble_bot.bot.event import (
    AudioEvent,
    ChannelTextEvent,
    ListMusicEvent,
    MusicEvent,
    RecordEvent,
    TextEvent,
    UserTextEvent,
    VocodeEvent,
)
from python_mumble_bot.musicxml.parser import parse_musicxml

MUSIC_XML_DIR = Path("audio/music")
VOCODE_API_URL = "https://mumble.stream/speak_spectrogram"
VOCODE_API_HEADERS = {"Content-Type": "application/json"}

log = logging.getLogger("pmb.mumble")


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
    NOTES_TO_SEMITONES = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}

    RESAMPLE_FILTER = transform.RESAMPLE_FILTER
    SETRATE_FILTER = transform.SETRATE_FILTER

    # Spawning ffmpeg per play costs ~85ms (225ms cold), so cache the decoded
    # PCM. Bounded by total bytes (~10s clip = ~1MB of 48kHz mono PCM).
    PCM_CACHE_MAX_BYTES = 64 * 1024 * 1024

    SAMPLE_RATE = 48000
    # Keep pymumble's output buffer topped to ~this much. Small = snappy
    # interrupts/overlap; large enough to ride out the occasional scheduling gap.
    MIX_TARGET_SECS = 0.04

    def __init__(self, mumble, state_manager):
        self.mumble = mumble
        self.state_manager = state_manager
        self._pcm_cache = OrderedDict()
        self._pcm_cache_bytes = 0

        # Software mixer: pymumble has no notion of overlapping voices (its
        # output is one sequential PCM stream), so we keep our own per-"voice"
        # buffers and feed pymumble a single pre-mixed stream. A voice is
        # {pcm, pos}; the mixer thread sums the active ones each frame.
        self._voices = {}
        self._mix_lock = threading.Lock()
        self._mixer_thread = threading.Thread(
            target=self._mixer_loop, name="pmb-mixer", daemon=True
        )
        self._mixer_thread.start()

    def _frame_bytes(self, so):
        # One packet's worth of mono 16-bit PCM (matches pymumble's chunking).
        channels = getattr(so, "channels", 1) or 1
        return int(self.SAMPLE_RATE * so.get_audio_per_packet()) * 2 * channels

    def _mixer_loop(self):
        while True:
            try:
                self._mix_tick()
            except Exception:
                log.exception("mixer tick failed")
            time.sleep(0.005)

    def _mix_tick(self):
        so = getattr(self.mumble, "sound_output", None)
        if so is None:
            return
        with self._mix_lock:
            if not self._voices:
                return
            frame_bytes = self._frame_bytes(so)
            guard = 0
            # Top the output buffer up to the target, mixing all active voices.
            while (
                self._voices
                and so.get_buffer_size() < self.MIX_TARGET_SECS
                and guard < 25
            ):
                guard += 1
                mixed = None
                finished = []
                for key, v in self._voices.items():
                    chunk = v["pcm"][v["pos"]:v["pos"] + frame_bytes]
                    if not chunk:
                        finished.append(key)
                        continue
                    v["pos"] += len(chunk)
                    if len(chunk) < frame_bytes:  # pad the final partial frame
                        chunk = chunk + b"\x00" * (frame_bytes - len(chunk))
                    mixed = chunk if mixed is None else audioop.add(mixed, chunk, 2)
                for key in finished:
                    del self._voices[key]
                if mixed is None:
                    break
                so.add_sound(mixed)

    def _submit_voice(self, key, pcm, append):
        if not pcm:
            return
        with self._mix_lock:
            v = self._voices.get(key)
            if append and v is not None and v["pos"] < len(v["pcm"]):
                # Concatenate after the not-yet-played remainder (compact the
                # already-played head so the buffer doesn't grow unbounded).
                v["pcm"] = v["pcm"][v["pos"]:] + pcm
                v["pos"] = 0
            else:
                self._voices[key] = {"pcm": pcm, "pos": 0}

    def _get_pcm(self, ref, file, pitch_filter, volume, speed, shift):
        # Cache key includes the file mtime (so a trim/re-upload invalidates it)
        # and every transform param (so pitch/speed/volume changes are distinct).
        try:
            mtime = os.path.getmtime(file)
        except OSError:
            mtime = 0
        key = (
            str(file), round(mtime, 3), pitch_filter,
            round(volume, 3), round(speed, 4), round(shift, 4),
        )
        pcm = self._pcm_cache.get(key)
        if pcm is not None:
            self._pcm_cache.move_to_end(key)  # mark most-recently-used
            return pcm, True

        pcm = transform.transform_audio(
            file, pitch_filter, volume, speed, shift, desired_output="pcm"
        )
        self._pcm_cache[key] = pcm
        self._pcm_cache_bytes += len(pcm)
        while self._pcm_cache_bytes > self.PCM_CACHE_MAX_BYTES and len(self._pcm_cache) > 1:
            _, evicted = self._pcm_cache.popitem(last=False)  # evict oldest
            self._pcm_cache_bytes -= len(evicted)
        return pcm, False

    def accept(self, event):
        return (
            isinstance(event, AudioEvent)
            or isinstance(event, MusicEvent)
            or isinstance(event, VocodeEvent)
        )

    def dispatch(self, event):
        if isinstance(event, AudioEvent):
            self._play_clips(event, self.RESAMPLE_FILTER)
        elif isinstance(event, VocodeEvent):
            self._process_vocode_event(event)
        elif isinstance(event, MusicEvent):
            self._play_music(event)

    def _process_vocode_event(self, event):
        file = "/tmp/vocode.wav"

        data = json.dumps({"text": event.words, "speaker": event.speaker})

        response = requests.post(VOCODE_API_URL, headers=VOCODE_API_HEADERS, data=data)

        encoded_base64 = response.json()["audio_base64"]
        wav = base64.b64decode(encoded_base64)

        f = open(file, "wb")
        f.write(wav)
        f.close()

        pcm = transform.transform_audio(
            file,
            self.RESAMPLE_FILTER,
            self.state_manager.get_volume(),
            1,
            0,
            desired_output="pcm",
        )

        with open("/tmp/vocode.pcm", "wb") as f:
            f.write(pcm)

        self._play_sound(pcm)

    def _play_clips(self, event, pitch_filter):
        key = event.voice_key or "default"
        segment = b""
        for ref, speed, shift in zip(
            event.data, event.playback_speeds, event.semitone_shifts
        ):
            file = self.state_manager.find_audio_clip(ref)
            gain = transform.gain_db_to_multiplier(
                self.state_manager.get_clip_gain_db(ref)
            )
            volume = self.state_manager.get_volume() * gain
            t0 = time.monotonic()
            pcm, cached = self._get_pcm(
                ref, file, pitch_filter, volume, float(speed[:-1]), float(shift[:-1])
            )
            segment += pcm
            log.info(
                "[timing] %s %s=%.0fms pcm=%dKiB cache=%dMiB voice=%s",
                ref,
                "cache" if cached else "ffmpeg",
                (time.monotonic() - t0) * 1000,
                len(pcm) // 1024,
                self._pcm_cache_bytes // (1024 * 1024),
                key,
            )
        # Replace this voice (interrupt/restart) for single web plays; append for
        # queues / legacy events so they stay sequential.
        self._submit_voice(key, segment, event.append)

    def _play_music(self, event):
        piece = "audio/music/{0}".format(event.piece)
        processing_dir = "audio/music_processing/{0}".format(event.piece)
        output_file = "audio/music_processing/{0}.wav".format(event.piece)
        clip = event.data
        base_speed = event.speed
        root_pitch = event.root_pitch
        volume = event.volume

        measure_limit = None if event.measure_limit is None else event.measure_limit - 1

        file = self.state_manager.find_audio_clip(clip)

        measures = parse_musicxml("{0}.xml".format(piece))

        measure_duration = measures["measure_length"]

        # Now, in each measures, concatenate the pcm data for
        # each voice. If there are rests for the voices,
        # then these must be filled in with blank data.
        measure_voice_note_wav_file_format = "{0}_measure{1}_voice{2}_note{3}.wav"
        measure_voice_wav_file_format = "{0}_measure{1}_voice{2}.wav"
        measure_wav_file_format = "{0}_measure{1}.wav"

        measure_files = []
        root_octave = None

        for measure_number, measure in enumerate(measures["measures"]):
            if measure_limit is not None and measure_number > measure_limit:
                break

            voice_to_note_numbers = {}

            # Extract each voiceline as its own set of audio data
            for voice, notes in measure.items():
                if notes == []:  # entire voiceline is at rest for the measure
                    continue

                for note_number, note in enumerate(notes):
                    octave = note.octave
                    alter = note.alter
                    note_name = note.note_name
                    speed = base_speed * (measure_duration / note.duration) / 10

                    if note_name == "rest":
                        pitch = 0
                        note_volume = 0

                    else:
                        if root_octave is None:
                            root_octave = octave

                        octave_shift = octave - root_octave
                        octave_semitone_shift = 12 * octave_shift

                        pitch = (
                            root_pitch
                            + self.NOTES_TO_SEMITONES[note_name]
                            + octave_semitone_shift
                            + alter
                        )
                        note_volume = self.state_manager.get_volume()

                    file_name = measure_voice_note_wav_file_format.format(
                        processing_dir, measure_number, voice, note_number
                    )
                    transform.transform_audio(
                        file,
                        self.SETRATE_FILTER,
                        note_volume,
                        speed,
                        pitch,
                        desired_output="wav",
                        output_file=file_name,
                    )

                voice_to_note_numbers[voice] = len(notes)

            # Now, concatenate each voice into one file
            for voice, num_notes in voice_to_note_numbers.items():
                files = [
                    measure_voice_note_wav_file_format.format(
                        processing_dir, measure_number, voice, n
                    )
                    for n in range(0, num_notes)
                ]
                command = self._concatenate_wav_inputs(files)
                command.append(
                    measure_voice_wav_file_format.format(
                        processing_dir, measure_number, voice
                    )
                )

                p = sp.Popen(command, stderr=sp.DEVNULL)
                p.communicate()

            measure_voice_files = [
                measure_voice_wav_file_format.format(processing_dir, measure_number, v)
                for v in list(voice_to_note_numbers.keys())
            ]

            amix_command = ["ffmpeg"]
            for mvf in measure_voice_files:
                amix_command.append("-i")
                amix_command.append(mvf)
            amix_command.append("-y")
            amix_command.append("-filter_complex")

            # Normalise downmixed audio; when downmixing, volume of each input is set to 1/N where N is number of inputs, so increase volume of each by N
            amix_command.append(
                "amix=inputs={0}:duration=longest,volume={1}".format(
                    len(measure_voice_files), len(measure_voice_files)
                )
            )
            # amix_command.append("amix=inputs={0}:duration=longest".format(len(measure_voice_files)))
            # amix_command.append(
            #     "amix=inputs={0}:duration=longest:dropout_transition=0,dynaudnorm,volume={1}".format(
            #         len(measure_voice_files), math.ceil(len(measure_voice_files) / 2)
            #     )
            # )
            # amix_command.append("amix=inputs={0}:duration=longest:dropout_transition=0,dynaudnorm".format(len(measure_voice_files)))

            measure_file = measure_wav_file_format.format(
                processing_dir, measure_number
            )
            amix_command.append(measure_file)

            p = sp.Popen(amix_command, stderr=sp.DEVNULL)
            p.communicate()

            # p = sp.Popen(["ffmpeg-normalize", measure_file, "-o", measure_file, "-f" ])
            measure_files.append(measure_file)

        command = self._concatenate_wav_inputs(measure_files)
        command.append(output_file)

        p = sp.Popen(command, stderr=sp.DEVNULL)
        p.communicate()

        final_file_name = "final.wav"
        parts = output_file.split("/")
        parts[-1] = final_file_name
        final_file = "/".join(parts)

        command = [
            "ffmpeg",
            "-i",
            output_file,
            "-af",
            "loudnorm=I=-24:LRA=11:TP=-1.5",
            final_file,
            "-y",
        ]
        p = sp.Popen(command)
        p.communicate()

        print(command)
        print("done")

        pcm = transform.transform_audio(
            output_file, self.RESAMPLE_FILTER, volume, 1, 1, desired_output="pcm"
        )
        self._play_sound(pcm)

    def _play_sound(self, pcm):
        # Vocode / music render straight to PCM; play them through the mixer on
        # a shared system voice (appending so multi-part renders stay sequential).
        self._submit_voice("__system__", pcm, append=True)

    def stop(self):
        """Panic-stop: drop every active voice and flush the output buffer."""
        with self._mix_lock:
            self._voices.clear()
        try:
            self.mumble.sound_output.clear_buffer()
        except Exception:
            pass

    @staticmethod
    def _concatenate_wav_inputs(files):
        command = ["sox"]
        [command.append(f) for f in files]
        return command


class TextMessageManager(EventManager):
    def __init__(self, mumble_wrapper):
        self.mumble_wrapper = mumble_wrapper
        self.channel_wrapper = None

    def accept(self, event):
        return isinstance(event, TextEvent)

    def dispatch(self, event):
        if isinstance(event, ChannelTextEvent):
            self._set_channel_wrapper(event.channel_name)
            self.channel_wrapper.send(event.data)

        elif isinstance(event, UserTextEvent):
            event.user.send_text_message(event.data)

        elif isinstance(event, ListMusicEvent):
            songs = [s.split(".")[0] for s in os.listdir("audio/music")]
            songs.sort()

            self._set_channel_wrapper()
            self.channel_wrapper.send(
                "The following songs are available: <br>" + ",<br>".join(songs)
            )

    def _set_channel_wrapper(self, channel_name=os.getenv(ROOT_CHANNEL)):
        if self.channel_wrapper is None:
            self.channel_wrapper = self.mumble_wrapper.get_channel(channel_name)


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

        self.is_recording = True
        self.mumble_wrapper.set_receive_sound(True)
        self.mumble_wrapper.start_recording()

        for user_wrapper in self.mumble_wrapper.get_users():
            user_name = user_wrapper.get_name()

            file_name = "".join(
                [user_name, "-mumble-", now.strftime(date_format), ".wav"]
            )
            path = self.recording_dir.joinpath(file_name)

            file = wave.open(path.as_posix(), "wb")
            file.setparams((1, 2, BITRATE, 0, "NONE", "not compressed"))
            self.files[user_name] = file

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


class CommandManager(EventManager):
    POLL_INTERVAL = 0.02

    def __init__(self, mongo_interface, playback_manager, text_message_manager):
        self.mongo_interface = mongo_interface
        self.playback_manager = playback_manager
        self.text_message_manager = text_message_manager
        self._last_poll = 0

    def loop(self):
        now = time.time()
        if now - self._last_poll < self.POLL_INTERVAL:
            return
        self._last_poll = now

        command = self.mongo_interface.get_next_pending_command()
        if command is None:
            return

        self.mongo_interface.mark_command_done(command["_id"])
        cmd_type = command.get("type", "play")

        # How long the command sat between the web enqueuing it and the bot
        # picking it up (bounded below by the 0.1s poll interval).
        created = command.get("created_at")
        if isinstance(created, dt.datetime):
            waited = (dt.datetime.utcnow() - created).total_seconds() * 1000
            log.info(
                "[timing] picked up %s %s after %.0fms in queue",
                cmd_type,
                command.get("clip_ref", ""),
                waited,
            )

        if cmd_type == "announce":
            self.text_message_manager.process(ChannelTextEvent(command["message"]))
            return

        if cmd_type == "stop":
            self.playback_manager.stop()
            return

        if cmd_type == "restart":
            # The command is already marked done above, so exiting is safe — no
            # restart loop. Docker (restart: unless-stopped) brings the bot back
            # and it reconnects to its channel on startup.
            self.text_message_manager.process(
                ChannelTextEvent(
                    f"<b>{command.get('requested_by', 'web')}</b> restarted the bot"
                )
            )
            os._exit(0)

        speed = command.get("speed", 1.0)
        pitch = command.get("pitch", 0)

        if cmd_type == "play":
            clip_name = command.get("clip_name") or command["clip_ref"]
            cmd_str = f"/pp {speed:g}x {pitch}s {clip_name}"
            msg = f"<b>{command['requested_by']}</b> played: {cmd_str}"
            self.text_message_manager.process(ChannelTextEvent(msg))

        if cmd_type == "queue_play":
            # Queues stay sequential on a shared voice (can overlap live presses).
            voice_key, append = "__queue__", True
        else:
            # Single plays key by requester: spamming interrupts your own clip,
            # while different people overlap.
            voice_key, append = (command.get("requested_by") or "web"), False

        event = AudioEvent(
            [command["clip_ref"]],
            [f"{speed}x"],
            [f"{pitch}s"],
            voice_key=voice_key,
            append=append,
        )
        self.playback_manager.process(event)


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

    def get_clip_gain_db(self, ref):
        return self.mongo_interface.get_gain_db_by_ref(ref)

    def get_volume(self):
        return self.mongo_interface.get_volume()


class VoiceStateManager(EventManager):
    """Publishes who is currently in the bot's channel into `voice_state`.

    Mirrors the Discord bot's voice_state doc so the shared web app can gate
    playback on presence. In Mumble the user's identity is their username, so
    each member is published as {id: name, name: name}.
    """

    POLL_INTERVAL = 2.0

    def __init__(self, mumble, mongo_interface):
        self.mumble = mumble
        self.mongo_interface = mongo_interface
        self._last_poll = 0

    def loop(self):
        now = time.time()
        if now - self._last_poll < self.POLL_INTERVAL:
            return
        self._last_poll = now
        self._publish()

    def _publish(self):
        try:
            my_channel = self.mumble.my_channel()
            channel_id = my_channel["channel_id"]
            channel_name = my_channel.get("name", str(channel_id))
        except Exception:
            return

        bot_name = os.getenv(MUMBLE_USERNAME)
        members = []
        for session in list(self.mumble.users):
            user = self.mumble.users[session]
            try:
                if user["channel_id"] != channel_id:
                    continue
                name = user[NAME]
            except Exception:
                continue
            if name == bot_name:
                continue
            members.append({"id": name, "name": name})

        channels = [
            {
                "id": str(channel_id),
                "name": channel_name,
                "users": len(members),
                "members": members,
            }
        ]
        try:
            self.mongo_interface.db.voice_state.update_one(
                {"_id": "state"},
                {
                    "$set": {
                        "channels": channels,
                        "current_channel_id": str(channel_id),
                        "present": members,
                    }
                },
                upsert=True,
            )
        except Exception:
            pass
