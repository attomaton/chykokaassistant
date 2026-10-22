"""Test configuration: sets required env vars before any app import, and
provides an isolated in-memory SQLite database plus fake Telegram/OpenAI
service doubles so tests never make real network calls.
"""
from __future__ import annotations

import os

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-telegram-token")
os.environ.setdefault("TELEGRAM_WEBHOOK_SECRET", "test-webhook-secret")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("ADMIN_SETUP_SECRET", "test-admin-secret")
os.environ.setdefault("APP_URL", "https://example-test.invalid")
os.environ.setdefault("ENVIRONMENT", "test")

from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from bot.context import BotContext
from config import get_settings
from database.models import Base
from services.telegram_service import TelegramAPIError


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest.fixture
def settings():
    get_settings.cache_clear()
    return get_settings()


class FakeTelegramService:
    def __init__(self, *, fail_send: bool = False, fail_chat_ids: set[int] | None = None) -> None:
        self.sent_messages: list[dict[str, Any]] = []
        self.answered_callbacks: list[dict[str, Any]] = []
        self.fail_send = fail_send
        self.fail_chat_ids = fail_chat_ids or set()

    async def send_message(self, chat_id: int, text: str, *, reply_markup: dict | None = None) -> dict:
        if self.fail_send or chat_id in self.fail_chat_ids:
            raise TelegramAPIError("simulated delivery failure")
        entry = {"chat_id": chat_id, "text": text, "reply_markup": reply_markup}
        self.sent_messages.append(entry)
        return {"message_id": len(self.sent_messages)}

    async def answer_callback_query(self, callback_query_id: str, text: str | None = None) -> dict:
        self.answered_callbacks.append({"callback_query_id": callback_query_id, "text": text})
        return {}


class FakeOpenAIService:
    def __init__(self, result=None, *, error: Exception | None = None) -> None:
        self._result = result
        self._error = error
        self.calls: list[dict[str, Any]] = []

    async def get_structured_answer(
        self,
        *,
        business_knowledge,
        conversation_history,
        customer_message,
        catalog_block="",
    ):
        self.calls.append(
            {
                "business_knowledge": business_knowledge,
                "conversation_history": conversation_history,
                "customer_message": customer_message,
                "catalog_block": catalog_block,
            }
        )
        if self._error is not None:
            raise self._error
        return self._result


@pytest.fixture
def fake_telegram() -> FakeTelegramService:
    return FakeTelegramService()


def make_ctx(session, settings, telegram=None, openai_service=None, knowledge=None) -> BotContext:
    return BotContext(
        session=session,
        telegram=telegram or FakeTelegramService(),
        openai_service=openai_service,
        knowledge=knowledge,
        settings=settings,
    )
