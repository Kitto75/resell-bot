from decimal import Decimal, InvalidOperation
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.exc import IntegrityError
from app.config import get_settings
from app.database.models import RechargeStatus, ResellerStatus, TransactionType
from app.database.repositories import InboundRepository, RechargeRepository, ResellerRepository, SettingsRepository, TransactionRepository
from app.database.session import SessionLocal
from app.keyboards.admin import admin_back_cancel, balance_action_keyboard, confirm_keyboard, edit_field_keyboard, inbound_keyboard, maintenance_keyboard, panel, recharge_actions, resellers_keyboard, resellers_menu, status_keyboard, tx_filter_keyboard, tx_page_keyboard
from app.services.billing import BillingService
from app.services.marzban import MarzbanClient, MarzbanError
from app.states.admin import AddReseller, BalanceEdit, EditReseller, InboundPermissions, MaintenanceMode, RechargeModeration, TransactionBrowsing

router = Router()
PAGE_SIZE = 5


def client() -> MarzbanClient:
    s = get_settings(); return MarzbanClient(s.marzban_base_url, s.marzban_username, s.marzban_password)

def money(text: str | None) -> Decimal | None:
    try: value = Decimal((text or '').strip())
    except InvalidOperation: return None
    return value if value >= 0 else None

async def show_panel(message: Message) -> None:
    await message.answer("Admin panel\nChoose an action. Every tool below is available through guided buttons.", reply_markup=panel())

