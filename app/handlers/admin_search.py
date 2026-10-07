"""Admin-only quick lookup: send a username (or /user <username>) and get the service info.

This router is included LAST and only matches when the admin has NO active FSM state,
so it can never interfere with create/renew/recharge/... flows that are waiting for text.
"""
import logging
import re

from aiogram import Router
from aiogram.filters import Command, StateFilter
from aiogram.types import Message

from app.config import get_settings
from app.handlers.admin import client
from app.services.marzban import MarzbanError
from app.services.user_info import format_admin_user_info

logger = logging.getLogger(__name__)
router = Router()
LOOKUP_RE = re.compile(r"^[A-Za-z0-9_]{3,64}$")


def _lookup_username(text: str | None) -> str | None:
    candidate = (text or "").strip()
    return candidate.lower() if LOOKUP_RE.fullmatch(candidate) else None


async def _is_admin_username_text(message: Message, is_admin: bool = False) -> bool:
    return bool(is_admin) and _lookup_username(message.text) is not None


async def _send_lookup(message: Message, username: str) -> None:
    try:
        info = await client().get_user_with_activity(username)
    except MarzbanError as exc:
        if exc.status == 404:
            await message.answer(f"❌ کاربری با نام «{username}» در پنل پیدا نشد.")
        else:
            logger.exception("Admin user lookup failed username=%s status=%s", username, exc.status)
            await message.answer("❌ دریافت اطلاعات از پنل ناموفق بود. لاگ‌ها را بررسی کنید.")
        return
    await message.answer(format_admin_user_info(info, get_settings().timezone))


@router.message(Command("user"))
async def admin_user_command(message: Message, is_admin: bool) -> None:
    if not is_admin:
        return
    parts = (message.text or "").split(maxsplit=1)
    username = _lookup_username(parts[1] if len(parts) > 1 else None)
    if username is None:
        await message.answer("Usage: /user username")
        return
    await _send_lookup(message, username)


@router.message(StateFilter(None), _is_admin_username_text)
async def admin_user_search(message: Message) -> None:
    await _send_lookup(message, _lookup_username(message.text))
