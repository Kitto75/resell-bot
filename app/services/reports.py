from app.config import get_settings
from app.database.models import OperationLog, Reseller
from app.services.datetime import persian_date_time


def operation_report(reseller: Reseller, log: OperationLog) -> str:
    date, time = persian_date_time(get_settings().timezone)
    return (
        "📋 گزارش عملیات\n"
        f"ریسلر: {reseller.display_name}\nشناسه تلگرام: {reseller.telegram_id}\n"
        f"نام کاربری: {log.username}\nنوع: {log.operation_type.value}\nحجم اضافه‌شده: {log.added_gb}\nروز اضافه‌شده: {log.added_days}\n"
        f"هزینه: {log.charged_amount}\nموجودی: {log.balance_before} → {log.balance_after}\n"
        f"تاریخ شمسی: {date}\nزمان: {time}\nمنطقه زمانی: Asia/Tehran"
    )
