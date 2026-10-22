from __future__ import annotations

from bot.handlers import customer as customer_handlers
from bot.locales import t
from bot.states.definitions import FSMState
from database.models import RequestStatus
from database.repositories.support_request_repository import SupportRequestRepository
from database.repositories.user_repository import UserRepository
from services.escalation_service import EscalationService
from tests.conftest import FakeTelegramService, make_ctx


async def _make_admin_and_customer(session):
    users = UserRepository(session)
    admin = await users.get_or_create(
        telegram_user_id=900, username="admin", first_name="Ad", last_name=None, language_code="en"
    )
    admin.role = "admin"
    customer = await users.get_or_create(
        telegram_user_id=901, username="cust", first_name="Cus", last_name=None, language_code="en"
    )
    await session.commit()
    return admin, customer


async def test_create_and_notify_saves_lead_and_notifies_admin(session):
    admin, customer = await _make_admin_and_customer(session)
    telegram = FakeTelegramService()
    service = EscalationService(session, telegram)

    public_id, notified = await service.create_and_notify(
        user=customer,
        original_question="Do you deliver on Sundays?",
        escalation_reason="Not documented",
        missing_information=["Sunday delivery availability"],
        customer_name="Cus Tomer",
        customer_phone="+15551234567",
        customer_email=None,
    )
    await session.commit()

    assert notified is True
    requests_repo = SupportRequestRepository(session)
    request = await requests_repo.get_by_public_id(public_id)
    assert request is not None
    assert request.status == RequestStatus.NOTIFIED.value
    assert request.admin_notified_at is not None

    admin_message = telegram.sent_messages[-1]
    assert admin_message["chat_id"] == admin.telegram_user_id
    assert "Do you deliver on Sundays?" in admin_message["text"]
    assert public_id in admin_message["text"]


async def test_create_and_notify_when_admin_notification_fails(session):
    _, customer = await _make_admin_and_customer(session)
    telegram = FakeTelegramService(fail_send=True)
    service = EscalationService(session, telegram)

    public_id, notified = await service.create_and_notify(
        user=customer,
        original_question="Any question",
        escalation_reason="reason",
        missing_information=[],
        customer_name="Name",
        customer_phone=None,
        customer_email="a@b.com",
    )
    await session.commit()

    assert notified is False
    requests_repo = SupportRequestRepository(session)
    request = await requests_repo.get_by_public_id(public_id)
    assert request.status == RequestStatus.PENDING.value
    assert request.admin_notified_at is None


async def test_create_and_notify_when_no_admin_configured(session):
    users = UserRepository(session)
    customer = await users.get_or_create(
        telegram_user_id=902, username="c", first_name=None, last_name=None, language_code=None
    )
    await session.commit()

    telegram = FakeTelegramService()
    service = EscalationService(session, telegram)
    public_id, notified = await service.create_and_notify(
        user=customer,
        original_question="q",
        escalation_reason="r",
        missing_information=[],
        customer_name=None,
        customer_phone="+15551234567",
        customer_email=None,
    )
    await session.commit()

    assert notified is False
    assert telegram.sent_messages == []


async def test_full_contact_collection_flow(session, settings):
    admin, customer = await _make_admin_and_customer(session)
    telegram = FakeTelegramService()
    ctx = make_ctx(session, settings, telegram=telegram)

    customer.fsm_state = FSMState.AWAITING_ESCALATION_CONFIRM
    customer.fsm_data = {"question": "Do you ship internationally?", "reason": "not documented", "missing": []}
    await session.commit()

    await customer_handlers.handle_callback(ctx, customer, "esc:contact", "cbq-1")
    assert customer.fsm_state == FSMState.COLLECTING_NAME

    await customer_handlers.handle_text_message(ctx, customer, "Jane Doe")
    assert customer.fsm_state == FSMState.COLLECTING_PHONE

    await customer_handlers.handle_text_message(ctx, customer, "+15551234567")
    assert customer.fsm_state == FSMState.COLLECTING_EMAIL

    await customer_handlers.handle_callback(ctx, customer, "field:skip:email", "cbq-2")
    assert customer.fsm_state == FSMState.CONFIRMING_CONTACT

    await customer_handlers.handle_callback(ctx, customer, "contact:confirm", "cbq-3")
    await session.commit()

    assert customer.fsm_state == FSMState.NONE

    requests_repo = SupportRequestRepository(session)
    unresolved = await requests_repo.list_unresolved()
    assert len(unresolved) == 1

    final_message = telegram.sent_messages[-1]["text"]
    assert final_message == t("request_forwarded", public_id=unresolved[0].public_request_id)
    assert unresolved[0].customer_name == "Jane Doe"
    assert unresolved[0].customer_phone == "+15551234567"


async def test_contact_flow_requires_at_least_one_contact_method(session, settings):
    _, customer = await _make_admin_and_customer(session)
    telegram = FakeTelegramService()
    ctx = make_ctx(session, settings, telegram=telegram)

    customer.fsm_state = FSMState.AWAITING_ESCALATION_CONFIRM
    customer.fsm_data = {"question": "q", "reason": "r", "missing": []}
    await session.commit()

    await customer_handlers.handle_callback(ctx, customer, "esc:contact", "cbq-1")
    await customer_handlers.handle_text_message(ctx, customer, "Jane Doe")
    await customer_handlers.handle_callback(ctx, customer, "field:skip:phone", "cbq-2")
    await customer_handlers.handle_callback(ctx, customer, "field:skip:email", "cbq-3")

    # Both skipped -> must be bounced back to collecting phone, not allowed to confirm.
    assert customer.fsm_state == FSMState.COLLECTING_PHONE
    assert telegram.sent_messages[-1]["text"] == t("need_one_contact")
