import os
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from app.limiter import limiter
from app.routers import clips, commands, stats, users, voice
from app.database import get_db

PENDING_COMMANDS_TTL_SECONDS = 30 * 24 * 60 * 60  # 30 days

app = FastAPI(title="Python Mumble Bot Web")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

@app.on_event("startup")
def create_indexes():
    db = get_db()
    db.pending_commands.create_index("created_at", expireAfterSeconds=PENDING_COMMANDS_TTL_SECONDS)
    # play_log is the durable, append-only stats source (no TTL).
    db.play_log.create_index("played_at")
    _backfill_play_log(db)


def _backfill_play_log(db):
    """Seed play_log from existing (not-yet-expired) pending_commands once, so
    stats aren't empty on first deploy."""
    if db.play_log.estimated_document_count() > 0:
        return
    docs = []
    for c in db.pending_commands.find(
        {"type": {"$in": ["play", "queue_play"]}},
        {"clip_ref": 1, "clip_name": 1, "requested_by": 1, "created_at": 1, "pitch": 1, "speed": 1, "_id": 0},
    ):
        if not c.get("clip_ref") or not c.get("created_at"):
            continue
        docs.append({
            "clip_ref": c["clip_ref"],
            "clip_name": c.get("clip_name") or c["clip_ref"],
            "requested_by": c.get("requested_by") or "unknown",
            "pitch": c.get("pitch", 0),
            "speed": c.get("speed", 1.0),
            "played_at": c["created_at"],
        })
    if docs:
        db.play_log.insert_many(docs)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(users.router)
app.include_router(clips.router)
app.include_router(commands.router)
app.include_router(stats.router)
app.include_router(voice.router)

@app.get("/health")
def health():
    return {"status": "ok"}

APP_TITLE = os.getenv("APP_TITLE", "Voice Clips")

@app.get("/api/config")
def config():
    return {"title": APP_TITLE}

FRONTEND_DIST = Path("frontend/dist")

if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def serve_spa(full_path: str):
        return FileResponse(FRONTEND_DIST / "index.html")
