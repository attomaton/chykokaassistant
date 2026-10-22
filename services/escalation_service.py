"""Orchestrates creating a support request and notifying the administrator."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards.admin_kb import admin_request_keyboard
from database.models import RequestStatus, SupportRequest, User
from database.repositories.support_request_repository import SupportRequestRepository
from database.repositories.user_repository import UserRepository
from services.telegram_service import TelegramAPIError, TelegramService

logger = logging.getLogger(__name__)


class EscalationService:
    def __init__(self, session: AsyncSession, telegram: TelegramService) -> None:
        self._session = session
        self._telegram = telegram
        self._requests = SupportRequestRepository(session)
        self._users = UserRepository(session)

    async def create_and_notify(
        self,
        *,
        user: User,
        original_question: str,
        escalation_reason: str | None,
        missing_information: list[str] | None,
        customer_name: str | None,
        customer_phone: str | None,
        customer_email: str | None,
    ) -> tuple[str, bool]:
        """Save the lead, then attempt to notify the admin.

        Returns (public_request_id, admin_was_notified). The caller must not
        tell the customer their request was "forwarded" unless the second
        value is True; if False, it is still safely persisted as pending.
        """
        public_id = uuid.uuid4().hex[:10]
        request = await self._requests.create(
            public_request_id=public_id,
            user_id=user.id,
            original_question=original_question[:4000],
            escalation_reason=(escalation_reason or "")[:500],
            missing_information=(missing_information or [])[:20],
            customer_name=customer_name,
            customer_phone=customer_phone,
            customer_email=customer_email,
            status=RequestStatus.PENDING.value,
        )
        # Commit the lead durably before attempting notification/telling the
        # customer anything, so a later failure in this request cannot leave
        # the customer believing their request was saved when it was not.
        await self._session.commit()

        notified = await self.notify_admin(request, user)
        await self._session.commit()
        return public_id, notified

    async def notify_admin(self, request: SupportRequest, user: User | None) -> bool:
        admin = await self._users.get_admin()
        if admin is None:
            logger.error("no_admin_configured request_id=%s", request.public_request_id)
            return False

        text = self._format_admin_message(request, user)
        try:
            await self._telegram.send_message(
                admin.telegram_user_id,
                text,
                reply_markup=admin_request_keyboard(request.public_request_id),
            )
        except TelegramAPIError:
            logger.error("admin_notify_failed request_id=%s", request.public_request_id)
            return False

        request.admin_notified_at = datetime.now(timezone.utc)
        if request.status != RequestStatus.RESOLVED.value:
            request.status = RequestStatus.NOTIFIED.value
        return True

    @staticmethod
    def _format_admin_message(request: SupportRequest, user: User | None) -> str:
        username = f"@{user.username}" if user and user.username else "N/A"
        telegram_id = user.telegram_user_id if user else "N/A"
        missing = ", ".join(request.missing_information or []) or "N/A"
        return (
            f"New customer request #{request.public_request_id}\n\n"
            f"Customer:\n"
            f"Name: {request.customer_name or 'N/A'}\n"
            f"Phone: {request.customer_phone or 'N/A'}\n"
            f"Email: {request.customer_email or 'N/A'}\n"
            f"Telegram: {username}\n"
            f"Telegram ID: {telegram_id}\n\n"
            f"Original question:\n{request.original_question}\n\n"
            f"AI escalation reason:\n{request.escalation_reason or 'N/A'}\n\n"
            f"Missing information:\n{missing}\n\n"
            f"Created:\n{request.created_at}"
        )
