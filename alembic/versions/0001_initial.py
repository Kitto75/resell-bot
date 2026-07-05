"""initial

Revision ID: 0001_initial
Revises: 
Create Date: 2026-07-05
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

reseller_status = sa.Enum("active", "disabled", "archived", name="resellerstatus")
transaction_type = sa.Enum("increase", "decrease", "set_balance", "create_user", "renew_user", "recharge", name="transactiontype")
recharge_status = sa.Enum("pending", "approved", "rejected", name="rechargestatus")
operation_type = sa.Enum("create", "renew", name="operationtype")

def upgrade() -> None:
    op.create_table("resellers", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("telegram_id", sa.Integer(), nullable=False), sa.Column("display_name", sa.String(255), nullable=False), sa.Column("balance", sa.Numeric(12, 2), nullable=False), sa.Column("price_per_gb", sa.Numeric(12, 2), nullable=False), sa.Column("status", reseller_status, nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_resellers_telegram_id", "resellers", ["telegram_id"], unique=True)
    op.create_table("bot_settings", sa.Column("key", sa.String(100), primary_key=True), sa.Column("value", sa.Text(), nullable=False))
    op.create_table("balance_transactions", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("reseller_id", sa.Integer(), sa.ForeignKey("resellers.id", ondelete="CASCADE"), nullable=False), sa.Column("type", transaction_type, nullable=False), sa.Column("amount", sa.Numeric(12, 2), nullable=False), sa.Column("balance_before", sa.Numeric(12, 2), nullable=False), sa.Column("balance_after", sa.Numeric(12, 2), nullable=False), sa.Column("description", sa.Text()), sa.Column("created_by", sa.Integer()), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_balance_transactions_reseller_id", "balance_transactions", ["reseller_id"])
    op.create_index("ix_balance_transactions_created_at", "balance_transactions", ["created_at"])
    op.create_table("recharge_requests", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("reseller_id", sa.Integer(), sa.ForeignKey("resellers.id", ondelete="CASCADE"), nullable=False), sa.Column("amount", sa.Numeric(12, 2), nullable=False), sa.Column("receipt_file_id", sa.String(255)), sa.Column("receipt_text", sa.Text()), sa.Column("status", recharge_status, nullable=False), sa.Column("admin_reason", sa.Text()), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_recharge_requests_reseller_id", "recharge_requests", ["reseller_id"])
    op.create_table("reseller_inbounds", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("reseller_id", sa.Integer(), sa.ForeignKey("resellers.id", ondelete="CASCADE"), nullable=False), sa.Column("inbound_tag", sa.String(255), nullable=False), sa.UniqueConstraint("reseller_id", "inbound_tag"))
    op.create_index("ix_reseller_inbounds_reseller_id", "reseller_inbounds", ["reseller_id"])
    op.create_table("created_users", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("reseller_id", sa.Integer(), sa.ForeignKey("resellers.id", ondelete="CASCADE"), nullable=False), sa.Column("username", sa.String(255), nullable=False), sa.Column("marzban_status", sa.String(50), nullable=False), sa.Column("total_gb", sa.Integer(), nullable=False), sa.Column("total_days", sa.Integer(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_created_users_reseller_id", "created_users", ["reseller_id"])
    op.create_index("ix_created_users_username", "created_users", ["username"])
    op.create_index("ix_created_users_reseller_username", "created_users", ["reseller_id", "username"])
    op.create_table("operation_logs", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("reseller_id", sa.Integer(), sa.ForeignKey("resellers.id", ondelete="CASCADE"), nullable=False), sa.Column("username", sa.String(255), nullable=False), sa.Column("operation_type", operation_type, nullable=False), sa.Column("added_gb", sa.Integer(), nullable=False), sa.Column("added_days", sa.Integer(), nullable=False), sa.Column("charged_amount", sa.Numeric(12, 2), nullable=False), sa.Column("balance_before", sa.Numeric(12, 2), nullable=False), sa.Column("balance_after", sa.Numeric(12, 2), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_operation_logs_reseller_id", "operation_logs", ["reseller_id"])
    op.create_index("ix_operation_logs_username", "operation_logs", ["username"])

def downgrade() -> None:
    for table in ["operation_logs", "created_users", "reseller_inbounds", "recharge_requests", "balance_transactions", "bot_settings", "resellers"]: op.drop_table(table)
