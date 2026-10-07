from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from app.database.models import Reseller, TransactionType


def panel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 مدیریت ریسلرها", callback_data="adm:resellers"), InlineKeyboardButton(text="➕ افزودن ریسلر", callback_data="adm:add_reseller")],
        [InlineKeyboardButton(text="➕ ساخت کاربر", callback_data="adm:mb:create"), InlineKeyboardButton(text="♻️ تمدید کاربر", callback_data="adm:mb:renew")],
        [InlineKeyboardButton(text="⏸ غیرفعال‌سازی کاربر", callback_data="adm:mb:disable"), InlineKeyboardButton(text="▶️ فعال‌سازی کاربر", callback_data="adm:mb:enable")],
        [InlineKeyboardButton(text="🗑 حذف کاربر", callback_data="adm:mb:delete")],
        [InlineKeyboardButton(text="👥 یوزرهای ریسلر", callback_data="adm:reseller_users")],
        [InlineKeyboardButton(text="🧾 تراکنش‌ها", callback_data="adm:tx"), InlineKeyboardButton(text="🌐 دسترسی گروه‌ها", callback_data="adm:inbounds")],
        [InlineKeyboardButton(text="📄 گزارش PDF", callback_data="adm:rpt")],
        [InlineKeyboardButton(text="⚙️ تنظیمات تمدید", callback_data="adm:renewal_settings")],
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


def destructive_confirm_keyboard(confirm_data: str, back_data: str, text: str = "🗑 حذف قطعی") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=text, callback_data=confirm_data)],
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
    rows.append([InlineKeyboardButton(text="🔎 تغییر فیلتر", callback_data=f"adm:txsel:{reseller_id}"), InlineKeyboardButton(text="📄 گزارش PDF", callback_data=f"adm:rpt:s:{reseller_id}")])
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



def reseller_bulk_actions_keyboard(reseller_id: int, disable_count: int | None = None, enable_count: int | None = None) -> InlineKeyboardMarkup:
    disable_suffix = f" ({disable_count})" if disable_count is not None else ""
    enable_suffix = f" ({enable_count})" if enable_count is not None else ""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"⏸ غیرفعال‌سازی همه یوزرها{disable_suffix}", callback_data=f"adm:ru:bulk:{reseller_id}:disable")],
        [InlineKeyboardButton(text=f"▶️ فعال‌سازی همه یوزرها{enable_suffix}", callback_data=f"adm:ru:bulk:{reseller_id}:enable")],
        [InlineKeyboardButton(text="👤 کارت ریسلر", callback_data=f"adm:rc:{reseller_id}")],
        [InlineKeyboardButton(text="⬅️ انتخاب ریسلر", callback_data="adm:reseller_users"), InlineKeyboardButton(text="❌ لغو", callback_data="adm:cancel")],
    ])


def reseller_bulk_confirm_keyboard(reseller_id: int, action: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ تایید عملیات گروهی", callback_data=f"adm:ru:bulk_confirm:{reseller_id}:{action}")],
        [InlineKeyboardButton(text="بازگشت", callback_data=f"adm:rusel:{reseller_id}"), InlineKeyboardButton(text="لغو", callback_data="adm:cancel")],
    ])

def reseller_users_page_keyboard(reseller_id: int, users, page: int, has_next: bool) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=user.username, callback_data=f"adm:ru:user:{reseller_id}:{user.id}")] for user in users]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️ قبلی", callback_data=f"adm:ru:page:{reseller_id}:{page-1}"))
    if has_next:
        nav.append(InlineKeyboardButton(text="بعدی ➡️", callback_data=f"adm:ru:page:{reseller_id}:{page+1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="⬅️ انتخاب ریسلر", callback_data="adm:reseller_users"), InlineKeyboardButton(text="🏠 پنل مدیریت", callback_data="adm:panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def reseller_user_actions_keyboard(reseller_id: int, created_user_id: int, page: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="▶️ فعال‌سازی", callback_data=f"adm:ru:act:{reseller_id}:{created_user_id}:enable:{page}")],
        [InlineKeyboardButton(text="⏸ غیرفعال‌سازی", callback_data=f"adm:ru:act:{reseller_id}:{created_user_id}:disable:{page}")],
        [InlineKeyboardButton(text="بازگشت", callback_data=f"adm:ru:page:{reseller_id}:{page}")],
        [InlineKeyboardButton(text="🏠 پنل مدیریت", callback_data="adm:panel")],
    ])


def renewal_settings_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ انتخاب تمدید افزایشی", callback_data="adm:renewal:set:additive")],
        [InlineKeyboardButton(text="🔄 انتخاب تمدید با ریست و جایگزینی", callback_data="adm:renewal:set:replace")],
        [InlineKeyboardButton(text="بازگشت", callback_data="adm:panel")],
    ])


