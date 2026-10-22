"""End-to-end handler behavior for the `recommend` status and Ukrainian UI."""
from __future__ import annotations

from pathlib import Path

from bot.handlers import customer as customer_handlers
from bot.handlers import start as start_handlers
from bot.locales import t
from bot.states.definitions import FSMState
from database.repositories.user_repository import UserRepository
from services.knowledge_service import KnowledgeService
from services.openai_service import AIResult
from tests.conftest import FakeOpenAIService, make_ctx

CATALOG_MD = """
# Lakomka Store

## Structured Product Catalog

| product_id | Назва | Ціна | Наявність | Категорія | Теги |
|---|---|---|---|---|---|
| dried_persimmon | Хурма | 340 | невідомо | Сухофрукти | сухофрукт |
| walnut | Волоський горіх | 150 | в наявності | Горіхи | горіх |
"""


def _knowledge(tmp_path: Path) -> KnowledgeService:
    path = tmp_path / "business.md"
    path.write_text(CATALOG_MD, encoding="utf-8")
    return KnowledgeService(path, max_characters=80000)


async def _customer(session):
    user = await UserRepository(session).get_or_create(
        telegram_user_id=555, username="c", first_name=None, last_name=None, language_code="ru"
    )
    await session.commit()
    return user


async def _run(session, settings, fake_telegram, tmp_path, result, message):
    ctx = make_ctx(
        session,
        settings,
        telegram=fake_telegram,
        openai_service=FakeOpenAIService(result),
        knowledge=_knowledge(tmp_path),
    )
    user = await _customer(session)
    await customer_handlers.handle_text_message(ctx, user, message)
    return user


def _recommend(**overrides) -> AIResult:
    payload = {
        "status": "recommend",
        "answer": "До хурми добре пасує волоський горіх — він додає хрусткої текстури.",
        "confidence": 0.9,
        "response_type": "general_recommendation",
        "recommended_product_ids": ["walnut"],
    }
    payload.update(overrides)
    return AIResult(**payload)


async def test_recommend_status_sends_validated_recommendation(
    session, settings, fake_telegram, tmp_path
):
    user = await _run(
        session, settings, fake_telegram, tmp_path, _recommend(), "Що краще взяти до хурми?"
    )
    sent = fake_telegram.sent_messages[-1]["text"]
    assert "волоський горіх" in sent.lower()
    assert "150 ₴" in sent  # price supplied by the backend, not the model
    assert user.fsm_state in (FSMState.NONE, None)


async def test_recommendation_with_invented_product_escalates_in_ukrainian(
    session, settings, fake_telegram, tmp_path
):
    user = await _run(
        session,
        settings,
        fake_telegram,
        tmp_path,
        _recommend(recommended_product_ids=["premium_belgian_chocolate"]),
        "Що порадите?",
    )
    assert user.fsm_state == FSMState.AWAITING_ESCALATION_CONFIRM
    assert fake_telegram.sent_messages[-1]["text"] == t("unknown_answer")
    assert "premium_belgian_chocolate" not in fake_telegram.sent_messages[-1]["text"]


async def test_recommendation_never_shows_an_invented_price(
    session, settings, fake_telegram, tmp_path
):
    await _run(
        session,
        settings,
        fake_telegram,
        tmp_path,
        _recommend(answer="Волоський горіх зараз лише 49 грн!"),
        "Скільки коштує горіх?",
    )
    sent = fake_telegram.sent_messages[-1]["text"]
    assert "49" not in sent
    assert sent == t("unknown_answer")


async def test_recommendation_never_claims_unconfirmed_availability(
    session, settings, fake_telegram, tmp_path
):
    """Stock is `невідомо` for хурма, so no in-stock claim may be rendered."""
    await _run(
        session,
        settings,
        fake_telegram,
        tmp_path,
        _recommend(recommended_product_ids=["dried_persimmon"], answer="Раджу хурму."),
        "Що порадите?",
    )
    sent = fake_telegram.sent_messages[-1]["text"]
    assert "в наявності" not in sent


