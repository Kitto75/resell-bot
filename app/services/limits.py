"""Admin-defined limits for what resellers may create / renew.

Stored in bot_settings (no migration needed):
  limits:global        {"max_days": 31, "min_gb": 5, "max_gb": 100}      (missing/0 = no limit)
  limits:r:<id>        per-reseller overrides; a field that is present replaces the global value
                       (0 = "explicitly unlimited for this reseller"), a missing field follows the global one.

Saving a *global* value for a field also clears that field from every reseller's overrides, so it applies to everybody again.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.database.models import Reseller
from app.database.repositories import SettingsRepository

GLOBAL_KEY = "limits:global"
FIELDS = ("max_days", "min_gb", "max_gb")
FIELD_LABELS = {"max_days": "📅 حداکثر روز اعتبار", "min_gb": "📦 حداقل حجم", "max_gb": "📦 حداکثر حجم"}
FIELD_UNITS = {"max_days": "روز", "min_gb": "گیگابایت", "max_gb": "گیگابایت"}


def reseller_key(reseller_id: int) -> str:
    return f"limits:r:{reseller_id}"


def message_key(reseller_id: int) -> str:
    return f"rmsg:{reseller_id}"


@dataclass(frozen=True)
class Limits:
    max_days: int | None = None
    min_gb: int | None = None
    max_gb: int | None = None

    def check_days(self, days: int) -> str | None:
        if self.max_days and days > self.max_days:
            return f"مدت اعتبار نباید بیشتر از {self.max_days} روز باشد."
        return None

    def check_gb(self, gb: int) -> str | None:
        if self.min_gb and self.max_gb and self.min_gb > self.max_gb:
            return "محدوده‌ی مجاز حجم برای شما نامعتبر تنظیم شده است؛ با مدیر تماس بگیرید."
        if self.min_gb and self.max_gb and not self.min_gb <= gb <= self.max_gb:
            return f"حجم باید بین {self.min_gb} تا {self.max_gb} گیگابایت باشد."
        if self.min_gb and gb < self.min_gb:
            return f"حجم باید حداقل {self.min_gb} گیگابایت باشد."
        if self.max_gb and gb > self.max_gb:
            return f"حجم نباید بیشتر از {self.max_gb} گیگابایت باشد."
        return None

    def gb_hint(self) -> str:
        if self.min_gb and self.max_gb: return f" (مجاز: {self.min_gb} تا {self.max_gb} گیگابایت)"
        if self.min_gb: return f" (حداقل {self.min_gb} گیگابایت)"
        if self.max_gb: return f" (حداکثر {self.max_gb} گیگابایت)"
        return ""

    def days_hint(self) -> str:
        return f" (حداکثر {self.max_days} روز)" if self.max_days else ""


def _decode(raw: str | None) -> dict[str, int]:
    try:
        data = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        return {}
    if not isinstance(data, dict): return {}
    clean: dict[str, int] = {}
    for field in FIELDS:
        value = data.get(field)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            clean[field] = value
    return clean


async def load_global(session) -> dict[str, int]:
    return _decode(await SettingsRepository(session).get(GLOBAL_KEY))


async def load_overrides(session, reseller_id: int) -> dict[str, int]:
    return _decode(await SettingsRepository(session).get(reseller_key(reseller_id)))


def merge(global_values: dict[str, int], overrides: dict[str, int]) -> dict[str, tuple[int | None, str]]:
    """field -> (value or None for unlimited, 'global' | 'custom')."""
    result: dict[str, tuple[int | None, str]] = {}
    for field in FIELDS:
        if field in overrides:
            result[field] = (overrides[field] or None, "custom")
        else:
            result[field] = (global_values.get(field) or None, "global")
    return result


async def effective_detail(session, reseller_id: int) -> dict[str, tuple[int | None, str]]:
    return merge(await load_global(session), await load_overrides(session, reseller_id))


async def effective_limits(session, reseller_id: int) -> Limits:
    detail = await effective_detail(session, reseller_id)
    return Limits(**{field: detail[field][0] for field in FIELDS})


def validate_combination(values: dict[str, int | None]) -> str | None:
    min_gb, max_gb = values.get("min_gb"), values.get("max_gb")
    if min_gb and max_gb and min_gb > max_gb:
        return f"حداقل حجم ({min_gb}) نمی‌تواند بیشتر از حداکثر حجم ({max_gb}) باشد."
    return None


async def set_reseller_field(session, reseller_id: int, field: str, value: int) -> str | None:
    """value 0 = unlimited for this reseller. Returns an error text or None."""
    assert field in FIELDS
    repo = SettingsRepository(session)
    overrides = await load_overrides(session, reseller_id)
    overrides[field] = value
    error = validate_combination({f: v[0] for f, v in merge(await load_global(session), overrides).items()})
    if error: return error
    await repo.set(reseller_key(reseller_id), json.dumps(overrides))
    return None


async def reset_reseller(session, reseller_id: int) -> None:
    await SettingsRepository(session).set(reseller_key(reseller_id), "{}")


async def set_global_field(session, field: str, value: int, reseller_ids: list[int]) -> tuple[str | None, int]:
    """Set the global value (0 = no limit) and re-apply it to everybody. Returns (error, number of overrides cleared)."""
    assert field in FIELDS
    repo = SettingsRepository(session)
    values = await load_global(session)
    values[field] = value
    error = validate_combination({f: values.get(f) or None for f in FIELDS})
    if error: return error, 0
    await repo.set(GLOBAL_KEY, json.dumps(values))
    cleared = 0
    for rid in reseller_ids:
        overrides = await load_overrides(session, rid)
        if field in overrides:
            del overrides[field]
            await repo.set(reseller_key(rid), json.dumps(overrides))
            cleared += 1
    return None, cleared


def describe(value: int | None, field: str) -> str:
    return f"{value} {FIELD_UNITS[field]}" if value else "بدون محدودیت"


async def conflicting_resellers(session, resellers: list[Reseller]) -> list[str]:
    names = []
    for reseller in resellers:
        detail = await effective_detail(session, reseller.id)
        if validate_combination({f: v[0] for f, v in detail.items()}):
            names.append(reseller.display_name)
    return names


def summary_text(detail: dict[str, tuple[int | None, str]]) -> str:
    """One compact line for the reseller card, e.g. '📅 حداکثر 31 روز • 📦 5 تا 100 گیگابایت (اختصاصی)'."""
    days, gb_min, gb_max = detail["max_days"][0], detail["min_gb"][0], detail["max_gb"][0]
    parts = [f"📅 حداکثر {days} روز" if days else None]
    if gb_min and gb_max: parts.append(f"📦 {gb_min} تا {gb_max} گیگابایت")
    elif gb_min: parts.append(f"📦 حداقل {gb_min} گیگابایت")
    elif gb_max: parts.append(f"📦 حداکثر {gb_max} گیگابایت")
    text = " • ".join(p for p in parts if p) or "بدون محدودیت"
    return text + (" (اختصاصی)" if any(source == "custom" for _, source in detail.values()) else "")
