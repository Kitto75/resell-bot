"""Formatting of panel user info: last online / last subscription update / admin lookup card."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

import jdatetime

from app.services.datetime import to_local

BYTES_PER_GB = 1024 ** 3
_FRACTION = re.compile(r"\.(\d+)")


def parse_panel_datetime(value: Any) -> datetime | None:
    """ISO string / unix timestamp -> aware UTC datetime. Naive values are treated as UTC."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, timezone.utc) if value > 0 else None
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromtimestamp(float(text), timezone.utc)
    except ValueError:
        pass
    # Python 3.10 only accepts 3 or 6 fraction digits.
    text = _FRACTION.sub(lambda m: "." + m.group(1)[:6].ljust(6, "0"), text, count=1)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _relative_parts(value: Any, now: datetime | None) -> tuple[int, str] | None:
    moment = parse_panel_datetime(value)
    if moment is None:
        return None
    seconds = max(0, int(((now or datetime.now(timezone.utc)) - moment).total_seconds()))
    if seconds < 60:
        return 0, "now"
    minutes = seconds // 60
    if minutes < 60:
        return minutes, "minute"
    hours = minutes // 60
    if hours < 24:
        return hours, "hour"
    return hours // 24, "day"


def format_relative_time(value: Any, now: datetime | None = None) -> str:
    """English, e.g. '30 minute ago'."""
    parts = _relative_parts(value, now)
    if parts is None:
        return "Never"
    count, unit = parts
    return "just now" if unit == "now" else f"{count} {unit} ago"


def format_relative_time_fa(value: Any, now: datetime | None = None) -> str:
    """Persian, e.g. '30 دقیقه پیش'."""
    parts = _relative_parts(value, now)
    if parts is None:
        return "ثبت نشده"
    count, unit = parts
    names = {"minute": "دقیقه", "hour": "ساعت", "day": "روز"}
    return "همین الان" if unit == "now" else f"{count} {names[unit]} پیش"


def reseller_activity_lines(info: dict[str, Any], now: datetime | None = None) -> str:
    """Two lines shown to resellers (renewal screen only), right below the app/User-Agent line."""
    return (
        f"آخرین زمان آنلاین: {format_relative_time_fa(info.get('online_at'), now)}\n"
        f"آخرین آپدیت سابسکریپشن: {format_relative_time_fa(info.get('sub_last_update_at'), now)}"
    )


def _remaining_text(info: dict[str, Any], now: datetime) -> str:
    status = str(getattr(info.get("status"), "value", info.get("status")))
    if status == "on_hold":
        duration = int(info.get("on_hold_expire_duration") or 0)
        return f"{duration // 86400} day (on hold)" if duration else "On hold"
    expire = int(info.get("expire") or 0)
    if expire <= 0:
        return "Unlimited"
    seconds = expire - int(now.timestamp())
    if seconds <= 0:
        return "Expired"
    if seconds >= 86400:
        return f"{seconds // 86400} day"
    if seconds >= 3600:
        return f"{seconds // 3600} hour"
    return f"{max(1, seconds // 60)} minute"


def _expiration_date(info: dict[str, Any], tz_name: str) -> str:
    status = str(getattr(info.get("status"), "value", info.get("status")))
    expire = int(info.get("expire") or 0)
    if expire > 0:
        local = to_local(datetime.fromtimestamp(expire, timezone.utc), tz_name)
        return jdatetime.datetime.fromgregorian(datetime=local).strftime("%Y/%m/%d")
    return "Starts at first connection" if status == "on_hold" else "Unlimited"


def format_admin_user_info(info: dict[str, Any], tz_name: str = "Asia/Tehran", now: datetime | None = None) -> str:
    from app.services.marzban import extract_last_user_agent

    now = now or datetime.now(timezone.utc)
    status = str(getattr(info.get("status"), "value", info.get("status")) or "unknown")
    used = int(info.get("used_traffic") or 0)
    limit = int(info.get("data_limit") or 0)
    limit_text = f"{limit / BYTES_PER_GB:.1f} GB" if limit > 0 else "Unlimited"
    agent = extract_last_user_agent(info)
    return "\n".join([
        f"Username : {info.get('username') or 'Unknown'} ({status})",
        f"Data Used : {used / BYTES_PER_GB:.3f} GB ({limit_text})",
        f"Date Left : {_remaining_text(info, now)}",
        f"Expiration Date : {_expiration_date(info, tz_name)}",
        f"App Used : {'Unknown' if agent == 'نامشخص' else agent}",
        f"Last online time : {format_relative_time(info.get('online_at'), now)}",
        f"Last update sub : {format_relative_time(info.get('sub_last_update_at'), now)}",
    ])
