from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

def back_cancel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ برگشت", callback_data="back"), InlineKeyboardButton(text="❌ لغو", callback_data="cancel")]])

def reseller_confirm(confirm_data: str, back_data: str, confirm_text: str = "✅ تایید") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=confirm_text, callback_data=confirm_data)],
        [InlineKeyboardButton(text="⬅️ برگشت", callback_data=back_data), InlineKeyboardButton(text="❌ لغو", callback_data="cancel")],
    ])