async def test_budget_request_uses_backend_prices(
    session, settings, fake_telegram, tmp_path
):
    await _run(
        session,
        settings,
        fake_telegram,
        tmp_path,
        _recommend(
            answer="Ось набір для вас.",
            recommended_product_ids=["walnut", "dried_persimmon"],
        ),
        "Підбери набір до 600 грн",
    )
    sent = fake_telegram.sent_messages[-1]["text"]
    assert t("budget_summary", total="490", budget="600") in sent


async def test_low_confidence_recommendation_escalates_instead_of_recommending(
    session, settings, fake_telegram, tmp_path
):
    user = await _run(
        session,
        settings,
        fake_telegram,
        tmp_path,
        _recommend(confidence=0.2),
        "Що порадите?",
    )
    assert user.fsm_state == FSMState.AWAITING_ESCALATION_CONFIRM


async def test_broad_question_can_ask_one_clarifying_question(
    session, settings, fake_telegram, tmp_path
):
    result = AIResult(
        status="needs_clarification",
        answer="",
        confidence=0.9,
        suggested_follow_up_question="Набір потрібен для подарунка чи для себе?",
    )
    user = await _run(session, settings, fake_telegram, tmp_path, result, "Порадьте набір")
    assert fake_telegram.sent_messages[-1]["text"] == "Набір потрібен для подарунка чи для себе?"
    assert user.fsm_state in (FSMState.NONE, None)


async def test_allergy_question_escalates_when_allergen_data_missing(
    session, settings, fake_telegram, tmp_path
):
    result = AIResult(
        status="escalate",
        answer="",
        confidence=0.9,
        reason="Allergen data not documented",
        missing_information=["Склад та алергени"],
    )
    user = await _run(
        session, settings, fake_telegram, tmp_path, result, "Чи є в горіхах алергени?"
    )
    assert user.fsm_state == FSMState.AWAITING_ESCALATION_CONFIRM
    assert fake_telegram.sent_messages[-1]["text"] == t("unknown_answer")
    assert user.fsm_data["missing"] == ["Склад та алергени"]


async def test_catalog_is_passed_to_the_model(session, settings, fake_telegram, tmp_path):
    """The model must only ever see IDs that actually exist."""
    ai = FakeOpenAIService(_recommend())
    ctx = make_ctx(
        session,
        settings,
        telegram=fake_telegram,
        openai_service=ai,
        knowledge=_knowledge(tmp_path),
    )
    user = await _customer(session)
    await customer_handlers.handle_text_message(ctx, user, "Що порадите?")

    block = ai.calls[-1]["catalog_block"]
    assert "walnut" in block
    assert "dried_persimmon" in block


async def test_informational_commands_are_ukrainian(session, settings, fake_telegram):
    ctx = make_ctx(session, settings, telegram=fake_telegram)
    user = await _customer(session)

    await start_handlers.handle_start(ctx, user)
    await start_handlers.handle_help(ctx, user)
    await start_handlers.handle_privacy(ctx, user)

    texts = [m["text"] for m in fake_telegram.sent_messages]
    assert texts == [t("start_message"), t("help_message"), t("privacy_message")]
    for text in texts:
        assert "Hello" not in text and "Privacy information" not in text


async def test_answers_in_ukrainian_even_when_customer_writes_russian(
    session, settings, fake_telegram, tmp_path
):
    """Default language stays Ukrainian regardless of the customer's language."""
    user = await _run(
        session,
        settings,
        fake_telegram,
        tmp_path,
        AIResult(status="escalate", answer="", confidence=0.9),
        "Что посоветуете к хурме?",
    )
    assert user.language_code == "ru"
    assert fake_telegram.sent_messages[-1]["text"] == t("unknown_answer")
