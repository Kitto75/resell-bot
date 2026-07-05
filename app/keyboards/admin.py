from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

def panel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Resellers", callback_data="adm:resellers"), InlineKeyboardButton(text="🧾 Transactions", callback_data="adm:tx")],
        [InlineKeyboardButton(text="🛠 Maintenance", callback_data="adm:maintenance"), InlineKeyboardButton(text="🌐 Inbounds", callback_data="adm:inbounds")],
    ])

def recharge_actions(request_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Approve", callback_data=f"adm:recharge:approve:{request_id}"), InlineKeyboardButton(text="❌ Reject", callback_data=f"adm:recharge:reject:{request_id}")]])
