from __future__ import annotations

from typing import Any


def admin_request_keyboard(public_request_id: str) -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {"text": "Reply", "callback_data": f"admin:reply:{public_request_id}"},
                {"text": "Mark resolved", "callback_data": f"admin:resolve:{public_request_id}"},
            ],
            [{"text": "View details", "callback_data": f"admin:view:{public_request_id}"}],
        ]
    }


def admin_menu_keyboard() -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [{"text": "Recent requests", "callback_data": "admin:requests"}],
            [{"text": "Stats", "callback_data": "admin:stats"}],
            [{"text": "Reload knowledge base", "callback_data": "admin:reload"}],
        ]
    }


def admin_reply_confirm_keyboard(public_request_id: str) -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {"text": "Send", "callback_data": f"admin:send_reply:{public_request_id}"},
                {"text": "Cancel", "callback_data": f"admin:cancel_reply:{public_request_id}"},
            ]
        ]
    }


def resolve_prompt_keyboard(public_request_id: str) -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {"text": "Yes, mark resolved", "callback_data": f"admin:resolve:{public_request_id}"},
                {"text": "Not yet", "callback_data": f"admin:skip_resolve:{public_request_id}"},
            ]
        ]
    }
