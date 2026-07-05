from datetime import datetime
from zoneinfo import ZoneInfo
import jdatetime


def tehran_now(tz_name: str = "Asia/Tehran") -> datetime:
    return datetime.now(ZoneInfo(tz_name))


def persian_date_time(tz_name: str = "Asia/Tehran") -> tuple[str, str]:
    now = tehran_now(tz_name)
    jalali = jdatetime.datetime.fromgregorian(datetime=now)
    return jalali.strftime("%Y/%m/%d"), jalali.strftime("%H:%M:%S")
