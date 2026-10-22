"""Register the Telegram webhook for this bot.

Reads TELEGRAM_BOT_TOKEN, TELEGRAM_WEBHOOK_SECRET, and APP_URL directly from
the environment (does not require DATABASE_URL or other unrelated secrets).

Usage:
    python scripts/set_webhook.py
"""
from __future__ import annotations

import os
import sys

import httpx


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        print(f"Missing required environment variable: {name}", file=sys.stderr)
        sys.exit(1)
    return value


def main() -> None:
    token = _require("TELEGRAM_BOT_TOKEN")
    secret = _require("TELEGRAM_WEBHOOK_SECRET")
    app_url = _require("APP_URL").rstrip("/")
    webhook_url = f"{app_url}/api/telegram/webhook"

    response = httpx.post(
        f"https://api.telegram.org/bot{token}/setWebhook",
        json={
            "url": webhook_url,
            "secret_token": secret,
            "allowed_updates": ["message", "callback_query"],
        },
        timeout=15.0,
    )
    data = response.json()
    if data.get("ok"):
        print(f"Webhook registered successfully: {webhook_url}")
    else:
        print(f"Failed to register webhook: {data.get('description', 'unknown error')}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
