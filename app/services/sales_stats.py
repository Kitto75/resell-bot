"""Sales (created / renewed accounts) and charge (recharges / manual increases) statistics for a time window."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import jdatetime
from sqlalchemy import func, select

from app.database.models import BalanceTransaction, OperationLog, OperationType, Reseller, TransactionType
from app.services.reports import SEPARATOR, rtl_lines
from app.utils.formatting import format_toman

PERIODS = {"1d": (timedelta(days=1), "۱ روز اخیر"), "7d": (timedelta(days=7), "۷ روز اخیر"), "30d": (timedelta(days=30), "۱ ماه اخیر"), "all": (None, "کل سوابق")}
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_DATE = re.compile(r"(?<!\d)(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})(?!\d)")
_SEPARATORS = re.compile(r"(تا|الی|to|[\s\-–—،,.:])+", re.IGNORECASE)

CUSTOM_RANGE_HELP = (
    "🗓 بازه دلخواه\\n\\n"
    "تاریخ شروع و پایان را در یک پیام و با فاصله بفرستید:\\n"
    "• شمسی: 1405/07/01 1405/07/20\\n"
    "• میلادی: 2026-09-23 2026-10-12\\n"
    "• با «تا» هم می‌شود: 1405/07/01 تا 1405/07/20\\n"
    "• فقط یک روز: 1405/07/20\\n\\n"
    "سال کمتر از 1700 شمسی و بقیه میلادی حساب می‌شود. بازه شامل کل روز شروع و کل روز پایان است (به وقت تهران)."
).replace("\\n", "\n")


def _day_bounds(day: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    start = datetime(day.year, day.month, day.day, tzinfo=tz)
    return start, start + timedelta(days=1)


def _to_naive_utc(moment: datetime) -> datetime:
    return moment.astimezone(timezone.utc).replace(tzinfo=None)  # same naive-UTC form the database stores


def _jalali(day: date) -> str:
    return jdatetime.date.fromgregorian(date=day).strftime("%Y/%m/%d")


def window_for(period: str, tz_name: str, now: datetime | None = None) -> tuple[datetime | None, datetime | None, str]:
    """(start, end, label) as naive UTC; start/end None = unbounded."""
    delta, name = PERIODS[period]
    if delta is None:
        return None, None, name
    now = now or datetime.now(timezone.utc)
    local_now = now.astimezone(ZoneInfo(tz_name))
    return _to_naive_utc(now - delta), _to_naive_utc(now), f"{name} ({_jalali((local_now - delta).date())} تا {_jalali(local_now.date())})"


def parse_custom_range(text: str | None, tz_name: str) -> tuple[datetime, datetime, str]:
    """Accepts one or two dates (Jalali or Gregorian). Raises ValueError with a message that can be shown to the admin."""
    raw = (text or "").translate(_DIGITS)
    matches = list(_DATE.finditer(raw))
    leftover = _DATE.sub(" ", raw)
    if not 1 <= len(matches) <= 2 or _SEPARATORS.sub("", leftover).strip():
        raise ValueError("فرمت بازه درست نیست. مثال: 1405/07/01 1405/07/20 (یا فقط یک تاریخ).")
    days: list[date] = []
    for m in matches:
        year, month, day = (int(g) for g in m.groups())
        try:
            days.append(jdatetime.date(year, month, day).togregorian() if year < 1700 else date(year, month, day))
        except ValueError:
            raise ValueError(f"تاریخ «{m.group(0)}» وجود ندارد.") from None
    first, last = (days[0], days[-1]) if days[0] <= days[-1] else (days[-1], days[0])
    tz = ZoneInfo(tz_name)
    start, end = _day_bounds(first, tz)[0], _day_bounds(last, tz)[1]
    label = f"بازه دلخواه ({_jalali(first)} تا {_jalali(last)})" if first != last else f"بازه دلخواه ({_jalali(first)})"
    return _to_naive_utc(start), _to_naive_utc(end), label


@dataclass
class SalesStats:
    created_count: int = 0
    created_sum: Decimal = Decimal("0")
    renewed_count: int = 0
    renewed_sum: Decimal = Decimal("0")
    recharge_count: int = 0
    recharge_sum: Decimal = Decimal("0")
    manual_count: int = 0
    manual_sum: Decimal = Decimal("0")
    per_reseller: dict[str, dict[str, Decimal]] = field(default_factory=dict)

    @property
    def sales_total(self) -> Decimal: return self.created_sum + self.renewed_sum

    @property
    def charge_total(self) -> Decimal: return self.recharge_sum + self.manual_sum


def _bounded(stmt, column, start, end):
    if start is not None: stmt = stmt.where(column >= start)
    if end is not None: stmt = stmt.where(column < end)
    return stmt


async def collect_sales_stats(session, start: datetime | None, end: datetime | None) -> SalesStats:
    stats = SalesStats()
    names = {r.id: r.display_name for r in (await session.scalars(select(Reseller))).all()}
    per = stats.per_reseller

    def add(reseller_id: int, key: str, amount: Decimal) -> None:
        row = per.setdefault(names.get(reseller_id, str(reseller_id)), {"sales": Decimal("0"), "charge": Decimal("0")})
        row[key] += Decimal(amount)

    op_stmt = _bounded(select(OperationLog.reseller_id, OperationLog.operation_type, func.count(OperationLog.id), func.coalesce(func.sum(OperationLog.charged_amount), 0)).group_by(OperationLog.reseller_id, OperationLog.operation_type), OperationLog.created_at, start, end)
    for reseller_id, op_type, count, total in (await session.execute(op_stmt)).all():
        total = Decimal(total)
        if op_type == OperationType.create: stats.created_count += count; stats.created_sum += total
        else: stats.renewed_count += count; stats.renewed_sum += total
        add(reseller_id, "sales", total)

    tx_stmt = _bounded(select(BalanceTransaction.reseller_id, BalanceTransaction.type, func.count(BalanceTransaction.id), func.coalesce(func.sum(BalanceTransaction.amount), 0)).where(BalanceTransaction.type.in_([TransactionType.recharge, TransactionType.increase]), BalanceTransaction.amount > 0).group_by(BalanceTransaction.reseller_id, BalanceTransaction.type), BalanceTransaction.created_at, start, end)
    for reseller_id, tx_type, count, total in (await session.execute(tx_stmt)).all():
        total = Decimal(total)
        if tx_type == TransactionType.recharge: stats.recharge_count += count; stats.recharge_sum += total
        else: stats.manual_count += count; stats.manual_sum += total
        add(reseller_id, "charge", total)
    return stats


def format_sales_text(stats: SalesStats, label: str, top: int = 10) -> str:
    lines = ["📈 آمار شارژ و فروش", SEPARATOR, f"🗓 بازه: {label}", "",
             "🛒 فروش",
             f"• اکانت ساخته‌شده: {stats.created_count} مورد — {format_toman(stats.created_sum)}",
             f"• تمدید: {stats.renewed_count} مورد — {format_toman(stats.renewed_sum)}",
             f"• جمع فروش: {format_toman(stats.sales_total)}", "",
             "💳 شارژ حساب",
             f"• شارژ تأییدشده: {stats.recharge_count} مورد — {format_toman(stats.recharge_sum)}",
             f"• افزایش دستی مدیر: {stats.manual_count} مورد — {format_toman(stats.manual_sum)}",
             f"• جمع شارژ: {format_toman(stats.charge_total)}"]
    ranked = sorted(stats.per_reseller.items(), key=lambda kv: kv[1]["sales"] + kv[1]["charge"], reverse=True)[:top]
    if ranked:
        lines += ["", "🏆 به تفکیک ریسلر (فروش | شارژ)"] + [f"• {name}: {format_toman(v['sales'])} | {format_toman(v['charge'])}" for name, v in ranked]
    return rtl_lines(lines)
