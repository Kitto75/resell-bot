from typing import Any, Awaitable, Callable
from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject
from app.database.repositories import SettingsRepository
from app.database.session import SessionLocal

class MaintenanceMiddleware(BaseMiddleware):
    async def __call__(self, handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]], event: TelegramObject, data: dict[str, Any]) -> Any:
        if data.get("is_admin"): return await handler(event, data)
        async with SessionLocal() as session:
            enabled = await SettingsRepository(session).get_bool("maintenance_mode")
        if enabled:
            if isinstance(event, Message):
                await event.answer("🔧 ربات در حال تعمیرات است. لطفا بعدا دوباره تلاش کنید.")
            elif isinstance(event, CallbackQuery):
                await event.answer("🔧 ربات در حال تعمیرات است. لطفا بعدا دوباره تلاش کنید.", show_alert=True)
            return None
        return await handler(event, data)
