"""Administrator authorization checks.

Every admin-only command or callback must call `is_admin` and re-verify
against the database on every single request. The Telegram user ID on an
incoming update/callback_query always comes from Telegram's own servers (it
cannot be spoofed by the client), so checking it against the stored admin
record is a sufficient and necessary authorization boundary - callback_data
strings must never be trusted as proof of privilege by themselves.
"""
from __future__ import annotations

from database.models import User, UserRole


def is_admin(user: User | None) -> bool:
    return bool(user and user.role == UserRole.ADMIN.value)
