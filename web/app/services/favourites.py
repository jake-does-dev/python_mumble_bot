from typing import List
from app.database import get_db


class FavouritesService:
    def __init__(self):
        self.db = get_db()

    def get_favourites(self, username: str) -> List[str]:
        return [
            f["clip_ref"]
            for f in self.db.favourites.find({"username": username})
        ]

    def toggle_favourite(self, username: str, clip_ref: str) -> bool:
        existing = self.db.favourites.find_one({
            "username": username,
            "clip_ref": clip_ref
        })
        if existing:
            self.db.favourites.delete_one({
                "username": username,
                "clip_ref": clip_ref
            })
            return False
        else:
            self.db.favourites.insert_one({
                "username": username,
                "clip_ref": clip_ref
            })
            return True