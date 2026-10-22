from __future__ import annotations

from bot.handlers import admin as admin_handlers
from bot.middleware.auth import is_admin
from database.repositories.user_repository import UserRepository
from tests.conftest import make_ctx


async def test_is_admin_true_only_for_admin_role(session):
    users = UserRepository(session)
    customer = await users.get_or_create(
        telegram_user_id=1, username="c", first_name=None, last_name=None, language_code=None
    )
    admin = await users.get_or_create(
        telegram_user_id=2, username="a", first_name=None, last_name=None, language_code=None
    )
    admin.role = "admin"
    await session.commit()

    assert is_admin(admin) is True
    assert is_admin(customer) is False
    assert is_admin(None) is False


async def test_customer_cannot_invoke_admin_commands(session, settings, fake_telegram):
    ctx = make_ctx(session, settings, telegram=fake_telegram)
    users = UserRepository(session)
    customer = await users.get_or_create(
        telegram_user_id=3, username="c2", first_name=None, last_name=None, language_code=None
    )
    await session.commit()

    await admin_handlers.handle_admin_menu(ctx, customer)
    await admin_handlers.handle_requests(ctx, customer)
    await admin_handlers.handle_stats(ctx, customer)
    await admin_handlers.handle_reload(ctx, customer)

    assert len(fake_telegram.sent_messages) == 4
    for message in fake_telegram.sent_messages:
        assert "only available to the bot administrator" in message["text"]


async def test_customer_cannot_invoke_admin_callback(session, settings, fake_telegram):
    ctx = make_ctx(session, settings, telegram=fake_telegram)
    users = UserRepository(session)
    customer = await users.get_or_create(
        telegram_user_id=4, username="c3", first_name=None, last_name=None, language_code=None
    )
    await session.commit()

    await admin_handlers.handle_admin_callback(ctx, customer, "admin:resolve:abc123", "cbq-1")

    assert fake_telegram.answered_callbacks[-1]["text"] == "Not authorized."
    assert "only available to the bot administrator" in fake_telegram.sent_messages[-1]["text"]
