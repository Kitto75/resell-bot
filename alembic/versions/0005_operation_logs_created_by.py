"""add actor telegram id to operation logs

Revision ID: 0005_operation_logs_created_by
Revises: 0004_reseller_telegram_accounts
Create Date: 2026-07-06
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_operation_logs_created_by"
down_revision = "0004_reseller_telegram_accounts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("operation_logs", sa.Column("created_by", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("operation_logs", "created_by")
