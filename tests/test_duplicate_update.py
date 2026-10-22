from __future__ import annotations

from database.repositories.processed_update_repository import ProcessedUpdateRepository


async def test_mark_if_new_returns_true_once_then_false(session):
    repo = ProcessedUpdateRepository(session)

    first = await repo.mark_if_new(12345)
    await session.commit()
    second = await repo.mark_if_new(12345)
    await session.commit()

    assert first is True
    assert second is False


async def test_mark_if_new_is_independent_per_update_id(session):
    repo = ProcessedUpdateRepository(session)

    assert await repo.mark_if_new(1) is True
    assert await repo.mark_if_new(2) is True
    await session.commit()
