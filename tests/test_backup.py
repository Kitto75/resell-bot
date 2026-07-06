from pathlib import Path

import pytest

from app.services.backup import get_sqlite_db_path


def test_get_sqlite_db_path_relative() -> None:
    assert get_sqlite_db_path("sqlite:///bot.db") == Path("bot.db").resolve()
    assert get_sqlite_db_path("sqlite+aiosqlite:///bot.db") == Path("bot.db").resolve()


def test_get_sqlite_db_path_absolute() -> None:
    assert get_sqlite_db_path("sqlite:////tmp/bot.db") == Path("/tmp/bot.db")
    assert get_sqlite_db_path("sqlite+aiosqlite:////tmp/bot.db") == Path("/tmp/bot.db")


def test_get_sqlite_db_path_rejects_non_sqlite() -> None:
    with pytest.raises(ValueError):
        get_sqlite_db_path("postgresql+asyncpg://user:pass@localhost/db")
