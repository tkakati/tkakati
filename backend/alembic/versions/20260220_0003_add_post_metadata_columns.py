"""add metadata columns to posts

Revision ID: 20260220_0003
Revises: 20260220_0002
Create Date: 2026-02-20 10:05:00.000000

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260220_0003"
down_revision: str | None = "20260220_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("posts", sa.Column("seniority", sa.String(length=120), nullable=True))
    op.add_column("posts", sa.Column("location", sa.String(length=120), nullable=True))
    op.add_column("posts", sa.Column("remote", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("posts", "remote")
    op.drop_column("posts", "location")
    op.drop_column("posts", "seniority")
