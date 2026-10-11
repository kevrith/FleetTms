"""a business can stop trips whose driver or vehicle has an expired document

Revision ID: 0035
Revises: 0034
Create Date: 2026-10-11 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0035'
down_revision: str | Sequence[str] | None = '0034'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('businesses', sa.Column('document_rule', sa.String(length=5), server_default=sa.text("'warn'"), nullable=False))
    op.add_column('businesses', sa.Column('required_documents', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("""'["insurance", "driving_licence"]'::jsonb"""), nullable=False))
    op.add_column('trips', sa.Column('compliance_override_reason', sa.String(length=200), nullable=True))
    op.add_column('trips', sa.Column('compliance_override_by_user_id', sa.Uuid(), nullable=True))
    op.add_column('trips', sa.Column('compliance_override_at', sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key('fk_trips_compliance_override_by_user_id', 'trips', 'users', ['compliance_override_by_user_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    op.drop_constraint('fk_trips_compliance_override_by_user_id', 'trips', type_='foreignkey')
    op.drop_column('trips', 'compliance_override_at')
    op.drop_column('trips', 'compliance_override_by_user_id')
    op.drop_column('trips', 'compliance_override_reason')
    op.drop_column('businesses', 'required_documents')
    op.drop_column('businesses', 'document_rule')
