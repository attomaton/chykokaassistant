"""Customer conversation flow: AI Q&A, escalation offer, and contact
collection. All multi-step state lives in `user.fsm_state` / `user.fsm_data`
because Vercel functions cannot rely on in-process memory between updates.
"""
from __future__ import annotations

import logging

from bot.context import BotContext
from bot.locales import t
from bot.keyboards.customer_kb import (
    confirm_contact_keyboard,
    contact_share_keyboard,
    delete_data_confirm_keyboard,
    escalation_offer_keyboard,
    remove_keyboard,
    skip_back_cancel_keyboard,
)
from bot.states.definitions import (
    KEY_EMAIL,
    KEY_MISSING,
    KEY_NAME,
    KEY_PHONE,
    KEY_QUESTION,
    KEY_REASON,
    FSMState,
)
from database.models import User
from database.repositories.conversation_repository import ConversationRepository
from database.repositories.user_repository import UserRepository
from services.catalog_service import CatalogService
from services.escalation_service import EscalationService
from services.knowledge_service import KnowledgeBaseError
from services.openai_service import OpenAIServiceError
from services.recommendation_service import build_recommendation, parse_budget
from services.validation import validate_email, validate_name, validate_phone

logger = logging.getLogger(__name__)


def _reset_fsm(user: User) -> None:
    user.fsm_state = FSMState.NONE
    user.fsm_data = {}


async def handle_new(ctx: BotContext, user: User) -> None:
    await ConversationRepository(ctx.session).clear(user.id)
    _reset_fsm(user)
    await ctx.telegram.send_message(user.telegram_user_id, t("conversation_cleared"))


async def handle_cancel(ctx: BotContext, user: User) -> None:
    had_state = user.fsm_state not in (None, FSMState.NONE)
    _reset_fsm(user)
    if had_state:
        await ctx.telegram.send_message(
            user.telegram_user_id, t("cancelled"), reply_markup=remove_keyboard()
        )
    else:
        await ctx.telegram.send_message(user.telegram_user_id, t("nothing_to_cancel"))


async def handle_delete_my_data_command(ctx: BotContext, user: User) -> None:
    user.fsm_state = FSMState.AWAITING_DELETE_CONFIRM
    user.fsm_data = {}
    await ctx.telegram.send_message(
        user.telegram_user_id,
        t("delete_data_confirm"),
        reply_markup=delete_data_confirm_keyboard(),
    )


async def _offer_escalation(
    ctx: BotContext,
    user: User,
    *,
    original_question: str,
    reason: str,
    missing_information: list[str],
    message_key: str = "unknown_answer",
) -> None:
    user.fsm_state = FSMState.AWAITING_ESCALATION_CONFIRM
    user.fsm_data = {
        KEY_QUESTION: original_question[:4000],
        KEY_REASON: (reason or "")[:500],
        KEY_MISSING: (missing_information or [])[:20],
    }
    await ctx.telegram.send_message(
        user.telegram_user_id,
        t(message_key),
        reply_markup=escalation_offer_keyboard(),
    )


async def handle_text_message(ctx: BotContext, user: User, text: str) -> None:
    text = text.strip()
    if not text:
        return

    state = user.fsm_state or FSMState.NONE

    if state == FSMState.COLLECTING_NAME:
        await _handle_collect_name(ctx, user, text)
        return
    if state == FSMState.COLLECTING_PHONE:
        await _handle_collect_phone(ctx, user, text)
        return
    if state == FSMState.COLLECTING_EMAIL:
        await _handle_collect_email(ctx, user, text)
        return

    # Any other in-progress state means we're waiting on a button press, not
    # free text - gently remind the customer instead of silently ignoring.
    if state not in (FSMState.NONE, None):
        await ctx.telegram.send_message(user.telegram_user_id, t("use_buttons"))
        return

    await _handle_qa_message(ctx, user, text)


