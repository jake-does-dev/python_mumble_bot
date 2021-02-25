class Note:
    def __init__(self, note_name, alter, octave, start_time, duration):
        self.note_name = note_name
        self.alter = alter
        self.octave = octave
        self.start_time = start_time
        self.duration = duration

    def __str__(self):
        return "Note['note_name': {0}, 'alter': {1}, 'octave': {2}, 'start_time': {3}, 'duration': {4}]".format(
            self.note_name, self.alter, self.octave, self.start_time, self.duration
        )
    