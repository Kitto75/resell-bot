import asyncio
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.config import get_settings
from app.handlers import admin, common, reseller
from app.middlewares.auth import AuthMiddleware
from app.middlewares.maintenance import MaintenanceMiddleware
from app.services.scheduler import restore_backup_job, set_scheduler
from app.utils.logger import setup_logging

async def main() -> None:
    settings = get_settings(); setup_logging(settings.log_level)
    bot = Bot(settings.bot_token); dp = Dispatcher(storage=MemoryStorage())
    scheduler = AsyncIOScheduler(timezone=settings.timezone); set_scheduler(scheduler)
    auth_middleware = AuthMiddleware()
    maintenance_middleware = MaintenanceMiddleware()
    dp.message.middleware(auth_middleware)
    dp.callback_query.middleware(auth_middleware)
    dp.message.middleware(maintenance_middleware)
    dp.callback_query.middleware(maintenance_middleware)
    dp.include_router(common.router); dp.include_router(admin.router); dp.include_router(reseller.router)
    await restore_backup_job(scheduler, bot); scheduler.start()
    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)

if __name__ == "__main__":
    asyncio.run(main())
