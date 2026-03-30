"""create analysis records

Revision ID: 20260327_000001
Revises:
Create Date: 2026-03-27 00:00:01
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260327_000001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "analysis_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("ticker", sa.String(length=24), nullable=False),
        sa.Column("recommendation", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_analysis_records_ticker", "analysis_records", ["ticker"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_analysis_records_ticker", table_name="analysis_records")
    op.drop_table("analysis_records")
