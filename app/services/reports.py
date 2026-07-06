from app.config import get_settings
from app.database.models import OperationLog, Reseller
from app.services.datetime import persian_date_time
from app.utils.formatting import format_toman


def operation_report(reseller: Reseller, log: OperationLog) -> str:
    date, time = persian_date_time(get_settings().timezone)
    return (
        "📋 گزارش عملیات\n"
        f"ریسلر: {reseller.display_name}\nشناسه تلگرام: {reseller.telegram_id}\n"
        f"نام کاربری: {log.username}\nنوع: {log.operation_type.value}\nحجم اضافه‌شده: {log.added_gb}\nروز اضافه‌شده: {log.added_days}\n"
        f"هزینه: {format_toman(log.charged_amount)}\nموجودی: {format_toman(log.balance_before)} → {format_toman(log.balance_after)}\n"
        f"تاریخ: {date}\nزمان: {time}"
    )
