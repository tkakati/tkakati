"""add hiring_signals table

Revision ID: 20260224_0004
Revises: 20260220_0003
Create Date: 2026-02-24 11:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260224_0004"
down_revision: str | None = "20260220_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "hiring_signals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company", sa.String(length=255), nullable=True),
        sa.Column("role", sa.String(length=255), nullable=True),
        sa.Column("seniority", sa.String(length=120), nullable=True),
        sa.Column("is_hiring", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("signal_strength", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("signal_type", sa.String(length=20), nullable=False, server_default="noise"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("reasoning", sa.Text(), nullable=True),
        sa.Column("source_url", sa.String(length=2048), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_hiring_signals_id"), "hiring_signals", ["id"], unique=False)
    op.create_index(op.f("ix_hiring_signals_company"), "hiring_signals", ["company"], unique=False)
    op.create_index(op.f("ix_hiring_signals_source_url"), "hiring_signals", ["source_url"], unique=False)
    op.create_index(op.f("ix_hiring_signals_timestamp"), "hiring_signals", ["timestamp"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_hiring_signals_timestamp"), table_name="hiring_signals")
    op.drop_index(op.f("ix_hiring_signals_source_url"), table_name="hiring_signals")
    op.drop_index(op.f("ix_hiring_signals_company"), table_name="hiring_signals")
    op.drop_index(op.f("ix_hiring_signals_id"), table_name="hiring_signals")
    op.drop_table("hiring_signals")
