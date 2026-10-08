"""work order photos

Revision ID: 0029
Revises: 0028
Create Date: 2026-10-05 11:20:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0029'
down_revision: str | Sequence[str] | None = '0028'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'work_orders',
        sa.Column('photo_ids', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column('work_orders', 'photo_ids')
