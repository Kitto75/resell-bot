from typing import Any, Awaitable, Callable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User
from app.config import get_settings
from app.database.repositories import ResellerRepository
from app.database.session import SessionLocal
from app.database.models import ResellerStatus

class AuthMiddleware(BaseMiddleware):
    async def __call__(self, handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]], event: TelegramObject, data: dict[str, Any]) -> Any:
        user: User | None = data.get("event_from_user")
        if user is None: return await handler(event, data)
        data["is_admin"] = user.id in get_settings().admin_ids
        async with SessionLocal() as session:
            reseller = await ResellerRepository(session).get_by_telegram_id(user.id)
            data["reseller"] = reseller if reseller and reseller.status == ResellerStatus.active else reseller
        return await handler(event, data)
