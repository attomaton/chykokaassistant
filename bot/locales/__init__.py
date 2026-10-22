"""Centralized customer-facing message catalog.

All customer-visible text lives here, keyed by a stable message key, so
handlers never hardcode a user-facing string and a future locale can be
added without touching handler code. Ukrainian (`uk`) is the default and
the fallback locale: a key missing from any other locale resolves to the
Ukrainian text rather than leaking an English/technical string.
"""
from __future__ import annotations

from bot.locales import uk as _uk

DEFAULT_LOCALE = "uk"

LOCALES: dict[str, dict[str, str]] = {
    "uk": _uk.MESSAGES,
}


class MissingTranslationError(KeyError):
    """Raised when a key exists in no locale at all, including the fallback."""


def t(key: str, locale: str | None = None, **kwargs: object) -> str:
    """Resolve a message key, falling back to Ukrainian, then formatting it.

    An unknown `locale` and a key missing from a known locale both fall back
    to `DEFAULT_LOCALE`. A key present in no locale is a programming error and
    raises, so a broken key can never be silently shown to a customer.
    """
    catalog = LOCALES.get(locale or DEFAULT_LOCALE)
    if catalog is None or key not in catalog:
        catalog = LOCALES[DEFAULT_LOCALE]
    if key not in catalog:
        raise MissingTranslationError(key)
    template = catalog[key]
    return template.format(**kwargs) if kwargs else template
