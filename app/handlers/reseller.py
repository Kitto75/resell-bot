from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from app.config import get_settings
from app.database.models import OperationType, Reseller
from app.database.repositories import RechargeRepository
from app.database.session import SessionLocal
from app.keyboards.admin import recharge_actions
from app.keyboards.common import back_cancel
from app.keyboards.reseller import dashboard
from app.services.billing import BYTES_PER_GB, BillingService, InsufficientBalanceError
from app.services.marzban import MarzbanClient, MarzbanError
from app.services.reports import operation_report
from app.services.validators import valid_username
from app.states.reseller import CreateUser, Recharge, RenewUser

router = Router()

def client() -> MarzbanClient:
    s = get_settings(); return MarzbanClient(s.marzban_base_url, s.marzban_username, s.marzban_password)


@router.callback_query(F.data == "back")
async def back_to_dashboard(cb: CallbackQuery, state: FSMContext, reseller: Reseller | None) -> None:
    await state.clear()
    if reseller is None:
        await cb.answer("Reseller account not found.", show_alert=True)
        return
    await cb.message.answer("Dashboard", reply_markup=dashboard())
    await cb.answer()

@router.callback_query(F.data == "res:help")
async def help_start(cb: CallbackQuery, reseller: Reseller | None) -> None:
    if reseller is None:
        await cb.answer("Reseller account not found.", show_alert=True)
        return
    await cb.message.answer(
        "Help\n"
        "• Create User: add a new Marzban user and charge your balance.\n"
        "• Renew User: add traffic and days to an existing user.\n"
        "• Request Balance: send a top-up amount and receipt to admins.\n"
        "Use ❌ Cancel to leave any active form."
    )
    await cb.answer()

