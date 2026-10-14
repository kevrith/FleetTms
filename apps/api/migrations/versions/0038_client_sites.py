"""client sites, the client on a trip, and a driver-added client waiting for the office

Revision ID: 0038
Revises: 0037
Create Date: 2026-10-13 09:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0038'
down_revision: str | Sequence[str] | None = '0037'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('client_sites',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('client_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=160), nullable=False),
    sa.Column('address', sa.String(length=255), nullable=True),
    sa.Column('lat', sa.Float(), nullable=False),
    sa.Column('lng', sa.Float(), nullable=False),
    sa.Column('radius_m', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('saved_by_user_id', sa.Uuid(), nullable=True),
    sa.Column('saved_from_trip_id', sa.Uuid(), nullable=True),
    sa.Column('verified_by_code', sa.Boolean(), nullable=False),
    sa.Column('confirmed_by_user_id', sa.Uuid(), nullable=True),
    sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('business_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['saved_by_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['confirmed_by_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('business_id', 'client_id', 'name')
    )
    op.create_index(op.f('ix_client_sites_business_id'), 'client_sites', ['business_id'], unique=False)
    op.create_index(op.f('ix_client_sites_client_id'), 'client_sites', ['client_id'], unique=False)

    op.add_column('clients', sa.Column('needs_review', sa.Boolean(), server_default=sa.text('false'), nullable=False))
    op.add_column('saved_routes', sa.Column('site_id', sa.Uuid(), nullable=True))
    op.create_foreign_key('fk_saved_routes_site_id', 'saved_routes', 'client_sites', ['site_id'], ['id'], ondelete='SET NULL')
    op.add_column('trips', sa.Column('client_id', sa.Uuid(), nullable=True))
    op.add_column('trips', sa.Column('site_id', sa.Uuid(), nullable=True))
    op.create_foreign_key('fk_trips_client_id', 'trips', 'clients', ['client_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_trips_site_id', 'trips', 'client_sites', ['site_id'], ['id'], ondelete='SET NULL')
    op.create_index(op.f('ix_trips_client_id'), 'trips', ['client_id'], unique=False)

    # Trips that already have a job get that job's client; routes that already have a mapped drop-off become confirmed sites, so what the
    # office entered is on the client's list of places and a driver choosing the client is guided there.
    op.execute("UPDATE trips SET client_id = jobs.client_id FROM jobs WHERE trips.job_id = jobs.id")
    op.execute(
        """
        INSERT INTO client_sites (id, business_id, client_id, name, lat, lng, radius_m, status, verified_by_code, is_active, created_at)
        SELECT DISTINCT ON (business_id, client_id, dropoff) gen_random_uuid(), business_id, client_id, dropoff, dropoff_lat, dropoff_lng,
               LEAST(GREATEST(site_radius_m, 50), 20000), 'confirmed', false, true, now()
        FROM saved_routes
        WHERE client_id IS NOT NULL AND dropoff_lat IS NOT NULL AND dropoff_lng IS NOT NULL
        ORDER BY business_id, client_id, dropoff, is_active DESC, created_at
        ON CONFLICT DO NOTHING
        """
    )
    op.execute(
        """
        UPDATE saved_routes SET site_id = client_sites.id FROM client_sites
        WHERE client_sites.business_id = saved_routes.business_id AND client_sites.client_id = saved_routes.client_id
          AND client_sites.name = saved_routes.dropoff AND saved_routes.dropoff_lat IS NOT NULL AND saved_routes.dropoff_lng IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_trips_client_id'), table_name='trips')
    op.drop_constraint('fk_trips_site_id', 'trips', type_='foreignkey')
    op.drop_constraint('fk_trips_client_id', 'trips', type_='foreignkey')
    op.drop_column('trips', 'site_id')
    op.drop_column('trips', 'client_id')
    op.drop_constraint('fk_saved_routes_site_id', 'saved_routes', type_='foreignkey')
    op.drop_column('saved_routes', 'site_id')
    op.drop_column('clients', 'needs_review')
    op.drop_index(op.f('ix_client_sites_client_id'), table_name='client_sites')
    op.drop_index(op.f('ix_client_sites_business_id'), table_name='client_sites')
    op.drop_table('client_sites')
