"""Every fallback, error, and contact-collection step must be Ukrainian."""
from __future__ import annotations

import re

from bot import router
from bot.handlers import customer as customer_handlers
from bot.keyboards.customer_kb import (
    confirm_contact_keyboard,
    contact_share_keyboard,
    delete_data_confirm_keyboard,
    escalation_offer_keyboard,
    skip_back_cancel_keyboard,
)
from bot.locales import t
from bot.states.definitions import FSMState
from database.repositories.user_repository import UserRepository
from services.knowledge_service import KnowledgeService
from services.openai_service import OpenAIServiceError
from services.validation import validate_email, validate_name, validate_phone
from tests.conftest import FakeOpenAIService, FakeTelegramService, make_ctx

LATIN_WORD_RE = re.compile(r"[A-Za-z]{3,}")
# Bot command names, the brand, and protocol nouns legitimately stay Latin.
ALLOWED_LATIN = re.compile(r"(/\w+|Lakomka Store|Telegram|OpenAI|Email|email)")


def _assert_ukrainian(text: str) -> None:
    leftover = LATIN_WORD_RE.findall(ALLOWED_LATIN.sub("", text))
    assert not leftover, f"untranslated English in customer message: {leftover} -> {text!r}"


async def _customer(session, telegram_user_id=777):
    user = await UserRepository(session).get_or_create(
        telegram_user_id=telegram_user_id, username="c", first_name=None, last_name=None, language_code=None
    )
    await session.commit()
    return user


async def test_openai_failure_fallback_is_ukrainian(session, settings, fake_telegram, tmp_path):
    path = tmp_path / "business.md"
    path.write_text("# Store\n\nSome content.", encoding="utf-8")
    ctx = make_ctx(
        session,
        settings,
        telegram=fake_telegram,
        openai_service=FakeOpenAIService(error=OpenAIServiceError("down")),
        knowledge=KnowledgeService(path, max_characters=80000),
    )
    user = await _customer(session)
    await customer_handlers.handle_text_message(ctx, user, "Скільки коштує хурма?")

    sent = fake_telegram.sent_messages[-1]["text"]
    assert sent == t("openai_unavailable")
    _assert_ukrainian(sent)
    assert user.fsm_state == FSMState.AWAITING_ESCALATION_CONFIRM


async def test_knowledge_base_failure_fallback_is_ukrainian(session, settings, fake_telegram, tmp_path):
    ctx = make_ctx(
        session,
        settings,
        telegram=fake_telegram,
        openai_service=FakeOpenAIService(None),
        knowledge=KnowledgeService(tmp_path / "missing.md", max_characters=80000),
    )
    user = await _customer(session)
    await customer_handlers.handle_text_message(ctx, user, "Питання")

    sent = fake_telegram.sent_messages[-1]["text"]
    assert sent == t("service_unavailable")
    _assert_ukrainian(sent)


async def test_telegram_failure_does_not_lose_the_saved_request(session, settings):
    """Admin notification failing must still yield a Ukrainian 'saved' message."""
    users = UserRepository(session)
    admin = await users.get_or_create(
        telegram_user_id=800, username="a", first_name=None, last_name=None, language_code=None
    )
    admin.role = "admin"
    customer = await _customer(session, telegram_user_id=801)

    # Only the admin's chat fails, so the customer still receives a reply.
    telegram = FakeTelegramService(fail_chat_ids={admin.telegram_user_id})
    ctx = make_ctx(session, settings, telegram=telegram)

    customer.fsm_state = FSMState.CONFIRMING_CONTACT
    customer.fsm_data = {"question": "q", "reason": "r", "missing": [], "phone": "+380661112233"}
    await session.commit()

    await customer_handlers.handle_callback(ctx, customer, "contact:confirm", "cbq")

    sent = telegram.sent_messages[-1]["text"]
    assert sent.startswith("Дякую!")
    assert "збережено" in sent
    _assert_ukrainian(sent)


