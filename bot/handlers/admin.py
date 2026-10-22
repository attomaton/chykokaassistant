"""Administrator commands and callbacks.

Every entry point re-verifies the caller is the registered administrator via
`is_admin`, checked against the database on this request - never trusting
callback_data or prior state alone.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from bot.context import BotContext
from bot.keyboards.admin_kb import admin_menu_keyboard, admin_reply_confirm_keyboard, resolve_prompt_keyboard
from bot.locales import t
from bot.middleware.auth import is_admin
from bot.states.definitions import KEY_DRAFT, KEY_REQUEST_ID, FSMState
from database.models import DeliveryStatus, User
from database.repositories.admin_reply_repository import AdminReplyRepository
from database.repositories.support_request_repository import SupportRequestRepository
from database.repositories.user_repository import UserRepository
from services.knowledge_service import KnowledgeBaseError
from services.telegram_service import TelegramAPIError

logger = logging.getLogger(__name__)

NOT_ADMIN_MESSAGE = "This action is only available to the bot administrator."


async def _reject_non_admin(ctx: BotContext, user: User) -> None:
    logger.warning("unauthorized_admin_action_attempt telegram_user_id=%s", user.telegram_user_id)
    await ctx.telegram.send_message(user.telegram_user_id, NOT_ADMIN_MESSAGE)


async def handle_claim(ctx: BotContext, user: User, secret_arg: str | None) -> None:
    user_repo = UserRepository(ctx.session)

    if ctx.settings.admin_telegram_id is not None:
        await ctx.telegram.send_message(
            user.telegram_user_id, "Administrator claiming is disabled for this bot."
        )
        return

    if await user_repo.get_admin() is not None:
        await ctx.telegram.send_message(
            user.telegram_user_id, "An administrator has already been registered for this bot."
        )
        return

    if not ctx.settings.admin_setup_secret:
        await ctx.telegram.send_message(
            user.telegram_user_id, "Administrator claiming is not configured for this bot."
        )
        return

    if not secret_arg or secret_arg.strip() != ctx.settings.admin_setup_secret:
        logger.warning("admin_claim_failed telegram_user_id=%s", user.telegram_user_id)
        await ctx.telegram.send_message(user.telegram_user_id, "Invalid or missing setup secret.")
        return

    claimed = await user_repo.claim_admin_if_none_exists(user.id, user.telegram_user_id)
    if not claimed:
        await ctx.telegram.send_message(
            user.telegram_user_id, "An administrator has already been registered for this bot."
        )
        return

    logger.info("admin_claimed telegram_user_id=%s", user.telegram_user_id)
    await ctx.telegram.send_message(
        user.telegram_user_id, "You are now registered as the administrator for this bot."
    )


async def handle_admin_menu(ctx: BotContext, user: User) -> None:
    if not is_admin(user):
        await _reject_non_admin(ctx, user)
        return
    await ctx.telegram.send_message(
        user.telegram_user_id, "Administrator menu:", reply_markup=admin_menu_keyboard()
    )


async def handle_requests(ctx: BotContext, user: User) -> None:
    if not is_admin(user):
        await _reject_non_admin(ctx, user)
        return
    from bot.keyboards.admin_kb import admin_request_keyboard

    requests_repo = SupportRequestRepository(ctx.session)
    requests = await requests_repo.list_unresolved(limit=10)
    if not requests:
        await ctx.telegram.send_message(user.telegram_user_id, "No unresolved requests right now.")
        return

    await ctx.telegram.send_message(user.telegram_user_id, f"Recent unresolved requests ({len(requests)}):")
    for request in requests:
        snippet = request.original_question[:200]
        text = (
            f"#{request.public_request_id} [{request.status}]\n"
            f"Q: {snippet}\n"
            f"Created: {request.created_at}"
        )
        await ctx.telegram.send_message(
            user.telegram_user_id, text, reply_markup=admin_request_keyboard(request.public_request_id)
        )


async def handle_stats(ctx: BotContext, user: User) -> None:
    if not is_admin(user):
        await _reject_non_admin(ctx, user)
        return
    users_repo = UserRepository(ctx.session)
    requests_repo = SupportRequestRepository(ctx.session)

    customers = await users_repo.count_customers()
    total_requests = await requests_repo.count_total()
    pending = await requests_repo.count_by_status("pending")
    notified = await requests_repo.count_by_status("notified")
    resolved = await requests_repo.count_by_status("resolved")
    since = datetime.now(timezone.utc) - timedelta(days=1)
    last_24h = await requests_repo.count_created_since(since)

    text = (
        "Bot statistics:\n"
        f"Customers: {customers}\n"
        f"Total support requests: {total_requests}\n"
        f"  Pending: {pending}\n"
        f"  Notified (awaiting reply): {notified}\n"
        f"  Resolved: {resolved}\n"
        f"Requests in the last 24h: {last_24h}"
    )
    await ctx.telegram.send_message(user.telegram_user_id, text)


async def handle_reload(ctx: BotContext, user: User) -> None:
    if not is_admin(user):
        await _reject_non_admin(ctx, user)
        return
    try:
        kb = ctx.knowledge.reload()
    except KnowledgeBaseError as exc:
        logger.error("kb_reload_failed error=%s", str(exc))
        await ctx.telegram.send_message(user.telegram_user_id, f"Failed to reload knowledge base: {exc}")
        return
    await ctx.telegram.send_message(
        user.telegram_user_id,
        f"Knowledge base reloaded. hash={kb.content_hash} chars={kb.char_count}",
    )


async def handle_admin_text(ctx: BotContext, user: User, text: str) -> bool:
    """Handle free text while the admin is composing a reply.

    Returns True if the text was consumed by the admin reply flow.
    """
    if user.fsm_state != FSMState.ADMIN_AWAITING_REPLY:
        return False
    if not is_admin(user):
        return False

    text = text.strip()
    if not text:
        return True
    if len(text) > ctx.settings.max_message_length:
        await ctx.telegram.send_message(
            user.telegram_user_id,
            f"Reply is too long (max {ctx.settings.max_message_length} characters).",
        )
        return True

    data = dict(user.fsm_data or {})
    data[KEY_DRAFT] = text
    user.fsm_data = data
    user.fsm_state = FSMState.ADMIN_CONFIRM_REPLY

    public_id = data.get(KEY_REQUEST_ID, "")
    await ctx.telegram.send_message(
        user.telegram_user_id,
        f"Preview of your reply to request #{public_id}:\n\n{text}",
        reply_markup=admin_reply_confirm_keyboard(public_id),
    )
    return True


async def handle_admin_callback(ctx: BotContext, user: User, callback_data: str, callback_query_id: str) -> None:
    if not is_admin(user):
        await ctx.telegram.answer_callback_query(callback_query_id, "Not authorized.")
        await _reject_non_admin(ctx, user)
        return

    await ctx.telegram.answer_callback_query(callback_query_id)
    parts = callback_data.split(":")
    action = parts[1] if len(parts) > 1 else ""

    if action == "requests":
        await handle_requests(ctx, user)
        return
    if action == "stats":
        await handle_stats(ctx, user)
        return
    if action == "reload":
        await handle_reload(ctx, user)
        return

    public_id = parts[2] if len(parts) > 2 else ""
    requests_repo = SupportRequestRepository(ctx.session)

    if action == "reply":
        request = await requests_repo.get_by_public_id(public_id)
        if request is None:
            await ctx.telegram.send_message(user.telegram_user_id, "Request not found.")
            return
        user.fsm_state = FSMState.ADMIN_AWAITING_REPLY
        user.fsm_data = {KEY_REQUEST_ID: public_id}
        await ctx.telegram.send_message(
            user.telegram_user_id, f"Type your reply to request #{public_id}:"
        )
        return

    if action == "cancel_reply":
        user.fsm_state = FSMState.NONE
        user.fsm_data = {}
        await ctx.telegram.send_message(user.telegram_user_id, "Reply cancelled.")
        return

    if action == "send_reply":
        await _send_admin_reply(ctx, user, public_id)
        return

    if action == "resolve":
        request = await requests_repo.get_by_public_id(public_id)
        if request is None:
            await ctx.telegram.send_message(user.telegram_user_id, "Request not found.")
            return
        await requests_repo.mark_resolved(request)
        await ctx.telegram.send_message(user.telegram_user_id, f"Request #{public_id} marked resolved.")
        return

    if action == "skip_resolve":
        await ctx.telegram.send_message(user.telegram_user_id, "Okay, left unresolved.")
        return

    if action == "view":
        await _send_request_details(ctx, user, public_id)
        return


async def _send_admin_reply(ctx: BotContext, user: User, public_id: str) -> None:
    requests_repo = SupportRequestRepository(ctx.session)
    request = await requests_repo.get_by_public_id(public_id)
    if request is None:
        await ctx.telegram.send_message(user.telegram_user_id, "Request not found.")
        user.fsm_state = FSMState.NONE
        user.fsm_data = {}
        return

    data = dict(user.fsm_data or {})
    draft = data.get(KEY_DRAFT, "")
    if not draft:
        await ctx.telegram.send_message(user.telegram_user_id, "No draft reply found, please try again.")
        user.fsm_state = FSMState.NONE
        user.fsm_data = {}
        return

    customer_repo = UserRepository(ctx.session)
    customer = await customer_repo.get_by_pk(request.user_id) if request.user_id else None

    delivery_status = DeliveryStatus.FAILED.value
    if customer is not None:
        try:
            await ctx.telegram.send_message(
                customer.telegram_user_id,
                t("admin_reply_to_customer", public_id=public_id, message=draft),
            )
            delivery_status = DeliveryStatus.SENT.value
        except TelegramAPIError:
            logger.error("admin_reply_delivery_failed request_id=%s", public_id)
            delivery_status = DeliveryStatus.FAILED.value
    else:
        logger.error("admin_reply_no_customer request_id=%s", public_id)

    await AdminReplyRepository(ctx.session).create(
        support_request_id=request.id,
        admin_user_id=user.id,
        message=draft,
        delivery_status=delivery_status,
    )

    user.fsm_state = FSMState.NONE
    user.fsm_data = {}

    if delivery_status == DeliveryStatus.SENT.value:
        await ctx.telegram.send_message(user.telegram_user_id, "Reply sent to the customer.")
    else:
        await ctx.telegram.send_message(
            user.telegram_user_id,
            "Reply saved, but delivery to the customer failed (they may have "
            "blocked the bot). You can retry by replying again.",
        )

    await ctx.telegram.send_message(
        user.telegram_user_id,
        "Mark this request as resolved?",
        reply_markup=resolve_prompt_keyboard(public_id),
    )


async def _send_request_details(ctx: BotContext, user: User, public_id: str) -> None:
    requests_repo = SupportRequestRepository(ctx.session)
    request = await requests_repo.get_by_public_id(public_id)
    if request is None:
        await ctx.telegram.send_message(user.telegram_user_id, "Request not found.")
        return

    customer_repo = UserRepository(ctx.session)
    customer = await customer_repo.get_by_pk(request.user_id) if request.user_id else None
    username = f"@{customer.username}" if customer and customer.username else "N/A"
    telegram_id = customer.telegram_user_id if customer else "N/A"
    missing = ", ".join(request.missing_information or []) or "N/A"

    text = (
        f"Request #{request.public_request_id}\n"
        f"Status: {request.status}\n\n"
        f"Customer:\n"
        f"Name: {request.customer_name or 'N/A'}\n"
        f"Phone: {request.customer_phone or 'N/A'}\n"
        f"Email: {request.customer_email or 'N/A'}\n"
        f"Telegram: {username}\n"
        f"Telegram ID: {telegram_id}\n\n"
        f"Original question:\n{request.original_question}\n\n"
        f"AI escalation reason:\n{request.escalation_reason or 'N/A'}\n\n"
        f"Missing information:\n{missing}\n\n"
        f"Created: {request.created_at}\n"
        f"Admin notified: {request.admin_notified_at or 'not yet'}\n"
        f"Resolved: {request.resolved_at or 'not yet'}"
    )
    await ctx.telegram.send_message(user.telegram_user_id, text)
