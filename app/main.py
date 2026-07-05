import asyncio
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from app.config import get_settings
from app.handlers import admin, common, reseller
from app.middlewares.auth import AuthMiddleware
from app.middlewares.maintenance import MaintenanceMiddleware
from app.utils.logger import setup_logging

async def main() -> None:
    settings = get_settings(); setup_logging(settings.log_level)
    bot = Bot(settings.bot_token); dp = Dispatcher(storage=MemoryStorage())
    dp.update.middleware(AuthMiddleware()); dp.update.middleware(MaintenanceMiddleware())
    dp.include_router(common.router); dp.include_router(admin.router); dp.include_router(reseller.router)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
