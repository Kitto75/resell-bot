from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import jdatetime


def tehran_now(tz_name: str = "Asia/Tehran") -> datetime:
    return datetime.now(ZoneInfo(tz_name))


def persian_date_time(tz_name: str = "Asia/Tehran") -> tuple[str, str]:
    now = tehran_now(tz_name)
    jalali = jdatetime.datetime.fromgregorian(datetime=now)
    return jalali.strftime("%Y/%m/%d"), jalali.strftime("%H:%M:%S")


def jalali_filename_datetime(tz_name: str = "Asia/Tehran") -> str:
    now = tehran_now(tz_name)
    jalali = jdatetime.datetime.fromgregorian(datetime=now)
    return jalali.strftime("%Y-%m-%d-%H-%M")


def to_local(value: datetime | None, tz_name: str = "Asia/Tehran") -> datetime | None:
    """DB datetimes come back naive from SQLite (stored as UTC); treat them as UTC and convert."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(ZoneInfo(tz_name))


def jalali_datetime_text(value: datetime | None, tz_name: str = "Asia/Tehran") -> str:
    local = to_local(value, tz_name)
    if local is None:
        return "نامشخص"
    return jdatetime.datetime.fromgregorian(datetime=local).strftime("%Y/%m/%d - %H:%M")
