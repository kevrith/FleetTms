"""a phone's push address on the user

Revision ID: 0032
Revises: 0031
Create Date: 2026-10-08 21:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0032'
down_revision: str | Sequence[str] | None = '0031'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('users', sa.Column('push_token', sa.String(length=200), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'push_token')
