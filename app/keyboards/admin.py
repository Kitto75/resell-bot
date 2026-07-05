from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from app.database.models import Reseller, TransactionType


def panel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Resellers", callback_data="adm:resellers"), InlineKeyboardButton(text="➕ Add Reseller", callback_data="adm:add_reseller")],
        [InlineKeyboardButton(text="🧾 Transactions", callback_data="adm:tx"), InlineKeyboardButton(text="🌐 Inbounds", callback_data="adm:inbounds")],
        [InlineKeyboardButton(text="🛠 Maintenance Mode", callback_data="adm:maintenance")],
    ])


def admin_back_cancel(back: str = "adm:panel") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Back", callback_data=back), InlineKeyboardButton(text="❌ Cancel", callback_data="adm:cancel")]
    ])


def confirm_keyboard(confirm_data: str, back_data: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Confirm", callback_data=confirm_data)],
        [InlineKeyboardButton(text="⬅️ Back", callback_data=back_data), InlineKeyboardButton(text="❌ Cancel", callback_data="adm:cancel")],
    ])


def resellers_keyboard(resellers: list[Reseller], prefix: str, back: str = "adm:panel") -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=f"{r.display_name} ({r.telegram_id})", callback_data=f"{prefix}:{r.id}")] for r in resellers]
    rows.append([InlineKeyboardButton(text="⬅️ Back", callback_data=back), InlineKeyboardButton(text="❌ Cancel", callback_data="adm:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def maintenance_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Enable Maintenance", callback_data="adm:maint:set:on")],
        [InlineKeyboardButton(text="🚫 Disable Maintenance", callback_data="adm:maint:set:off")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="adm:panel"), InlineKeyboardButton(text="❌ Cancel", callback_data="adm:cancel")],
    ])


def inbound_keyboard(tags: list[str], selected: list[str] | None, all_allowed: bool) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=("✅ All Inbounds" if all_allowed else "☑️ All Inbounds"), callback_data="adm:inb:all")]]
    for tag in tags:
        checked = all_allowed or tag in (selected or [])
        rows.append([InlineKeyboardButton(text=f"{'✅' if checked else '☐'} {tag}", callback_data=f"adm:inb:toggle:{tag}")])
    rows += [[InlineKeyboardButton(text="💾 Save Changes", callback_data="adm:inb:save")], [InlineKeyboardButton(text="⬅️ Back", callback_data="adm:inbounds"), InlineKeyboardButton(text="❌ Cancel", callback_data="adm:cancel")]]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def tx_filter_keyboard(reseller_id: int) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="All types", callback_data=f"adm:txfilter:{reseller_id}:all")]]
    labels = {
        TransactionType.create_user: "create_user",
        TransactionType.renew_user: "renew_user",
        TransactionType.increase: "manual_increase",
        TransactionType.decrease: "manual_decrease",
        TransactionType.recharge: "recharge_approved",
    }
    for tx_type, label in labels.items():
        rows.append([InlineKeyboardButton(text=label, callback_data=f"adm:txfilter:{reseller_id}:{tx_type.value}")])
    rows.append([InlineKeyboardButton(text="⬅️ Back", callback_data="adm:tx"), InlineKeyboardButton(text="❌ Cancel", callback_data="adm:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def tx_page_keyboard(reseller_id: int, tx_type: str, page: int, has_next: bool) -> InlineKeyboardMarkup:
    nav = []
    if page > 0: nav.append(InlineKeyboardButton(text="⬅️ Previous", callback_data=f"adm:txpage:{reseller_id}:{tx_type}:{page-1}"))
    if has_next: nav.append(InlineKeyboardButton(text="Next ➡️", callback_data=f"adm:txpage:{reseller_id}:{tx_type}:{page+1}"))
    rows = [nav] if nav else []
    rows.append([InlineKeyboardButton(text="🔎 Change Filter", callback_data=f"adm:txsel:{reseller_id}")])
    rows.append([InlineKeyboardButton(text="⬅️ Back", callback_data="adm:tx"), InlineKeyboardButton(text="❌ Cancel", callback_data="adm:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)



def resellers_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Add Reseller", callback_data="adm:add_reseller")],
        [InlineKeyboardButton(text="✏️ Edit Reseller", callback_data="adm:edit_reseller")],
        [InlineKeyboardButton(text="💰 Edit Balance", callback_data="adm:balance")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="adm:panel"), InlineKeyboardButton(text="❌ Cancel", callback_data="adm:cancel")],
    ])

def edit_field_keyboard(reseller_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Display Name", callback_data=f"adm:editfield:{reseller_id}:display_name")],
        [InlineKeyboardButton(text="Price per GB", callback_data=f"adm:editfield:{reseller_id}:price_per_gb")],
        [InlineKeyboardButton(text="Status", callback_data=f"adm:editfield:{reseller_id}:status")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="adm:resellers"), InlineKeyboardButton(text="❌ Cancel", callback_data="adm:cancel")],
    ])

def status_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="active", callback_data="adm:editstatus:active"), InlineKeyboardButton(text="disabled", callback_data="adm:editstatus:disabled")],
        [InlineKeyboardButton(text="archived", callback_data="adm:editstatus:archived")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="adm:edit_reseller"), InlineKeyboardButton(text="❌ Cancel", callback_data="adm:cancel")],
    ])

def balance_action_keyboard(reseller_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Increase", callback_data=f"adm:balact:{reseller_id}:increase"), InlineKeyboardButton(text="Decrease", callback_data=f"adm:balact:{reseller_id}:decrease")],
        [InlineKeyboardButton(text="Set Balance", callback_data=f"adm:balact:{reseller_id}:set_balance")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="adm:balance"), InlineKeyboardButton(text="❌ Cancel", callback_data="adm:cancel")],
    ])

def recharge_actions(request_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Approve", callback_data=f"adm:recharge:approve:{request_id}"), InlineKeyboardButton(text="❌ Reject", callback_data=f"adm:recharge:reject:{request_id}")]
    ])
