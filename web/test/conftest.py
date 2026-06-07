"""Shared fixtures for the web service-layer tests.

The services all do ``from app.database import get_db`` and call it in their
constructors, opening a real Mongo connection. For tests we swap every binding
of ``get_db`` for one that returns a fresh in-memory ``mongomock`` database, so
the suite runs anywhere (incl. CI) with no Mongo and no shared state between
tests.

Env vars that app modules read at import time are set here, at conftest load,
before any ``app.*`` module is imported by a test.
"""

import importlib
import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
os.environ.setdefault("MONGODB_USERNAME", "test")
os.environ.setdefault("MONGODB_PASSWORD", "test")
os.environ.setdefault("MONGODB_HOST", "localhost")

import mongomock  # noqa: E402
import pytest  # noqa: E402

# Every module that binds `get_db` and so needs redirecting at the fake DB.
_GET_DB_MODULES = [
    "app.database",
    "app.services.users",
    "app.services.commands",
    "app.services.presence",
    "app.services.clips",
    "app.services.songs",
    "app.services.stats",
    "app.services.votes",
    "app.services.favourites",
    "app.services.entrance",
    "app.routers.voice",
]


@pytest.fixture
def db(monkeypatch):
    """A fresh in-memory `voice_clips` database, wired into every service."""
    client = mongomock.MongoClient()
    test_db = client["voice_clips"]
    for modname in _GET_DB_MODULES:
        try:
            mod = importlib.import_module(modname)
        except Exception:
            continue
        if hasattr(mod, "get_db"):
            monkeypatch.setattr(mod, "get_db", lambda _db=test_db: _db)
    return test_db