async def test_contact_collection_flow_is_entirely_ukrainian(session, settings):
    telegram = FakeTelegramService()
    ctx = make_ctx(session, settings, telegram=telegram)
    customer = await _customer(session, telegram_user_id=802)
    customer.fsm_state = FSMState.AWAITING_ESCALATION_CONFIRM
    customer.fsm_data = {"question": "Чи є доставка?", "reason": "r", "missing": []}
    await session.commit()

    await customer_handlers.handle_callback(ctx, customer, "esc:contact", "c1")
    assert telegram.sent_messages[-1]["text"] == t("ask_name")

    await customer_handlers.handle_text_message(ctx, customer, "Олена")
    assert telegram.sent_messages[-2]["text"] == t("ask_phone")

    await customer_handlers.handle_text_message(ctx, customer, "+380661112233")
    assert telegram.sent_messages[-1]["text"] == t("ask_email")

    await customer_handlers.handle_callback(ctx, customer, "field:skip:email", "c2")
    assert customer.fsm_state == FSMState.CONFIRMING_CONTACT
    summary = telegram.sent_messages[-2]["text"]
    assert "Перевірте дані:" in summary
    assert "Олена" in summary
    assert "Чи є доставка?" in summary
    assert telegram.sent_messages[-1]["text"] == t("confirm_send_question")

    for message in telegram.sent_messages:
        _assert_ukrainian(message["text"])


async def test_validation_errors_are_ukrainian():
    assert validate_phone("nope") == t("invalid_phone")
    assert validate_email("nope") == t("invalid_email")
    assert validate_name("x") == t(
        "invalid_name", min_length=2, max_length=80
    )
    # Valid values still pass.
    assert validate_phone("+380661112233") is None
    assert validate_email("test@example.com") is None
    assert validate_name("Олена") is None


def test_all_keyboard_buttons_are_ukrainian():
    keyboards = [
        escalation_offer_keyboard(),
        contact_share_keyboard(),
        confirm_contact_keyboard(),
        delete_data_confirm_keyboard(),
        skip_back_cancel_keyboard("email"),
    ]
    labels = []
    for keyboard in keyboards:
        for row in keyboard.get("inline_keyboard", []) + keyboard.get("keyboard", []):
            labels.extend(button["text"] for button in row)

    assert labels, "no button labels found"
    for label in labels:
        _assert_ukrainian(label)
    assert t("btn_leave_contacts") in labels
    assert t("btn_share_phone") in labels


async def test_unknown_command_and_rate_limit_are_ukrainian(session, settings, fake_telegram):
    ctx = make_ctx(session, settings, telegram=fake_telegram)
    user = await _customer(session, telegram_user_id=803)

    await router._handle_command(ctx, user, "/definitelynotacommand")
    sent = fake_telegram.sent_messages[-1]["text"]
    assert sent == t("unknown_command")
    _assert_ukrainian(sent)


async def test_data_deletion_messages_are_ukrainian(session, settings, fake_telegram):
    ctx = make_ctx(session, settings, telegram=fake_telegram)
    user = await _customer(session, telegram_user_id=804)

    await customer_handlers.handle_delete_my_data_command(ctx, user)
    assert fake_telegram.sent_messages[-1]["text"] == t("delete_data_confirm")

    await customer_handlers.handle_callback(ctx, user, "delete:cancel", "c1")
    assert fake_telegram.sent_messages[-1]["text"] == t("data_delete_cancelled")

    for message in fake_telegram.sent_messages:
        _assert_ukrainian(message["text"])


async def test_cancel_and_new_are_ukrainian(session, settings, fake_telegram):
    ctx = make_ctx(session, settings, telegram=fake_telegram)
    user = await _customer(session, telegram_user_id=805)

    await customer_handlers.handle_cancel(ctx, user)
    assert fake_telegram.sent_messages[-1]["text"] == t("nothing_to_cancel")

    user.fsm_state = FSMState.COLLECTING_NAME
    await customer_handlers.handle_cancel(ctx, user)
    assert fake_telegram.sent_messages[-1]["text"] == t("cancelled")

    await customer_handlers.handle_new(ctx, user)
    assert fake_telegram.sent_messages[-1]["text"] == t("conversation_cleared")


async def test_message_too_long_error_is_ukrainian(session, settings, fake_telegram):
    ctx = make_ctx(session, settings, telegram=fake_telegram)
    user = await _customer(session, telegram_user_id=806)

    await customer_handlers.handle_text_message(ctx, user, "я" * (settings.max_message_length + 1))
    sent = fake_telegram.sent_messages[-1]["text"]
    assert sent == t("message_too_long", max_length=settings.max_message_length)
    _assert_ukrainian(sent)
