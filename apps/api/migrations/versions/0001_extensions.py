"""enable postgis and timescaledb

Revision ID: 0001
Revises:
"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS timescaledb")
    op.execute("DROP EXTENSION IF EXISTS postgis")
