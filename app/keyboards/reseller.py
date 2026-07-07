from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

def dashboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ ساخت کاربر", callback_data="res:create"), InlineKeyboardButton(text="🔄 تمدید کاربر", callback_data="res:renew")],
        [InlineKeyboardButton(text="⏸ غیرفعال‌سازی کاربر", callback_data="res:mb:disable"), InlineKeyboardButton(text="▶️ فعال‌سازی کاربر", callback_data="res:mb:enable")],
        [InlineKeyboardButton(text="💳 درخواست شارژ", callback_data="res:recharge"), InlineKeyboardButton(text="ℹ️ راهنما", callback_data="res:help")],
    ])


def created_user_actions() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="داشبورد", callback_data="back")],
    ])
