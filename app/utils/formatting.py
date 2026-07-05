from __future__ import annotations
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

BYTES_PER_GB = 1024 ** 3

def _decimal(amount: Any) -> Decimal:
    try:
        return Decimal(str(amount or 0))
    except (InvalidOperation, ValueError):
        return Decimal('0')

def format_toman(amount: Any) -> str:
    value = _decimal(amount).quantize(Decimal('1'))
    return f"{int(value):,} تومان"

def format_bytes_to_gb(value: Any) -> str:
    try:
        gb = int(value or 0) / BYTES_PER_GB
    except (TypeError, ValueError):
        gb = 0
    text = f"{gb:.2f}".rstrip('0').rstrip('.')
    return f"{text} گیگابایت"

def format_seconds_to_days(seconds: Any) -> str:
    try:
        seconds = int(seconds or 0)
    except (TypeError, ValueError):
        seconds = 0
    if seconds >= 86400:
        return f"{seconds // 86400} روز"
    return f"{max(0, seconds // 3600)} ساعت"

def format_remaining_time(expire: Any = None, remaining_seconds: Any = None, remaining_days: Any = None) -> str:
    if remaining_days is not None:
        try: return f"{int(remaining_days)} روز"
        except (TypeError, ValueError): pass
    if remaining_seconds is not None:
        return format_seconds_to_days(remaining_seconds)
    try:
        exp = int(expire or 0)
    except (TypeError, ValueError):
        exp = 0
    if exp <= 0: return "نامحدود"
    return format_seconds_to_days(exp - int(datetime.now(timezone.utc).timestamp()))

def status_fa(status: Any) -> str:
    value = getattr(status, 'value', status)
    return {'active': 'فعال', 'disabled': 'غیرفعال', 'archived': 'بایگانی‌شده', 'on_hold': 'در انتظار اتصال', 'limited': 'محدود', 'expired': 'منقضی'}.get(str(value), str(value))
