from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import RequestStatus, SupportRequest


class SupportRequestRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        public_request_id: str,
        user_id: int | None,
        original_question: str,
        escalation_reason: str | None,
        missing_information: list[str] | None,
        customer_name: str | None,
        customer_phone: str | None,
        customer_email: str | None,
        status: str = RequestStatus.PENDING.value,
    ) -> SupportRequest:
        request = SupportRequest(
            public_request_id=public_request_id,
            user_id=user_id,
            original_question=original_question,
            escalation_reason=escalation_reason,
            missing_information=missing_information or [],
            customer_name=customer_name,
            customer_phone=customer_phone,
            customer_email=customer_email,
            status=status,
        )
        self._session.add(request)
        await self._session.flush()
        return request

    async def get_by_public_id(self, public_request_id: str) -> SupportRequest | None:
        result = await self._session.execute(
            select(SupportRequest).where(SupportRequest.public_request_id == public_request_id)
        )
        return result.scalar_one_or_none()

    async def list_unresolved(self, limit: int = 10) -> list[SupportRequest]:
        result = await self._session.execute(
            select(SupportRequest)
            .where(SupportRequest.status != RequestStatus.RESOLVED.value)
            .order_by(SupportRequest.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def mark_resolved(self, request: SupportRequest) -> None:
        request.status = RequestStatus.RESOLVED.value
        request.resolved_at = datetime.now(timezone.utc)
        await self._session.flush()

    async def count_total(self) -> int:
        result = await self._session.execute(select(func.count()).select_from(SupportRequest))
        return int(result.scalar_one())

    async def count_by_status(self, status: str) -> int:
        result = await self._session.execute(
            select(func.count()).select_from(SupportRequest).where(SupportRequest.status == status)
        )
        return int(result.scalar_one())

    async def count_created_since(self, since: datetime) -> int:
        result = await self._session.execute(
            select(func.count()).select_from(SupportRequest).where(SupportRequest.created_at >= since)
        )
        return int(result.scalar_one())
