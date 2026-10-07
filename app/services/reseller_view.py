"""Text builders for the admin reseller list / reseller card / group-access screens."""
from __future__ import annotations

from dataclasses import dataclass, field

from app.services.reports import SEPARATOR, rtl_lines
from app.utils.formatting import format_toman

PAGE_SIZE = 6
STATUS_ICON = {"active": "🟢", "disabled": "⛔", "archived": "📦"}
STATUS_TEXT = {"active": "فعال", "disabled": "غیرفعال", "archived": "بایگانی‌شده"}


@dataclass
class ResellerRow:
    id: int
    name: str
    status: str
    balance: object
    price_per_gb: object
    users: int = 0
    groups: list[str] = field(default_factory=list)  # empty == all groups
    telegram_ids: list[int] = field(default_factory=list)  # primary first
    created_text: str = ""


def group_summary(groups: list[str], limit: int = 4) -> str:
    if not groups:
        return "همه گروه‌ها"
    shown = "، ".join(groups[:limit]) + ("…" if len(groups) > limit else "")
    return f"{len(groups)} گروه ({shown})"


def page_count(total: int) -> int:
    return max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)


def reseller_list_text(rows: list[ResellerRow], page: int, total: int, archived_view: bool) -> str:
    title = "📦 ریسلرهای بایگانی‌شده" if archived_view else "👥 ریسلرها"
    lines = [f"{title} ({total})  |  صفحه {page + 1} از {page_count(total)}", SEPARATOR]
    if not rows:
        lines.append("موردی برای نمایش نیست.")
    for index, row in enumerate(rows):
        if index:
            lines.append("")
        lines += [
            f"{STATUS_ICON.get(row.status, '⚪️')} {row.name}",
            f"💰 {format_toman(row.balance)}  •  💲 {format_toman(row.price_per_gb)} / GB",
            f"👥 {row.users} اکانت  •  🌐 {group_summary(row.groups, 2)}",
        ]
    lines += ["", "برای مدیریت هر ریسلر روی نامش بزنید."]
    return rtl_lines(lines)


def reseller_card_text(row: ResellerRow) -> str:
    ids = "، ".join(f"{tid}{' (اصلی)' if i == 0 else ''}" for i, tid in enumerate(row.telegram_ids)) or "-"
    lines = [
        f"👤 {row.name}",
        SEPARATOR,
        f"{STATUS_ICON.get(row.status, '⚪️')} وضعیت: {STATUS_TEXT.get(row.status, row.status)}",
        f"💰 موجودی: {format_toman(row.balance)}",
        f"💲 قیمت هر گیگابایت: {format_toman(row.price_per_gb)}",
        f"👥 اکانت‌های ساخته‌شده: {row.users}",
        f"🌐 دسترسی گروه‌ها: {group_summary(row.groups, 6)}",
        f"🆔 تلگرام: {ids}",
    ]
    if row.created_text:
        lines.append(f"🗓 تاریخ ثبت: {row.created_text}")
    return rtl_lines(lines)


def delete_choice_text(row: ResellerRow) -> str:
    return rtl_lines([
        f"🗑 حذف ریسلر «{row.name}»",
        SEPARATOR,
        "📦 بایگانی (پیشنهادی)",
        "• ریسلر از لیست‌ها حذف می‌شود و دیگر نمی‌تواند از ربات استفاده کند.",
        "• موجودی، تراکنش‌ها و گزارش‌ها حفظ می‌شود و هر زمان بخواهید برمی‌گردد.",
        "",
        "🗑 حذف کامل",
        "• همه سوابق این ریسلر از دیتابیس ربات پاک می‌شود (برگشت‌پذیر نیست).",
        "• آیدی تلگرام آزاد می‌شود تا بتوان دوباره ثبتش کرد.",
        "",
        "ℹ️ در هر دو حالت اکانت‌های ساخته‌شده در پنل دست‌نخورده می‌مانند.",
        "اگر می‌خواهید اکانت‌ها قطع شوند، اول «غیرفعال‌سازی همه یوزرها» را بزنید؛ بعد از حذف کامل دیگر نمی‌توان آن‌ها را به این ریسلر ربط داد.",
    ])


def hard_delete_confirm_text(row: ResellerRow, counts: dict[str, int]) -> str:
    return rtl_lines([
        f"⚠️ حذف کامل «{row.name}»",
        SEPARATOR,
        f"💰 موجودی فعلی: {format_toman(row.balance)}",
        f"👥 اکانت‌های ثبت‌شده: {counts.get('users', 0)}",
        f"🧾 تراکنش‌ها: {counts.get('transactions', 0)}",
        f"📋 گزارش عملیات: {counts.get('operations', 0)}",
        f"💳 درخواست‌های شارژ: {counts.get('recharges', 0)}",
        "",
        "همه این موارد برای همیشه پاک می‌شود. مطمئنید؟",
    ])


def group_access_text(reseller_name: str, names: list[str], selected: list[str], mode: str, saved_text: str, stale: list[str], disabled_count: int, dirty: bool, saved_now: bool = False) -> str:
    lines = [f"🌐 دسترسی گروه‌های «{reseller_name}»", SEPARATOR, "ریسلر فقط می‌تواند اکانت‌هایی با گروه‌های مجاز خودش بسازد.", ""]
    if mode == "all":
        lines.append(f"📌 حالت: همه گروه‌ها ({len(names)} گروه، شامل گروه‌هایی که بعداً در پنل ساخته شوند)")
    else:
        lines.append(f"📌 حالت: فقط گروه‌های انتخاب‌شده ({len(selected)} از {len(names)})")
        lines += [f"   • {name}" for name in selected] or ["   (هنوز گروهی انتخاب نشده)"]
    if stale:
        lines += ["", f"⚠️ این گروه‌ها دیگر در پنل نیستند (یا غیرفعال شده‌اند) و با ذخیره حذف می‌شوند: {'، '.join(stale)}"]
    if disabled_count:
        lines.append(f"ℹ️ {disabled_count} گروه غیرفعال در پنل نمایش داده نمی‌شود.")
    lines += ["", f"ذخیره‌شده فعلی: {saved_text}", "✅ = مجاز   ⬜ = غیرمجاز"]
    if saved_now:
        lines += ["", "💾 ذخیره شد."]
    elif dirty:
        lines += ["", "🔸 تغییرات هنوز ذخیره نشده است."]
    return rtl_lines(lines)