@router.callback_query(F.data == "cancel")
async def cancel(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear(); await cb.message.answer("Cancelled."); await cb.answer()

@router.callback_query(F.data == "res:create")
async def create_start(cb: CallbackQuery, state: FSMContext, reseller: Reseller | None) -> None:
    if reseller is None: return
    await state.set_state(CreateUser.username); await cb.message.answer("Enter username:", reply_markup=back_cancel()); await cb.answer()

@router.message(CreateUser.username)
async def create_username(message: Message, state: FSMContext) -> None:
    username = (message.text or "").strip()
    if not valid_username(username): await message.answer("Invalid username. Use lowercase letters, numbers and underscore only."); return
    await state.update_data(username=username); await state.set_state(CreateUser.gb); await message.answer("Enter traffic in GB:", reply_markup=back_cancel())

@router.message(CreateUser.gb)
async def create_gb(message: Message, state: FSMContext, reseller: Reseller) -> None:
    try: gb = int(message.text or "")
    except ValueError: await message.answer("Enter a valid whole number."); return
    if gb <= 0: await message.answer("GB must be positive."); return
    cost = Decimal(gb) * reseller.price_per_gb
    await state.update_data(gb=gb, cost=str(cost)); await state.set_state(CreateUser.days); await message.answer("Enter validity in days:", reply_markup=back_cancel())

@router.message(CreateUser.days)
async def create_days(message: Message, state: FSMContext) -> None:
    try: days = int(message.text or "")
    except ValueError: await message.answer("Enter a valid whole number."); return
    if days <= 0: await message.answer("Days must be positive."); return
    data = await state.update_data(days=days)
    await state.set_state(CreateUser.confirm); await message.answer(f"Confirm create {data['username']}\nGB: {data['gb']}\nDays: {days}\nCost: {data['cost']}\nSend YES to confirm.", reply_markup=back_cancel())

@router.message(CreateUser.confirm)
async def create_confirm(message: Message, state: FSMContext, reseller: Reseller) -> None:
    if (message.text or "").upper() != "YES": await message.answer("Send YES to confirm or Cancel."); return
    data = await state.get_data(); username = data["username"]; gb = int(data["gb"]); days = int(data["days"])
    async with SessionLocal() as session, session.begin():
        db_reseller = await session.get(type(reseller), reseller.id)
        if db_reseller is None: return
        cost = BillingService(session).calculate_cost(gb, db_reseller.price_per_gb)
        if db_reseller.balance < cost: await message.answer("Insufficient balance."); await state.clear(); return
        payload = {"username": username, "status": "on_hold", "data_limit": gb * BYTES_PER_GB, "expire": int((datetime.now(timezone.utc) + timedelta(days=days)).timestamp()), "note": f"Created by reseller: {db_reseller.display_name} ({db_reseller.telegram_id})"}
        try: await client().create_user(payload)
        except MarzbanError as exc: await message.answer(f"Marzban error: {exc}"); await state.clear(); raise
        log = await BillingService(session).charge_for_operation(db_reseller, username, OperationType.create, gb, days)
        report = operation_report(db_reseller, log)
    for admin_id in get_settings().admin_ids: await message.bot.send_message(admin_id, report)
    await state.clear(); await message.answer("✅ User created successfully.")

@router.callback_query(F.data == "res:renew")
async def renew_start(cb: CallbackQuery, state: FSMContext, reseller: Reseller | None) -> None:
    if reseller is None: return
    await state.set_state(RenewUser.username); await cb.message.answer("Enter username to renew:", reply_markup=back_cancel()); await cb.answer()

@router.message(RenewUser.username)
async def renew_username(message: Message, state: FSMContext) -> None:
    username = (message.text or "").strip()
    try: info = await client().get_user(username)
    except MarzbanError as exc: await message.answer(f"Cannot retrieve user: {exc}"); return
    await state.update_data(username=username, info=info); await state.set_state(RenewUser.confirm_user)
    await message.answer(f"Username: {username}\nTotal quota: {info.get('data_limit')}\nUsed traffic: {info.get('used_traffic')}\nRemaining days: {info.get('remaining_days')}\nExpiration: {info.get('expire')}\nStatus: {info.get('status')}\nLast online: {info.get('online_at')}\nUser-Agent: {info.get('last_user_agent')}\nSend YES to continue.", reply_markup=back_cancel())

@router.message(RenewUser.confirm_user)
async def renew_confirm_user(message: Message, state: FSMContext) -> None:
    if (message.text or "").upper() != "YES": await message.answer("Send YES to continue."); return
    await state.set_state(RenewUser.gb); await message.answer("Additional GB:", reply_markup=back_cancel())

@router.message(RenewUser.gb)
async def renew_gb(message: Message, state: FSMContext) -> None:
    try: gb = int(message.text or "")
    except ValueError: await message.answer("Enter a valid number."); return
    await state.update_data(gb=gb); await state.set_state(RenewUser.days); await message.answer("Additional days:", reply_markup=back_cancel())

@router.message(RenewUser.days)
async def renew_days(message: Message, state: FSMContext, reseller: Reseller) -> None:
    try: days = int(message.text or "")
    except ValueError: await message.answer("Enter a valid number."); return
    data = await state.update_data(days=days); cost = Decimal(data["gb"]) * reseller.price_per_gb
    await state.set_state(RenewUser.confirm); await message.answer(f"Renew {data['username']}\nGB: {data['gb']}\nDays: {days}\nCost: {cost}\nSend YES to confirm.", reply_markup=back_cancel())

@router.message(RenewUser.confirm)
async def renew_confirm(message: Message, state: FSMContext, reseller: Reseller) -> None:
    if (message.text or "").upper() != "YES": await message.answer("Send YES to confirm."); return
    data = await state.get_data(); username = data["username"]; gb = int(data["gb"]); days = int(data["days"])
    async with SessionLocal() as session, session.begin():
        db_reseller = await session.get(type(reseller), reseller.id)
        if db_reseller is None: return
        cost = BillingService(session).calculate_cost(gb, db_reseller.price_per_gb)
        if db_reseller.balance < cost: await message.answer("Insufficient balance."); await state.clear(); return
        try:
            user = await client().get_user(username)
            payload = {"data_limit": int(user.get("data_limit") or 0) + gb * BYTES_PER_GB, "expire": int(user.get("expire") or datetime.now(timezone.utc).timestamp()) + days * 86400}
            await client().modify_user(username, payload)
        except MarzbanError as exc: await message.answer(f"Marzban error: {exc}"); await state.clear(); raise
        log = await BillingService(session).charge_for_operation(db_reseller, username, OperationType.renew, gb, days)
        report = operation_report(db_reseller, log)
    for admin_id in get_settings().admin_ids: await message.bot.send_message(admin_id, report)
    await state.clear(); await message.answer("✅ User renewed successfully.")

@router.callback_query(F.data == "res:recharge")
async def recharge_start(cb: CallbackQuery, state: FSMContext, reseller: Reseller | None) -> None:
    if reseller is None: return
    await state.set_state(Recharge.amount); await cb.message.answer("Enter recharge amount:", reply_markup=back_cancel()); await cb.answer()

@router.message(Recharge.amount)
async def recharge_amount(message: Message, state: FSMContext) -> None:
    try: amount = Decimal(message.text or "")
    except InvalidOperation: await message.answer("Enter a valid amount."); return
    await state.update_data(amount=str(amount)); await state.set_state(Recharge.receipt); await message.answer("Send payment receipt image or text:", reply_markup=back_cancel())

@router.message(Recharge.receipt)
async def recharge_receipt(message: Message, state: FSMContext, reseller: Reseller) -> None:
    data = await state.get_data(); file_id = message.photo[-1].file_id if message.photo else None; text = message.caption or message.text
    async with SessionLocal() as session, session.begin():
        req = await RechargeRepository(session).create(reseller.id, Decimal(data["amount"]), file_id, text)
    caption = f"Recharge request #{req.id}\nReseller: {reseller.display_name}\nAmount: {req.amount}\nReceipt: {text or 'image'}"
    for admin_id in get_settings().admin_ids:
        if file_id: await message.bot.send_photo(admin_id, file_id, caption=caption, reply_markup=recharge_actions(req.id))
        else: await message.bot.send_message(admin_id, caption, reply_markup=recharge_actions(req.id))
    await state.clear(); await message.answer("Request sent to admin.")
