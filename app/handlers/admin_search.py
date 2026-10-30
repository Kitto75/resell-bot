"""Admin-only quick lookup: send a username (or /user <username>) and get the service info.

This router is included LAST and only matches when the admin has NO active FSM state,
so it can never interfere with create/renew/recharge/... flows that are waiting for text.
"""
import logging

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.config import get_settings
from app.handlers.admin import _primary_subscription_url, client
from app.services.delivery import send_account_message
from app.services.marzban import MarzbanError
from app.services.validators import fetch_user_by_name, valid_existing_username
from app.services.user_info import format_admin_user_info

logger = logging.getLogger(__name__)
router = Router()
def _lookup_username(text: str | None) -> str | None:
    """The typed name if it looks like a panel username (letters, digits and _ - . @ are all valid there)."""
    candidate = (text or "").strip()
    return candidate if valid_existing_username(candidate) else None


async def _is_admin_username_text(message: Message, is_admin: bool = False) -> bool:
    return bool(is_admin) and _lookup_username(message.text) is not None


def _user_actions_keyboard(username: str) -> InlineKeyboardMarkup | None:
    qr, renew = f"adm:qr:{username}", f"adm:rn:{username}"
    if max(len(qr.encode()), len(renew.encode())) > 64:  # Telegram callback_data limit
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📱 QR Code", callback_data=qr), InlineKeyboardButton(text="♻️ تمدید", callback_data=renew)]])


async def _send_lookup(message: Message, username: str) -> None:
    panel = client()
    try:
        username, info = await fetch_user_by_name(panel.get_user_with_activity, username)
    except MarzbanError as exc:
        if exc.status == 404:
            await message.answer(f"❌ کاربری با نام «{username}» در پنل پیدا نشد.")
        else:
            logger.exception("Admin user lookup failed username=%s status=%s", username, exc.status)
            await message.answer("❌ دریافت اطلاعات از پنل ناموفق بود. لاگ‌ها را بررسی کنید.")
        return
    await message.answer(format_admin_user_info(info, get_settings().timezone), reply_markup=_user_actions_keyboard(str(info.get("username") or username)))


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


@router.callback_query(F.data.startswith("adm:qr:"))
async def admin_user_qr(cb: CallbackQuery, is_admin: bool) -> None:
    if not is_admin:
        await cb.answer("فقط مدیر مجاز است.", show_alert=True); return
    username = (cb.data or "").split(":", 2)[2]
    await cb.answer()
    marzban = client()
    try:
        info = await marzban.get_user(username)
    except MarzbanError as exc:
        logger.exception("Admin QR lookup failed username=%s status=%s", username, exc.status)
        await cb.message.answer(f"❌ کاربری با نام «{username}» پیدا نشد." if exc.status == 404 else "❌ دریافت اطلاعات از پنل ناموفق بود.")
        return
    await send_account_message(cb.message, username=username, data_limit=info.get("data_limit"), subscription_url=marzban.absolute_subscription_url(_primary_subscription_url(info)))
