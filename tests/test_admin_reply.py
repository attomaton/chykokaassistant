from __future__ import annotations

from bot.handlers import admin as admin_handlers
from bot.states.definitions import FSMState
from database.models import RequestStatus
from database.repositories.support_request_repository import SupportRequestRepository
from database.repositories.user_repository import UserRepository
from services.escalation_service import EscalationService
from tests.conftest import FakeTelegramService, make_ctx


async def _seed_request(session):
    users = UserRepository(session)
    admin = await users.get_or_create(
        telegram_user_id=700, username="admin", first_name=None, last_name=None, language_code=None
    )
    admin.role = "admin"
    customer = await users.get_or_create(
        telegram_user_id=701, username="cust", first_name=None, last_name=None, language_code=None
    )
    await session.commit()

    escalation = EscalationService(session, FakeTelegramService())
    public_id, _ = await escalation.create_and_notify(
        user=customer,
        original_question="Is gift wrapping available?",
        escalation_reason="not documented",
        missing_information=[],
        customer_name="Cus",
        customer_phone="+15551234567",
        customer_email=None,
    )
    await session.commit()
    return admin, customer, public_id


async def test_admin_reply_flow_delivers_message_and_prompts_resolve(session, settings):
    admin, customer, public_id = await _seed_request(session)
    telegram = FakeTelegramService()
    ctx = make_ctx(session, settings, telegram=telegram)

    await admin_handlers.handle_admin_callback(ctx, admin, f"admin:reply:{public_id}", "cbq-1")
    assert admin.fsm_state == FSMState.ADMIN_AWAITING_REPLY

    consumed = await admin_handlers.handle_admin_text(ctx, admin, "Yes, gift wrapping is available for $2.")
    assert consumed is True
    assert admin.fsm_state == FSMState.ADMIN_CONFIRM_REPLY

    await admin_handlers.handle_admin_callback(ctx, admin, f"admin:send_reply:{public_id}", "cbq-2")
    await session.commit()

    customer_message = next(m for m in telegram.sent_messages if m["chat_id"] == customer.telegram_user_id)
    assert "gift wrapping is available" in customer_message["text"]
    assert admin.fsm_state == FSMState.NONE

    requests_repo = SupportRequestRepository(session)
    request = await requests_repo.get_by_public_id(public_id)
    assert request.status != RequestStatus.RESOLVED.value  # not resolved until admin confirms

    await admin_handlers.handle_admin_callback(ctx, admin, f"admin:resolve:{public_id}", "cbq-3")
    await session.commit()
    request = await requests_repo.get_by_public_id(public_id)
    assert request.status == RequestStatus.RESOLVED.value


async def test_admin_reply_delivery_failure_is_saved_as_failed(session, settings):
    admin, customer, public_id = await _seed_request(session)
    telegram = FakeTelegramService(fail_chat_ids={customer.telegram_user_id})
    ctx = make_ctx(session, settings, telegram=telegram)

    admin.fsm_state = FSMState.ADMIN_AWAITING_REPLY
    admin.fsm_data = {"request_id": public_id}
    await session.commit()

    await admin_handlers.handle_admin_text(ctx, admin, "We'll get back to you.")
    await admin_handlers._send_admin_reply(ctx, admin, public_id)
    await session.commit()

    assert admin.fsm_state == FSMState.NONE
    admin_messages = [m for m in telegram.sent_messages if m["chat_id"] == admin.telegram_user_id]
    assert any("delivery to the customer failed" in m["text"] for m in admin_messages)

    from database.repositories.support_request_repository import SupportRequestRepository

    requests_repo = SupportRequestRepository(session)
    request = await requests_repo.get_by_public_id(public_id)
    assert request is not None


async def test_non_admin_cannot_trigger_reply_callback(session, settings):
    _, customer, public_id = await _seed_request(session)
    telegram = FakeTelegramService()
    ctx = make_ctx(session, settings, telegram=telegram)

    await admin_handlers.handle_admin_callback(ctx, customer, f"admin:reply:{public_id}", "cbq-x")

    assert customer.fsm_state in (None, "none")
    assert "only available to the bot administrator" in telegram.sent_messages[-1]["text"]
