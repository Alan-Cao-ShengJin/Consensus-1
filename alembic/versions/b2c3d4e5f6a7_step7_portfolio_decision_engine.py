"""Step 7: portfolio decision engine tables and fields

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-03-12 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str]] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- New fields on portfolio_positions ---
    op.add_column('portfolio_positions', sa.Column('probation_start_date', sa.Date(), nullable=True))
    op.add_column('portfolio_positions', sa.Column('probation_reviews_count', sa.Integer(), server_default='0', nullable=False))
    op.add_column('portfolio_positions', sa.Column('cooldown_until', sa.Date(), nullable=True))
    op.add_column('portfolio_positions', sa.Column('exit_date', sa.Date(), nullable=True))
    op.add_column('portfolio_positions', sa.Column('exit_reason', sa.String(length=100), nullable=True))

    # --- New field on candidates ---
    op.add_column('candidates', sa.Column('cooldown_until', sa.Date(), nullable=True))

    # --- New table: portfolio_reviews ---
    op.create_table('portfolio_reviews',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('review_date', sa.Date(), nullable=False),
        sa.Column('review_type', sa.String(length=50), nullable=False),
        sa.Column('holdings_reviewed', sa.Integer(), server_default='0', nullable=False),
        sa.Column('candidates_reviewed', sa.Integer(), server_default='0', nullable=False),
        sa.Column('turnover_pct', sa.Float(), server_default='0.0', nullable=False),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_portfolio_reviews_review_date'), 'portfolio_reviews', ['review_date'], unique=False)

    # --- New table: portfolio_decisions ---
    op.create_table('portfolio_decisions',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('review_id', sa.Integer(), nullable=False),
        sa.Column('ticker', sa.String(length=20), nullable=False),
        sa.Column('action', sa.Enum('initiate', 'add', 'hold', 'trim', 'probation', 'exit', 'no_action', name='actiontype'), nullable=False),
        sa.Column('action_score', sa.Float(), nullable=False),
        sa.Column('target_weight_change', sa.Float(), nullable=True),
        sa.Column('suggested_weight', sa.Float(), nullable=True),
        sa.Column('reason_codes', sa.Text(), nullable=True),
        sa.Column('rationale', sa.Text(), nullable=True),
        sa.Column('blocking_conditions', sa.Text(), nullable=True),
        sa.Column('required_followup', sa.Text(), nullable=True),
        sa.Column('was_executed', sa.Boolean(), server_default='0', nullable=False),
        sa.Column('generated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['review_id'], ['portfolio_reviews.id']),
        sa.ForeignKeyConstraint(['ticker'], ['companies.ticker']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_portfolio_decisions_review_id'), 'portfolio_decisions', ['review_id'], unique=False)
    op.create_index(op.f('ix_portfolio_decisions_ticker'), 'portfolio_decisions', ['ticker'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_portfolio_decisions_ticker'), table_name='portfolio_decisions')
    op.drop_index(op.f('ix_portfolio_decisions_review_id'), table_name='portfolio_decisions')
    op.drop_table('portfolio_decisions')
    op.drop_index(op.f('ix_portfolio_reviews_review_date'), table_name='portfolio_reviews')
    op.drop_table('portfolio_reviews')
    op.drop_column('candidates', 'cooldown_until')
    op.drop_column('portfolio_positions', 'exit_reason')
    op.drop_column('portfolio_positions', 'exit_date')
    op.drop_column('portfolio_positions', 'cooldown_until')
    op.drop_column('portfolio_positions', 'probation_reviews_count')
    op.drop_column('portfolio_positions', 'probation_start_date')
