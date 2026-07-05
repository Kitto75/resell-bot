from app.config import get_settings
from app.database.models import OperationLog, Reseller
from app.services.datetime import persian_date_time


def operation_report(reseller: Reseller, log: OperationLog) -> str:
    date, time = persian_date_time(get_settings().timezone)
    return (
        "📋 Operation Report\n"
        f"Reseller: {reseller.display_name}\nTelegram ID: {reseller.telegram_id}\n"
        f"Username: {log.username}\nType: {log.operation_type.value}\nAdded GB: {log.added_gb}\nAdded days: {log.added_days}\n"
        f"Charged: {log.charged_amount}\nBalance: {log.balance_before} → {log.balance_after}\n"
        f"Persian date: {date}\nPersian time: {time}\nTimezone: Asia/Tehran"
    )
