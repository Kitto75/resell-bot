"""Small admin settings stored in bot_settings (key/value)."""
from __future__ import annotations

from app.database.repositories import SettingsRepository

ON_HOLD_DAYS_KEY = "on_hold_days"
MAX_ON_HOLD_DAYS = 3650


async def get_on_hold_days(session) -> int | None:
    """None = not set: new accounts stay on_hold until the user connects for the first time."""
    raw = await SettingsRepository(session).get(ON_HOLD_DAYS_KEY)
    try:
        value = int(raw) if raw else 0
    except ValueError:
        return None
    return value if value > 0 else None


async def set_on_hold_days(session, days: int | None) -> None:
    await SettingsRepository(session).set(ON_HOLD_DAYS_KEY, str(days) if days else "")
