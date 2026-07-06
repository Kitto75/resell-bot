from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlparse

from aiogram import Bot
from aiogram.types import FSInputFile

from app.config import get_settings
from app.services.datetime import jalali_filename_datetime, persian_date_time

logger = logging.getLogger(__name__)
BACKUP_ENABLED_KEY = "backup_enabled"
BACKUP_INTERVAL_KEY = "backup_interval_minutes"
BACKUP_LAST_TIME_KEY = "backup_last_time"
DEFAULT_BACKUP_INTERVAL_MINUTES = 60


def get_sqlite_db_path(database_url: str) -> Path:
    parsed = urlparse(database_url)
    if parsed.scheme not in {"sqlite", "sqlite+aiosqlite"}:
        raise ValueError("not sqlite")
    if parsed.netloc and parsed.netloc != "":
        raw = f"/{parsed.netloc}{parsed.path}"
    else:
        raw = parsed.path
    raw = unquote(raw)
    if raw.startswith("/") and not raw.startswith("//") and database_url.count("/") == 3:
        raw = raw.lstrip("/")
    if raw in {"", ":memory:"}:
        raise ValueError("sqlite memory database is not a file")
    return Path(raw).expanduser().resolve()


def sqlite_backup_supported() -> bool:
    try:
        get_sqlite_db_path(get_settings().database_url)
        return True
    except ValueError:
        return False


async def get_backup_status() -> tuple[bool, int, str | None]:
    from app.database.repositories import SettingsRepository
    from app.database.session import SessionLocal

    async with SessionLocal() as session:
        repo = SettingsRepository(session)
        enabled = await repo.get_bool(BACKUP_ENABLED_KEY, False)
        interval = int(await repo.get(BACKUP_INTERVAL_KEY, str(DEFAULT_BACKUP_INTERVAL_MINUTES)) or DEFAULT_BACKUP_INTERVAL_MINUTES)
        last_time = await repo.get(BACKUP_LAST_TIME_KEY)
    return enabled, interval, last_time


async def set_backup_enabled(enabled: bool) -> None:
    from app.database.repositories import SettingsRepository
    from app.database.session import SessionLocal

    async with SessionLocal() as session, session.begin():
        await SettingsRepository(session).set_bool(BACKUP_ENABLED_KEY, enabled)


async def set_backup_interval(minutes: int) -> None:
    from app.database.repositories import SettingsRepository
    from app.database.session import SessionLocal

    async with SessionLocal() as session, session.begin():
        await SettingsRepository(session).set(BACKUP_INTERVAL_KEY, str(minutes))


async def send_database_backup(bot: Bot, admin_ids: list[int] | None = None) -> bool:
    settings = get_settings()
    try:
        db_path = get_sqlite_db_path(settings.database_url)
    except ValueError:
        logger.warning("Database backup requested for non-SQLite DATABASE_URL")
        return False
    if not db_path.exists() or not db_path.is_file():
        logger.error("SQLite database file does not exist path=%s", db_path)
        return False
    filename = f"backup-{jalali_filename_datetime(settings.timezone)}.db"
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix="resell-bot-backup-", suffix=".db", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        shutil.copy2(db_path, tmp_path)
        document = FSInputFile(tmp_path, filename=filename)
        targets = admin_ids or settings.admin_ids
        for admin_id in targets:
            await bot.send_document(admin_id, document, caption="💾 بکاپ پایگاه داده SQLite")
        date, time = persian_date_time(settings.timezone)
        from app.database.repositories import SettingsRepository
        from app.database.session import SessionLocal

        async with SessionLocal() as session, session.begin():
            await SettingsRepository(session).set(BACKUP_LAST_TIME_KEY, f"{date} {time}")
        return True
    except Exception:
        logger.exception("Failed to send SQLite database backup")
        return False
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
