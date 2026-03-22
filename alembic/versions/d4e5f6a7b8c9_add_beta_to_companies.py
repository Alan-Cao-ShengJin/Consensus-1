"""Add beta column to companies table.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-03-17
"""
from alembic import op
import sqlalchemy as sa

revision = 'd4e5f6a7b8c9'
down_revision = 'c3d4e5f6a7b8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('companies', sa.Column('beta', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('companies', 'beta')
