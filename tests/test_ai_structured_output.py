from __future__ import annotations

import pytest
from pydantic import ValidationError

from bot.handlers import customer as customer_handlers
from bot.locales import t
from bot.states.definitions import FSMState
from database.repositories.user_repository import UserRepository
from services.knowledge_service import KnowledgeService
from services.openai_service import AIResult, OpenAIServiceError
from tests.conftest import FakeOpenAIService, make_ctx


def test_ai_result_rejects_invalid_status():
    with pytest.raises(ValidationError):
        AIResult(status="maybe", answer="hi", confidence=0.9)


def test_ai_result_rejects_out_of_range_confidence():
    with pytest.raises(ValidationError):
        AIResult(status="answered", answer="hi", confidence=1.5)


def test_ai_result_accepts_valid_payload():
    result = AIResult(status="answered", answer="We open at 8am.", confidence=0.9)
    assert result.missing_information == []
    assert result.suggested_follow_up_question is None


async def _make_business_knowledge(tmp_path):
    file_path = tmp_path / "business.md"
    file_path.write_text("# Test Business\nWe are open 9-5.", encoding="utf-8")
    return KnowledgeService(file_path, max_characters=1000)


async def test_high_confidence_answered_is_sent_directly(session, settings, fake_telegram, tmp_path):
    knowledge = await _make_business_knowledge(tmp_path)
    ai = FakeOpenAIService(AIResult(status="answered", answer="We're open 9-5.", confidence=0.95))
    ctx = make_ctx(session, settings, telegram=fake_telegram, openai_service=ai, knowledge=knowledge)

    users = UserRepository(session)
    user = await users.get_or_create(
        telegram_user_id=10, username="u", first_name=None, last_name=None, language_code=None
    )
    await session.commit()

    await customer_handlers.handle_text_message(ctx, user, "What are your hours?")

    assert fake_telegram.sent_messages[-1]["text"] == "We're open 9-5."
    assert user.fsm_state in (None, FSMState.NONE)


async def test_low_confidence_answer_triggers_escalation_offer(session, settings, fake_telegram, tmp_path):
    knowledge = await _make_business_knowledge(tmp_path)
    ai = FakeOpenAIService(AIResult(status="answered", answer="Maybe 9-5?", confidence=0.3, reason="unsure"))
    ctx = make_ctx(session, settings, telegram=fake_telegram, openai_service=ai, knowledge=knowledge)

    users = UserRepository(session)
    user = await users.get_or_create(
        telegram_user_id=11, username="u2", first_name=None, last_name=None, language_code=None
    )
    await session.commit()

    await customer_handlers.handle_text_message(ctx, user, "What are your hours?")

    assert user.fsm_state == FSMState.AWAITING_ESCALATION_CONFIRM
    assert fake_telegram.sent_messages[-1]["text"] == t("unknown_answer")


async def test_explicit_escalate_status_triggers_escalation_offer(session, settings, fake_telegram, tmp_path):
    knowledge = await _make_business_knowledge(tmp_path)
    ai = FakeOpenAIService(
        AIResult(
            status="escalate",
            answer="I don't have that information.",
            confidence=0.9,
            reason="not documented",
            missing_information=["refund policy for custom orders"],
        )
    )
    ctx = make_ctx(session, settings, telegram=fake_telegram, openai_service=ai, knowledge=knowledge)

    users = UserRepository(session)
    user = await users.get_or_create(
        telegram_user_id=12, username="u3", first_name=None, last_name=None, language_code=None
    )
    await session.commit()

    await customer_handlers.handle_text_message(ctx, user, "Can I return a custom order?")

    assert user.fsm_state == FSMState.AWAITING_ESCALATION_CONFIRM
    assert user.fsm_data["missing"] == ["refund policy for custom orders"]


async def test_openai_unavailable_offers_escalation_instead_of_guessing(session, settings, fake_telegram, tmp_path):
    knowledge = await _make_business_knowledge(tmp_path)
    ai = FakeOpenAIService(error=OpenAIServiceError("boom"))
    ctx = make_ctx(session, settings, telegram=fake_telegram, openai_service=ai, knowledge=knowledge)

    users = UserRepository(session)
    user = await users.get_or_create(
        telegram_user_id=13, username="u4", first_name=None, last_name=None, language_code=None
    )
    await session.commit()

    await customer_handlers.handle_text_message(ctx, user, "Any question")

    assert user.fsm_state == FSMState.AWAITING_ESCALATION_CONFIRM
    assert user.fsm_data["reason"] == "AI service unavailable"
