from __future__ import annotations

from bot.handlers import admin as admin_handlers
from database.repositories.user_repository import UserRepository
from tests.conftest import make_ctx


async def test_claim_registers_first_admin(session, settings, fake_telegram):
    ctx = make_ctx(session, settings, telegram=fake_telegram)
    users = UserRepository(session)
    user = await users.get_or_create(
        telegram_user_id=111, username="alice", first_name="Alice", last_name=None, language_code="en"
    )
    await session.commit()

    await admin_handlers.handle_claim(ctx, user, settings.admin_setup_secret)
    await session.commit()

    refreshed = await users.get_by_telegram_id(111)
    assert refreshed.role == "admin"
    assert "administrator" in fake_telegram.sent_messages[-1]["text"].lower()


async def test_claim_rejects_wrong_secret(session, settings, fake_telegram):
    ctx = make_ctx(session, settings, telegram=fake_telegram)
    users = UserRepository(session)
    user = await users.get_or_create(
        telegram_user_id=222, username="bob", first_name="Bob", last_name=None, language_code="en"
    )
    await session.commit()

    await admin_handlers.handle_claim(ctx, user, "wrong-secret")
    await session.commit()

    refreshed = await users.get_by_telegram_id(222)
    assert refreshed.role == "customer"
    assert "invalid" in fake_telegram.sent_messages[-1]["text"].lower()


async def test_second_claim_attempt_is_rejected(session, settings, fake_telegram):
    ctx = make_ctx(session, settings, telegram=fake_telegram)
    users = UserRepository(session)
    first = await users.get_or_create(
        telegram_user_id=333, username="carol", first_name="Carol", last_name=None, language_code="en"
    )
    second = await users.get_or_create(
        telegram_user_id=444, username="dave", first_name="Dave", last_name=None, language_code="en"
    )
    await session.commit()

    await admin_handlers.handle_claim(ctx, first, settings.admin_setup_secret)
    await session.commit()

    await admin_handlers.handle_claim(ctx, second, settings.admin_setup_secret)
    await session.commit()

    refreshed_second = await users.get_by_telegram_id(444)
    assert refreshed_second.role == "customer"
    assert "already been registered" in fake_telegram.sent_messages[-1]["text"].lower()


async def test_claim_disabled_when_admin_telegram_id_configured(session, settings, fake_telegram, monkeypatch):
    monkeypatch.setattr(settings, "admin_telegram_id", 999)
    ctx = make_ctx(session, settings, telegram=fake_telegram)
    users = UserRepository(session)
    user = await users.get_or_create(
        telegram_user_id=555, username="erin", first_name="Erin", last_name=None, language_code="en"
    )
    await session.commit()

    await admin_handlers.handle_claim(ctx, user, settings.admin_setup_secret)
    await session.commit()

    refreshed = await users.get_by_telegram_id(555)
    assert refreshed.role == "customer"
    assert "disabled" in fake_telegram.sent_messages[-1]["text"].lower()


async def test_ensure_seeded_admin_auto_installs_configured_id(session):
    users = UserRepository(session)
    await users.ensure_seeded_admin(777)
    await session.commit()

    admin = await users.get_by_telegram_id(777)
    assert admin is not None
    assert admin.role == "admin"
