from typing import Any, Awaitable, Callable
from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject
from app.database.repositories import SettingsRepository
from app.database.session import SessionLocal

class MaintenanceMiddleware(BaseMiddleware):
    async def __call__(self, handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]], event: TelegramObject, data: dict[str, Any]) -> Any:
        if data.get("is_admin"): return await handler(event, data)
        async with SessionLocal() as session:
            enabled = await SettingsRepository(session).get_bool("maintenance_mode")
        if enabled:
            if isinstance(event, Message): await event.answer("🔧 Bot is currently under maintenance. Please try again later.")
            return None
        return await handler(event, data)
