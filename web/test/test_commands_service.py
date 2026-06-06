"""Tests for the web command layer (`CommandsService`).

This is the exact surface where the queue regression happened: the web enqueues
`pending_commands` docs that the bot later dispatches. These lock down the doc
*types* and *shapes* the bot relies on, plus the stop/restart cancellation
filters, so a future change can't silently stop queues (or songs) from playing.
"""

from datetime import datetime, timedelta

from app.services.commands import CommandsService


def _pending(db, **q):
    return list(db.pending_commands.find({**q}))


def test_enqueue_play_inserts_command_and_logs(db):
    svc = CommandsService()
    cmd = svc.enqueue_play("dm0", "dry_fart", "winneh", pitch=3, speed=1.5)

    cmds = _pending(db, type="play")
    assert len(cmds) == 1
    doc = cmds[0]
    assert doc["clip_ref"] == "dm0"
    assert doc["clip_name"] == "dry_fart"
    assert doc["requested_by"] == "winneh"
    assert doc["status"] == "pending"
    assert doc["pitch"] == 3 and doc["speed"] == 1.5
    # returned command mirrors the stored doc
    assert cmd["type"] == "play" and cmd["clip_ref"] == "dm0"
    # a durable play_log row is written for stats
    logs = list(db.play_log.find({}))
    assert len(logs) == 1 and logs[0]["clip_ref"] == "dm0"


def test_enqueue_queue_produces_announce_plus_ordered_queue_plays(db):
    svc = CommandsService()
    items = [
        {"clip_ref": "a0", "clip_name": "alpha", "pitch": 0, "speed": 1.0},
        {"clip_ref": "b0", "clip_name": "bravo", "pitch": 2, "speed": 1.0},
        {"clip_ref": "c0", "clip_name": "charlie", "pitch": 0, "speed": 0.5},
    ]
    svc.enqueue_queue(items, "winneh", "my queue")

    assert len(_pending(db, type="announce")) == 1
    # The bot drains pending in natural (insertion) order, so that — not the
    # millisecond-precision created_at — is what must preserve queue order.
    queue_plays = _pending(db, type="queue_play")
    # one queue_play per item, IN ORDER — this is the bit that broke before
    assert [d["clip_ref"] for d in queue_plays] == ["a0", "b0", "c0"]
    assert all(d["status"] == "pending" for d in queue_plays)
    assert all(d["requested_by"] == "winneh" for d in queue_plays)
    # play_log captures every queued clip
    assert len(list(db.play_log.find({}))) == 3


def test_enqueue_queue_falls_back_to_ref_when_no_name(db):
    svc = CommandsService()
    svc.enqueue_queue([{"clip_ref": "x9"}], "winneh", "q")
    qp = _pending(db, type="queue_play")[0]
    assert qp["clip_name"] == "x9"  # name defaults to the ref


def test_enqueue_song_writes_log_announce_and_play_song(db):
    svc = CommandsService()
    svc.enqueue_song(
        song_filename="gstq.mid",
        song_name="God Save the Queen",
        clip_ref="dm0",
        clip_name="dry_fart",
        requested_by="winneh",
        transpose=2,
        speed=1.0,
        gain=1.5,
        max_seconds=30.0,
        song_id="song-1",
    )

    assert len(_pending(db, type="announce")) == 1
    play_songs = _pending(db, type="play_song")
    assert len(play_songs) == 1
    ps = play_songs[0]
    assert ps["song"] == "gstq.mid"
    assert ps["clip_ref"] == "dm0"
    assert ps["transpose"] == 2 and ps["max_seconds"] == 30.0
    assert ps["status"] == "pending"
    # The announce must be drained before the play_song so chat reads right.
    # Mongo stores datetimes at millisecond precision, so the microsecond bump
    # in created_at can collapse — natural (insertion) order is the real
    # guarantee the bot's poll loop relies on.
    order = [d["type"] for d in db.pending_commands.find({})]
    assert order.index("announce") < order.index("play_song")
    # durable song_log row
    logs = list(db.song_log.find({}))
    assert len(logs) == 1 and logs[0]["song_name"] == "God Save the Queen"


def test_enqueue_skip_song(db):
    svc = CommandsService()
    svc.enqueue_skip_song("winneh")
    skips = _pending(db, type="skip_song")
    assert len(skips) == 1 and skips[0]["requested_by"] == "winneh"


