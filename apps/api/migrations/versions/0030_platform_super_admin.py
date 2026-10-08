"""platform super admin

Revision ID: 0030
Revises: 0029
Create Date: 2026-10-06 21:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0030'
down_revision: str | Sequence[str] | None = '0029'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('users', sa.Column('is_platform_super', sa.Boolean(), server_default=sa.text('false'), nullable=False))
    # Everyone who runs the console today was put there from the command line, so they become super admins.
    op.execute("UPDATE users SET is_platform_super = true WHERE is_platform_admin")


def downgrade() -> None:
    op.drop_column('users', 'is_platform_super')
