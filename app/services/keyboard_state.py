"""Send the persistent «🏠 داشبورد» reply keyboard once per user instead of before every main menu.

A reply keyboard can't share a message with the inline panel, so re-sending it on every /start or dashboard
press meant two messages each time. Telegram keeps the keyboard until it is removed, so once is enough."""
from __future__ import annotations

from datetime import datetime, timezone

from app.database.repositories import SettingsRepository

CUTOFF_KEY = "reply_kb_cutoff"
USER_KEY = "reply_kb:{}"


def _now_naive_utc() -> datetime:
    # whole seconds: the database stamps created_at with one-second resolution, so a reseller registered right after
    # this moment must not look "older" than the cutoff because of the dropped fraction
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


async def needs_reply_keyboard(session, user_id: int, registered_at: datetime | None = None) -> bool:
    """True only for someone who has never been given the keyboard.

    Everyone registered BEFORE this behaviour first ran already got it from the old code (it was sent on every /start),
    so they are assumed to have it; only resellers registered afterwards get it once."""
    repo = SettingsRepository(session)
    if await repo.get(USER_KEY.format(user_id)):
        return False
    raw = await repo.get(CUTOFF_KEY)
    if not raw:
        await repo.set(CUTOFF_KEY, _now_naive_utc().isoformat())
        return False  # first run of the new behaviour: everybody that exists right now already has the keyboard
    try:
        cutoff = datetime.fromisoformat(raw)
    except ValueError:
        return False
    if registered_at is not None and registered_at < cutoff:
        return False
    return True


async def mark_reply_keyboard_sent(session, user_id: int) -> None:
    await SettingsRepository(session).set(USER_KEY.format(user_id), "1")
