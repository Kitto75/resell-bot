from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.database.models import ResellerStatus
from app.database.repositories import SettingsRepository
from app.database.session import SessionLocal
from app.services.limits import message_key


class DisabledResellerMiddleware(BaseMiddleware):
    """A disabled/archived reseller gets the custom message the admin set when disabling them.
    No message set -> the bot stays completely silent (buttons just stop the loading spinner)."""

    async def __call__(self, handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]], event: TelegramObject, data: dict[str, Any]) -> Any:
        reseller = data.get("reseller")
        if data.get("is_admin") or reseller is None or reseller.status == ResellerStatus.active:
            return await handler(event, data)
        async with SessionLocal() as session:
            text = ((await SettingsRepository(session).get(message_key(reseller.id))) or "").strip()
        if isinstance(event, CallbackQuery):
            await event.answer()
            if text and event.message is not None: await event.message.answer(text)
        elif isinstance(event, Message) and text:
            await event.answer(text)
        return None
