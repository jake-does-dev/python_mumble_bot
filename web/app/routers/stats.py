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
