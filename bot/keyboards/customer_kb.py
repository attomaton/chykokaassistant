from __future__ import annotations

from typing import Any

from bot.locales import t


def escalation_offer_keyboard() -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {"text": t("btn_leave_contacts"), "callback_data": "esc:contact"},
                {"text": t("btn_cancel"), "callback_data": "esc:cancel"},
            ]
        ]
    }


def contact_share_keyboard() -> dict[str, Any]:
    return {
        "keyboard": [[{"text": t("btn_share_phone"), "request_contact": True}]],
        "resize_keyboard": True,
        "one_time_keyboard": True,
    }


def remove_keyboard() -> dict[str, Any]:
    return {"remove_keyboard": True}


def skip_back_cancel_keyboard(field: str, *, allow_back: bool = True) -> dict[str, Any]:
    row = [{"text": t("btn_skip"), "callback_data": f"field:skip:{field}"}]
    if allow_back:
        row.append({"text": t("btn_back"), "callback_data": f"field:back:{field}"})
    row.append({"text": t("btn_cancel"), "callback_data": "esc:cancel"})
    return {"inline_keyboard": [row]}


def confirm_contact_keyboard() -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {"text": t("btn_confirm"), "callback_data": "contact:confirm"},
                {"text": t("btn_edit"), "callback_data": "field:back:confirm"},
            ],
            [{"text": t("btn_cancel"), "callback_data": "esc:cancel"}],
        ]
    }


def delete_data_confirm_keyboard() -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {"text": t("btn_delete_yes"), "callback_data": "delete:confirm"},
                {"text": t("btn_cancel"), "callback_data": "delete:cancel"},
            ]
        ]
    }
