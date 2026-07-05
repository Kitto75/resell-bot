from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

def back_cancel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Back", callback_data="back"), InlineKeyboardButton(text="❌ Cancel", callback_data="cancel")]])
