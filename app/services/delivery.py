"""One-message delivery of an account: QR code + name/limit line + copyable subscription link."""
from __future__ import annotations

import asyncio
import logging
from html import escape
from typing import Any

from aiogram.types import BufferedInputFile, InlineKeyboardMarkup, Message

from app.services.qr import make_subscription_qr_png
from app.services.reports import RLM

logger = logging.getLogger(__name__)
BYTES_PER_GB = 1024 ** 3
CAPTION_LIMIT = 1024  # Telegram photo caption limit (visible characters)
STATUS_ICON = {"active": "🟢", "on_hold": "🕒", "disabled": "⛔", "expired": "⌛", "limited": "📉"}


def limit_text(data_limit: Any, spaced: bool = False) -> str:
    try:
        limit = int(data_limit or 0)
    except (TypeError, ValueError):
        limit = 0
    if limit <= 0:
        return "Unlimited"
    gb = f"{limit / BYTES_PER_GB:.2f}".rstrip("0").rstrip(".")
    return f"{gb} GB" if spaced else f"{gb}GB"


def days_text(days: int) -> str:
    return f"{days} Day" if days == 1 else f"{days} Days"


def account_line(username: str, data_limit: Any, days: int | None = None) -> str:
    """Lookup:   testaccount | 35GB
    Creation: testaccount | 35 GB | 31 Days"""
    if days is None:
        return f"{username} | {limit_text(data_limit)}"
    return f"{username} | {limit_text(data_limit, spaced=True)} | {days_text(days)}"


def build_caption(username: str, data_limit: Any, subscription_url: str, days: int | None = None) -> str:
    return f"{escape(account_line(username, data_limit, days))}\n\n<code>{escape(subscription_url)}</code>"


def _qr_png_bytes(url: str, username: str) -> bytes:
    path = make_subscription_qr_png(url, username)
    try:
        return path.read_bytes()
    finally:
        path.unlink(missing_ok=True)


async def send_account_message(message: Message, *, username: str, data_limit: Any, subscription_url: str | None, days: int | None = None, reply_markup: InlineKeyboardMarkup | None = None) -> None:
    """Everything in ONE message: QR image, "name | limit [| days]" and the link in monospace (tap to copy)."""
    line = account_line(username, data_limit, days)
    if not subscription_url:
        await message.answer(f"{line}\n\nلینک اشتراک در پاسخ پنل پیدا نشد؛ لطفاً از پنل بررسی کنید.", reply_markup=reply_markup)
        return
    caption = build_caption(username, data_limit, subscription_url, days)
    try:
        png = await asyncio.to_thread(_qr_png_bytes, subscription_url, username)
    except Exception:
        logger.exception("Failed to generate subscription QR username=%s", username)
        await message.answer(caption, parse_mode="HTML", reply_markup=reply_markup)  # still one message, just without the QR
        return
    photo = BufferedInputFile(png, filename=f"{username}_subscription.png")
    if len(line) + 2 + len(subscription_url) > CAPTION_LIMIT:  # extremely long link: keep the QR, send the link right below
        await message.answer_photo(photo, caption=escape(line), parse_mode="HTML")
        await message.answer(f"<code>{escape(subscription_url)}</code>", parse_mode="HTML", reply_markup=reply_markup)
        return
    await message.answer_photo(photo, caption=caption, parse_mode="HTML", reply_markup=reply_markup)


def accounts_list_text(rows: list[tuple[str, str | None, Any]], page: int, has_next: bool) -> str:
    """rows: (username, panel status or None, data_limit or None). Names are <code> so a tap copies them."""
    if not rows:
        return "هنوز هیچ اکانتی توسط شما ساخته نشده است."
    lines = [f"{RLM}📋 <b>اکانت‌های من</b>  •  صفحه {page + 1}", "━━━━━━━━━━━━━━", ""]
    for username, status, limit in rows:
        icon = STATUS_ICON.get(status or "", "▫️")
        suffix = f" | {limit_text(limit)}" if limit is not None else ""
        lines.append(f"{icon} <code>{escape(username)}</code>{suffix}")
    if has_next:
        lines += ["", f"{RLM}برای دیدن ادامه لیست روی «نمایش بیشتر» بزنید."]
    lines += ["", f"{RLM}💡 برای دریافت <b>لینک اشتراک و QR Code</b>، نام اکانت را کامل و دقیق برایم بفرستید.", f"{RLM}(با لمس نام هر اکانت، کپی می‌شود.)"]
    return "\n".join(lines)
