from __future__ import annotations

from fastapi.testclient import TestClient

from app import app, settings

client = TestClient(app)


def test_webhook_rejects_missing_secret_header():
    response = client.post("/api/telegram/webhook", json={"update_id": 1})
    assert response.status_code == 401


def test_webhook_rejects_wrong_secret_header():
    response = client.post(
        "/api/telegram/webhook",
        json={"update_id": 1},
        headers={"X-Telegram-Bot-Api-Secret-Token": "wrong-secret"},
    )
    assert response.status_code == 401


def test_webhook_handles_malformed_json_safely():
    response = client.post(
        "/api/telegram/webhook",
        content=b"not-json{{{",
        headers={
            "X-Telegram-Bot-Api-Secret-Token": settings.telegram_webhook_secret,
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_webhook_handles_missing_update_id_safely():
    response = client.post(
        "/api/telegram/webhook",
        json={"message": {"text": "hi"}},
        headers={"X-Telegram-Bot-Api-Secret-Token": settings.telegram_webhook_secret},
    )
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_root_and_health_do_not_leak_secrets():
    response = client.get("/")
    assert response.status_code == 200
    body = response.text
    assert settings.telegram_bot_token not in body
    assert settings.openai_api_key not in body
    assert settings.telegram_webhook_secret not in body
