"""report schedules

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-02 18:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0009'
down_revision: str | Sequence[str] | None = '0008'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('report_schedules',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('frequency', sa.Enum('daily', 'weekly', 'monthly', name='reportfrequency', native_enum=False, length=20), nullable=False),
    sa.Column('channel', sa.Enum('email', 'whatsapp', name='reportchannel', native_enum=False, length=20), nullable=False),
    sa.Column('recipient', sa.String(length=255), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('last_period_end', sa.Date(), nullable=True),
    sa.Column('last_error', sa.String(length=255), nullable=True),
    sa.Column('created_by_user_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('business_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_report_schedules_business_id'), 'report_schedules', ['business_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_report_schedules_business_id'), table_name='report_schedules')
    op.drop_table('report_schedules')
