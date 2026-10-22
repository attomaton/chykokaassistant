"""Print the current Telegram webhook configuration (local troubleshooting).

Never prints the bot token; only the webhook URL and delivery metadata that
Telegram itself returns.

Usage:
    python scripts/webhook_info.py
"""
from __future__ import annotations

import json
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
    response = httpx.post(f"https://api.telegram.org/bot{token}/getWebhookInfo", timeout=15.0)
    data = response.json()
    if not data.get("ok"):
        print(f"Failed to fetch webhook info: {data.get('description', 'unknown error')}", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(data.get("result", {}), indent=2))


if __name__ == "__main__":
    main()
