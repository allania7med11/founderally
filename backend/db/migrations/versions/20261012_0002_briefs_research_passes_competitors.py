"""briefs, research_passes, competitors; runs gain round, pass, cost_usd and lose brief_id

Revision ID: 0002
Revises: 0001

Generated with `make makemigrations`. The brief points at its run, not the other way: one run has one brief per
round, so the key sits on the briefs side and `runs.brief_id` (0001, a bare uuid with no brief behind it) goes.
Skeleton data only; a database with 0001 rows is reset with `make down` before `make migrate`.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = '0002'
down_revision = '0001'


def upgrade() -> None:
    op.create_table('briefs',
    sa.Column('brief_id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('thread_id', sa.Uuid(), nullable=False),
    sa.Column('run_id', sa.Uuid(), nullable=True),
    sa.Column('round', sa.Integer(), nullable=False),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('brief', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['run_id'], ['runs.run_id'], ),
    sa.PrimaryKeyConstraint('brief_id')
    )
    op.create_index(op.f('ix_briefs_tenant_id'), 'briefs', ['tenant_id'], unique=False)
    op.create_index('ux_briefs_run_round_confirmed', 'briefs', ['run_id', 'round'], unique=True, postgresql_where="status = 'confirmed'")
    op.create_table('competitors',
    sa.Column('competitor_id', sa.Uuid(), nullable=False),
    sa.Column('run_id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('round', sa.Integer(), nullable=False),
    sa.Column('pass', sa.Integer(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('offer', sa.Text(), nullable=True),
    sa.Column('price', sa.Text(), nullable=True),
    sa.Column('channel', sa.Text(), nullable=True),
    sa.Column('source_url', sa.Text(), nullable=False),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['run_id'], ['runs.run_id'], ),
    sa.PrimaryKeyConstraint('competitor_id')
    )
    op.create_index(op.f('ix_competitors_run_id'), 'competitors', ['run_id'], unique=False)
    op.create_index(op.f('ix_competitors_tenant_id'), 'competitors', ['tenant_id'], unique=False)
    op.create_table('research_passes',
    sa.Column('run_id', sa.Uuid(), nullable=False),
    sa.Column('round', sa.Integer(), nullable=False),
    sa.Column('pass', sa.Integer(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('pages', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('candidates', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('verdicts', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('rows_found', sa.Integer(), nullable=True),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['run_id'], ['runs.run_id'], ),
    sa.PrimaryKeyConstraint('run_id', 'round', 'pass')
    )
    op.create_index(op.f('ix_research_passes_tenant_id'), 'research_passes', ['tenant_id'], unique=False)
    op.add_column('runs', sa.Column('round', sa.Integer(), server_default='1', nullable=False))
    op.add_column('runs', sa.Column('pass', sa.Integer(), server_default='1', nullable=False))
    op.add_column('runs', sa.Column('cost_usd', sa.Numeric(precision=10, scale=6), server_default='0', nullable=False))
    op.drop_column('runs', 'brief_id')


def downgrade() -> None:
    # Nullable on the way back: existing runs have no brief id to put there.
    op.add_column('runs', sa.Column('brief_id', sa.UUID(), autoincrement=False, nullable=True))
    op.drop_column('runs', 'cost_usd')
    op.drop_column('runs', 'pass')
    op.drop_column('runs', 'round')
    op.drop_index(op.f('ix_research_passes_tenant_id'), table_name='research_passes')
    op.drop_table('research_passes')
    op.drop_index(op.f('ix_competitors_tenant_id'), table_name='competitors')
    op.drop_index(op.f('ix_competitors_run_id'), table_name='competitors')
    op.drop_table('competitors')
    op.drop_index('ux_briefs_run_round_confirmed', table_name='briefs', postgresql_where="status = 'confirmed'")
    op.drop_index(op.f('ix_briefs_tenant_id'), table_name='briefs')
    op.drop_table('briefs')
