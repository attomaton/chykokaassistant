"""Localization: every customer-facing key resolves to Ukrainian text."""
from __future__ import annotations

import re

import pytest

from bot.locales import DEFAULT_LOCALE, LOCALES, MissingTranslationError, t
from bot.locales.uk import MESSAGES

# Keys the spec requires to exist by name.
REQUIRED_KEYS = {
    "start_message",
    "help_message",
    "privacy_message",
    "unknown_answer",
    "offer_manager",
    "btn_leave_contacts",
    "btn_cancel",
    "btn_share_phone",
    "btn_skip",
    "btn_back",
    "btn_confirm",
    "request_saved",
    "request_forwarded",
    "invalid_phone",
    "invalid_email",
    "service_unavailable",
    "openai_unavailable",
    "manager_unavailable",
}

CYRILLIC_RE = re.compile(r"[а-яїієґА-ЯЇІЄҐ]")
# Latin words that are legitimately not translated: commands, brand, protocol.
ALLOWED_LATIN = re.compile(
    r"(/\w+|Lakomka Store|Telegram|OpenAI|Email|email|UAH|\{[a-z_]+\})"
)


def test_default_locale_is_ukrainian():
    assert DEFAULT_LOCALE == "uk"
    assert "uk" in LOCALES


def test_required_keys_exist():
    missing = REQUIRED_KEYS - set(MESSAGES)
    assert not missing, f"missing localization keys: {sorted(missing)}"


@pytest.mark.parametrize("key", sorted(MESSAGES))
def test_every_message_is_ukrainian(key):
    """No customer-facing value may be English prose."""
    value = MESSAGES[key]
    assert value.strip(), f"{key} is empty"
    assert CYRILLIC_RE.search(value), f"{key} has no Ukrainian text: {value!r}"


@pytest.mark.parametrize("key", sorted(MESSAGES))
def test_no_untranslated_english_words(key):
    """Catch leftover English phrases hiding inside an otherwise Ukrainian string."""
    stripped = ALLOWED_LATIN.sub("", MESSAGES[key])
    leftover = re.findall(r"[A-Za-z]{3,}", stripped)
    assert not leftover, f"{key} contains untranslated English: {leftover}"


def test_missing_key_falls_back_to_ukrainian():
    """An unknown locale resolves through the Ukrainian catalog, not an error."""
    assert t("cancelled", locale="fr") == MESSAGES["cancelled"]
    assert t("cancelled", locale=None) == MESSAGES["cancelled"]


def test_unknown_key_raises_rather_than_leaking_a_placeholder():
    with pytest.raises(MissingTranslationError):
        t("this_key_does_not_exist")


def test_formatting_arguments_are_substituted():
    rendered = t("request_forwarded", public_id="abc123")
    assert "abc123" in rendered
    assert "{public_id}" not in rendered
