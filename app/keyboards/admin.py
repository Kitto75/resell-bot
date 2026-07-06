from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from app.database.models import Reseller, TransactionType


def panel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 مدیریت ریسلرها", callback_data="adm:resellers"), InlineKeyboardButton(text="➕ افزودن ریسلر", callback_data="adm:add_reseller")],
        [InlineKeyboardButton(text="🧾 تراکنش‌ها", callback_data="adm:tx"), InlineKeyboardButton(text="🌐 اینباندها", callback_data="adm:inbounds")],
        [InlineKeyboardButton(text="🛠 حالت تعمیرات", callback_data="adm:maintenance"), InlineKeyboardButton(text="💾 بکاپ", callback_data="adm:backup")],
    ])


def admin_back_cancel(back: str = "adm:panel") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ برگشت", callback_data=back), InlineKeyboardButton(text="❌ لغو", callback_data="adm:cancel")]
    ])


def confirm_keyboard(confirm_data: str, back_data: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ تایید", callback_data=confirm_data)],
        [InlineKeyboardButton(text="⬅️ برگشت", callback_data=back_data), InlineKeyboardButton(text="❌ لغو", callback_data="adm:cancel")],
    ])


def resellers_keyboard(resellers: list[Reseller], prefix: str, back: str = "adm:panel") -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=f"{r.display_name} ({r.telegram_id})", callback_data=f"{prefix}:{r.id}")] for r in resellers]
    rows.append([InlineKeyboardButton(text="⬅️ برگشت", callback_data=back), InlineKeyboardButton(text="❌ لغو", callback_data="adm:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def maintenance_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ فعال‌سازی تعمیرات", callback_data="adm:maint:set:on")],
        [InlineKeyboardButton(text="🚫 غیرفعال‌سازی تعمیرات", callback_data="adm:maint:set:off")],
        [InlineKeyboardButton(text="⬅️ برگشت", callback_data="adm:panel"), InlineKeyboardButton(text="❌ لغو", callback_data="adm:cancel")],
    ])


def inbound_keyboard(tags: list[str], selected: list[str] | None, all_allowed: bool) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=("✅ همه اینباندها" if all_allowed else "☑️ همه اینباندها"), callback_data="adm:inb:all")]]
    for tag in tags:
        checked = all_allowed or tag in (selected or [])
        rows.append([InlineKeyboardButton(text=f"{'✅' if checked else '☐'} {tag}", callback_data=f"adm:inb:toggle:{tag}")])
    rows += [[InlineKeyboardButton(text="💾 ذخیره تغییرات", callback_data="adm:inb:save")], [InlineKeyboardButton(text="⬅️ برگشت", callback_data="adm:inbounds"), InlineKeyboardButton(text="❌ لغو", callback_data="adm:cancel")]]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def tx_filter_keyboard(reseller_id: int) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="همه انواع", callback_data=f"adm:txfilter:{reseller_id}:all")]]
    labels = {
        TransactionType.create_user: "ساخت کاربر",
        TransactionType.renew_user: "تمدید کاربر",
        TransactionType.increase: "افزایش دستی",
        TransactionType.decrease: "کاهش دستی",
        TransactionType.recharge: "شارژ تاییدشده",
    }
    for tx_type, label in labels.items():
        rows.append([InlineKeyboardButton(text=label, callback_data=f"adm:txfilter:{reseller_id}:{tx_type.value}")])
    rows.append([InlineKeyboardButton(text="⬅️ برگشت", callback_data="adm:tx"), InlineKeyboardButton(text="❌ لغو", callback_data="adm:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def tx_page_keyboard(reseller_id: int, tx_type: str, page: int, has_next: bool) -> InlineKeyboardMarkup:
    nav = []
    if page > 0: nav.append(InlineKeyboardButton(text="⬅️ قبلی", callback_data=f"adm:txpage:{reseller_id}:{tx_type}:{page-1}"))
    if has_next: nav.append(InlineKeyboardButton(text="بعدی ➡️", callback_data=f"adm:txpage:{reseller_id}:{tx_type}:{page+1}"))
    rows = [nav] if nav else []
    rows.append([InlineKeyboardButton(text="🔎 تغییر فیلتر", callback_data=f"adm:txsel:{reseller_id}")])
    rows.append([InlineKeyboardButton(text="⬅️ برگشت", callback_data="adm:tx"), InlineKeyboardButton(text="❌ لغو", callback_data="adm:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)



def resellers_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 لیست ریسلرها", callback_data="adm:reseller_list")],
        [InlineKeyboardButton(text="➕ افزودن ریسلر", callback_data="adm:add_reseller")],
        [InlineKeyboardButton(text="✏️ ویرایش ریسلر", callback_data="adm:edit_reseller")],
        [InlineKeyboardButton(text="💰 ویرایش موجودی", callback_data="adm:balance")],
        [InlineKeyboardButton(text="👥 اکانت‌های تلگرام ریسلر", callback_data="adm:tg_accounts")],
        [InlineKeyboardButton(text="⬅️ برگشت", callback_data="adm:panel"), InlineKeyboardButton(text="❌ لغو", callback_data="adm:cancel")],
    ])

def edit_field_keyboard(reseller_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="نام نمایشی", callback_data=f"adm:editfield:{reseller_id}:display_name")],
        [InlineKeyboardButton(text="قیمت هر گیگابایت", callback_data=f"adm:editfield:{reseller_id}:price_per_gb")],
        [InlineKeyboardButton(text="وضعیت", callback_data=f"adm:editfield:{reseller_id}:status")],
        [InlineKeyboardButton(text="⬅️ برگشت", callback_data="adm:resellers"), InlineKeyboardButton(text="❌ لغو", callback_data="adm:cancel")],
    ])

def status_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="فعال", callback_data="adm:editstatus:active"), InlineKeyboardButton(text="غیرفعال", callback_data="adm:editstatus:disabled")],
        [InlineKeyboardButton(text="بایگانی‌شده", callback_data="adm:editstatus:archived")],
        [InlineKeyboardButton(text="⬅️ برگشت", callback_data="adm:edit_reseller"), InlineKeyboardButton(text="❌ لغو", callback_data="adm:cancel")],
    ])

