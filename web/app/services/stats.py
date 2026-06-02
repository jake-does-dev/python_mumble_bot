from collections import Counter, defaultdict
from datetime import datetime, timedelta

from app.database import get_db

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
    """Reads from the durable, append-only `play_log` collection.

    Each play_log doc: {clip_ref, clip_name, requested_by, played_at, pitch, speed}.
    `clip_name` is resolved to the clip's *current* name where possible (clips may
    have been renamed since they were played).
    """

    def __init__(self):
        self.db = get_db()

    # -- helpers -----------------------------------------------------------

    def _clip_maps(self):
        names, tags = {}, {}
        for c in self.db.clips.find(
            {}, {"identifier": 1, "name": 1, "tags": 1, "_id": 0}
        ):
            names[c["identifier"]] = c["name"]
            tags[c["identifier"]] = c.get("tags", [])
        return names, tags

    def _fetch(self, period, now, extra=None):
        query = {}
        delta = _PERIODS.get(period, _PERIODS["7d"])
        if delta is not None:
            query["played_at"] = {"$gte": now - delta}
        if extra:
            query.update(extra)
        return list(self.db.play_log.find(query, {"_id": 0}))

    @staticmethod
    def _label(rec, clip_names):
        ref = rec.get("clip_ref")
        return clip_names.get(ref) or rec.get("clip_name") or ref

    # -- overview ----------------------------------------------------------

    def get_stats(self, period: str = "7d", tz_offset: int = 0) -> dict:
        if period not in _PERIODS:
            period = "7d"
        now = datetime.utcnow()
        records = self._fetch(period, now)
        clip_names, clip_tags = self._clip_maps()

        def to_local(dt):
            return dt - timedelta(minutes=tz_offset)

        clip_counts = Counter()
        user_counts = Counter()
        user_clip = defaultdict(Counter)
        tag_counts = Counter()
        heatmap = [[0] * 24 for _ in range(7)]

        for rec in records:
            label = self._label(rec, clip_names)
            user = rec.get("requested_by") or "unknown"
            clip_counts[label] += 1
            user_counts[user] += 1
            user_clip[user][label] += 1
            for tag in clip_tags.get(rec.get("clip_ref"), []):
                tag_counts[tag] += 1
            played = rec.get("played_at")
            if isinstance(played, datetime):
                local = to_local(played)
                heatmap[local.weekday()][local.hour] += 1

        timeline = self._timeline(records, period, now, tz_offset)

        hour_totals = [sum(heatmap[d][h] for d in range(7)) for h in range(24)]
        day_totals = [sum(heatmap[d]) for d in range(7)]
        busiest_hour = max(range(24), key=lambda h: hour_totals[h]) if records else None
        busiest_day = (
            WEEKDAYS[max(range(7), key=lambda d: day_totals[d])] if records else None
        )

        # Clip of the week is always the last 7 days, independent of the selected
        # period.
        week = self._fetch("7d", now)
        week_counts = Counter(self._label(r, clip_names) for r in week)
        clip_of_week = None
        if week_counts:
            name, count = week_counts.most_common(1)[0]
            clip_of_week = {"name": name, "count": count}

        return {
            "period": period,
            "total_plays": len(records),
            "unique_clips": len(clip_counts),
            "unique_users": len(user_counts),
            "clip_of_week": clip_of_week,
            "top_clips": [
                {"name": name, "count": count}
                for name, count in clip_counts.most_common(15)
            ],
            "clip_cloud": [
                {"name": name, "count": count}
                for name, count in clip_counts.most_common(50)
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

    # -- drill-downs -------------------------------------------------------

    def get_user_stats(self, username: str, period: str = "7d", tz_offset: int = 0):
        if period not in _PERIODS:
            period = "7d"
        now = datetime.utcnow()
        records = self._fetch(period, now, {"requested_by": username})
        clip_names, _ = self._clip_maps()

        clip_counts = Counter(self._label(r, clip_names) for r in records)
        hours = Counter()
        for r in records:
            played = r.get("played_at")
            if isinstance(played, datetime):
                hours[(played - timedelta(minutes=tz_offset)).hour] += 1
        busiest_hour = hours.most_common(1)[0][0] if hours else None

        return {
            "username": username,
            "period": period,
            "total_plays": len(records),
            "unique_clips": len(clip_counts),
            "busiest_hour": busiest_hour,
            "top_clips": [
                {"name": n, "count": c} for n, c in clip_counts.most_common(15)
            ],
            "timeline": self._timeline(records, period, now, tz_offset),
        }

    def get_clip_stats(self, name: str, period: str = "7d", tz_offset: int = 0):
        if period not in _PERIODS:
            period = "7d"
        now = datetime.utcnow()
        # Prefer matching by stable identifier (handles renames); fall back to the
        # recorded name for deleted clips.
        clip = self.db.clips.find_one({"name": name}, {"identifier": 1, "_id": 0})
        extra = {"clip_ref": clip["identifier"]} if clip else {"clip_name": name}
        records = self._fetch(period, now, extra)

        user_counts = Counter(r.get("requested_by") or "unknown" for r in records)
        played_times = [
            r["played_at"] for r in records if isinstance(r.get("played_at"), datetime)
        ]

        return {
            "name": name,
            "period": period,
            "total_plays": len(records),
            "unique_users": len(user_counts),
            "first_played": min(played_times).isoformat() + "Z" if played_times else None,
            "last_played": max(played_times).isoformat() + "Z" if played_times else None,
            "top_users": [
                {"user": u, "count": c} for u, c in user_counts.most_common(15)
            ],
            "timeline": self._timeline(records, period, now, tz_offset),
        }

    # -- timeline ----------------------------------------------------------

    def _timeline(self, records, period, now, tz_offset):
        """Bucketed play counts over the period (hourly for 24h, else daily)."""
        now_local = now - timedelta(minutes=tz_offset)

        if period == "24h":
            base = now_local.replace(minute=0, second=0, microsecond=0)
            buckets = [base - timedelta(hours=i) for i in range(23, -1, -1)]
            counts = Counter()
            for r in records:
                played = r.get("played_at")
                if isinstance(played, datetime):
                    key = (played - timedelta(minutes=tz_offset)).replace(
                        minute=0, second=0, microsecond=0
                    )
                    counts[key] += 1
            return [
                {"label": b.strftime("%H:00"), "count": counts.get(b, 0)}
                for b in buckets
            ]

        counts = Counter()
        first = None
        for r in records:
            played = r.get("played_at")
            if isinstance(played, datetime):
                d = (played - timedelta(minutes=tz_offset)).date()
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
            span = min(span, 90)

        days = [today - timedelta(days=i) for i in range(span - 1, -1, -1)]
        return [
            {"label": d.strftime("%d %b"), "count": counts.get(d, 0)} for d in days
        ]
