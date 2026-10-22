from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import BotSetting, User, UserRole

_ADMIN_CLAIM_KEY = "admin_telegram_id"


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_telegram_id(self, telegram_user_id: int) -> User | None:
        result = await self._session.execute(select(User).where(User.telegram_user_id == telegram_user_id))
        return result.scalar_one_or_none()

    async def get_by_pk(self, user_id: int) -> User | None:
        return await self._session.get(User, user_id)

    async def get_admin(self) -> User | None:
        result = await self._session.execute(select(User).where(User.role == UserRole.ADMIN.value))
        return result.scalars().first()

    async def get_or_create(
        self,
        *,
        telegram_user_id: int,
        username: str | None,
        first_name: str | None,
        last_name: str | None,
        language_code: str | None,
    ) -> User:
        user = await self.get_by_telegram_id(telegram_user_id)
        if user is None:
            user = User(
                telegram_user_id=telegram_user_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
                language_code=language_code,
                role=UserRole.CUSTOMER.value,
            )
            self._session.add(user)
            await self._session.flush()
        else:
            user.username = username
            user.first_name = first_name
            user.last_name = last_name
            user.language_code = language_code
        return user

    async def claim_admin_if_none_exists(self, user_id: int, telegram_user_id: int) -> bool:
        """Atomically register the first administrator.

        Uses a SAVEPOINT plus the bot_settings primary-key uniqueness as the
        race guard: only one concurrent request can successfully insert the
        "admin_telegram_id" row, so only one caller can ever return True,
        even under concurrent /claim attempts. A failed attempt is rolled
        back to the savepoint without discarding the outer transaction's
        other pending changes (e.g. the caller's own user upsert).
        """
        if await self.get_admin() is not None:
            return False
        try:
            async with self._session.begin_nested():
                self._session.add(BotSetting(key=_ADMIN_CLAIM_KEY, value=str(telegram_user_id)))
                await self._session.flush()
        except IntegrityError:
            return False

        user = await self.get_by_pk(user_id)
        if user is None:
            return False
        user.role = UserRole.ADMIN.value
        await self._session.flush()
        return True

    async def ensure_seeded_admin(self, telegram_user_id: int) -> None:
        """Auto-install ADMIN_TELEGRAM_ID as administrator if none exists yet."""
        if await self.get_admin() is not None:
            return
        try:
            async with self._session.begin_nested():
                existing = await self.get_by_telegram_id(telegram_user_id)
                if existing is not None:
                    existing.role = UserRole.ADMIN.value
                else:
                    self._session.add(User(telegram_user_id=telegram_user_id, role=UserRole.ADMIN.value))
                await self._session.flush()
        except IntegrityError:
            pass

    async def count_customers(self) -> int:
        result = await self._session.execute(
            select(func.count()).select_from(User).where(User.role == UserRole.CUSTOMER.value)
        )
        return int(result.scalar_one())

    async def delete_personal_data(self, user: User) -> None:
        """Anonymize personal identifiers while preserving row linkage for
        support requests that must remain (e.g. accounting/legal retention).
        """
        user.username = None
        user.first_name = None
        user.last_name = None
        user.fsm_state = None
        user.fsm_data = None
        await self._session.flush()
