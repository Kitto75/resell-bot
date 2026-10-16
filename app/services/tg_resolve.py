"""Find a reseller's numeric Telegram id from a @username, and find resellers by name / id / @username.

Telegram bots cannot look up arbitrary users by @username. We can resolve it when
  1) the person already talked to THIS bot (we remember username -> id whenever we see them), or
  2) Telegram itself resolves it for the bot (works for some public accounts).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from app.database.repositories import ResellerRepository, SettingsRepository

logger = logging.getLogger(__name__)
KEY_PREFIX = "tgu:"
_USERNAME = re.compile(r"^@?([A-Za-z][A-Za-z0-9_]{3,31})$")
_LINK = re.compile(r"^(?:https?://)?(?:t|telegram)\.me/([A-Za-z][A-Za-z0-9_]{3,31})/?$", re.IGNORECASE)
_seen: dict[str, int] = {}  # in-memory cache so we only write when something changed


@dataclass(frozen=True)
class Target:
    telegram_id: int | None = None
    username: str | None = None


def parse_target(text: str | None) -> Target | None:
    """'123456' -> id, '@name' / 'name' / 't.me/name' -> username, anything else -> None."""
    value = (text or "").strip()
    if not value: return None
    if re.fullmatch(r"-?\d{3,20}", value):
        return Target(telegram_id=int(value))
    link = _LINK.match(value)
    if link: return Target(username=link.group(1).lower())
    match = _USERNAME.match(value)
    return Target(username=match.group(1).lower()) if match else None


async def remember_user(user) -> None:
    """Called for every user the bot talks to; keeps username -> id so admins can add them by @username."""
    username = (getattr(user, "username", None) or "").lower()
    if not username or _seen.get(username) == user.id: return
    try:
        from app.database.session import SessionLocal
        async with SessionLocal() as session, session.begin():
            await SettingsRepository(session).set(KEY_PREFIX + username, str(user.id))
        _seen[username] = user.id
    except Exception:
        logger.exception("Could not remember telegram username")


async def known_id(username: str) -> int | None:
    from app.database.session import SessionLocal
    async with SessionLocal() as session:
        raw = await SettingsRepository(session).get(KEY_PREFIX + username.lower())
    try: return int(raw) if raw else None
    except ValueError: return None


async def resolve_username(bot, username: str) -> int | None:
    found = await known_id(username)
    if found: return found
    try:
        chat = await bot.get_chat("@" + username.lstrip("@"))
    except Exception:
        return None
    return chat.id if getattr(chat, "type", None) == "private" else None


UNRESOLVED_TEXT = (
    "نتوانستم آیدی عددی این یوزرنیم را پیدا کنم.\n"
    "تلگرام به ربات‌ها اجازه نمی‌دهد آیدی هر کاربری را از روی یوزرنیم بخوانند؛ فقط وقتی ممکن است که آن شخص قبلاً یک‌بار این ربات را /start کرده باشد.\n\n"
    "یکی از این دو کار را بکنید:\n• از ریسلر بخواهید ربات را /start کند و دوباره یوزرنیم را بفرستید.\n• آیدی عددی را مستقیم وارد کنید."
)
INVALID_TEXT = "ورودی نامعتبر است. آیدی عددی (مثل 123456789) یا یوزرنیم (مثل @username) بفرستید."


async def resolve_input(bot, text: str | None) -> tuple[int | None, str | None, str | None]:
    """-> (telegram_id, @username or None, error text or None)"""
    target = parse_target(text)
    if target is None: return None, None, INVALID_TEXT
    if target.telegram_id is not None: return target.telegram_id, None, None
    resolved = await resolve_username(bot, target.username)
    if resolved is None: return None, target.username, UNRESOLVED_TEXT
    return resolved, target.username, None


async def find_resellers(session, query: str | None, limit: int = 8):
    """Resellers matching a display name (exact, then partial), numeric id, or known @username."""
    text = (query or "").strip()
    if not text: return []
    repo = ResellerRepository(session)
    everyone = await repo.list(include_archived=True)
    lowered = text.lower().lstrip("@")
    exact = [r for r in everyone if r.display_name.lower() == text.lower()]
    if exact: return exact[:limit]
    target = parse_target(text)
    telegram_id = target.telegram_id if target and target.telegram_id is not None else None
    if telegram_id is None and text.isdigit() and len(text) <= 20:
        telegram_id = int(text)
    if telegram_id is None and target and target.username:
        telegram_id = await known_id(target.username)
    if telegram_id is not None:
        found = await repo.get_by_telegram_id(telegram_id)
        if found: return [found]
    return [r for r in everyone if lowered in r.display_name.lower()][:limit]
