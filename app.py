"""FastAPI application: health endpoints + the Telegram webhook.

Processing happens synchronously inside the request handler (no
BackgroundTasks, no threads) because Vercel serverless functions may be
frozen or torn down immediately after the HTTP response is sent - anything
that must reliably happen (DB writes, Telegram/OpenAI calls) must be awaited
before returning.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Header, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import text

from bot.context import BotContext
from bot.router import handle_update
from config import get_settings
from database.repositories.processed_update_repository import ProcessedUpdateRepository
from database.repositories.user_repository import UserRepository
from database.session import get_session_factory
from services.knowledge_service import KnowledgeBaseError, KnowledgeService
from services.openai_service import OpenAIService
from services.telegram_service import TelegramService

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("app")

settings = get_settings()
knowledge_service = KnowledgeService(settings.business_md_path, settings.max_knowledge_characters)
telegram_service = TelegramService(settings.telegram_bot_token, settings.telegram_timeout_seconds)
openai_service = OpenAIService(settings.openai_api_key, settings.openai_model, settings.openai_timeout_seconds)

app = FastAPI(title="Telegram Business Assistant")


@app.on_event("startup")
async def on_startup() -> None:
    # Best-effort only: some serverless runtimes may not invoke ASGI
    # lifespan events per-request, so nothing here is relied upon for
    # correctness. The knowledge base is loaded lazily on first use anyway.
    try:
        kb = knowledge_service.load()
        logger.info("startup_knowledge_base_ready hash=%s chars=%d", kb.content_hash, kb.char_count)
    except KnowledgeBaseError as exc:
        logger.error("startup_knowledge_base_error error=%s", str(exc))


@app.get("/")
async def root() -> dict:
    return {"status": "ok", "service": "telegram-business-assistant"}


@app.get("/health")
async def health() -> JSONResponse:
    session_factory = get_session_factory()
    db_ok = True
    try:
        async with session_factory() as session:
            await session.execute(text("SELECT 1"))
    except Exception:
        logger.exception("health_check_db_failed")
        db_ok = False
    status_code = 200 if db_ok else 503
    return JSONResponse({"status": "ok" if db_ok else "degraded", "database": db_ok}, status_code=status_code)


@app.post("/api/telegram/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> Response:
    if not settings.telegram_webhook_secret or x_telegram_bot_api_secret_token != settings.telegram_webhook_secret:
        logger.warning("webhook_invalid_secret")
        return Response(status_code=401)

    try:
        payload = await request.json()
    except Exception:
        logger.warning("webhook_malformed_json")
        return JSONResponse({"ok": True})

    if not isinstance(payload, dict):
        logger.warning("webhook_malformed_payload")
        return JSONResponse({"ok": True})

    update_id = payload.get("update_id")
    if update_id is None:
        logger.warning("webhook_missing_update_id")
        return JSONResponse({"ok": True})

    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            dedup_repo = ProcessedUpdateRepository(session)
            is_new = await dedup_repo.mark_if_new(update_id)
            await session.commit()
            if not is_new:
                logger.info("webhook_duplicate_update update_id=%s", update_id)
                return JSONResponse({"ok": True})

            if settings.admin_telegram_id is not None:
                await UserRepository(session).ensure_seeded_admin(settings.admin_telegram_id)
                await session.commit()

            ctx = BotContext(
                session=session,
                telegram=telegram_service,
                openai_service=openai_service,
                knowledge=knowledge_service,
                settings=settings,
            )
            await handle_update(ctx, payload)
            await session.commit()
        except Exception:
            await session.rollback()
            # Never log full update payloads: they may contain customer
            # personal data (names, phone numbers, emails, messages).
            logger.exception("webhook_processing_error update_id=%s", update_id)

    return JSONResponse({"ok": True})
