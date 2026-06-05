from fastapi import APIRouter, Depends

from app.auth import get_current_user
from app.services.stats import StatsService

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("/")
def get_stats(
    period: str = "7d",
    tz_offset: int = 0,
    current_user: str = Depends(get_current_user),
):
    return StatsService().get_stats(period=period, tz_offset=tz_offset)


@router.get("/user/{username}")
def get_user_stats(
    username: str,
    period: str = "7d",
    tz_offset: int = 0,
    current_user: str = Depends(get_current_user),
):
    return StatsService().get_user_stats(username, period=period, tz_offset=tz_offset)


@router.get("/clip/{name}")
def get_clip_stats(
    name: str,
    period: str = "7d",
    tz_offset: int = 0,
    current_user: str = Depends(get_current_user),
):
    return StatsService().get_clip_stats(name, period=period, tz_offset=tz_offset)


# -- song stats (read from song_log) --------------------------------------


@router.get("/songs/")
def get_song_stats(
    period: str = "7d",
    tz_offset: int = 0,
    current_user: str = Depends(get_current_user),
):
    return StatsService().get_song_stats(period=period, tz_offset=tz_offset)


@router.get("/songs/song/{name}")
def get_song_detail_stats(
    name: str,
    period: str = "7d",
    tz_offset: int = 0,
    current_user: str = Depends(get_current_user),
):
    return StatsService().get_song_detail_stats(name, period=period, tz_offset=tz_offset)


@router.get("/songs/user/{username}")
def get_song_user_stats(
    username: str,
    period: str = "7d",
    tz_offset: int = 0,
    current_user: str = Depends(get_current_user),
):
    return StatsService().get_song_user_stats(username, period=period, tz_offset=tz_offset)
