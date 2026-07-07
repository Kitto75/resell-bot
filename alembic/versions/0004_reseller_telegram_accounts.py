"""add reseller telegram accounts

Revision ID: 0004_reseller_telegram_accounts
Revises: 0003_unique_created_users_username
Create Date: 2026-07-06
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_reseller_telegram_accounts"
down_revision = "0003_unique_created_users_username"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reseller_telegram_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("reseller_id", sa.Integer(), sa.ForeignKey("resellers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("telegram_id", sa.Integer(), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_reseller_telegram_accounts_reseller_id", "reseller_telegram_accounts", ["reseller_id"])
    op.create_index("ix_reseller_telegram_accounts_telegram_id", "reseller_telegram_accounts", ["telegram_id"], unique=True)
    op.execute(
        """
        INSERT INTO reseller_telegram_accounts (reseller_id, telegram_id, is_primary, created_at, updated_at)
        SELECT id, telegram_id, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        FROM resellers
        WHERE telegram_id IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_index("ix_reseller_telegram_accounts_telegram_id", table_name="reseller_telegram_accounts")
    op.drop_index("ix_reseller_telegram_accounts_reseller_id", table_name="reseller_telegram_accounts")
    op.drop_table("reseller_telegram_accounts")
