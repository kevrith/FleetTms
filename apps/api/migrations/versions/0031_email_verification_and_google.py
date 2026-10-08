"""email verification and google sign-in

Revision ID: 0031
Revises: 0030
Create Date: 2026-10-06 22:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0031'
down_revision: str | Sequence[str] | None = '0030'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('users', sa.Column('email_verified_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('users', sa.Column('email_verify_token_hash', sa.String(length=64), nullable=True))
    op.add_column('users', sa.Column('email_verify_expires_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('users', sa.Column('google_sub', sa.String(length=64), nullable=True))
    op.create_unique_constraint('uq_users_google_sub', 'users', ['google_sub'])
    # Everyone who already has an email address keeps working: only sign-ups from now on have to confirm theirs.
    op.execute("UPDATE users SET email_verified_at = now() WHERE email IS NOT NULL")


def downgrade() -> None:
    op.drop_constraint('uq_users_google_sub', 'users', type_='unique')
    op.drop_column('users', 'google_sub')
    op.drop_column('users', 'email_verify_expires_at')
    op.drop_column('users', 'email_verify_token_hash')
    op.drop_column('users', 'email_verified_at')