def report_scope_keyboard(resellers: list[Reseller]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="👥 همه ریسلرها", callback_data="adm:rpt:s:all")]]
    rows += [[InlineKeyboardButton(text=r.display_name, callback_data=f"adm:rpt:s:{r.id}")] for r in resellers]
    rows.append([InlineKeyboardButton(text="⬅️ برگشت", callback_data="adm:panel"), InlineKeyboardButton(text="❌ لغو", callback_data="adm:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def report_period_keyboard(scope: str) -> InlineKeyboardMarkup:
    periods = [("7d", "📅 ۷ روز اخیر"), ("30d", "📅 ۳۰ روز اخیر"), ("cur", "🗓 ماه شمسی جاری"), ("all", "♾ کل سوابق")]
    rows = [[InlineKeyboardButton(text=label, callback_data=f"adm:rpt:go:{scope}:{key}")] for key, label in periods]
    rows.append([InlineKeyboardButton(text="⬅️ برگشت", callback_data="adm:rpt"), InlineKeyboardButton(text="❌ لغو", callback_data="adm:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def reseller_list_keyboard(rows, page: int, total: int, archived_view: bool, archived_count: int) -> InlineKeyboardMarkup:
    from app.services.reseller_view import PAGE_SIZE, STATUS_ICON
    view = "r" if archived_view else "a"
    keyboard = [[InlineKeyboardButton(text=f"{STATUS_ICON.get(r.status, '⚪️')} {r.name}", callback_data=f"adm:rc:{r.id}")] for r in rows]
    nav = []
    if page > 0: nav.append(InlineKeyboardButton(text="⬅️ قبلی", callback_data=f"adm:rl:{view}:{page - 1}"))
    if (page + 1) * PAGE_SIZE < total: nav.append(InlineKeyboardButton(text="بعدی ➡️", callback_data=f"adm:rl:{view}:{page + 1}"))
    if nav: keyboard.append(nav)
    if archived_view:
        keyboard.append([InlineKeyboardButton(text="👥 بازگشت به ریسلرهای فعال", callback_data="adm:rl:a:0")])
    else:
        keyboard.append([InlineKeyboardButton(text="➕ افزودن ریسلر", callback_data="adm:add_reseller")] + ([InlineKeyboardButton(text=f"📦 بایگانی‌شده‌ها ({archived_count})", callback_data="adm:rl:r:0")] if archived_count else []))
    keyboard.append([InlineKeyboardButton(text="⬅️ برگشت", callback_data="adm:resellers"), InlineKeyboardButton(text="🏠 پنل مدیریت", callback_data="adm:panel")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def reseller_card_keyboard(reseller_id: int, status: str, list_view: str = "a") -> InlineKeyboardMarkup:
    rid = reseller_id
    if status == "archived":
        status_row = [InlineKeyboardButton(text="♻️ بازگردانی ریسلر", callback_data=f"adm:rc:st:{rid}:active")]
    elif status == "active":
        status_row = [InlineKeyboardButton(text="⏸ غیرفعال‌سازی ریسلر", callback_data=f"adm:rc:st:{rid}:disabled")]
    else:
        status_row = [InlineKeyboardButton(text="▶️ فعال‌سازی ریسلر", callback_data=f"adm:rc:st:{rid}:active")]
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ ویرایش", callback_data=f"adm:editsel:{rid}"), InlineKeyboardButton(text="💰 موجودی", callback_data=f"adm:balsel:{rid}")],
        [InlineKeyboardButton(text="🌐 گروه‌ها", callback_data=f"adm:inbsel:{rid}"), InlineKeyboardButton(text="🧾 تراکنش‌ها", callback_data=f"adm:txsel:{rid}")],
        [InlineKeyboardButton(text="👥 یوزرها", callback_data=f"adm:rusel:{rid}"), InlineKeyboardButton(text="🆔 آیدی‌های تلگرام", callback_data=f"adm:tgsel:{rid}")],
        status_row,
        [InlineKeyboardButton(text="🗑 حذف ریسلر", callback_data=f"adm:rdel:{rid}")],
        [InlineKeyboardButton(text="⬅️ لیست ریسلرها", callback_data=f"adm:rl:{list_view}:0")],
    ])


def reseller_delete_keyboard(reseller_id: int) -> InlineKeyboardMarkup:
    rid = reseller_id
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 بایگانی (پیشنهادی)", callback_data=f"adm:rdel:do:arch:{rid}")],
        [InlineKeyboardButton(text="🗑 حذف کامل", callback_data=f"adm:rdel:c:hard:{rid}")],
        [InlineKeyboardButton(text="⏸ اول غیرفعال‌سازی همه یوزرها", callback_data=f"adm:rusel:{rid}")],
        [InlineKeyboardButton(text="⬅️ برگشت", callback_data=f"adm:rc:{rid}")],
    ])


def reseller_hard_delete_keyboard(reseller_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 بله، برای همیشه حذف شود", callback_data=f"adm:rdel:do:hard:{reseller_id}")],
        [InlineKeyboardButton(text="⬅️ انصراف", callback_data=f"adm:rdel:{reseller_id}")],
    ])


def group_access_keyboard(names: list[str], selected: list[str], mode: str) -> InlineKeyboardMarkup:
    all_mode = mode == "all"
    rows = [[InlineKeyboardButton(text=f"{'✅' if all_mode else '⬜'} همه گروه‌ها (بدون محدودیت)", callback_data="adm:inb:all")]]
    for index, name in enumerate(names):
        checked = all_mode or name in selected
        rows.append([InlineKeyboardButton(text=f"{'✅' if checked else '⬜'} {name}", callback_data=f"adm:inb:t:{index}")])
    rows.append([InlineKeyboardButton(text="💾 ذخیره", callback_data="adm:inb:save")])
    rows.append([InlineKeyboardButton(text="⬅️ برگشت", callback_data="adm:inbounds"), InlineKeyboardButton(text="❌ لغو", callback_data="adm:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