async def _handle_qa_message(ctx: BotContext, user: User, text: str) -> None:
    if len(text) > ctx.settings.max_message_length:
        await ctx.telegram.send_message(
            user.telegram_user_id,
            t("message_too_long", max_length=ctx.settings.max_message_length),
        )
        return

    conv_repo = ConversationRepository(ctx.session)
    await conv_repo.add(user.id, "user", text)
    history = await conv_repo.get_recent(user.id, ctx.settings.max_conversation_turns, ctx.settings.conversation_ttl_minutes)
    # Exclude the turn we just added from what we send as "history" context;
    # it is passed separately as the current customer_message.
    history_for_model = [{"role": h.role, "content": h.content} for h in history[:-1]]

    try:
        kb = ctx.knowledge.load()
    except KnowledgeBaseError:
        logger.error("knowledge_base_unavailable")
        await _offer_escalation(
            ctx,
            user,
            original_question=text,
            reason="Knowledge base unavailable",
            missing_information=[],
            message_key="service_unavailable",
        )
        return

    catalog = CatalogService(kb.content)

    try:
        result = await ctx.openai_service.get_structured_answer(
            business_knowledge=kb.content,
            conversation_history=history_for_model,
            customer_message=text,
            catalog_block=catalog.catalog_prompt_block(),
        )
    except OpenAIServiceError:
        logger.error("ai_service_unavailable")
        await _offer_escalation(
            ctx,
            user,
            original_question=text,
            reason="AI service unavailable",
            missing_information=[],
            message_key="openai_unavailable",
        )
        return

    confident_enough = result.confidence >= ctx.settings.ai_confidence_threshold

    if result.status == "recommend" and confident_enough:
        await _handle_recommendation(ctx, user, text, result, catalog, conv_repo)
        return

    if result.status == "answered" and confident_enough:
        await conv_repo.add(user.id, "assistant", result.answer)
        await ctx.telegram.send_message(user.telegram_user_id, result.answer)
        return

    if result.status == "needs_clarification" and confident_enough:
        follow_up = result.suggested_follow_up_question or result.answer
        await conv_repo.add(user.id, "assistant", follow_up)
        await ctx.telegram.send_message(user.telegram_user_id, follow_up)
        return

    # status == "escalate", or confidence too low to trust the other statuses.
    await conv_repo.add(user.id, "assistant", result.answer)
    await _offer_escalation(
        ctx,
        user,
        original_question=text,
        reason=result.reason or "Low confidence answer",
        missing_information=result.missing_information,
    )


async def _handle_recommendation(
    ctx: BotContext,
    user: User,
    text: str,
    result,
    catalog: CatalogService,
    conv_repo: ConversationRepository,
) -> None:
    """Send a recommendation only after the backend has validated it.

    Product IDs the model invented are dropped here, prices come from the
    catalog, and a recommendation that survives none of that falls through to
    the normal escalation offer rather than being patched up.
    """
    outcome = build_recommendation(
        answer=result.answer,
        recommended_product_ids=result.recommended_product_ids,
        external_suggestions=result.external_suggestions,
        catalog=catalog,
        budget=parse_budget(text),
    )

    if outcome.should_escalate or outcome.text is None:
        logger.warning(
            "recommendation_rejected reason=%s rejected_ids=%s",
            outcome.escalation_reason,
            outcome.rejected_product_ids,
        )
        await _offer_escalation(
            ctx,
            user,
            original_question=text,
            reason=outcome.escalation_reason or "Recommendation failed validation",
            missing_information=result.missing_information,
        )
        return

    await conv_repo.add(user.id, "assistant", outcome.text)
    await ctx.telegram.send_message(user.telegram_user_id, outcome.text)


async def handle_contact_shared(ctx: BotContext, user: User, phone_number: str) -> None:
    if user.fsm_state != FSMState.COLLECTING_PHONE:
        return
    data = dict(user.fsm_data or {})
    data[KEY_PHONE] = phone_number.strip()[:32]
    user.fsm_data = data
    user.fsm_state = FSMState.COLLECTING_EMAIL
    await ctx.telegram.send_message(
        user.telegram_user_id,
        t("ask_email"),
        reply_markup=skip_back_cancel_keyboard("email"),
    )


async def _handle_collect_name(ctx: BotContext, user: User, text: str) -> None:
    error = validate_name(text)
    if error:
        await ctx.telegram.send_message(user.telegram_user_id, error)
        return
    data = dict(user.fsm_data or {})
    data[KEY_NAME] = text.strip()[:128]
    user.fsm_data = data
    user.fsm_state = FSMState.COLLECTING_PHONE
    await ctx.telegram.send_message(
        user.telegram_user_id,
        t("ask_phone"),
        reply_markup=contact_share_keyboard(),
    )
    await ctx.telegram.send_message(
        user.telegram_user_id,
        t("need_one_contact"),
        reply_markup=skip_back_cancel_keyboard("phone", allow_back=False),
    )


async def _handle_collect_phone(ctx: BotContext, user: User, text: str) -> None:
    error = validate_phone(text)
    if error:
        await ctx.telegram.send_message(user.telegram_user_id, error)
        return
    data = dict(user.fsm_data or {})
    data[KEY_PHONE] = text.strip()[:32]
    user.fsm_data = data
    user.fsm_state = FSMState.COLLECTING_EMAIL
    await ctx.telegram.send_message(
        user.telegram_user_id,
        t("ask_email"),
        reply_markup=skip_back_cancel_keyboard("email"),
    )


async def _handle_collect_email(ctx: BotContext, user: User, text: str) -> None:
    error = validate_email(text)
    if error:
        await ctx.telegram.send_message(user.telegram_user_id, error)
        return
    data = dict(user.fsm_data or {})
    data[KEY_EMAIL] = text.strip()[:128]
    user.fsm_data = data
    await _go_to_confirmation(ctx, user)


