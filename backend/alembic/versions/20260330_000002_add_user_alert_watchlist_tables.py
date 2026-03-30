"""add user, session, alert, and watchlist tables

Revision ID: 20260330_000002
Revises: 20260327_000001
Create Date: 2026-03-30 01:40:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260330_000002"
down_revision: Union[str, None] = "20260327_000001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("analysis_records", sa.Column("user_id", sa.String(length=36), nullable=True))
    op.create_index("ix_analysis_records_user_id", "analysis_records", ["user_id"], unique=False)

    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sessions_expires_at", "sessions", ["expires_at"], unique=False)
    op.create_index("ix_sessions_token_hash", "sessions", ["token_hash"], unique=True)
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"], unique=False)

    op.create_table(
        "saved_watchlist_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("ticker", sa.String(length=24), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "ticker", name="uq_saved_watchlist_user_ticker"),
    )
    op.create_index("ix_saved_watchlist_items_ticker", "saved_watchlist_items", ["ticker"], unique=False)
    op.create_index("ix_saved_watchlist_items_user_id", "saved_watchlist_items", ["user_id"], unique=False)

    op.create_table(
        "alerts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("ticker", sa.String(length=24), nullable=False),
        sa.Column("alert_type", sa.String(length=32), nullable=False),
        sa.Column("threshold_value", sa.Float(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_alerts_ticker", "alerts", ["ticker"], unique=False)
    op.create_index("ix_alerts_user_id", "alerts", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_alerts_user_id", table_name="alerts")
    op.drop_index("ix_alerts_ticker", table_name="alerts")
    op.drop_table("alerts")

    op.drop_index("ix_saved_watchlist_items_user_id", table_name="saved_watchlist_items")
    op.drop_index("ix_saved_watchlist_items_ticker", table_name="saved_watchlist_items")
    op.drop_table("saved_watchlist_items")

    op.drop_index("ix_sessions_user_id", table_name="sessions")
    op.drop_index("ix_sessions_token_hash", table_name="sessions")
    op.drop_index("ix_sessions_expires_at", table_name="sessions")
    op.drop_table("sessions")

    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")

    op.drop_index("ix_analysis_records_user_id", table_name="analysis_records")
    op.drop_column("analysis_records", "user_id")
