"""Top-level update dispatcher.

Resolves/creates the sending user, enforces rate limiting, then routes to
the appropriate command / callback / message handler. This is the single
entry point called by the FastAPI webhook route.
"""
from __future__ import annotations

import logging
from typing import Any

from bot.context import BotContext
from bot.locales import t
from bot.handlers import admin as admin_handlers
from bot.handlers import customer as customer_handlers
from bot.handlers import start as start_handlers
from bot.middleware.auth import is_admin
from bot.middleware.rate_limit import RateLimitExceeded, enforce_rate_limit
from bot.states.definitions import FSMState
from database.repositories.user_repository import UserRepository

logger = logging.getLogger(__name__)

CUSTOMER_COMMANDS = {"/start", "/help", "/new", "/cancel", "/privacy", "/delete_my_data"}
ADMIN_COMMANDS = {"/admin", "/requests", "/stats", "/reload"}


def _strip_bot_suffix(command: str) -> str:
    # Telegram sends "/cmd@BotName" in group chats; strip the suffix.
    return command.split("@", 1)[0]


async def handle_update(ctx: BotContext, update: dict[str, Any]) -> None:
    if "callback_query" in update:
        await _handle_callback_query(ctx, update["callback_query"])
        return
    if "message" in update:
        await _handle_message(ctx, update["message"])
        return
    logger.info("update_ignored_unsupported_type")


async def _resolve_user(ctx: BotContext, from_user: dict[str, Any]):
    telegram_user_id = from_user.get("id")
    if telegram_user_id is None:
        return None
    repo = UserRepository(ctx.session)
    user = await repo.get_or_create(
        telegram_user_id=telegram_user_id,
        username=(from_user.get("username") or "")[:64] or None,
        first_name=(from_user.get("first_name") or "")[:128] or None,
        last_name=(from_user.get("last_name") or "")[:128] or None,
        language_code=(from_user.get("language_code") or "")[:8] or None,
    )
    return user


async def _handle_message(ctx: BotContext, message: dict[str, Any]) -> None:
    from_user = message.get("from") or {}
    user = await _resolve_user(ctx, from_user)
    if user is None:
        return

    try:
        enforce_rate_limit(user, ctx.settings.rate_limit_messages_per_minute)
    except RateLimitExceeded:
        logger.warning("rate_limit_exceeded telegram_user_id=%s", user.telegram_user_id)
        await ctx.telegram.send_message(user.telegram_user_id, t("rate_limited"))
        return

    contact = message.get("contact")
    if contact and contact.get("phone_number"):
        await customer_handlers.handle_contact_shared(ctx, user, contact["phone_number"])
        return

    text = message.get("text")
    if not text:
        return

    if text.startswith("/"):
        await _handle_command(ctx, user, text)
        return

    # Admin composing a reply takes priority over the generic Q&A flow.
    if is_admin(user) and (user.fsm_state or FSMState.NONE) == FSMState.ADMIN_AWAITING_REPLY:
        consumed = await admin_handlers.handle_admin_text(ctx, user, text)
        if consumed:
            return

    await customer_handlers.handle_text_message(ctx, user, text)


async def _handle_command(ctx: BotContext, user, raw_text: str) -> None:
    parts = raw_text.strip().split(maxsplit=1)
    command = _strip_bot_suffix(parts[0]).lower()
    args = parts[1] if len(parts) > 1 else None

    if command == "/start":
        await start_handlers.handle_start(ctx, user)
    elif command == "/help":
        await start_handlers.handle_help(ctx, user)
    elif command == "/privacy":
        await start_handlers.handle_privacy(ctx, user)
    elif command == "/new":
        await customer_handlers.handle_new(ctx, user)
    elif command == "/cancel":
        await customer_handlers.handle_cancel(ctx, user)
    elif command == "/delete_my_data":
        await customer_handlers.handle_delete_my_data_command(ctx, user)
    elif command == "/claim":
        await admin_handlers.handle_claim(ctx, user, args)
    elif command == "/admin":
        await admin_handlers.handle_admin_menu(ctx, user)
    elif command == "/requests":
        await admin_handlers.handle_requests(ctx, user)
    elif command == "/stats":
        await admin_handlers.handle_stats(ctx, user)
    elif command == "/reload":
        await admin_handlers.handle_reload(ctx, user)
    else:
        await ctx.telegram.send_message(user.telegram_user_id, t("unknown_command"))


async def _handle_callback_query(ctx: BotContext, callback_query: dict[str, Any]) -> None:
    from_user = callback_query.get("from") or {}
    user = await _resolve_user(ctx, from_user)
    callback_query_id = callback_query.get("id", "")
    data = callback_query.get("data") or ""

    if user is None:
        await ctx.telegram.answer_callback_query(callback_query_id)
        return

    try:
        enforce_rate_limit(user, ctx.settings.rate_limit_messages_per_minute)
    except RateLimitExceeded:
        await ctx.telegram.answer_callback_query(callback_query_id, t("rate_limited_callback"))
        return

    if data.startswith("admin:"):
        await admin_handlers.handle_admin_callback(ctx, user, data, callback_query_id)
        return

    await customer_handlers.handle_callback(ctx, user, data, callback_query_id)
