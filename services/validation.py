"""Small, dependency-free validators for customer-supplied contact details.

Each validator returns None when valid, or a ready-to-send customer-facing
error message (resolved through `bot.locales`) when invalid.
"""
from __future__ import annotations

import re

from bot.locales import t

NAME_MIN_LENGTH = 2
NAME_MAX_LENGTH = 80
PHONE_MAX_LENGTH = 32
EMAIL_MAX_LENGTH = 128

_PHONE_RE = re.compile(r"^\+?[0-9][0-9\s\-()]{5,19}[0-9]$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def validate_name(value: str) -> str | None:
    value = value.strip()
    if not (NAME_MIN_LENGTH <= len(value) <= NAME_MAX_LENGTH):
        return t("invalid_name", min_length=NAME_MIN_LENGTH, max_length=NAME_MAX_LENGTH)
    return None


def validate_phone(value: str) -> str | None:
    value = value.strip()
    if len(value) > PHONE_MAX_LENGTH or not _PHONE_RE.match(value):
        return t("invalid_phone")
    return None


def validate_email(value: str) -> str | None:
    value = value.strip()
    if len(value) > EMAIL_MAX_LENGTH or not _EMAIL_RE.match(value):
        return t("invalid_email")
    return None
