from typing import Optional
from app.database import get_db
from app.auth import verify_password, hash_password


class UsersService:
    def __init__(self):
        self.db = get_db()

    def get_user(self, username: str) -> Optional[dict]:
        return self.db.users.find_one({"username": username})

    def authenticate(self, username: str, password: str) -> bool:
        user = self.get_user(username)
        if not user:
            return False
        return verify_password(password, user["password"])

    def create_user(self, username: str, password: str, is_admin: bool = False) -> bool:
        if self.get_user(username):
            return False
        self.db.users.insert_one({
            "username": username,
            "password": hash_password(password),
            "is_admin": is_admin
        })
        return True

    def list_users(self) -> list:
        return [
            {
                "username": u["username"],
                "is_admin": u.get("is_admin", False),
                "voice_id": u.get("voice_id"),
                "voice_name": u.get("voice_name"),
            }
            for u in self.db.users.find({}, {"password": 0}).sort("username", 1)
        ]

    def set_voice_link(
        self, username: str, voice_id: Optional[str], voice_name: Optional[str]
    ) -> bool:
        if not self.get_user(username):
            return False
        if voice_id:
            self.db.users.update_one(
                {"username": username},
                {"$set": {"voice_id": voice_id, "voice_name": voice_name}},
            )
        else:
            self.db.users.update_one(
                {"username": username},
                {"$unset": {"voice_id": "", "voice_name": ""}},
            )
        return True

    def is_admin(self, username: str) -> bool:
        user = self.get_user(username)
        if not user:
            return False
        return user.get("is_admin", False)

    def change_password(self, username: str, new_password: str) -> bool:
        user = self.get_user(username)
        if not user:
            return False
        self.db.users.update_one(
            {"username": username},
            {"$set": {"password": hash_password(new_password)}}
        )
        return True