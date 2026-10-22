"""Remove the currently configured Telegram webhook (local troubleshooting).

Usage:
    python scripts/delete_webhook.py
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
    response = httpx.post(
        f"https://api.telegram.org/bot{token}/deleteWebhook",
        json={"drop_pending_updates": False},
        timeout=15.0,
    )
    data = response.json()
    if data.get("ok"):
        print("Webhook deleted successfully.")
    else:
        print(f"Failed to delete webhook: {data.get('description', 'unknown error')}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
