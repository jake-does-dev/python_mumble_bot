class Event:
    def __init__(self, data):
        self.data = data

    def __eq__(self, other):
        return self.data == other.data


class AudioEvent(Event):
    def __init__(self, data):
        super().__init__(data)


class TextEvent(Event):
    def __init__(self, data):
        super().__init__(data)


class RecordEvent(Event):
    def __init__(self, data):
        super().__init__(data)
