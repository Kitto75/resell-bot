from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

BYTES_PER_GB = 1024 ** 3
SECONDS_PER_DAY = 86400
RENEWAL_MODE_KEY = "renewal_mode"

class RenewalMode(str, Enum):
    additive = "additive"
    replace = "replace"

def normalize_renewal_mode(value: str | None) -> RenewalMode:
    try:
        return RenewalMode(str(value or "").strip())
    except ValueError:
        return RenewalMode.additive

def renewal_mode_fa(mode: RenewalMode | str | None) -> str:
    mode = normalize_renewal_mode(mode.value if isinstance(mode, RenewalMode) else mode)
    return "ریست و جایگزینی" if mode is RenewalMode.replace else "افزایشی"

def renewal_mode_confirmation_text(mode: RenewalMode | str | None) -> str:
    mode = normalize_renewal_mode(mode.value if isinstance(mode, RenewalMode) else mode)
    if mode is RenewalMode.replace:
        return "حالت تمدید: ریست و جایگزینی\nمصرف کاربر صفر می‌شود.\nحجم جدید جایگزین حجم قبلی می‌شود.\nزمان جدید از لحظه تمدید محاسبه می‌شود."
    return "حالت تمدید: افزایشی\nحجم جدید به حجم فعلی اضافه می‌شود.\nروز جدید به زمان باقی‌مانده اضافه می‌شود."

@dataclass(frozen=True)
class RenewalCalculation:
    mode: RenewalMode
    previous_data_limit: int
    previous_expire: int
    resulting_data_limit: int
    resulting_expire: int
    reset_required: bool

def calculate_renewal(user: dict[str, Any], gb: int, days: int, mode: RenewalMode | str | None, now_ts: int | None = None) -> RenewalCalculation:
    parsed_mode = normalize_renewal_mode(mode.value if isinstance(mode, RenewalMode) else mode)
    now = int(now_ts if now_ts is not None else datetime.now(timezone.utc).timestamp())
    previous_data_limit = int(user.get("data_limit") or 0)
    previous_expire = int(user.get("expire") or 0)
    entered_bytes = int(gb) * BYTES_PER_GB
    entered_seconds = int(days) * SECONDS_PER_DAY
    if parsed_mode is RenewalMode.replace:
        resulting_data_limit = entered_bytes
        resulting_expire = now + entered_seconds
        reset_required = True
    else:
        resulting_data_limit = previous_data_limit + entered_bytes
        resulting_expire = max(previous_expire, now) + entered_seconds
        reset_required = False
    return RenewalCalculation(parsed_mode, previous_data_limit, previous_expire, resulting_data_limit, resulting_expire, reset_required)
