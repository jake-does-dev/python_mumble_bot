import math
import subprocess as sp

# Filter prefixes. RESAMPLE_FILTER preserves duration while shifting pitch;
# SETRATE_FILTER changes both rate and pitch (used for musical note rendering).
RESAMPLE_FILTER = "aresample=48000*"
SETRATE_FILTER = "asetrate=48000/"


def _atempo_chain(required_tempo):
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

    return tempo_filter


def gain_db_to_multiplier(gain_db):
    # Per-clip volume trim stored in dB (0 = unchanged). Converts to the linear
    # multiplier the ffmpeg `volume=` filter expects so it can be folded into
    # the global playback volume.
    return 10 ** ((gain_db or 0) / 20)


def generate_filter(pitch_filter, volume, speed, shift):
    shift_resample_multiplier = 2 ** (-shift / 12)
    required_tempo = speed / 2 ** (shift / 12)

    tempo_filter = _atempo_chain(required_tempo)

    pitch_filter = "".join([pitch_filter, str(shift_resample_multiplier)])
    volume_filter = "".join(["volume=", str(volume)])
    filter = ",".join([tempo_filter, volume_filter, pitch_filter])

    return filter


def generate_standard_filter(volume, speed, shift):
    # Pitch/speed filter for consumers that play a true 48kHz stereo stream
    # (e.g. Discord), as opposed to the Mumble path which reinterprets an
    # off-rate mono stream.
    #
    # The leading aresample=48000 is essential: it resamples the source to
    # 48kHz first (preserving true pitch) so the asetrate trick below operates
    # on a known rate. Without it, asetrate would reinterpret a non-48kHz
    # source (e.g. a 44.1kHz mp3) as 48kHz, playing it sharp and fast.
    #
    # Then: asetrate shifts pitch (and speed), aresample normalises back to
    # 48kHz preserving the shifted pitch, and atempo corrects the speed.
    ratio = 2 ** (shift / 12)
    set_rate = int(round(48000 * ratio))
    required_tempo = speed / ratio

    tempo_filter = _atempo_chain(required_tempo)

    return ",".join(
        [
            "aresample=48000",
            "asetrate={0}".format(set_rate),
            "aresample=48000",
            tempo_filter,
            "volume={0}".format(volume),
        ]
    )


def transform_audio(
    file,
    pitch_filter,
    volume,
    speed,
    shift,
    desired_output="pcm",
    output_file=None,
):
    filter = generate_filter(pitch_filter, volume, speed, shift)

    if desired_output == "pcm":
        return transform_as_pcm_data(file, filter)
    elif desired_output == "wav":
        return transform_as_wav(file, filter, output_file)


def transform_as_pcm_data(file, filter):
    encode_command = (
        "ffmpeg -hide_banner -loglevel error -i {0} "
        "-filter_complex {1} -ac 1 -f s16le -".format(file, filter)
    )
    proc = sp.Popen(encode_command.split(" "), stdout=sp.PIPE, stderr=sp.PIPE)
    out, err = proc.communicate()
    if proc.returncode != 0:
        print("FFMPEG ERROR:", err.decode()[:500])
    return out


def transform_as_wav(input, filter, output):
    filter = "{0},{1}".format(filter, "aresample=48000")
    encode_command = "ffmpeg -i {0} -filter_complex {1} -y {2}".format(
        input, filter, output
    )

    p = sp.Popen(encode_command.split(" "))
    p.communicate()
