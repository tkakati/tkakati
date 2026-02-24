"""expand hiring_signals and add signal_feedback

Revision ID: 20260224_0005
Revises: 20260224_0004
Create Date: 2026-02-24 12:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260224_0005"
down_revision: str | None = "20260224_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("hiring_signals", sa.Column("company_source", sa.String(length=20), nullable=False, server_default="llm"))
    op.add_column("hiring_signals", sa.Column("company_confidence", sa.Float(), nullable=False, server_default="0"))
    op.add_column("hiring_signals", sa.Column("hiring_confidence", sa.Float(), nullable=False, server_default="0"))
    op.add_column("hiring_signals", sa.Column("role_match_score", sa.Float(), nullable=False, server_default="0"))
    op.add_column("hiring_signals", sa.Column("review_status", sa.String(length=20), nullable=False, server_default="pending"))
    op.add_column("hiring_signals", sa.Column("review_label", sa.String(length=120), nullable=True))
    op.add_column("hiring_signals", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("hiring_signals", sa.Column("reviewed_by", sa.String(length=120), nullable=True))
    op.create_index(op.f("ix_hiring_signals_review_status"), "hiring_signals", ["review_status"], unique=False)

    op.create_table(
        "signal_feedback",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("signal_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("reviewer_id", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_signal_feedback_id"), "signal_feedback", ["id"], unique=False)
    op.create_index(op.f("ix_signal_feedback_signal_id"), "signal_feedback", ["signal_id"], unique=False)
    op.create_index(op.f("ix_signal_feedback_created_at"), "signal_feedback", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_signal_feedback_created_at"), table_name="signal_feedback")
    op.drop_index(op.f("ix_signal_feedback_signal_id"), table_name="signal_feedback")
    op.drop_index(op.f("ix_signal_feedback_id"), table_name="signal_feedback")
    op.drop_table("signal_feedback")

    op.drop_index(op.f("ix_hiring_signals_review_status"), table_name="hiring_signals")
    op.drop_column("hiring_signals", "reviewed_by")
    op.drop_column("hiring_signals", "reviewed_at")
    op.drop_column("hiring_signals", "review_label")
    op.drop_column("hiring_signals", "review_status")
    op.drop_column("hiring_signals", "role_match_score")
    op.drop_column("hiring_signals", "hiring_confidence")
    op.drop_column("hiring_signals", "company_confidence")
    op.drop_column("hiring_signals", "company_source")
