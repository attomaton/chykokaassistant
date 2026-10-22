"""Direct Telegram Bot API client built on httpx.

Direct HTTP calls (rather than a polling-oriented framework) are used
because the bot runs as a stateless serverless webhook handler on Vercel;
this avoids any framework assumptions about long-running dispatchers or
in-memory FSM storage. All outgoing text is sent without a Telegram
parse_mode, which avoids Markdown/HTML injection from user-supplied content
(names, questions, admin replies) that gets embedded in messages.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

TELEGRAM_MESSAGE_LIMIT = 4096
_MAX_ATTEMPTS = 3


class TelegramAPIError(Exception):
    pass


class TelegramService:
    def __init__(self, bot_token: str, timeout_seconds: float = 15.0) -> None:
        self._base_url = f"https://api.telegram.org/bot{bot_token}"
        self._timeout = timeout_seconds

    @staticmethod
    def truncate_message(text: str, limit: int = TELEGRAM_MESSAGE_LIMIT) -> str:
        if len(text) <= limit:
            return text
        return text[: limit - 20].rstrip() + "\n\n[message truncated]"

    async def _post(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._base_url}/{method}"
        last_error: str = "unknown error"
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            for attempt in range(1, _MAX_ATTEMPTS + 1):
                try:
                    response = await client.post(url, json=payload)
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    last_error = str(exc)
                    logger.warning("telegram_transport_error method=%s attempt=%d/%d", method, attempt, _MAX_ATTEMPTS)
                    if attempt < _MAX_ATTEMPTS:
                        await asyncio.sleep(0.5 * attempt)
                        continue
                    raise TelegramAPIError(f"Telegram request failed for {method}: {last_error}") from exc

                if response.status_code == 429:
                    retry_after = 1.0
                    try:
                        retry_after = float(response.json().get("parameters", {}).get("retry_after", 1))
                    except Exception:
                        pass
                    logger.warning("telegram_rate_limited method=%s retry_after=%s", method, retry_after)
                    if attempt < _MAX_ATTEMPTS:
                        await asyncio.sleep(retry_after)
                        continue
                    raise TelegramAPIError(f"Telegram rate limited on {method}")

                try:
                    data = response.json()
                except Exception as exc:
                    raise TelegramAPIError(f"Telegram returned a non-JSON response for {method}") from exc

                if not data.get("ok"):
                    description = str(data.get("description", ""))[:200]
                    logger.error("telegram_api_error method=%s description=%s", method, description)
                    raise TelegramAPIError(description or f"Telegram API error on {method}")

                return data.get("result", {})

        raise TelegramAPIError(f"Telegram request failed for {method}: {last_error}")

    async def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        reply_markup: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"chat_id": chat_id, "text": self.truncate_message(text)}
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        return await self._post("sendMessage", payload)

    async def answer_callback_query(self, callback_query_id: str, text: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text[:200]
        return await self._post("answerCallbackQuery", payload)

    async def set_webhook(self, url: str, secret_token: str) -> dict[str, Any]:
        return await self._post(
            "setWebhook",
            {"url": url, "secret_token": secret_token, "allowed_updates": ["message", "callback_query"]},
        )

    async def delete_webhook(self) -> dict[str, Any]:
        return await self._post("deleteWebhook", {"drop_pending_updates": False})

    async def get_webhook_info(self) -> dict[str, Any]:
        return await self._post("getWebhookInfo", {})
