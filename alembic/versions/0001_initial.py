"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-07-24

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(64)),
        sa.Column("first_name", sa.String(128)),
        sa.Column("last_name", sa.String(128)),
        sa.Column("language_code", sa.String(8)),
        sa.Column("role", sa.String(16), nullable=False, server_default="customer"),
        sa.Column("fsm_state", sa.String(64)),
        sa.Column("fsm_data", sa.JSON()),
        sa.Column("rate_window_start", sa.DateTime(timezone=True)),
        sa.Column("rate_window_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_users_telegram_user_id", "users", ["telegram_user_id"], unique=True)
    op.create_index("ix_users_role", "users", ["role"])

    op.create_table(
        "conversations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_conversations_user_id", "conversations", ["user_id"])
    op.create_index("ix_conversations_created_at", "conversations", ["created_at"])

    op.create_table(
        "support_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_request_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("original_question", sa.Text(), nullable=False),
        sa.Column("escalation_reason", sa.Text()),
        sa.Column("missing_information", sa.JSON()),
        sa.Column("customer_name", sa.String(128)),
        sa.Column("customer_phone", sa.String(32)),
        sa.Column("customer_email", sa.String(128)),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("admin_notified_at", sa.DateTime(timezone=True)),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_support_requests_public_request_id", "support_requests", ["public_request_id"], unique=True)
    op.create_index("ix_support_requests_user_id", "support_requests", ["user_id"])
    op.create_index("ix_support_requests_status", "support_requests", ["status"])
    op.create_index("ix_support_requests_created_at", "support_requests", ["created_at"])

    op.create_table(
        "admin_replies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "support_request_id",
            sa.Integer(),
            sa.ForeignKey("support_requests.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("admin_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("delivery_status", sa.String(16), nullable=False, server_default="pending"),
    )
    op.create_index("ix_admin_replies_support_request_id", "admin_replies", ["support_request_id"])

    op.create_table(
        "bot_settings",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("value", sa.Text()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "processed_updates",
        sa.Column("update_id", sa.BigInteger(), primary_key=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("processed_updates")
    op.drop_table("bot_settings")
    op.drop_index("ix_admin_replies_support_request_id", table_name="admin_replies")
    op.drop_table("admin_replies")
    op.drop_index("ix_support_requests_created_at", table_name="support_requests")
    op.drop_index("ix_support_requests_status", table_name="support_requests")
    op.drop_index("ix_support_requests_user_id", table_name="support_requests")
    op.drop_index("ix_support_requests_public_request_id", table_name="support_requests")
    op.drop_table("support_requests")
    op.drop_index("ix_conversations_created_at", table_name="conversations")
    op.drop_index("ix_conversations_user_id", table_name="conversations")
    op.drop_table("conversations")
    op.drop_index("ix_users_role", table_name="users")
    op.drop_index("ix_users_telegram_user_id", table_name="users")
    op.drop_table("users")
