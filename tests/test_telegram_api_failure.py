from __future__ import annotations

import httpx
import pytest

from services.telegram_service import TelegramAPIError, TelegramService


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict:
        return self._payload


async def test_telegram_api_error_response_raises(monkeypatch):
    service = TelegramService(bot_token="test-token")

    async def fake_post(self, url, json=None, **kwargs):
        return _FakeResponse({"ok": False, "description": "chat not found"})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    with pytest.raises(TelegramAPIError):
        await service.send_message(123, "hello")


async def test_telegram_transport_error_is_retried_then_raises(monkeypatch):
    service = TelegramService(bot_token="test-token")
    calls = {"n": 0}

    async def fake_post(self, url, json=None, **kwargs):
        calls["n"] += 1
        raise httpx.ConnectError("boom")

    async def instant_sleep(_seconds):
        return None

    import services.telegram_service as telegram_service_module

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    monkeypatch.setattr(telegram_service_module.asyncio, "sleep", instant_sleep)

    with pytest.raises(TelegramAPIError):
        await service.send_message(123, "hello")

    assert calls["n"] == 3


async def test_telegram_success_returns_result(monkeypatch):
    service = TelegramService(bot_token="test-token")

    async def fake_post(self, url, json=None, **kwargs):
        return _FakeResponse({"ok": True, "result": {"message_id": 42}})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    result = await service.send_message(123, "hello")
    assert result["message_id"] == 42
