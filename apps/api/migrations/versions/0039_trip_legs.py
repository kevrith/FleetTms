"""loaded and empty kilometres of a trip, and why it ended away from the depot

Revision ID: 0039
Revises: 0038
Create Date: 2026-10-13 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0039'
down_revision: str | Sequence[str] | None = '0038'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('trips', sa.Column('loaded_km', sa.Integer(), nullable=True))
    op.add_column('trips', sa.Column('empty_km', sa.Integer(), nullable=True))
    op.add_column('trips', sa.Column('ended_away_reason', sa.String(length=200), nullable=True))


def downgrade() -> None:
    op.drop_column('trips', 'ended_away_reason')
    op.drop_column('trips', 'empty_km')
    op.drop_column('trips', 'loaded_km')
