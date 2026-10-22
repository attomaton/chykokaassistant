from __future__ import annotations

from services.validation import validate_email, validate_name, validate_phone


def test_validate_name_accepts_reasonable_names():
    assert validate_name("Jo") is None
    assert validate_name("Jane Doe") is None


def test_validate_name_rejects_too_short_or_too_long():
    assert validate_name("J") is not None
    assert validate_name("x" * 200) is not None


def test_validate_phone_accepts_common_formats():
    assert validate_phone("+1 555 123 4567") is None
    assert validate_phone("555-123-4567") is None


def test_validate_phone_rejects_garbage():
    assert validate_phone("not-a-phone") is not None
    assert validate_phone("123") is not None


def test_validate_email_accepts_valid_address():
    assert validate_email("name@example.com") is None


def test_validate_email_rejects_invalid_address():
    assert validate_email("not-an-email") is not None
    assert validate_email("missing@domain") is not None
