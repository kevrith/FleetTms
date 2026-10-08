"""what was received for a trip that has no invoice

Revision ID: 0033
Revises: 0032
Create Date: 2026-10-08 23:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0033'
down_revision: str | Sequence[str] | None = '0032'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('trips', sa.Column('received_cents', sa.BigInteger(), nullable=True))
    op.add_column('trips', sa.Column('received_note', sa.String(length=200), nullable=True))
    op.add_column('trips', sa.Column('received_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('trips', 'received_at')
    op.drop_column('trips', 'received_note')
    op.drop_column('trips', 'received_cents')
