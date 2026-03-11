"""Step 6: prices table, document source_key + external_id

Revision ID: a1b2c3d4e5f6
Revises: dd6550e7a397
Create Date: 2026-03-12 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str]] = 'dd6550e7a397'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- New prices table ---
    op.create_table('prices',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('ticker', sa.String(length=20), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('open', sa.Float(), nullable=True),
        sa.Column('high', sa.Float(), nullable=True),
        sa.Column('low', sa.Float(), nullable=True),
        sa.Column('close', sa.Float(), nullable=True),
        sa.Column('adj_close', sa.Float(), nullable=True),
        sa.Column('volume', sa.Integer(), nullable=True),
        sa.Column('source', sa.String(length=50), nullable=True),
        sa.ForeignKeyConstraint(['ticker'], ['companies.ticker'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('ticker', 'date', name='uq_price_ticker_date'),
    )
    op.create_index(op.f('ix_prices_ticker'), 'prices', ['ticker'], unique=False)
    op.create_index(op.f('ix_prices_date'), 'prices', ['date'], unique=False)

    # --- Add source_key and external_id to documents ---
    op.add_column('documents', sa.Column('source_key', sa.String(length=100), nullable=True))
    op.add_column('documents', sa.Column('external_id', sa.String(length=255), nullable=True))
    op.create_index(op.f('ix_documents_source_key'), 'documents', ['source_key'], unique=False)
    op.create_index(op.f('ix_documents_external_id'), 'documents', ['external_id'], unique=False)
    op.create_unique_constraint('uq_source_external', 'documents', ['source_key', 'external_id'])


def downgrade() -> None:
    op.drop_constraint('uq_source_external', 'documents', type_='unique')
    op.drop_index(op.f('ix_documents_external_id'), table_name='documents')
    op.drop_index(op.f('ix_documents_source_key'), table_name='documents')
    op.drop_column('documents', 'external_id')
    op.drop_column('documents', 'source_key')
    op.drop_index(op.f('ix_prices_date'), table_name='prices')
    op.drop_index(op.f('ix_prices_ticker'), table_name='prices')
    op.drop_table('prices')
