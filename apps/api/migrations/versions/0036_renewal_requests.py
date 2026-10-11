"""a renewal of a licence or insurance, with its proof, waiting for a manager to approve

Revision ID: 0036
Revises: 0035
Create Date: 2026-10-11 15:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0036'
down_revision: str | Sequence[str] | None = '0035'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('renewal_requests',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('doc_type', sa.String(length=20), nullable=False),
    sa.Column('vehicle_id', sa.Uuid(), nullable=True),
    sa.Column('membership_id', sa.Uuid(), nullable=True),
    sa.Column('new_expires_on', sa.Date(), nullable=False),
    sa.Column('proof_kind', sa.String(length=20), nullable=False),
    sa.Column('reference', sa.String(length=80), nullable=True),
    sa.Column('photo_id', sa.Uuid(), nullable=True),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('submitted_by_user_id', sa.Uuid(), nullable=True),
    sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('decided_by_user_id', sa.Uuid(), nullable=True),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('decision_note', sa.String(length=200), nullable=True),
    sa.Column('document_id', sa.Uuid(), nullable=True),
    sa.Column('business_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['decided_by_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['document_id'], ['compliance_documents.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['membership_id'], ['memberships.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['photo_id'], ['photos.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['submitted_by_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['vehicle_id'], ['vehicles.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_renewal_requests_business_id'), 'renewal_requests', ['business_id'], unique=False)
    op.create_index(op.f('ix_renewal_requests_membership_id'), 'renewal_requests', ['membership_id'], unique=False)
    op.create_index(op.f('ix_renewal_requests_status'), 'renewal_requests', ['status'], unique=False)
    op.create_index(op.f('ix_renewal_requests_vehicle_id'), 'renewal_requests', ['vehicle_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_renewal_requests_vehicle_id'), table_name='renewal_requests')
    op.drop_index(op.f('ix_renewal_requests_status'), table_name='renewal_requests')
    op.drop_index(op.f('ix_renewal_requests_membership_id'), table_name='renewal_requests')
    op.drop_index(op.f('ix_renewal_requests_business_id'), table_name='renewal_requests')
    op.drop_table('renewal_requests')
