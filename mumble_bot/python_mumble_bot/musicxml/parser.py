from pathlib import Path
from xml.etree import ElementTree as ET

from python_mumble_bot.music.piece import Note


def parse_musicxml(path_to_musicxml):
    path = Path(path_to_musicxml)

    tree = ET.parse(path)
    root = tree.getroot()
    piano_part = root.findall("part")[0]
    raw_measures = [m for m in piano_part.iterfind("measure")]

    measures = []
    current_notes = []
    measure_length = None

    # repeat_start_measure = None

    for measure in raw_measures:
        voices_to_notes = {}

        if measure_length is None and measure.find("backup") is not None:
            measure_length = int(measure.find("backup").find("duration").text)

        # measure_number = int(measure.attrib["number"])
        notes = [n for n in measure.iterfind("note")]

        current_voice = None
        chord_dummy_voice = 100
        current_time = 0
        for note_number, note in enumerate(notes):
            voice = int(note.find("voice").text)

            if current_voice is None:
                current_voice = voice
                current_time = 0
                current_notes = []
            elif current_voice is not voice:
                voices_to_notes[current_voice] = current_notes
                current_voice = voice
                current_time = 0
                current_notes = []

            pitch = note.find("pitch")
            if not pitch:  # then this is a rest
                rest_duration = int(note.find("duration").text)

                if current_notes != []:
                    current_notes[-1].duration += rest_duration
                else:
                    start_time = current_time
                    current_time += rest_duration
                    current_notes.append(Note("rest", 0, 0, start_time, rest_duration))

            else:
                note_name = pitch.find("step").text

                if note.find("grace") is not None:
                    continue

                if pitch.find("alter") is None:
                    alter = 0
                else:
                    alter = int(pitch.find("alter").text)
                octave = int(pitch.find("octave").text)
                duration = int(note.find("duration").text)

                if note.find("chord") is not None:
                    voices_to_notes[chord_dummy_voice] = [
                        Note(note_name, alter, octave, start_time, duration)
                    ]
                    chord_dummy_voice += 1
                else:
                    start_time = current_time
                    current_time += duration
                    current_notes.append(
                        Note(note_name, alter, octave, start_time, duration)
                    )

        if current_notes != []:
            voices_to_notes[current_voice] = current_notes

        measures.append(voices_to_notes)

        # if measure.find('barline') is not None:
        #     # Maybe there's a repeat!
        #     repeat = measure.find('barline').find('repeat')
        #     if repeat is not None:
        #         if repeat.attrib['direction'] == 'forward':
        #             repeat_start_measure = measure_number
        #         else:
        #             # at the end of the repeat
        #             num_measures = measure_number - repeat_start_measure + 1
        #             [measures.append(m) for m in measures[len(measures) - num_measures: len(measures)]]
        #             repeat_start_measure = None

    if measure_length is None:
        # Assume this is 4/4
        measure_length = 8

    return {"measure_length": measure_length, "measures": measures}
