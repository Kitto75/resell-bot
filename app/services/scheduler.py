from __future__ import annotations

import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram import Bot

from app.services.backup import DEFAULT_BACKUP_INTERVAL_MINUTES, get_backup_status, send_database_backup, sqlite_backup_supported

logger = logging.getLogger(__name__)
_scheduler: AsyncIOScheduler | None = None
BACKUP_JOB_ID = "sqlite_database_backup"


def set_scheduler(scheduler: AsyncIOScheduler) -> None:
    global _scheduler
    _scheduler = scheduler


def get_scheduler() -> AsyncIOScheduler | None:
    return _scheduler


def schedule_backup_job(scheduler: AsyncIOScheduler, bot: Bot, interval_minutes: int) -> None:
    scheduler.add_job(
        send_database_backup,
        "interval",
        minutes=max(1, interval_minutes),
        args=[bot],
        id=BACKUP_JOB_ID,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )


def remove_backup_job(scheduler: AsyncIOScheduler) -> None:
    if scheduler.get_job(BACKUP_JOB_ID) is not None:
        scheduler.remove_job(BACKUP_JOB_ID)


async def restore_backup_job(scheduler: AsyncIOScheduler, bot: Bot) -> None:
    enabled, interval, _ = await get_backup_status()
    if enabled and sqlite_backup_supported():
        schedule_backup_job(scheduler, bot, interval or DEFAULT_BACKUP_INTERVAL_MINUTES)
        logger.info("Restored SQLite backup scheduler interval_minutes=%s", interval)
