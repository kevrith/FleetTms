"""a vehicle can take its distance from GPS instead of a faulty odometer

Revision ID: 0034
Revises: 0033
Create Date: 2026-10-11 09:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0034'
down_revision: str | Sequence[str] | None = '0033'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('vehicles', sa.Column('distance_source', sa.String(length=10), server_default=sa.text("'odometer'"), nullable=False))
    op.add_column('trips', sa.Column('km_credited', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('trips', 'km_credited')
    op.drop_column('vehicles', 'distance_source')
