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