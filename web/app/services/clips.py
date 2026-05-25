from typing import Optional, List
from app.database import get_db


class ClipsService:
    def __init__(self):
        self.db = get_db()

    def get_clips(
        self,
        search: Optional[str] = None,
        tag: Optional[str] = None,
    ) -> List[dict]:
        query = {}
        if search:
            query["$or"] = [
                {"name": {"$regex": search, "$options": "i"}},
                {"identifier": {"$regex": search, "$options": "i"}},
            ]
        if tag:
            query["tags"] = tag

        return list(self.db.clips.find(query, {"_id": 0}))

    def get_clip_by_ref(self, ref: str) -> Optional[dict]:
        clip = self.db.clips.find_one({"identifier": ref}, {"_id": 0})
        if not clip:
            clip = self.db.clips.find_one({"name": ref}, {"_id": 0})
        return clip

    def get_all_tags(self) -> List[str]:
        tags = self.db.clips.distinct("tags")
        return sorted(tags)