def test_enqueue_stop_cancels_pending_playables_and_inserts_stop(db):
    svc = CommandsService()
    # a play, a queue_play and a play_song are all in flight
    svc.enqueue_play("a0", "alpha", "winneh")
    svc.enqueue_queue([{"clip_ref": "b0", "clip_name": "bravo"}], "winneh", "q")
    svc.enqueue_song("s.mid", "song", "a0", "alpha", "winneh")

    svc.enqueue_stop("winneh")

    # every playable type is now marked done...
    for t in ("play", "queue_play", "play_song"):
        assert all(d["status"] == "done" for d in _pending(db, type=t)), t
    # ...a stop command is queued for the bot...
    stops = _pending(db, type="stop", status="pending")
    assert len(stops) == 1
    # ...but the announce docs are NOT cancelled (not playables)
    assert any(d["status"] == "pending" for d in _pending(db, type="announce"))


def test_enqueue_stop_leaves_already_done_and_other_pending_untouched(db):
    svc = CommandsService()
    db.pending_commands.insert_one(
        {"type": "play", "status": "done", "clip_ref": "old", "created_at": datetime.utcnow()}
    )
    db.pending_commands.insert_one(
        {"type": "join", "status": "pending", "created_at": datetime.utcnow()}
    )
    svc.enqueue_stop("winneh")
    # the unrelated pending join survives
    assert _pending(db, type="join")[0]["status"] == "pending"


def test_enqueue_restart_cancels_playables_and_inserts_restart(db):
    svc = CommandsService()
    svc.enqueue_play("a0", "alpha", "winneh")
    svc.enqueue_restart("winneh")
    assert all(d["status"] == "done" for d in _pending(db, type="play"))
    assert len(_pending(db, type="restart", status="pending")) == 1


def test_enqueue_join_and_leave(db):
    svc = CommandsService()
    svc.enqueue_join("123", "winneh")
    svc.enqueue_leave("winneh")
    assert _pending(db, type="join")[0]["channel_id"] == "123"
    assert len(_pending(db, type="leave")) == 1


def test_get_next_pending_and_mark_done_roundtrip(db):
    svc = CommandsService()
    svc.enqueue_play("a0", "alpha", "winneh")
    nxt = svc.get_next_pending()
    assert nxt is not None and nxt["type"] == "play"
    svc.mark_done(nxt["_id"])
    assert svc.get_next_pending() is None


def test_get_song_state_empty(db):
    assert CommandsService().get_song_state() == {"current": None, "queue": []}


def test_get_song_state_serialises_started_at(db):
    started = datetime(2026, 6, 6, 12, 0, 0)
    db.song_state.insert_one(
        {
            "_id": "singleton",
            "current": {"song_name": "x", "clip_name": "c", "started_at": started, "duration_s": 10},
            "queue": [{"song_name": "y"}],
        }
    )
    state = CommandsService().get_song_state()
    assert state["current"]["started_at"] == started.isoformat() + "Z"
    assert state["current"]["song_name"] == "x"
    assert state["queue"] == [{"song_name": "y"}]


def test_get_history_joins_clip_names_and_formats(db):
    played = datetime(2026, 6, 6, 9, 0, 0)
    db.clips.insert_one({"identifier": "a0", "name": "alpha-renamed"})
    db.play_log.insert_one(
        {"clip_ref": "a0", "clip_name": "alpha", "requested_by": "winneh",
         "pitch": 1, "speed": 2.0, "played_at": played}
    )
    hist = CommandsService().get_history()
    assert len(hist) == 1
    row = hist[0]
    # current clip name (from clips) wins over the logged name
    assert row["clip_name"] == "alpha-renamed"
    assert row["played_at"] == played.isoformat() + "Z"
    assert row["pitch"] == 1 and row["speed"] == 2.0


def test_last_stop_and_last_restart(db):
    svc = CommandsService()
    assert svc.last_stop() == {"at": None, "by": None}
    svc.enqueue_stop("winneh")
    assert svc.last_stop()["by"] == "winneh"
    svc.enqueue_restart("bob")
    assert svc.last_restart()["by"] == "bob"


def test_history_orders_newest_first(db):
    svc = CommandsService()
    base = datetime(2026, 6, 6, 9, 0, 0)
    for i in range(3):
        db.play_log.insert_one(
            {"clip_ref": f"r{i}", "clip_name": f"n{i}", "requested_by": "w",
             "pitch": 0, "speed": 1.0, "played_at": base + timedelta(minutes=i)}
        )
    hist = CommandsService().get_history()
    assert [h["clip_ref"] for h in hist] == ["r2", "r1", "r0"]
