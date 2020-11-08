import os
import time
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
    CONNECTION_STR = "".join(
        [
            "mongodb+srv://appUser:",
            os.getenv("PMB_MONGODB_PASSWORD"),
            "@python-mumble-bot.r2fj8.mongodb.net/clips?retryWrites=true&w=majority",
        ]
    )

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

    def add_file(
        self, file, upload_time=time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    ):
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
            TAGS: [],
        }

        self.client.clips.clips.insert_one(document)
        self.client.clips.identifiers.update_one(
            {"_id": prefix_doc_id}, {"$set": {NEXT_ID: identifier_number + 1}}
        )

    def get_clips(self):
        if self.clips_collection is None:
            self.refresh()

        return self.clips_collection.find({})

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

    def tag(self, ref, tag):
        file = self._find_file_by_ref(ref)
        tags = file[TAGS]
        tags.append(tag)
        tags = sorted(list(set(tags)))

        self.client.clips.identifiers.update_one(
            {"_id": file[ID]}, {"$set": {TAGS: tags}}
        )

    def untag(self, ref, tag):
        file = self._find_file_by_ref(ref)
        tags = file[TAGS]
        tags.remove(tag)
        tags = sorted(list(set(tags)))

        self.client.clips.identifiers.update_one(
            {"_id": file[ID]}, {"$set": {TAGS: tags}}
        )


if __name__ == "__main__":
    (root, _, files) = next(os.walk(Path("audio/new/")))

    mongo_interface = MongoInterface()
    # mongo_interface.set_up_identifiers()

    data = ((os.path.getmtime("".join([root, "/", f])), f) for f in files)
    for creation_time, file in sorted(data):
        readable_time = time.strftime(
            "%Y-%m-%d %H:%M:%S", time.localtime(creation_time)
        )
        mongo_interface.add_file(file, readable_time)
