"""add unique constraint to created_users username

Revision ID: 0003_unique_created_users_username
Revises: 0002_recharge_processing_metadata
Create Date: 2026-07-05 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_unique_created_users_username"
down_revision: Union[str, None] = "0002_recharge_processing_metadata"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INDEX_NAME = "uq_created_users_username"
_TABLE_NAME = "created_users"
_COLUMN_NAME = "username"
_DUPLICATE_USERNAME_SQL = sa.text(
    """
    SELECT username, COUNT(*) AS count
    FROM created_users
    GROUP BY username
    HAVING COUNT(*) > 1
    ORDER BY username
    """
)


def _raise_if_duplicate_usernames() -> None:
    duplicates = op.get_bind().execute(_DUPLICATE_USERNAME_SQL).fetchall()
    if not duplicates:
        return

    sample = ", ".join(f"{row.username!r} ({row.count})" for row in duplicates[:10])
    extra = "" if len(duplicates) <= 10 else f", and {len(duplicates) - 10} more"
    raise RuntimeError(
        "Cannot add a unique index on created_users.username because duplicate "
        f"usernames already exist: {sample}{extra}. Resolve the duplicates "
        "without deleting data silently, then rerun the migration. Diagnostic SQL: "
        "SELECT username, COUNT(*) FROM created_users GROUP BY username "
        "HAVING COUNT(*) > 1 ORDER BY username;"
    )


def upgrade() -> None:
    _raise_if_duplicate_usernames()

    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        op.execute(
            f"CREATE UNIQUE INDEX IF NOT EXISTS {_INDEX_NAME} "
            f"ON {_TABLE_NAME} ({_COLUMN_NAME})"
        )
    else:
        op.create_index(_INDEX_NAME, _TABLE_NAME, [_COLUMN_NAME], unique=True)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        op.execute(f"DROP INDEX IF EXISTS {_INDEX_NAME}")
    else:
        op.drop_index(_INDEX_NAME, table_name=_TABLE_NAME)
