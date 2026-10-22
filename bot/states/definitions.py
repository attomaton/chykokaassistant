"""FSM state names, persisted on the User row (see database/models.py).

Kept as plain string constants rather than a strict enum column so the
database stays portable and forward-compatible without a migration for
every new state.
"""
from __future__ import annotations


class FSMState:
    NONE = "none"

    # Customer escalation / contact-collection flow
    AWAITING_ESCALATION_CONFIRM = "awaiting_escalation_confirm"
    COLLECTING_NAME = "collecting_name"
    COLLECTING_PHONE = "collecting_phone"
    COLLECTING_EMAIL = "collecting_email"
    CONFIRMING_CONTACT = "confirming_contact"

    # Administrator reply flow
    ADMIN_AWAITING_REPLY = "admin_awaiting_reply"
    ADMIN_CONFIRM_REPLY = "admin_confirm_reply"

    # Data deletion confirmation
    AWAITING_DELETE_CONFIRM = "awaiting_delete_confirm"


# fsm_data keys (all states share one JSON blob on the user row)
KEY_QUESTION = "question"
KEY_REASON = "reason"
KEY_MISSING = "missing"
KEY_NAME = "name"
KEY_PHONE = "phone"
KEY_EMAIL = "email"
KEY_REQUEST_ID = "request_id"
KEY_DRAFT = "draft"
