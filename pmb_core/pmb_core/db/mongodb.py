import os
from datetime import datetime
from pathlib import Path

import pymongo

from pmb_core.constants import (
    CREATION_TIME,
    DEFAULT_DATABASE,
    FILE,
    FILE_PREFIX,
    ID,
    IDENTIFIER,
    IDENTIFIER_PREFIX,
    MONGODB_DATABASE,
    MONGODB_HOST,
    MONGODB_PASSWORD,
    MONGODB_USERNAME,
    NAME,
    NEXT_ID,
    TAGS,
)


class MongoInterface:
    NEW_CLIPS_PATH = Path("audio/new/")
    ALL_CLIPS_PATH = Path("audio/")

    def __init__(self):
        self.client = None
        self.file_prefixes_collection = None
        self.clips_collection = None
        self.volume = None
        self.db_name = os.getenv(MONGODB_DATABASE, DEFAULT_DATABASE)
        self.db = None

    def connect(self):
        self.client = pymongo.MongoClient(
            "".join(
                [
                    "mongodb://",
                    os.getenv(MONGODB_USERNAME),
                    ":",
                    os.getenv(MONGODB_PASSWORD),
                    "@",
                    os.getenv(MONGODB_HOST),
                    ":27017/",
                    self.db_name,
                    "?authSource=admin",
                ]
            )
        )

        self.db = self.client[self.db_name]
        self.volume = self.get_volume()

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
            self.db.identifiers.insert_one(id_doc)

    def refresh(self):
        self.file_prefixes_collection = self.db.identifiers
        self.clips_collection = self.db.clips

    def set_volume(self, volume):
        self.volume = volume
        self.db.playback_volume.update_one(
            {}, {"$set": {"playback_volume": volume}}
        )

    def get_volume(self):
        record = self.db.playback_volume.find_one({})
        return record["playback_volume"]

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

        self.db.clips.insert_one(document)
        self.db.identifiers.update_one(
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

            self.db.clips.update_one({"_id": file[ID]}, {"$set": {TAGS: tags}})
        self.refresh()

    def untag(self, references, tag):
        for ref in references:
            file = self._find_file_by_ref(ref)
            tags = file[TAGS]
            tags.remove(tag)
            tags = sorted(list(set(tags)))

            self.db.clips.update_one({"_id": file[ID]}, {"$set": {TAGS: tags}})
        self.refresh()

    def get_next_pending_command(self):
        return self.db.pending_commands.find_one_and_update(
            {"status": "pending"},
            {"$set": {"status": "processing"}},
            sort=[("created_at", pymongo.ASCENDING), ("_id", pymongo.ASCENDING)],
        )

    def mark_command_done(self, command_id):
        self.db.pending_commands.update_one(
            {"_id": command_id}, {"$set": {"status": "done"}}
        )

    def add_new_clips(self):
        new_clips = []

        root, _, files = next(os.walk(self.NEW_CLIPS_PATH))

        data = ((os.path.getmtime("".join([root, "/", f])), f) for f in files)
        for creation_time, file in sorted(data):
            date = datetime.fromtimestamp(creation_time)
            new_clip = self.add_clip(file, upload_time=date)
            new_clips.append(new_clip)
            os.rename(
                self.NEW_CLIPS_PATH.joinpath(file), self.ALL_CLIPS_PATH.joinpath(file)
            )

        self.refresh()

        return new_clips


def reset_mongo():
    mongo_interface = MongoInterface()
    mongo_interface.connect()
    mongo_interface.db.clips.delete_many({})

    for identifier_mapping in mongo_interface.db.identifiers.find({}):
        mongo_interface.db.identifiers.update_one(
            {"_id": identifier_mapping[ID]}, {"$set": {NEXT_ID: 0}}
        )


if __name__ == "__main__":
    reset = input(
        "Are you sure you want to delete all clips and reset all mappings in MongoDB? (y/N): "
    )
    if reset == "y":
        reset_mongo()