@router.callback_query(F.data == "adm:panel")
async def panel_cb(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: await cb.answer("Admins only.", show_alert=True); return
    await state.clear(); await show_panel(cb.message); await cb.answer()

@router.callback_query(F.data == "adm:cancel")
async def cancel(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    await state.clear(); await cb.message.answer("Cancelled. Back at the admin panel.", reply_markup=panel()); await cb.answer()

@router.message(Command("add_reseller"))
async def add_reseller_cmd(message: Message, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    await state.clear(); await state.set_state(AddReseller.telegram_id)
    await message.answer("Please enter the reseller Telegram ID.", reply_markup=admin_back_cancel())

@router.callback_query(F.data == "adm:resellers")
async def resellers_menu_cb(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    await state.clear(); await cb.message.answer("Reseller management", reply_markup=resellers_menu()); await cb.answer()

@router.callback_query(F.data == "adm:add_reseller")
async def add_reseller_start(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: await cb.answer("Admins only.", show_alert=True); return
    await state.clear(); await state.set_state(AddReseller.telegram_id)
    await cb.message.answer("Add Reseller\nPlease enter the reseller Telegram ID.", reply_markup=admin_back_cancel()); await cb.answer()

@router.message(AddReseller.telegram_id)
async def add_tid(message: Message, state: FSMContext) -> None:
    try: telegram_id = int((message.text or '').strip())
    except ValueError: await message.answer("Telegram ID must be a whole number. Please enter the reseller Telegram ID."); return
    await state.update_data(telegram_id=telegram_id); await state.set_state(AddReseller.balance)
    await message.answer("Please enter the initial balance.", reply_markup=admin_back_cancel("adm:add_reseller"))

@router.message(AddReseller.balance)
async def add_balance(message: Message, state: FSMContext) -> None:
    value = money(message.text)
    if value is None: await message.answer("Initial balance must be a positive number or 0. Please try again."); return
    await state.update_data(balance=str(value)); await state.set_state(AddReseller.price)
    await message.answer("Please enter price per GB.", reply_markup=admin_back_cancel("adm:add_reseller"))

@router.message(AddReseller.price)
async def add_price(message: Message, state: FSMContext) -> None:
    value = money(message.text)
    if value is None or value <= 0: await message.answer("Price per GB must be greater than 0. Please try again."); return
    await state.update_data(price=str(value)); await state.set_state(AddReseller.display_name)
    await message.answer("Please enter display name.", reply_markup=admin_back_cancel("adm:add_reseller"))

@router.message(AddReseller.display_name)
async def add_name(message: Message, state: FSMContext) -> None:
    name = (message.text or '').strip()
    if len(name) < 2: await message.answer("Display name must contain at least 2 characters. Please try again."); return
    data = await state.update_data(display_name=name); await state.set_state(AddReseller.confirm)
    await message.answer(f"Confirm new reseller:\n\nTelegram ID: {data['telegram_id']}\nInitial balance: {data['balance']}\nPrice per GB: {data['price']}\nDisplay name: {data['display_name']}", reply_markup=confirm_keyboard("adm:add:confirm", "adm:add_reseller"))

@router.callback_query(AddReseller.confirm, F.data == "adm:add:confirm")
async def add_confirm(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    data = await state.get_data()
    try:
        async with SessionLocal() as session, session.begin():
            await ResellerRepository(session).add(int(data['telegram_id']), data['display_name'], Decimal(data['balance']), Decimal(data['price']))
    except IntegrityError:
        await cb.message.answer("A reseller with that Telegram ID already exists. No changes were saved.", reply_markup=panel()); await state.clear(); await cb.answer(); return
    await state.clear(); await cb.message.answer("✅ Reseller created.", reply_markup=panel()); await cb.answer()


@router.callback_query(F.data == "adm:edit_reseller")
async def edit_reseller_start(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    await select_reseller(cb.message, state, EditReseller.select, "adm:editsel", "Select reseller to edit."); await cb.answer()

@router.callback_query(F.data.startswith("adm:editsel:"))
async def edit_reseller_field(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    reseller_id = int(cb.data.rsplit(":", 1)[1]); await state.update_data(reseller_id=reseller_id); await state.set_state(EditReseller.field)
    await cb.message.answer("Choose the field to update.", reply_markup=edit_field_keyboard(reseller_id)); await cb.answer()

@router.callback_query(F.data.startswith("adm:editfield:"))
async def edit_field(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    _, _, rid, field = cb.data.split(":"); await state.update_data(reseller_id=int(rid), field=field); await state.set_state(EditReseller.value)
    if field == "status":
        await cb.message.answer("Choose the new status.", reply_markup=status_keyboard())
    else:
        await cb.message.answer(f"Enter new {'display name' if field == 'display_name' else 'price per GB'}.", reply_markup=admin_back_cancel(f"adm:editsel:{rid}"))
    await cb.answer()

@router.callback_query(EditReseller.value, F.data.startswith("adm:editstatus:"))
async def edit_status_value(cb: CallbackQuery, state: FSMContext) -> None:
    status = cb.data.rsplit(":", 1)[1]
    data = await state.update_data(value=status); await state.set_state(EditReseller.confirm)
    await cb.message.answer(f"Confirm changing reseller status to {status}.", reply_markup=confirm_keyboard("adm:edit:confirm", f"adm:editsel:{data['reseller_id']}")); await cb.answer()

@router.message(EditReseller.value)
async def edit_text_value(message: Message, state: FSMContext) -> None:
    data = await state.get_data(); field = data['field']; value = (message.text or '').strip()
    if field == 'display_name' and len(value) < 2: await message.answer("Display name must contain at least 2 characters."); return
    if field == 'price_per_gb':
        amount = money(value)
        if amount is None or amount <= 0: await message.answer("Price per GB must be greater than 0."); return
        value = str(amount)
    await state.update_data(value=value); await state.set_state(EditReseller.confirm)
    await message.answer(f"Confirm updating {field} to {value}.", reply_markup=confirm_keyboard("adm:edit:confirm", f"adm:editsel:{data['reseller_id']}"))

@router.callback_query(EditReseller.confirm, F.data == "adm:edit:confirm")
async def edit_confirm(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    data = await state.get_data()
    async with SessionLocal() as session, session.begin():
        reseller = await ResellerRepository(session).get(int(data['reseller_id']))
        if reseller is None: await cb.answer("Reseller not found", show_alert=True); return
        if data['field'] == 'display_name': reseller.display_name = data['value']
        elif data['field'] == 'price_per_gb': reseller.price_per_gb = Decimal(data['value'])
        elif data['field'] == 'status': reseller.status = ResellerStatus(data['value'])
    await state.clear(); await cb.message.answer("✅ Reseller updated.", reply_markup=panel()); await cb.answer()

@router.callback_query(F.data == "adm:balance")
async def balance_start(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    await select_reseller(cb.message, state, BalanceEdit.select, "adm:balsel", "Select reseller for balance edit."); await cb.answer()

@router.callback_query(F.data.startswith("adm:balsel:"))
async def balance_action(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    reseller_id = int(cb.data.rsplit(":",1)[1]); await state.update_data(reseller_id=reseller_id); await state.set_state(BalanceEdit.action)
    await cb.message.answer("Choose balance action.", reply_markup=balance_action_keyboard(reseller_id)); await cb.answer()

@router.callback_query(F.data.startswith("adm:balact:"))
async def balance_amount(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    _, _, rid, action = cb.data.split(":"); await state.update_data(reseller_id=int(rid), balance_action=action); await state.set_state(BalanceEdit.amount)
    await cb.message.answer("Enter amount.", reply_markup=admin_back_cancel(f"adm:balsel:{rid}")); await cb.answer()

@router.message(BalanceEdit.amount)
async def balance_amount_msg(message: Message, state: FSMContext) -> None:
    amount = money(message.text)
    if amount is None: await message.answer("Amount must be a positive number or 0."); return
    data = await state.update_data(amount=str(amount)); await state.set_state(BalanceEdit.confirm)
    await message.answer(f"Confirm balance action: {data['balance_action']} {amount}.", reply_markup=confirm_keyboard("adm:balance:confirm", f"adm:balsel:{data['reseller_id']}"))

@router.callback_query(BalanceEdit.confirm, F.data == "adm:balance:confirm")
async def balance_confirm(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    data = await state.get_data(); amount = Decimal(data['amount']); action = data['balance_action']
    async with SessionLocal() as session, session.begin():
        reseller = await ResellerRepository(session).get(int(data['reseller_id']))
        if reseller is None: await cb.answer("Reseller not found", show_alert=True); return
        if action == 'set_balance':
            delta = amount - reseller.balance
            await BillingService(session).change_balance(reseller, delta, TransactionType.set_balance, f"Admin set balance to {amount}", cb.from_user.id)
        else:
            delta = amount if action == 'increase' else -amount
            await BillingService(session).change_balance(reseller, delta, TransactionType(action), f"Admin manual {action}", cb.from_user.id)
    await state.clear(); await cb.message.answer("✅ Balance updated.", reply_markup=panel()); await cb.answer()

@router.message(Command("maintenance"))
async def maintenance_cmd(message: Message, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    await maintenance_screen(message, state)

@router.callback_query(F.data == "adm:maintenance")
async def maintenance_cb(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    await maintenance_screen(cb.message, state); await cb.answer()

async def maintenance_screen(message: Message, state: FSMContext) -> None:
    async with SessionLocal() as session:
        enabled = await SettingsRepository(session).get_bool("maintenance_mode")
    await state.set_state(MaintenanceMode.menu)
    await message.answer(f"Maintenance Mode\nCurrent status: {'ON' if enabled else 'OFF'}", reply_markup=maintenance_keyboard())

@router.callback_query(F.data.startswith("adm:maint:set:"))
async def maintenance_set(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    enabled = cb.data.endswith(":on")
    await state.update_data(maintenance_enabled=enabled); await state.set_state(MaintenanceMode.confirm)
    await cb.message.answer(f"Confirm changing maintenance mode to {'ON' if enabled else 'OFF'}.", reply_markup=confirm_keyboard("adm:maint:confirm", "adm:maintenance")); await cb.answer()

@router.callback_query(MaintenanceMode.confirm, F.data == "adm:maint:confirm")
async def maintenance_confirm(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    data = await state.get_data(); enabled = bool(data.get('maintenance_enabled'))
    async with SessionLocal() as session, session.begin(): await SettingsRepository(session).set_bool("maintenance_mode", enabled)
    await state.clear(); await cb.message.answer(f"✅ Maintenance mode is now {'ON' if enabled else 'OFF'}.", reply_markup=panel()); await cb.answer()

async def select_reseller(message: Message, state: FSMContext, target_state, prefix: str, title: str) -> None:
    async with SessionLocal() as session: resellers = await ResellerRepository(session).list()
    await state.set_state(target_state)
    await message.answer(title, reply_markup=resellers_keyboard(resellers, prefix))

@router.callback_query(F.data == "adm:inbounds")
async def inbound_start(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    await select_reseller(cb.message, state, InboundPermissions.select_reseller, "adm:inbsel", "Select reseller to manage inbound permissions."); await cb.answer()

@router.callback_query(F.data.startswith("adm:inbsel:"))
async def inbound_reseller(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    reseller_id = int(cb.data.rsplit(":",1)[1])
    try: inbounds = await client().get_inbounds()
    except MarzbanError as exc: await cb.message.answer(f"Could not load inbounds: {exc}"); await cb.answer(); return
    tags = sorted({str(i.get('tag') or i.get('remark') or i.get('protocol') or i) for i in inbounds})
    async with SessionLocal() as session: allowed = await InboundRepository(session).allowed_tags(reseller_id)
    all_allowed = len(allowed) == 0
    await state.update_data(reseller_id=reseller_id, tags=tags, selected=allowed, all_allowed=all_allowed); await state.set_state(InboundPermissions.edit)
    await cb.message.answer("Inbound permissions\nDefault is All Inbounds. Toggle custom entries or save All Inbounds.", reply_markup=inbound_keyboard(tags, allowed, all_allowed)); await cb.answer()

@router.callback_query(InboundPermissions.edit, F.data == "adm:inb:all")
async def inbound_all(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.update_data(selected=[], all_allowed=True)
    await cb.message.answer("All inbounds selected. Save to apply.", reply_markup=inbound_keyboard(data['tags'], [], True)); await cb.answer()

@router.callback_query(InboundPermissions.edit, F.data.startswith("adm:inb:toggle:"))
async def inbound_toggle(cb: CallbackQuery, state: FSMContext) -> None:
    tag = cb.data.split(":",3)[3]; data = await state.get_data(); selected = set(data.get('selected') or [])
    if data.get('all_allowed'): selected = set(data.get('tags') or [])
    selected.remove(tag) if tag in selected else selected.add(tag)
    data = await state.update_data(selected=list(selected), all_allowed=False)
    await cb.message.answer("Custom inbound selection updated. Save to apply.", reply_markup=inbound_keyboard(data['tags'], list(selected), False)); await cb.answer()

@router.callback_query(InboundPermissions.edit, F.data == "adm:inb:save")
async def inbound_save(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(InboundPermissions.confirm)
    await cb.message.answer("Confirm saving inbound permission changes.", reply_markup=confirm_keyboard("adm:inb:confirm", "adm:inbounds")); await cb.answer()

@router.callback_query(InboundPermissions.confirm, F.data == "adm:inb:confirm")
async def inbound_confirm(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    data = await state.get_data(); tags = [] if data.get('all_allowed') else list(data.get('selected') or [])
    async with SessionLocal() as session, session.begin(): await InboundRepository(session).set_allowed_tags(int(data['reseller_id']), tags)
    await state.clear(); await cb.message.answer("✅ Inbound permissions saved.", reply_markup=panel()); await cb.answer()

@router.callback_query(F.data == "adm:tx")
async def tx_start(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    await select_reseller(cb.message, state, TransactionBrowsing.select_reseller, "adm:txsel", "Select reseller to browse transactions."); await cb.answer()

@router.callback_query(F.data.startswith("adm:txsel:"))
async def tx_select(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    reseller_id = int(cb.data.rsplit(":",1)[1]); await state.set_state(TransactionBrowsing.browse)
    await cb.message.answer("Choose transaction type filter.", reply_markup=tx_filter_keyboard(reseller_id)); await cb.answer()

@router.callback_query(F.data.startswith("adm:txfilter:"))
async def tx_filter(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    _, _, rid, tx_type = cb.data.split(":"); await send_tx_page(cb.message, int(rid), tx_type, 0); await cb.answer()

@router.callback_query(F.data.startswith("adm:txpage:"))
async def tx_page(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    _, _, rid, tx_type, page = cb.data.split(":"); await send_tx_page(cb.message, int(rid), tx_type, int(page)); await cb.answer()

async def send_tx_page(message: Message, reseller_id: int, tx_type: str, page: int) -> None:
    enum_type = None if tx_type == 'all' else TransactionType(tx_type)
    async with SessionLocal() as session:
        reseller = await ResellerRepository(session).get(reseller_id)
        txs = await TransactionRepository(session).recent(reseller_id, enum_type, PAGE_SIZE + 1, page * PAGE_SIZE)
    visible, has_next = txs[:PAGE_SIZE], len(txs) > PAGE_SIZE
    lines = [f"Transactions for {reseller.display_name if reseller else reseller_id}", f"Filter: {tx_type}", f"Page: {page + 1}", ""]
    if not visible: lines.append("No transactions found for this selection.")
    for tx in visible:
        lines.append(f"#{tx.id} • {tx.type.value} • {tx.amount} • {tx.balance_before} → {tx.balance_after}\n{tx.created_at} • {tx.description or 'No description'}")
    await message.answer("\n".join(lines), reply_markup=tx_page_keyboard(reseller_id, tx_type, page, has_next))

@router.callback_query(F.data.startswith("adm:recharge:"))
async def recharge_action(callback: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    _, _, action, req_id = callback.data.split(":")
    await state.update_data(recharge_action=action, recharge_id=int(req_id))
    if action == "approve":
        await state.set_state(RechargeModeration.confirm)
        await callback.message.answer(f"Confirm approving recharge request #{req_id}.", reply_markup=confirm_keyboard("adm:recharge:confirm", "adm:panel"))
    else:
        await state.set_state(RechargeModeration.reject_reason)
        await callback.message.answer(f"Please enter rejection reason for recharge request #{req_id}.", reply_markup=admin_back_cancel("adm:panel"))
    await callback.answer()

@router.message(RechargeModeration.reject_reason)
async def reject_reason(message: Message, state: FSMContext) -> None:
    reason = (message.text or '').strip()
    if len(reason) < 3: await message.answer("Please provide a clear rejection reason (at least 3 characters)."); return
    await state.update_data(reason=reason); await state.set_state(RechargeModeration.confirm)
    await message.answer(f"Confirm rejecting recharge request.\nReason: {reason}", reply_markup=confirm_keyboard("adm:recharge:confirm", "adm:panel"))

@router.callback_query(RechargeModeration.confirm, F.data == "adm:recharge:confirm")
async def recharge_confirm(callback: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    data = await state.get_data(); action = data['recharge_action']; req_id = int(data['recharge_id'])
    async with SessionLocal() as session, session.begin():
        req = await RechargeRepository(session).get(req_id)
        if req is None or req.status != RechargeStatus.pending: await callback.answer("Request not available", show_alert=True); return
        reseller = await ResellerRepository(session).get(req.reseller_id)
        if reseller is None: return
        if action == "approve":
            await BillingService(session).change_balance(reseller, req.amount, TransactionType.recharge, f"Recharge request #{req.id}", callback.from_user.id)
            req.status = RechargeStatus.approved
            await callback.bot.send_message(reseller.telegram_id, f"✅ Recharge approved: {req.amount}")
        else:
            req.status = RechargeStatus.rejected; req.admin_reason = data.get('reason')
            await callback.bot.send_message(reseller.telegram_id, f"❌ Recharge rejected.\nReason: {req.admin_reason}")
    await state.clear(); await callback.message.answer("✅ Recharge decision saved.", reply_markup=panel()); await callback.answer()
