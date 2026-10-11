"""what a renewal's proof was read as, and how it compares with what was typed

Revision ID: 0037
Revises: 0036
Create Date: 2026-10-11 18:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0037'
down_revision: str | Sequence[str] | None = '0036'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('renewal_requests', sa.Column('proof_check', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column('renewal_requests', 'proof_check')
