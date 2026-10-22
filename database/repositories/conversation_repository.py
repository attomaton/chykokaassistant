from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Conversation


class ConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, user_id: int, role: str, content: str) -> Conversation:
        turn = Conversation(user_id=user_id, role=role, content=content)
        self._session.add(turn)
        await self._session.flush()
        return turn

    async def get_recent(self, user_id: int, limit: int, ttl_minutes: int) -> list[Conversation]:
        """Return the most recent turns, oldest first, excluding stale ones."""
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=ttl_minutes)
        result = await self._session.execute(
            select(Conversation)
            .where(Conversation.user_id == user_id, Conversation.created_at >= cutoff)
            .order_by(Conversation.created_at.desc())
            .limit(limit)
        )
        turns = list(result.scalars().all())
        turns.reverse()
        return turns

    async def clear(self, user_id: int) -> None:
        await self._session.execute(delete(Conversation).where(Conversation.user_id == user_id))
        await self._session.flush()
