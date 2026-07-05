"""add recharge processing metadata

Revision ID: 0002_recharge_processing_metadata
Revises: 0001_initial
Create Date: 2026-07-05
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_recharge_processing_metadata"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("recharge_requests", sa.Column("processed_by_admin_id", sa.Integer(), nullable=True))
    op.add_column("recharge_requests", sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("recharge_requests", "processed_at")
    op.drop_column("recharge_requests", "processed_by_admin_id")
