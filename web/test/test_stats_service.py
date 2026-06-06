"""Tests for StatsService.

The music-stats page once rendered blank because the songs payload was missing
keys the frontend indexed into. These lock the response *contract* (the keys are
always present, even with no data) for both the clip and song overviews, plus
basic counting correctness.
"""

from datetime import datetime, timedelta

from app.services.stats import StatsService

_CLIP_KEYS = {"period", "total_plays", "unique_clips", "unique_users",
              "clip_of_week", "top_clips", "clip_cloud"}
_SONG_KEYS = {"period", "total_plays", "unique_songs", "unique_users",
              "song_of_week", "top_songs", "song_cloud", "top_users",
              "top_instruments", "user_favourites"}


def _recent(days_ago=0, **extra):
    return {"played_at": datetime.utcnow() - timedelta(days=days_ago), **extra}


def test_clip_stats_empty_returns_full_contract(db):
    stats = StatsService().get_stats(period="7d")
    assert _CLIP_KEYS <= set(stats)
    assert stats["total_plays"] == 0
    assert stats["top_clips"] == []
    assert stats["clip_of_week"] is None


def test_clip_stats_counts_and_top(db):
    db.clips.insert_one({"identifier": "a0", "name": "alpha", "tags": ["funny"]})
    for _ in range(3):
        db.play_log.insert_one(_recent(clip_ref="a0", clip_name="alpha", requested_by="bob"))
    db.play_log.insert_one(_recent(clip_ref="b0", clip_name="bravo", requested_by="sue"))

    stats = StatsService().get_stats(period="7d")
    assert stats["total_plays"] == 4
    assert stats["unique_clips"] == 2
    assert stats["unique_users"] == 2
    top = {c["name"]: c["count"] for c in stats["top_clips"]}
    assert top["alpha"] == 3 and top["bravo"] == 1
    assert stats["clip_of_week"] == {"name": "alpha", "count": 3}


def test_clip_stats_uses_current_clip_name_over_logged(db):
    # Clip renamed after the play was logged -> stats show the current name.
    db.clips.insert_one({"identifier": "a0", "name": "renamed", "tags": []})
    db.play_log.insert_one(_recent(clip_ref="a0", clip_name="old-name", requested_by="bob"))
    stats = StatsService().get_stats(period="7d")
    assert {c["name"] for c in stats["top_clips"]} == {"renamed"}


def test_song_stats_empty_returns_full_contract(db):
    stats = StatsService().get_song_stats(period="7d")
    assert _SONG_KEYS <= set(stats), _SONG_KEYS - set(stats)
    assert stats["total_plays"] == 0
    assert stats["top_songs"] == []
    assert stats["top_instruments"] == []
    assert stats["song_of_week"] is None


def test_song_stats_counts_songs_and_instruments(db):
    for _ in range(2):
        db.song_log.insert_one(_recent(
            song_id="s1", song_name="GSTQ", clip_ref="dm0", clip_name="dry_fart",
            requested_by="winneh"))
    db.song_log.insert_one(_recent(
        song_id="s2", song_name="Jingle", clip_ref="dm0", clip_name="dry_fart",
        requested_by="bob"))

    stats = StatsService().get_song_stats(period="7d")
    assert stats["total_plays"] == 3
    assert stats["unique_songs"] == 2
    songs = {s["name"]: s["count"] for s in stats["top_songs"]}
    assert songs == {"GSTQ": 2, "Jingle": 1}
    # dry_fart used as the instrument on all three plays
    instruments = {i["name"]: i["count"] for i in stats["top_instruments"]}
    assert instruments["dry_fart"] == 3
    assert stats["song_of_week"] == {"name": "GSTQ", "count": 2}
