from pathlib import Path
import zipfile

import pytest

from app.services import backup as backup_service
from app.services.backup import create_backup_zip_archive, get_sqlite_db_path


def test_get_sqlite_db_path_relative() -> None:
    assert get_sqlite_db_path("sqlite:///bot.db") == Path("bot.db").resolve()
    assert get_sqlite_db_path("sqlite+aiosqlite:///bot.db") == Path("bot.db").resolve()


def test_get_sqlite_db_path_absolute() -> None:
    assert get_sqlite_db_path("sqlite:////tmp/bot.db") == Path("/tmp/bot.db")
    assert get_sqlite_db_path("sqlite+aiosqlite:////tmp/bot.db") == Path("/tmp/bot.db")


def test_get_sqlite_db_path_rejects_non_sqlite() -> None:
    with pytest.raises(ValueError):
        get_sqlite_db_path("postgresql+asyncpg://user:pass@localhost/db")


def test_create_backup_zip_archive_contains_expected_files(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "bot.db"
    db_path.write_bytes(b"sqlite bytes")
    env_path = tmp_path / ".env"
    env_path.write_text("BOT_TOKEN=secret-token\n", encoding="utf-8")
    monkeypatch.setattr(backup_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(backup_service, "jalali_filename_datetime", lambda timezone: "2026-07-09-12-30")

    zip_path, temp_dir = create_backup_zip_archive(db_path, "UTC")
    try:
        assert zip_path.name == "backup-2026-07-09-12-30.zip"
        with zipfile.ZipFile(zip_path) as archive:
            assert sorted(archive.namelist()) == [".env", "backup-2026-07-09-12-30.db", "backup_info.txt"]
            assert archive.read("backup-2026-07-09-12-30.db") == b"sqlite bytes"
            assert archive.read(".env") == b"BOT_TOKEN=secret-token\n"
            info = archive.read("backup_info.txt").decode("utf-8")
            assert "Database filename: backup-2026-07-09-12-30.db" in info
            assert ".env: included" in info
            assert "sensitive configuration" in info
    finally:
        temp_dir.cleanup()

    assert not zip_path.exists()


def test_create_backup_zip_archive_skips_missing_env(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "bot.db"
    db_path.write_bytes(b"sqlite bytes")
    monkeypatch.setattr(backup_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(backup_service, "jalali_filename_datetime", lambda timezone: "2026-07-09-12-30")

    zip_path, temp_dir = create_backup_zip_archive(db_path, "UTC")
    try:
        with zipfile.ZipFile(zip_path) as archive:
            assert sorted(archive.namelist()) == ["backup-2026-07-09-12-30.db", "backup_info.txt"]
            info = archive.read("backup_info.txt").decode("utf-8")
            assert ".env: not included (file not found)" in info
    finally:
        temp_dir.cleanup()
