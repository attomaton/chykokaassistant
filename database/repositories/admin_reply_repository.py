from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from database.models import AdminReply, DeliveryStatus


class AdminReplyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        support_request_id: int,
        admin_user_id: int | None,
        message: str,
        delivery_status: str = DeliveryStatus.PENDING.value,
    ) -> AdminReply:
        reply = AdminReply(
            support_request_id=support_request_id,
            admin_user_id=admin_user_id,
            message=message,
            delivery_status=delivery_status,
        )
        self._session.add(reply)
        await self._session.flush()
        return reply
