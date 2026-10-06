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
    # Both are optional: the app runs on plain PostgreSQL (managed hosts such as Supabase or Render may not offer TimescaleDB).
    for extension in ("postgis", "timescaledb"):
        op.execute(
            f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = '{extension}') "
            f"THEN CREATE EXTENSION IF NOT EXISTS {extension}; END IF; END $$"
        )


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS timescaledb")
    op.execute("DROP EXTENSION IF EXISTS postgis")
