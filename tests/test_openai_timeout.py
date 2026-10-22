from __future__ import annotations

import httpx
import pytest
from openai import APIConnectionError, APITimeoutError

import services.openai_service as openai_service_module
from services.openai_service import OpenAIService, OpenAIServiceError


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    async def instant_sleep(_seconds):
        return None

    monkeypatch.setattr(openai_service_module.asyncio, "sleep", instant_sleep)


async def test_openai_timeout_retries_then_raises(monkeypatch):
    service = OpenAIService(api_key="test", model="gpt-test")
    calls = {"n": 0}

    async def fake_parse(**kwargs):
        calls["n"] += 1
        raise APITimeoutError(request=httpx.Request("POST", "https://api.openai.com/v1/responses"))

    monkeypatch.setattr(service._client.responses, "parse", fake_parse)

    with pytest.raises(OpenAIServiceError):
        await service.get_structured_answer(business_knowledge="kb", conversation_history=[], customer_message="hi")

    assert calls["n"] == 2


async def test_openai_connection_error_is_retried(monkeypatch):
    service = OpenAIService(api_key="test", model="gpt-test")
    calls = {"n": 0}

    async def fake_parse(**kwargs):
        calls["n"] += 1
        raise APIConnectionError(request=httpx.Request("POST", "https://api.openai.com/v1/responses"))

    monkeypatch.setattr(service._client.responses, "parse", fake_parse)

    with pytest.raises(OpenAIServiceError):
        await service.get_structured_answer(business_knowledge="kb", conversation_history=[], customer_message="hi")

    assert calls["n"] == 2
