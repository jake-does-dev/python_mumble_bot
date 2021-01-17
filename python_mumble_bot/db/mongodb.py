import os
from datetime import datetime
from pathlib import Path

import pymongo

from python_mumble_bot.bot.constants import (
    CREATION_TIME,
    FILE,
    FILE_PREFIX,
    ID,
    IDENTIFIER,
    IDENTIFIER_PREFIX,
    NAME,
    NEXT_ID,
    TAGS,
)


class MongoInterface:
    CONNECTION_STR = "mongodb://127.0.0.1:27017"
    NEW_CLIPS_PATH = Path("audio/new/")
    ALL_CLIPS_PATH = Path("audio/")
    NEW_CLIP_DAY_THRESHOLD = 2

    def __init__(self):
        self.client = None
        self.file_prefixes_collection = None
        self.clips_collection = None

    def connect(self):
        self.client = pymongo.MongoClient(self.CONNECTION_STR)

    def set_up_identifiers(self):
        id_prefix_map = {
            "daryl_": "dm",
            "david_": "dg",
            "dom_": "dh",
            "jake_": "ja",
            "ollie_": "oy",
            "will_": "wt",
            "generic": "",
        }

        for file_prefix, identifier_prefix in id_prefix_map.items():
            id_doc = {
                FILE_PREFIX: file_prefix,
                IDENTIFIER_PREFIX: identifier_prefix,
                NEXT_ID: 0,
            }
            self.client.clips.identifiers.insert_one(id_doc)

    def refresh(self):
        self.file_prefixes_collection = self.client.clips.identifiers
        self.clips_collection = self.client.clips.clips

    def add_clip(self, file, upload_time=datetime.now(), tags=None):
        if tags is None:
            tags = []
        if self.file_prefixes_collection is None:
            self.refresh()

        file_prefixes = [p[FILE_PREFIX] for p in self.file_prefixes_collection.find({})]

        name = file.split(".")[0]

        target_prefix = None
        for file_prefix in file_prefixes:
            if file_prefix in name:
                target_prefix = file_prefix
                break
        if target_prefix is None:
            target_prefix = "generic"

        prefix_doc = self.file_prefixes_collection.find_one(
            {FILE_PREFIX: target_prefix}
        )
        prefix_doc_id = prefix_doc["_id"]

        identifier_prefix = prefix_doc[IDENTIFIER_PREFIX]
        identifier_number = prefix_doc[NEXT_ID]
        identifier = "".join([identifier_prefix, str(identifier_number)])
        document = {
            IDENTIFIER: identifier,
            NAME: name,
            FILE: file,
            CREATION_TIME: upload_time,
            TAGS: tags,
        }

        self.client.clips.clips.insert_one(document)
        self.client.clips.identifiers.update_one(
            {"_id": prefix_doc_id}, {"$set": {NEXT_ID: identifier_number + 1}}
        )

        return identifier, name

    def get_clips(self, tag=None):
        if self.clips_collection is None:
            self.refresh()

        if tag is None:
            return self.clips_collection.find({})
        else:
            return self.clips_collection.find({TAGS: tag})

    def get_all_file_names(self):
        clips = self.get_clips()
        return [c[NAME] for c in clips]

    def get_file_by_ref(self, ref):
        file = self._find_file_by_ref(ref)
        return file[FILE]

    def _find_file_by_ref(self, ref):
        if self.clips_collection is None:
            self.refresh()

        file = self._search(IDENTIFIER, ref)
        if file is None:
            file = self._search(NAME, ref)

        if file is None:
            FileNotFoundError(
                "Cannot find the file with reference " + ref + " in MongoDB"
            )

        return file

    def _search(self, key, ref):
        return self.clips_collection.find_one({key: ref})

    def tag(self, references, tag):

        for ref in references:
            file = self._find_file_by_ref(ref)
            tags = file[TAGS]
            tags.append(tag)
            tags = sorted(list(set(tags)))

            self.client.clips.clips.update_one(
                {"_id": file[ID]}, {"$set": {TAGS: tags}}
            )
        self.refresh()

    def untag(self, references, tag):
        for ref in references:
            file = self._find_file_by_ref(ref)
            tags = file[TAGS]
            tags.remove(tag)
            tags = sorted(list(set(tags)))

            self.client.clips.clips.update_one(
                {"_id": file[ID]}, {"$set": {TAGS: tags}}
            )
        self.refresh()

    def add_new_clips(self):
        new_clips = []

        (root, _, files) = next(os.walk(self.NEW_CLIPS_PATH))

        data = ((os.path.getmtime("".join([root, "/", f])), f) for f in files)
        for creation_time, file in sorted(data):
            date = datetime.fromtimestamp(creation_time)
            # formatted_date = date.strftime(DATE_FORMAT)

            if (datetime.now() - date).days < self.NEW_CLIP_DAY_THRESHOLD:
                tags = ["new"]
            else:
                tags = []

            new_clip = self.add_clip(file, upload_time=date, tags=tags)
            new_clips.append(new_clip)
            os.rename(
                self.NEW_CLIPS_PATH.joinpath(file), self.ALL_CLIPS_PATH.joinpath(file)
            )

        self.refresh()

        return new_clips


def reset_mongo():
    mongo_interface = MongoInterface()
    mongo_interface.connect()
    mongo_interface.client.clips.clips.delete_many({})

    for identifier_mapping in mongo_interface.client.clips.identifiers.find({}):
        mongo_interface.client.clips.identifiers.update_one(
            {"_id": identifier_mapping[ID]}, {"$set": {NEXT_ID: 0}}
        )


if __name__ == "__main__":
    reset = input(
        "Are you sure you want to delete all clips and reset all mappings in MongoDB? (y/N): "
    )
    if reset == "y":
        reset_mongo()