def balance_action_keyboard(reseller_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="افزایش", callback_data=f"adm:balact:{reseller_id}:increase"), InlineKeyboardButton(text="کاهش", callback_data=f"adm:balact:{reseller_id}:decrease")],
        [InlineKeyboardButton(text="تنظیم موجودی", callback_data=f"adm:balact:{reseller_id}:set_balance")],
        [InlineKeyboardButton(text="⬅️ برگشت", callback_data="adm:balance"), InlineKeyboardButton(text="❌ لغو", callback_data="adm:cancel")],
    ])

def recharge_actions(request_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ تایید", callback_data=f"recharge:approve:{request_id}"), InlineKeyboardButton(text="❌ رد", callback_data=f"recharge:reject:{request_id}")]
    ])


def recharge_reject_keyboard(request_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="رد بدون دلیل", callback_data=f"recharge:reject_no_reason:{request_id}")],
        [InlineKeyboardButton(text="لغو", callback_data=f"recharge:cancel:{request_id}")],
    ])


def backup_keyboard(enabled: bool) -> InlineKeyboardMarkup:
    toggle = InlineKeyboardButton(
        text="غیرفعال‌سازی بکاپ" if enabled else "فعال‌سازی بکاپ",
        callback_data="adm:backup:disable" if enabled else "adm:backup:enable",
    )
    return InlineKeyboardMarkup(inline_keyboard=[
        [toggle],
        [InlineKeyboardButton(text="تغییر فاصله زمانی", callback_data="adm:backup:interval")],
        [InlineKeyboardButton(text="دریافت بکاپ الان", callback_data="adm:backup:now")],
        [InlineKeyboardButton(text="برگشت", callback_data="adm:panel")],
    ])


def telegram_accounts_actions(reseller_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ افزودن آیدی تلگرام", callback_data=f"adm:tg:add:{reseller_id}")],
        [InlineKeyboardButton(text="➖ حذف آیدی تلگرام", callback_data=f"adm:tg:remove:{reseller_id}")],
        [InlineKeyboardButton(text="⭐ تنظیم به عنوان اصلی", callback_data=f"adm:tg:primary:{reseller_id}")],
        [InlineKeyboardButton(text="⬅️ برگشت", callback_data="adm:resellers"), InlineKeyboardButton(text="❌ لغو", callback_data="adm:cancel")],
    ])

def telegram_account_keyboard(accounts, action: str, back_reseller_id: int) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=f"{'⭐ ' if account.is_primary else ''}{account.telegram_id}", callback_data=f"adm:tg:{action}:acct:{account.id}")] for account in accounts]
    rows.append([InlineKeyboardButton(text="⬅️ برگشت", callback_data=f"adm:tgsel:{back_reseller_id}"), InlineKeyboardButton(text="❌ لغو", callback_data="adm:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
