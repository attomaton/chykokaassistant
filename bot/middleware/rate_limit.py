"""DB-backed fixed-window rate limiting, per Telegram user.

Implemented against the database (not process memory) because Vercel
serverless instances do not share memory, and a purely in-memory limiter
would be trivially bypassed by requests landing on different instances.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from database.models import User

WINDOW = timedelta(seconds=60)


class RateLimitExceeded(Exception):
    pass


def enforce_rate_limit(user: User, limit_per_minute: int) -> None:
    now = datetime.now(timezone.utc)
    window_start = user.rate_window_start
    if window_start is not None and window_start.tzinfo is None:
        window_start = window_start.replace(tzinfo=timezone.utc)

    if window_start is None or now - window_start > WINDOW:
        user.rate_window_start = now
        user.rate_window_count = 1
        return

    user.rate_window_count = (user.rate_window_count or 0) + 1
    if user.rate_window_count > limit_per_minute:
        raise RateLimitExceeded()
