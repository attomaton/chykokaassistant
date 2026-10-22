"""Shared per-request context passed to every handler."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from config import Settings
from services.knowledge_service import KnowledgeService
from services.openai_service import OpenAIService
from services.telegram_service import TelegramService


@dataclass
class BotContext:
    session: AsyncSession
    telegram: TelegramService
    openai_service: OpenAIService
    knowledge: KnowledgeService
    settings: Settings
