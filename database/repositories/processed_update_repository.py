from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import ProcessedUpdate


class ProcessedUpdateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def mark_if_new(self, update_id: int) -> bool:
        """Atomically record update_id as processed.

        Returns True the first time a given update_id is seen, False on any
        subsequent (duplicate) delivery. Relies on the primary-key uniqueness
        constraint rather than a SELECT-then-INSERT check, which would race
        under concurrent deliveries of the same update.
        """
        try:
            async with self._session.begin_nested():
                self._session.add(ProcessedUpdate(update_id=update_id))
                await self._session.flush()
        except IntegrityError:
            return False
        return True
