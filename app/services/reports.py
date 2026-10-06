import re
from app.config import get_settings
from app.database.models import OperationLog, OperationType, Reseller, TransactionType
from app.services.datetime import jalali_datetime_text, persian_date_time
from app.utils.formatting import format_toman

# Every line starts with an RLM so Telegram lays the whole line out right-to-left,
# and balances are written on separate lines instead of "A → B" (arrows flip in RTL text).
RLM = "\u200f"
SEPARATOR = "━━━━━━━━━━━━━━"

TX_TYPE_LABELS = {
    TransactionType.create_user: "ساخت کاربر",
    TransactionType.renew_user: "تمدید کاربر",
    TransactionType.increase: "افزایش دستی",
    TransactionType.decrease: "کاهش دستی",
    TransactionType.set_balance: "تنظیم موجودی",
    TransactionType.recharge: "شارژ تاییدشده",
}
_ENGLISH_SUFFIX = re.compile(r"\s*:\s*(increase|decrease|set_balance)\s*$")


def rtl_lines(lines: list[str]) -> str:
    return "\n".join(f"{RLM}{line}" if line else "" for line in lines)


def tx_type_label(tx_type: TransactionType | str | None) -> str:
    if tx_type is None:
        return "همه انواع"
    try:
        return TX_TYPE_LABELS[TransactionType(tx_type)]
    except (KeyError, ValueError):
        return str(tx_type)


def clean_tx_description(description: str | None) -> str:
    return _ENGLISH_SUFFIX.sub("", description or "").strip() or "بدون توضیح"


def _tx_icon(tx) -> str:
    return "🟢" if tx.amount > 0 else ("🔴" if tx.amount < 0 else "⚪️")


def transaction_card(tx, tz_name: str) -> list[str]:
    return [
        f"{_tx_icon(tx)} {tx_type_label(tx.type)} • #{tx.id}",
        f"💰 مبلغ: {format_toman(abs(tx.amount))}",
        f"موجودی قبل: {format_toman(tx.balance_before)}",
        f"موجودی بعد: {format_toman(tx.balance_after)}",
        f"🕒 {jalali_datetime_text(tx.created_at, tz_name)}",
        f"📝 {clean_tx_description(tx.description)}",
    ]


def transactions_page_text(reseller_name: str, tx_type: str, page: int, txs: list, tz_name: str) -> str:
    filter_label = "همه انواع" if tx_type == "all" else tx_type_label(tx_type)
    lines = [f"🧾 تراکنش‌های {reseller_name}", f"🔎 فیلتر: {filter_label}  |  📄 صفحه {page + 1}", SEPARATOR]
    if not txs:
        lines.append("تراکنشی برای این انتخاب پیدا نشد.")
    for index, tx in enumerate(txs):
        if index:
            lines.append("")
        lines.extend(transaction_card(tx, tz_name))
    return rtl_lines(lines)


def operation_report(reseller: Reseller, log: OperationLog) -> str:
    date, time = persian_date_time(get_settings().timezone)
    is_create = log.operation_type == OperationType.create
    actor = getattr(log, "created_by", None) or reseller.telegram_id
    lines = [
        f"📋 گزارش عملیات • {'ساخت اکانت' if is_create else 'تمدید اکانت'}",
        SEPARATOR,
        f"👤 ریسلر: {reseller.display_name}",
        f"🆔 انجام‌دهنده: {actor}",
    ]
    if actor != reseller.telegram_id:
        lines.append(f"🆔 آیدی اصلی: {reseller.telegram_id}")
    lines += [
        f"🏷 نام کاربری: {log.username}",
        "",
        f"📦 حجم: {log.added_gb} گیگابایت",
        f"📅 مدت: {log.added_days} روز",
        f"💰 هزینه: {format_toman(log.charged_amount)}",
        f"موجودی قبل: {format_toman(log.balance_before)}",
        f"موجودی بعد: {format_toman(log.balance_after)}",
        "",
        f"🕒 تاریخ: {date} - {time[:5]}",
    ]
    return rtl_lines(lines)


def recharge_request_text(request_id: int, reseller_name: str, amount, receipt_text: str | None) -> str:
    return rtl_lines([
        f"💳 درخواست شارژ #{request_id}",
        SEPARATOR,
        f"👤 ریسلر: {reseller_name}",
        f"💰 مبلغ: {format_toman(amount)}",
        f"🧾 رسید: {receipt_text or 'تصویر'}",
    ])
