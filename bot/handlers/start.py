"""Customer-facing informational commands: /start, /help, /privacy.

Message text lives in `bot/locales`, not here - see that package for the
Ukrainian catalog and the fallback rules.
"""
from __future__ import annotations

from bot.context import BotContext
from bot.locales import t
from database.models import User


async def handle_start(ctx: BotContext, user: User) -> None:
    await ctx.telegram.send_message(user.telegram_user_id, t("start_message"))


async def handle_help(ctx: BotContext, user: User) -> None:
    await ctx.telegram.send_message(user.telegram_user_id, t("help_message"))


async def handle_privacy(ctx: BotContext, user: User) -> None:
    await ctx.telegram.send_message(user.telegram_user_id, t("privacy_message"))
