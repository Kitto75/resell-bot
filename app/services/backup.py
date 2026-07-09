from __future__ import annotations

import logging
import shutil
import tempfile
import zipfile
from datetime import datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from urllib.parse import unquote, urlparse
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.types import FSInputFile

from app.config import get_settings
from app.services.datetime import jalali_filename_datetime, persian_date_time

logger = logging.getLogger(__name__)
BACKUP_ENABLED_KEY = "backup_enabled"
BACKUP_INTERVAL_KEY = "backup_interval_minutes"
BACKUP_LAST_TIME_KEY = "backup_last_time"
DEFAULT_BACKUP_INTERVAL_MINUTES = 60
PROJECT_ROOT = Path(__file__).resolve().parents[2]
ZIP_COMPRESSION_LEVEL = 9


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


def find_project_env_file() -> Path | None:
    """Locate the project's .env file without creating or modifying it."""
    candidates = [PROJECT_ROOT / ".env", Path.cwd() / ".env"]
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate.resolve()
    logger.info("Project .env file was not found; backup archive will not include it")
    return None


def get_bot_version() -> str | None:
    for package_name in ("resell-bot", "resell_bot"):
        try:
            return version(package_name)
        except PackageNotFoundError:
            continue
    return None


def build_backup_info(
    *,
    created_at: datetime,
    db_filename: str,
    env_included: bool,
    env_error: str | None = None,
) -> str:
    included_files = [db_filename, "backup_info.txt"]
    env_status = "included"
    if env_included:
        included_files.insert(1, ".env")
    elif env_error:
        env_status = f"not included ({env_error})"
    else:
        env_status = "not included (file not found)"

    bot_version = get_bot_version() or "not available"
    return "\n".join(
        [
            "Resell Bot backup information",
            f"Backup creation date/time: {created_at.isoformat(timespec='seconds')}",
            f"Bot version: {bot_version}",
            f"Database filename: {db_filename}",
            f".env: {env_status}",
            "Included files:",
            *(f"- {name}" for name in included_files),
            "",
            "Security note: this archive may contain sensitive configuration and credentials; store it securely.",
            "",
        ]
    )


def create_backup_zip_archive(db_path: Path, timezone: str) -> tuple[Path, tempfile.TemporaryDirectory[str]]:
    """Create a temporary ZIP containing only the DB copy, .env when readable, and backup_info.txt."""
    timestamp = jalali_filename_datetime(timezone)
    db_filename = f"backup-{timestamp}.db"
    zip_filename = f"backup-{timestamp}.zip"
    temp_dir = tempfile.TemporaryDirectory(prefix="resell-bot-backup-")
    temp_path = Path(temp_dir.name)
    db_copy_path = temp_path / db_filename
    zip_path = temp_path / zip_filename
    env_path = find_project_env_file()
    env_included = False
    env_error: str | None = None

    try:
        shutil.copy2(db_path, db_copy_path)
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=ZIP_COMPRESSION_LEVEL) as archive:
            archive.write(db_copy_path, arcname=db_filename)
            if env_path is not None:
                try:
                    with env_path.open("rb") as env_file:
                        archive.writestr(".env", env_file.read())
                    env_included = True
                except OSError as exc:
                    env_error = f"could not read .env: {exc}"
                    logger.warning("Project .env file could not be read and was skipped: %s", exc)
            info_text = build_backup_info(
                created_at=datetime.now(ZoneInfo(timezone)),
                db_filename=db_filename,
                env_included=env_included,
                env_error=env_error,
            )
            archive.writestr("backup_info.txt", info_text)
        return zip_path, temp_dir
    except Exception:
        temp_dir.cleanup()
        logger.exception("Failed to create SQLite ZIP backup archive")
        raise


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

    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    try:
        zip_path, temp_dir = create_backup_zip_archive(db_path, settings.timezone)
        document = FSInputFile(zip_path, filename=zip_path.name)
        targets = admin_ids or settings.admin_ids
        for admin_id in targets:
            await bot.send_document(admin_id, document, caption="💾 بکاپ پایگاه داده SQLite (ZIP)")
        date, time = persian_date_time(settings.timezone)
        from app.database.repositories import SettingsRepository
        from app.database.session import SessionLocal

        async with SessionLocal() as session, session.begin():
            await SettingsRepository(session).set(BACKUP_LAST_TIME_KEY, f"{date} {time}")
        return True
    except Exception:
        logger.exception("Failed to send SQLite ZIP database backup")
        return False
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()
