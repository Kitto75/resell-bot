from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

def dashboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ ساخت کاربر", callback_data="res:create"), InlineKeyboardButton(text="🔄 تمدید کاربر", callback_data="res:renew")],
        [InlineKeyboardButton(text="⏸ غیرفعال‌سازی کاربر", callback_data="res:mb:disable"), InlineKeyboardButton(text="▶️ فعال‌سازی کاربر", callback_data="res:mb:enable")],
        [InlineKeyboardButton(text="📋 لیست اکانت‌های من", callback_data="res:users:0")],
        [InlineKeyboardButton(text="💳 درخواست شارژ", callback_data="res:recharge"), InlineKeyboardButton(text="ℹ️ راهنما", callback_data="res:help")],
    ])


def created_user_actions() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="داشبورد", callback_data="back")],
    ])


def my_users_pagination(page: int, has_next: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️ قبلی", callback_data=f"res:users:{page - 1}"))
    if has_next:
        nav.append(InlineKeyboardButton(text="نمایش بیشتر ➡️", callback_data=f"res:users:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="⬅️ برگشت به داشبورد", callback_data="back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
