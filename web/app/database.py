import os
import pymongo

MONGODB_USERNAME = os.getenv("MONGODB_USERNAME")
MONGODB_PASSWORD = os.getenv("MONGODB_PASSWORD")
MONGODB_HOST = os.getenv("MONGODB_HOST")

def get_db():
    client = pymongo.MongoClient(
        f"mongodb://{MONGODB_USERNAME}:{MONGODB_PASSWORD}@{MONGODB_HOST}:27017/voice_clips?authSource=admin"
    )
    return client.voice_clips