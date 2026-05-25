from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from app.limiter import limiter
from app.routers import clips, commands, users
from app.database import get_db

PENDING_COMMANDS_TTL_SECONDS = 30 * 24 * 60 * 60  # 30 days

app = FastAPI(title="Python Mumble Bot Web")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

@app.on_event("startup")
def create_indexes():
    db = get_db()
    db.pending_commands.create_index("created_at", expireAfterSeconds=PENDING_COMMANDS_TTL_SECONDS)

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

@app.get("/health")
def health():
    return {"status": "ok"}

FRONTEND_DIST = Path("frontend/dist")

if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def serve_spa(full_path: str):
        return FileResponse(FRONTEND_DIST / "index.html")
