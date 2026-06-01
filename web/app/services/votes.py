from typing import Dict

from app.database import get_db


class VotesService:
    def __init__(self):
        self.db = get_db()

    def set_vote(self, username: str, identifier: str, value: int) -> dict:
        if value not in (1, -1):
            value = 0

        if value == 0:
            self.db.votes.delete_one(
                {"username": username, "identifier": identifier}
            )
        else:
            self.db.votes.update_one(
                {"username": username, "identifier": identifier},
                {"$set": {"value": value}},
                upsert=True,
            )

        return {"score": self.score(identifier), "my_vote": value}

    def score(self, identifier: str) -> int:
        result = list(
            self.db.votes.aggregate(
                [
                    {"$match": {"identifier": identifier}},
                    {"$group": {"_id": None, "score": {"$sum": "$value"}}},
                ]
            )
        )
        return result[0]["score"] if result else 0

    def scores(self) -> Dict[str, int]:
        result = self.db.votes.aggregate(
            [{"$group": {"_id": "$identifier", "score": {"$sum": "$value"}}}]
        )
        return {r["_id"]: r["score"] for r in result}

    def user_votes(self, username: str) -> Dict[str, int]:
        return {
            v["identifier"]: v["value"]
            for v in self.db.votes.find({"username": username})
        }
