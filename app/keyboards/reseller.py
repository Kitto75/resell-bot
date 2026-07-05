from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

def dashboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Create User", callback_data="res:create"), InlineKeyboardButton(text="🔄 Renew User", callback_data="res:renew")],
        [InlineKeyboardButton(text="💳 Request Balance", callback_data="res:recharge"), InlineKeyboardButton(text="ℹ️ Help", callback_data="res:help")],
    ])
