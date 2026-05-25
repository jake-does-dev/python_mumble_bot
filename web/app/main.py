from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import clips, commands, users

app = FastAPI(title="Python Mumble Bot Web")

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