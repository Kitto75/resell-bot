"""add unique constraint to created_users username

Revision ID: 0003_unique_created_users_username
Revises: 0002_recharge_processing_metadata
Create Date: 2026-07-05 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op

revision: str = "0003_unique_created_users_username"
down_revision: Union[str, None] = "0002_recharge_processing_metadata"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint("uq_created_users_username", "created_users", ["username"])


def downgrade() -> None:
    op.drop_constraint("uq_created_users_username", "created_users", type_="unique")
