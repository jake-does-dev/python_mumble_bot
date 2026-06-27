import audioop
import base64
import datetime as dt
import json
import logging
import os
import re
import statistics
import subprocess as sp
import threading
import time
import wave
from collections import OrderedDict, deque
from pathlib import Path

import requests
from pmb_core.audio import transform
from pmb_core.audio.midi import parse_midi

from python_mumble_bot.bot.constants import (
    MUMBLE_USERNAME,
    NAME,
    ROOT_CHANNEL,
)
from python_mumble_bot.bot.event import (
    AudioEvent,
    CaptureEvent,
    ChannelTextEvent,
    ListMusicEvent,
    MidiSongEvent,
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

    # MIDI-song ("jukebox") render: clamp pitch shift to ±2 octaves, floor each
    # note so short notes still pop, and loudness-normalise the assembled mix.
    SONG_MAX_SEMITONE_SHIFT = 24
    SONG_MIN_NOTE_SECONDS = 0.08
    SONG_LOUDNORM = "loudnorm=I=-16:TP=-1.5:LRA=11"

    # Songs play on their own mixer voice, serialised one-at-a-time by the song
    # worker (a "now playing" + upcoming-queue mini-player, mirrored to the
    # shared `song_state` doc so the web can show it — same as the Discord bot).
    SONG_VOICE = "__song__"

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

        # Song queue: pending MidiSongEvents + the one currently playing. The
        # worker thread drains them one at a time so songs never overlap, and
        # mirrors the now-playing + queue to the `song_state` doc for the web.
        self._song_pending = []
        self._song_current = None  # dict the web renders, or None when idle
        self._song_lock = threading.Lock()
        self._skip_flag = threading.Event()
        self._song_state_clean = False  # cleared stale state on startup yet?
        self._song_worker_thread = threading.Thread(
            target=self._song_worker_loop, name="pmb-song-worker", daemon=True
        )
        self._song_worker_thread.start()

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
                    chunk = v["pcm"][v["pos"] : v["pos"] + frame_bytes]
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
                v["pcm"] = v["pcm"][v["pos"] :] + pcm
                v["pos"] = 0
            else:
                self._voices[key] = {"pcm": pcm, "pos": 0}

    def _get_pcm(self, ref, file, pitch_filter, volume, speed, shift, reverse=False):
        # Cache key includes the file mtime (so a trim/re-upload invalidates it)
        # and every transform param (so pitch/speed/volume/reverse changes are distinct).
        try:
            mtime = os.path.getmtime(file)
        except OSError:
            mtime = 0
        key = (
            str(file),
            round(mtime, 3),
            pitch_filter,
            round(volume, 3),
            round(speed, 4),
            round(shift, 4),
            reverse,
        )
        pcm = self._pcm_cache.get(key)
        if pcm is not None:
            self._pcm_cache.move_to_end(key)  # mark most-recently-used
            return pcm, True

        pcm = transform.transform_audio(
            file,
            pitch_filter,
            volume,
            speed,
            shift,
            desired_output="pcm",
            reverse=reverse,
        )
        self._pcm_cache[key] = pcm
        self._pcm_cache_bytes += len(pcm)
        while (
            self._pcm_cache_bytes > self.PCM_CACHE_MAX_BYTES
            and len(self._pcm_cache) > 1
        ):
            _, evicted = self._pcm_cache.popitem(last=False)  # evict oldest
            self._pcm_cache_bytes -= len(evicted)
        return pcm, False

    def accept(self, event):
        return (
            isinstance(event, AudioEvent)
            or isinstance(event, MusicEvent)
            or isinstance(event, MidiSongEvent)
            or isinstance(event, VocodeEvent)
        )

    def dispatch(self, event):
        if isinstance(event, AudioEvent):
            self._play_clips(event, self.RESAMPLE_FILTER)
        elif isinstance(event, VocodeEvent):
            self._process_vocode_event(event)
        elif isinstance(event, MidiSongEvent):
            self.enqueue_song(event)
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
        reverses = event.reverses or [False] * len(event.data)
        for ref, speed, shift, reverse in zip(
            event.data, event.playback_speeds, event.semitone_shifts, reverses
        ):
            file = self.state_manager.find_audio_clip(ref)
            gain = transform.gain_db_to_multiplier(
                self.state_manager.get_clip_gain_db(ref)
            )
            volume = self.state_manager.get_volume() * gain
            t0 = time.monotonic()
            pcm, cached = self._get_pcm(
                ref,
                file,
                pitch_filter,
                volume,
                float(speed[:-1]),
                float(shift[:-1]),
                reverse,
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

    def _render_midi_song(self, event):
        """Render a MIDI song into one mono PCM buffer using a clip as the
        instrument. Returns (pcm_bytes, duration_seconds), or (None, 0.0) if
        there's nothing to play.

        Each note triggers the clip pitch-shifted to that note's pitch (relative
        to the song's median, so shifts stay small), laid onto a silent canvas at
        its onset and capped to its duration. Overlapping notes (chords) mix via
        audioop.add. `max_seconds` (0 = full) caps the output length.
        """
        song_path = "audio/music/{0}".format(event.song_file)
        file = self.state_manager.find_audio_clip(event.clip_ref)
        try:
            notes, _duration = parse_midi(song_path)
        except Exception:
            log.exception("song: failed to parse %s", song_path)
            return None, 0.0
        if not notes:
            log.warning("song: %s has no notes", song_path)
            return None, 0.0

        sr = self.SAMPLE_RATE
        bpf = 2  # mono 16-bit
        speed = max(0.25, min(4.0, float(event.speed or 1.0)))
        transpose = int(event.transpose or 0)
        root = int(statistics.median(n.pitch for n in notes))
        limit_bytes = int(max(0.0, event.max_seconds or 0.0) * sr) * bpf  # 0 = no limit
        max_shift = self.SONG_MAX_SEMITONE_SHIFT

        def shift_for(note):
            return max(-max_shift, min(max_shift, note.pitch - root + transpose))

        # Render each distinct pitch-shift once (reuses the PCM cache).
        shift_pcm = {}
        for n in notes:
            if limit_bytes and int((n.start / speed) * sr) * bpf >= limit_bytes:
                continue
            shift = shift_for(n)
            if shift not in shift_pcm:
                pcm, _hit = self._get_pcm(
                    event.clip_ref, file, self.RESAMPLE_FILTER, 1.0, 1.0, shift
                )
                shift_pcm[shift] = pcm

        min_note_bytes = int(self.SONG_MIN_NOTE_SECONDS * sr) * bpf
        placements = []
        max_end = 0
        for n in notes:
            offset = int((n.start / speed) * sr) * bpf
            if limit_bytes and offset >= limit_bytes:
                continue
            pcm = shift_pcm.get(shift_for(n)) or b""
            if not pcm:
                continue
            cap = max(min_note_bytes, int((n.duration / speed) * sr) * bpf)
            seg = pcm[:cap]
            if limit_bytes:
                seg = seg[: limit_bytes - offset]  # don't ring past the cap
            if not seg:
                continue
            placements.append((offset, seg))
            max_end = max(max_end, offset + len(seg))

        if max_end == 0:
            return None, 0.0

        canvas = bytearray(max_end)
        for i, (offset, seg) in enumerate(placements):
            region = bytes(canvas[offset : offset + len(seg)])
            if len(region) < len(seg):
                seg = seg[: len(region)]
            if not seg:
                continue
            mixed = audioop.add(region, seg, 2)
            canvas[offset : offset + len(mixed)] = mixed
            # audioop holds the GIL; yield every few notes so the mixer thread
            # (5ms/tick) isn't starved during a long render → no stutter.
            if i % 8 == 7:
                time.sleep(0.001)

        gain_db = (self.state_manager.get_clip_gain_db(event.clip_ref) or 0) + (
            event.gain or 0
        )
        volume = self.state_manager.get_volume() * transform.gain_db_to_multiplier(
            gain_db
        )
        log.info(
            "[song] %s on %s: %d notes, %d shifts, %.1fs",
            event.song_file,
            event.clip_ref,
            len(notes),
            len(shift_pcm),
            len(canvas) / (sr * bpf),
        )
        pcm = self._finalize_song_pcm(bytes(canvas), volume)
        duration = len(pcm) / (sr * bpf)
        return pcm, duration

    def _finalize_song_pcm(self, pcm, volume):
        """Loudness-normalise the assembled mono canvas, apply the overall
        volume, and fade the last 30ms out (clean end, no click when the cap
        truncates a sound). Falls back to a plain volume scale if ffmpeg fails."""
        sr = self.SAMPLE_RATE
        dur = len(pcm) / (sr * 2)
        fade = min(0.03, dur)
        audio_filter = "{0},volume={1},afade=t=out:st={2:.3f}:d={3:.3f}".format(
            self.SONG_LOUDNORM, volume, max(0.0, dur - fade), fade
        )
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "s16le",
            "-ar",
            str(sr),
            "-ac",
            "1",
            "-i",
            "pipe:0",
            "-af",
            audio_filter,
            "-f",
            "s16le",
            "-ar",
            str(sr),
            "-ac",
            "1",
            "pipe:1",
        ]
        proc = sp.run(cmd, input=pcm, stdout=sp.PIPE, stderr=sp.PIPE)
        if proc.returncode == 0 and proc.stdout:
            return proc.stdout
        log.warning(
            "song: finalize failed (%s), using raw mix", proc.stderr.decode()[:200]
        )
        return audioop.mul(pcm, 2, volume)

    # -- song queue (now-playing + upcoming + skip) ------------------------

    def enqueue_song(self, event):
        """Queue a MIDI song; the worker plays it after any already in flight."""
        with self._song_lock:
            self._song_pending.append(event)
        self._publish_song_state()

    def skip_song(self):
        """Skip the song currently playing — the worker advances to the next."""
        self._skip_flag.set()

    def _drop_voice(self, key):
        with self._mix_lock:
            self._voices.pop(key, None)

    def _publish_song_state(self):
        """Mirror current + upcoming queue to the `song_state` singleton so the
        web shows a now-playing mini-player. Returns True on success. Guarded so
        it's a no-op (not a crash) before mongo is connected."""
        with self._song_lock:
            current = dict(self._song_current) if self._song_current else None
            queue = [
                {
                    "song_name": e.song_name,
                    "clip_name": e.clip_name,
                    "requested_by": e.requested_by,
                }
                for e in self._song_pending
            ]
        try:
            self.state_manager.mongo_interface.db.song_state.replace_one(
                {"_id": "singleton"},
                {
                    "_id": "singleton",
                    "current": current,
                    "queue": queue,
                    "updated_at": dt.datetime.utcnow(),
                },
                upsert=True,
            )
            return True
        except Exception:
            return False

    def _song_worker_loop(self):
        """Drain the song queue one at a time so songs never overlap."""
        while True:
            try:
                with self._song_lock:
                    event = self._song_pending.pop(0) if self._song_pending else None
                if event is None:
                    # Clear any stale now-playing left by a previous run, once
                    # mongo is reachable, then idle.
                    if not self._song_state_clean and self._publish_song_state():
                        self._song_state_clean = True
                    time.sleep(0.05)
                    continue
                self._play_one_song(event)
            except Exception:
                log.exception("song worker: tick failed")
                time.sleep(0.1)

    def _play_one_song(self, event):
        """Render one song and play it to completion (or until skipped)."""
        pcm, duration = self._render_midi_song(event)
        if not pcm:
            return
        with self._song_lock:
            self._song_current = {
                "song_name": event.song_name,
                "clip_name": event.clip_name,
                "requested_by": event.requested_by or "web",
                "started_at": dt.datetime.utcnow(),
                "duration_s": round(duration, 2),
            }
        self._skip_flag.clear()
        self._publish_song_state()
        # Own mixer voice, replacing (not appending) — the worker serialises, so
        # there's never more than one song voice at a time.
        self._submit_voice(self.SONG_VOICE, pcm, append=False)
        try:
            # The audio plays in real time over `duration`; wait that long (plus
            # a little for pymumble's buffer tail) unless skipped.
            deadline = time.monotonic() + duration + 0.2
            while time.monotonic() < deadline:
                if self._skip_flag.is_set():
                    log.info("song skipped: %s", event.song_name)
                    break
                time.sleep(0.05)
        finally:
            self._drop_voice(self.SONG_VOICE)  # cut it now (no-op if finished)
            self._skip_flag.clear()
            with self._song_lock:
                self._song_current = None
            self._publish_song_state()

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
        """Panic-stop: drop the song queue + every active voice, flush output."""
        with self._song_lock:
            self._song_pending.clear()
            self._song_current = None
        self._skip_flag.set()  # break the current song's wait loop, if any
        with self._mix_lock:
            self._voices.clear()
        try:
            self.mumble.sound_output.clear_buffer()
        except Exception:
            pass
        self._publish_song_state()

    # -- channel move (web "join a different channel" / "leave") -----------

    def join_channel(self, channel_id):
        """Move the bot ("summon" it) into the given channel. Mumble bots are
        always in a channel, so this is a move rather than a connect."""
        if channel_id is None:
            return
        try:
            self.mumble.channels[int(channel_id)].move_in()
            log.info("Moved to channel %s", channel_id)
        except Exception:
            log.exception("Failed to move to channel %s", channel_id)

    def leave_channel(self):
        """Mumble has no "disconnect from voice"; return to the home/root
        channel (closest equivalent to Discord's leave). Uses
        MUMBLE_SERVER_ROOT_CHANNEL if set, else the server root (id 0)."""
        try:
            root_name = os.getenv(ROOT_CHANNEL)
            if root_name:
                self.mumble.channels.find_by_name(root_name).move_in()
            else:
                self.mumble.channels[0].move_in()
            log.info("Returned to root channel")
        except Exception:
            log.exception("Failed to return to root channel")

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


class CaptureManager(EventManager):
    """The single sink for received audio.

    pymumble decodes every speaker's Opus stream into a per-user ``SoundChunk``
    (48 kHz mono int16). We register one ``PYMUMBLE_CLBK_SOUNDRECEIVED`` callback
    (``on_sound``) and from it:

      * keep a rolling per-user PCM buffer (the last ``BUFFER_SECONDS``) so the web
        UI can "clip that" — dump a chosen person's recent voice into a clip; and
      * when ``/pmb record`` is active, also write the per-user WAVs.

    Registering that callback stops pymumble filling the per-user ``sound`` queues,
    so this manager must be the *only* consumer of received audio (it therefore
    absorbs the old polling RecordingManager).

    Privacy: the rolling buffer only ever holds people who have **opted in** (via
    the web UI). Everyone else's audio is dropped the instant it arrives — never
    buffered. ``/record`` is a separate, deliberate, announced action and still
    captures everyone present.
    """

    BUFFER_SECONDS = 30
    SAMPLE_RATE = 48000  # pymumble decodes to 48 kHz mono int16
    OPTIN_REFRESH_SECS = 5  # how often to re-read consent from the DB

    def __init__(
        self,
        mumble_wrapper,
        mongo_interface,
        text_message_manager=None,
        captures_dir=Path("audio/captures"),
        recording_dir=Path("audio/recordings"),
    ):
        self.mumble_wrapper = mumble_wrapper
        self.mongo_interface = mongo_interface
        self.text_message_manager = text_message_manager
        self.captures_dir = captures_dir
        self.recording_dir = recording_dir
        self._lock = threading.Lock()
        self._buffers = {}  # user name -> deque[(chunk.time, pcm bytes)]
        self._optin = set()  # voice_ids consenting to be clipped
        self._optin_at = 0.0
        self.is_recording = False
        self._record_files = {}
        self._record_stamp = None

    # ---- audio sink (runs on pymumble's network thread) --------------------
    def on_sound(self, user, chunk):
        if chunk is None or not chunk.pcm:
            return
        name = user[NAME]
        with self._lock:
            # /record captures everyone present (deliberate, announced action).
            if self.is_recording:
                self._write_recording(name, chunk.pcm)
            # The rolling "clip that" buffer only holds opted-in users — everyone
            # else's audio is dropped right here and never stored.
            if name not in self._optin:
                return
            buf = self._buffers.get(name)
            if buf is None:
                buf = deque()
                self._buffers[name] = buf
            buf.append((chunk.time, chunk.pcm))
            cutoff = chunk.time - self.BUFFER_SECONDS
            while buf and buf[0][0] < cutoff:
                buf.popleft()

    # ---- consent ------------------------------------------------------------
    def loop(self):
        now = time.monotonic()
        if now - self._optin_at < self.OPTIN_REFRESH_SECS:
            return
        self._optin_at = now
        self._refresh_optin()

    def _refresh_optin(self):
        try:
            docs = self.mongo_interface.db.users.find(
                {"capture_optin": True, "voice_id": {"$ne": None}},
                {"voice_id": 1},
            )
            optin = {d.get("voice_id") for d in docs if d.get("voice_id")}
        except Exception:
            return
        with self._lock:
            self._optin = optin
            # Someone who just opted out should have their buffered audio purged
            # immediately, not linger for up to BUFFER_SECONDS.
            for name in [n for n in self._buffers if n not in optin]:
                del self._buffers[name]

    def clear_optin(self):
        """Wipe everyone's capture consent. Consent is session-scoped: it's
        cleared when the bot leaves/joins a channel (and at startup), so everyone
        must opt in again for each channel session. Returns how many were cleared."""
        try:
            res = self.mongo_interface.db.users.update_many(
                {"capture_optin": True}, {"$set": {"capture_optin": False}}
            )
            cleared = res.modified_count
        except Exception:
            log.exception("Failed to clear capture opt-ins")
            return 0
        with self._lock:
            self._optin = set()
            self._buffers.clear()
        if cleared:
            log.info("Capture consent reset: cleared %d opt-in(s)", cleared)
        return cleared

    # ---- events ------------------------------------------------------------
    def accept(self, event):
        return isinstance(event, (RecordEvent, CaptureEvent))

    def dispatch(self, event):
        if isinstance(event, RecordEvent):
            if event.data == "start":
                self._start_recording()
            else:
                self._stop_recording()
        elif isinstance(event, CaptureEvent):
            self._capture(event)

    # ---- "clip that" -------------------------------------------------------
    def _capture(self, event):
        target = event.target
        duration = max(
            1.0, min(float(event.duration or self.BUFFER_SECONDS), self.BUFFER_SECONDS)
        )
        with self._lock:
            opted = target in self._optin
            chunks = list(self._buffers.get(target, ())) if opted else []
        if not opted:
            self._announce(
                "<b>{0}</b> hasn't opted in to being clipped.".format(target)
            )
            return
        pcm = self._render_window(chunks, duration) if chunks else b""
        if not pcm:
            self._announce(
                "Nothing to clip for <b>{0}</b> (no recent audio)".format(target)
            )
            return

        self.captures_dir.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.utcnow().strftime("%Y%m%d%H%M%S")
        safe = re.sub(r"[^A-Za-z0-9_-]", "_", target) or "user"
        filename = "cap_{0}_{1}.wav".format(stamp, safe)
        path = self.captures_dir.joinpath(filename)
        with wave.open(path.as_posix(), "wb") as f:
            f.setparams((1, 2, self.SAMPLE_RATE, 0, "NONE", "not compressed"))
            f.writeframes(pcm)

        duration_s = round(len(pcm) / 2 / self.SAMPLE_RATE, 2)
        try:
            self.mongo_interface.db.pending_clips.insert_one(
                {
                    "target_voice": target,
                    "requested_by": event.requested_by,
                    "duration_s": duration_s,
                    "file": "captures/" + filename,
                    "created_at": dt.datetime.utcnow(),
                    "status": "pending",
                }
            )
        except Exception:
            log.exception("failed to store pending capture for %s", target)
            return

        self._announce(
            "<b>{0}</b> clipped the last {1:g}s of <b>{2}</b> — review it in the "
            "web UI".format(event.requested_by or "web", duration_s, target)
        )

    def _render_window(self, chunks, duration):
        """Lay the recent chunks onto a silence-filled canvas (so pauses are kept
        as real silence), take the last ``duration`` seconds, then strip the outer
        silence. Returns raw 48 kHz mono int16 PCM bytes."""
        last_time, last_pcm = chunks[-1]
        end = last_time + len(last_pcm) / 2 / self.SAMPLE_RATE
        start = end - duration
        canvas = bytearray(int(round(duration * self.SAMPLE_RATE)) * 2)

        for ctime, pcm in chunks:
            data = pcm
            offset = int(round((ctime - start) * self.SAMPLE_RATE))
            if offset < 0:
                # chunk began before the window — drop its leading part
                data = data[(-offset) * 2 :]
                offset = 0
            byte_off = offset * 2
            if byte_off >= len(canvas) or not data:
                continue
            data = data[: len(canvas) - byte_off]
            canvas[byte_off : byte_off + len(data)] = data

        # Trim leading/trailing silence, keeping int16 sample alignment. lstrip/
        # rstrip work byte-wise, so round the trimmed counts down to even bytes to
        # avoid splitting a sample whose other byte happens to be zero.
        left = len(canvas) - len(canvas.lstrip(b"\x00"))
        left -= left % 2
        canvas = canvas[left:]
        right = len(canvas) - len(canvas.rstrip(b"\x00"))
        right -= right % 2
        if right:
            canvas = canvas[:-right]
        return bytes(canvas)

    # ---- recording ---------------------------------------------------------
    def _start_recording(self):
        self.recording_dir.mkdir(parents=True, exist_ok=True)
        self.mumble_wrapper.start_recording()  # flags the bot as recording (UI)
        with self._lock:
            self._record_stamp = dt.datetime.now().strftime("%Y%m%d%H%M%S")
            self._record_files = {}
            self.is_recording = True

    def _stop_recording(self):
        with self._lock:
            self.is_recording = False
            files = self._record_files
            self._record_files = {}
        self.mumble_wrapper.stop_recording()
        for f in files.values():
            f.close()

    def _write_recording(self, name, pcm):
        # Called under self._lock from on_sound. Files are opened lazily so a user
        # who joins mid-recording still gets captured.
        f = self._record_files.get(name)
        if f is None:
            file_name = "{0}-mumble-{1}.wav".format(name, self._record_stamp)
            f = wave.open(self.recording_dir.joinpath(file_name).as_posix(), "wb")
            f.setparams((1, 2, self.SAMPLE_RATE, 0, "NONE", "not compressed"))
            self._record_files[name] = f
        f.writeframes(pcm)

    def _announce(self, message):
        if self.text_message_manager is None:
            return
        try:
            self.text_message_manager.process(ChannelTextEvent(message))
        except Exception:
            log.exception("capture announce failed")


class CommandManager(EventManager):
    POLL_INTERVAL = 0.02

    def __init__(
        self,
        mongo_interface,
        playback_manager,
        text_message_manager,
        capture_manager=None,
    ):
        self.mongo_interface = mongo_interface
        self.playback_manager = playback_manager
        self.text_message_manager = text_message_manager
        self.capture_manager = capture_manager
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

        if cmd_type == "play_song":
            # A MIDI song played with a clip as the instrument. The announce is a
            # separate command (see enqueue_song), so just queue it; the song
            # worker serialises playback and mirrors now-playing to the web.
            self.playback_manager.process(
                MidiSongEvent(
                    clip_ref=command["clip_ref"],
                    song_file=command["song"],
                    transpose=command.get("transpose", 0),
                    speed=command.get("speed", 1.0),
                    gain=command.get("gain", 0),
                    max_seconds=command.get("max_seconds", 0),
                    requested_by=command.get("requested_by"),
                    song_name=command.get("song_name"),
                    clip_name=command.get("clip_name"),
                )
            )
            return

        if cmd_type == "skip_song":
            self.playback_manager.skip_song()
            return

        if cmd_type == "clip_capture":
            # "Clip that": dump the last N seconds of a person's voice (held in the
            # CaptureManager's rolling buffer) into a pending capture for review.
            if self.capture_manager is not None:
                self.capture_manager.process(
                    CaptureEvent(
                        command.get("target_voice"),
                        command.get("duration", CaptureManager.BUFFER_SECONDS),
                        command.get("requested_by"),
                    )
                )
            return

        if cmd_type == "join":
            # "Summon" the bot to another channel. Mumble bots are always in a
            # channel, so this is a move, not a connect. Fresh session → fresh
            # consent: wipe opt-ins so everyone must opt in again.
            if self.capture_manager is not None:
                self.capture_manager.clear_optin()
            self.playback_manager.join_channel(command.get("channel_id"))
            return

        if cmd_type == "leave":
            # No "disconnect from voice" in Mumble — go back to the home/root
            # channel (the closest equivalent to Discord's leave). Clear consent
            # so nobody stays opted in while the bot is away.
            if self.capture_manager is not None:
                self.capture_manager.clear_optin()
            self.playback_manager.leave_channel()
            return

        speed = command.get("speed", 1.0)
        pitch = command.get("pitch", 0)
        reverse = bool(command.get("reverse", False))

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
            reverses=[reverse],
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
            current_id = self.mumble.my_channel()["channel_id"]
        except Exception:
            return

        bot_name = os.getenv(MUMBLE_USERNAME)
        # Group every (non-bot) user by the channel they're in, so the web can
        # list all channels and summon the bot to any of them.
        by_channel = {}
        for session in list(self.mumble.users):
            user = self.mumble.users[session]
            try:
                cid = user["channel_id"]
                name = user[NAME]
            except Exception:
                continue
            if name == bot_name:
                continue
            # A user must have both mic and audio on to play; capture self- and
            # server-applied mute/deaf so the web can gate it.
            by_channel.setdefault(cid, []).append(
                {
                    "id": name,
                    "name": name,
                    "mute": bool(user.get("self_mute") or user.get("mute")),
                    "deaf": bool(user.get("self_deaf") or user.get("deaf")),
                }
            )

        channels = []
        for cid in list(self.mumble.channels):
            try:
                channel_name = self.mumble.channels[cid]["name"]
            except Exception:
                channel_name = str(cid)
            members = by_channel.get(cid, [])
            channels.append(
                {
                    "id": str(cid),
                    "name": channel_name,
                    "users": len(members),
                    "members": members,
                }
            )
        channels.sort(key=lambda c: int(c["id"]))

        # The presence gate set is whoever is in the bot's own channel.
        present = by_channel.get(current_id, [])
        try:
            self.mongo_interface.db.voice_state.update_one(
                {"_id": "state"},
                {
                    "$set": {
                        "channels": channels,
                        "current_channel_id": str(current_id),
                        "present": present,
                    }
                },
                upsert=True,
            )
        except Exception:
            pass
