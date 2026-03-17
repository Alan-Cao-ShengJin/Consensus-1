"""Live orders and fills tables.

Revision ID: c3d4e5f6a7b8
Revises: dd6550e7a397
Create Date: 2026-03-16
"""
from alembic import op
import sqlalchemy as sa

revision = 'c3d4e5f6a7b8'
down_revision = 'dd6550e7a397'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'live_orders',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('order_id', sa.String(50), nullable=False),
        sa.Column('broker_order_id', sa.String(50), nullable=True),
        sa.Column('ticker', sa.String(20), nullable=False),
        sa.Column('side', sa.String(10), nullable=False),
        sa.Column('action_type', sa.String(20), nullable=False),
        sa.Column('quantity', sa.Float(), nullable=False),
        sa.Column('order_type', sa.String(20), nullable=False),
        sa.Column('limit_price', sa.Float(), nullable=True),
        sa.Column('time_in_force', sa.String(10), nullable=False, server_default='day'),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('filled_quantity', sa.Float(), nullable=False, server_default='0'),
        sa.Column('filled_avg_price', sa.Float(), nullable=True),
        sa.Column('intent_id', sa.String(100), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('state_history_json', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('submitted_at', sa.DateTime(), nullable=True),
        sa.Column('filled_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_live_orders_order_id', 'live_orders', ['order_id'], unique=True)
    op.create_index('ix_live_orders_broker_order_id', 'live_orders', ['broker_order_id'])
    op.create_index('ix_live_orders_ticker', 'live_orders', ['ticker'])

    op.create_table(
        'live_fills',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('fill_id', sa.String(50), nullable=False),
        sa.Column('order_id', sa.String(50), nullable=False),
        sa.Column('broker_order_id', sa.String(50), nullable=True),
        sa.Column('ticker', sa.String(20), nullable=False),
        sa.Column('side', sa.String(10), nullable=False),
        sa.Column('shares', sa.Float(), nullable=False),
        sa.Column('fill_price', sa.Float(), nullable=False),
        sa.Column('notional', sa.Float(), nullable=False),
        sa.Column('filled_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_live_fills_fill_id', 'live_fills', ['fill_id'], unique=True)
    op.create_index('ix_live_fills_order_id', 'live_fills', ['order_id'])
    op.create_index('ix_live_fills_ticker', 'live_fills', ['ticker'])


def downgrade() -> None:
    op.drop_table('live_fills')
    op.drop_table('live_orders')