async def _go_to_confirmation(ctx: BotContext, user: User) -> None:
    data = dict(user.fsm_data or {})
    if not data.get(KEY_PHONE) and not data.get(KEY_EMAIL):
        user.fsm_state = FSMState.COLLECTING_PHONE
        await ctx.telegram.send_message(
            user.telegram_user_id,
            t("need_one_contact"),
            reply_markup=contact_share_keyboard(),
        )
        return

    user.fsm_state = FSMState.CONFIRMING_CONTACT
    unset = t("not_specified")
    summary = t(
        "confirm_contact",
        name=data.get(KEY_NAME) or unset,
        phone=data.get(KEY_PHONE) or unset,
        email=data.get(KEY_EMAIL) or unset,
        question=data.get(KEY_QUESTION) or unset,
    )
    await ctx.telegram.send_message(
        user.telegram_user_id, summary, reply_markup=remove_keyboard()
    )
    await ctx.telegram.send_message(
        user.telegram_user_id, t("confirm_send_question"), reply_markup=confirm_contact_keyboard()
    )


async def handle_callback(ctx: BotContext, user: User, callback_data: str, callback_query_id: str) -> None:
    if callback_data == "esc:contact":
        if user.fsm_state != FSMState.AWAITING_ESCALATION_CONFIRM:
            await ctx.telegram.answer_callback_query(callback_query_id)
            return
        user.fsm_state = FSMState.COLLECTING_NAME
        await ctx.telegram.answer_callback_query(callback_query_id)
        await ctx.telegram.send_message(user.telegram_user_id, t("ask_name"))
        return

    if callback_data == "esc:cancel":
        _reset_fsm(user)
        await ctx.telegram.answer_callback_query(callback_query_id)
        await ctx.telegram.send_message(
            user.telegram_user_id, t("escalation_cancelled"), reply_markup=remove_keyboard()
        )
        return

    if callback_data.startswith("field:skip:"):
        field = callback_data.split(":", 2)[2]
        await ctx.telegram.answer_callback_query(callback_query_id)
        if field == "phone" and user.fsm_state == FSMState.COLLECTING_PHONE:
            data = dict(user.fsm_data or {})
            data.pop(KEY_PHONE, None)
            user.fsm_data = data
            user.fsm_state = FSMState.COLLECTING_EMAIL
            await ctx.telegram.send_message(
                user.telegram_user_id,
                t("ask_email"),
                reply_markup=skip_back_cancel_keyboard("email"),
            )
        elif field == "email" and user.fsm_state == FSMState.COLLECTING_EMAIL:
            data = dict(user.fsm_data or {})
            data.pop(KEY_EMAIL, None)
            user.fsm_data = data
            await _go_to_confirmation(ctx, user)
        return

    if callback_data.startswith("field:back:"):
        field = callback_data.split(":", 2)[2]
        await ctx.telegram.answer_callback_query(callback_query_id)
        if field == "email" or field == "confirm":
            user.fsm_state = FSMState.COLLECTING_PHONE
            await ctx.telegram.send_message(
                user.telegram_user_id,
                t("ask_phone_again"),
                reply_markup=contact_share_keyboard(),
            )
        return

    if callback_data == "contact:confirm":
        await ctx.telegram.answer_callback_query(callback_query_id)
        if user.fsm_state != FSMState.CONFIRMING_CONTACT:
            return
        await _submit_contact(ctx, user)
        return

    if callback_data == "delete:confirm":
        await ctx.telegram.answer_callback_query(callback_query_id)
        if user.fsm_state != FSMState.AWAITING_DELETE_CONFIRM:
            return
        await ConversationRepository(ctx.session).clear(user.id)
        await UserRepository(ctx.session).delete_personal_data(user)
        _reset_fsm(user)
        await ctx.telegram.send_message(user.telegram_user_id, t("data_deleted"))
        return

    if callback_data == "delete:cancel":
        await ctx.telegram.answer_callback_query(callback_query_id)
        _reset_fsm(user)
        await ctx.telegram.send_message(user.telegram_user_id, t("data_delete_cancelled"))
        return

    await ctx.telegram.answer_callback_query(callback_query_id)


async def _submit_contact(ctx: BotContext, user: User) -> None:
    data = dict(user.fsm_data or {})
    escalation = EscalationService(ctx.session, ctx.telegram)
    public_id, notified = await escalation.create_and_notify(
        user=user,
        original_question=data.get(KEY_QUESTION, ""),
        escalation_reason=data.get(KEY_REASON, ""),
        missing_information=data.get(KEY_MISSING, []),
        customer_name=data.get(KEY_NAME),
        customer_phone=data.get(KEY_PHONE),
        customer_email=data.get(KEY_EMAIL),
    )
    _reset_fsm(user)

    key = "request_forwarded" if notified else "request_saved"
    await ctx.telegram.send_message(user.telegram_user_id, t(key, public_id=public_id))
