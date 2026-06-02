from collections import Counter, defaultdict
from datetime import datetime, timedelta

from app.database import get_db

# Only real clip plays count towards stats (skip announce/join/leave control rows).
PLAY_TYPES = ["play", "queue_play"]
WEEKDAYS = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]

# period key -> lookback window (None = all time)
_PERIODS = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
    "all": None,
}


class StatsService:
    def __init__(self):
        self.db = get_db()

    def get_stats(self, period: str = "7d", tz_offset: int = 0) -> dict:
        """Aggregate play history.

        tz_offset is JS `Date.getTimezoneOffset()` (minutes that UTC is ahead of
        local), so local = utc - tz_offset, used for hour/day-of-week bucketing.
        """
        if period not in _PERIODS:
            period = "7d"

        now = datetime.utcnow()
        query = {"status": "done", "type": {"$in": PLAY_TYPES}}
        delta = _PERIODS[period]
        if delta is not None:
            query["created_at"] = {"$gte": now - delta}

        commands = list(
            self.db.pending_commands.find(
                query,
                {
                    "clip_ref": 1,
                    "clip_name": 1,
                    "requested_by": 1,
                    "created_at": 1,
                    "_id": 0,
                },
            )
        )

        # Canonical names + tags keyed by identifier (clips may have been renamed
        # since they were played, so prefer the current clip name).
        clip_names = {}
        clip_tags = {}
        for c in self.db.clips.find({}, {"identifier": 1, "name": 1, "tags": 1, "_id": 0}):
            clip_names[c["identifier"]] = c["name"]
            clip_tags[c["identifier"]] = c.get("tags", [])

        def to_local(dt):
            return dt - timedelta(minutes=tz_offset)

        clip_counts = Counter()
        user_counts = Counter()
        user_clip = defaultdict(Counter)
        tag_counts = Counter()
        heatmap = [[0] * 24 for _ in range(7)]

        for c in commands:
            ref = c.get("clip_ref")
            label = clip_names.get(ref) or c.get("clip_name") or ref
            user = c.get("requested_by") or "unknown"
            clip_counts[label] += 1
            user_counts[user] += 1
            user_clip[user][label] += 1
            for tag in clip_tags.get(ref, []):
                tag_counts[tag] += 1
            created = c.get("created_at")
            if isinstance(created, datetime):
                local = to_local(created)
                heatmap[local.weekday()][local.hour] += 1

        timeline = self._timeline(commands, period, now, tz_offset)

        # Busiest hour / day across the whole grid.
        hour_totals = [sum(heatmap[d][h] for d in range(7)) for h in range(24)]
        day_totals = [sum(heatmap[d]) for d in range(7)]
        busiest_hour = max(range(24), key=lambda h: hour_totals[h]) if commands else None
        busiest_day = (
            WEEKDAYS[max(range(7), key=lambda d: day_totals[d])] if commands else None
        )

        return {
            "period": period,
            "total_plays": len(commands),
            "unique_clips": len(clip_counts),
            "unique_users": len(user_counts),
            "top_clips": [
                {"name": name, "count": count}
                for name, count in clip_counts.most_common(15)
            ],
            "top_users": [
                {"user": user, "count": count}
                for user, count in user_counts.most_common()
            ],
            "user_favourites": [
                {
                    "user": user,
                    "clip_name": user_clip[user].most_common(1)[0][0],
                    "count": user_clip[user].most_common(1)[0][1],
                    "total": total,
                }
                for user, total in user_counts.most_common()
            ],
            "top_tags": [
                {"tag": tag, "count": count}
                for tag, count in tag_counts.most_common(12)
            ],
            "timeline": timeline,
            "heatmap": heatmap,
            "busiest_hour": busiest_hour,
            "busiest_day": busiest_day,
        }

    def _timeline(self, commands, period, now, tz_offset):
        """Bucketed play counts over the period (hourly for 24h, else daily)."""
        now_local = now - timedelta(minutes=tz_offset)

        if period == "24h":
            base = now_local.replace(minute=0, second=0, microsecond=0)
            buckets = [base - timedelta(hours=i) for i in range(23, -1, -1)]
            counts = Counter()
            for c in commands:
                created = c.get("created_at")
                if isinstance(created, datetime):
                    key = (created - timedelta(minutes=tz_offset)).replace(
                        minute=0, second=0, microsecond=0
                    )
                    counts[key] += 1
            return [
                {"label": b.strftime("%H:00"), "count": counts.get(b, 0)}
                for b in buckets
            ]

        # Daily buckets.
        counts = Counter()
        first = None
        for c in commands:
            created = c.get("created_at")
            if isinstance(created, datetime):
                d = (created - timedelta(minutes=tz_offset)).date()
                counts[d] += 1
                if first is None or d < first:
                    first = d

        today = now_local.date()
        if period == "7d":
            span = 7
        elif period == "30d":
            span = 30
        else:  # all
            span = (today - first).days + 1 if first else 1
            span = min(span, 90)  # cap so the chart stays readable

        days = [today - timedelta(days=i) for i in range(span - 1, -1, -1)]
        return [
            {"label": d.strftime("%d %b"), "count": counts.get(d, 0)} for d in days
        ]
