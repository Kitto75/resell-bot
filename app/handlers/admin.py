from decimal import Decimal
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from app.config import get_settings
from app.database.models import RechargeStatus, TransactionType
from app.database.repositories import RechargeRepository, ResellerRepository, SettingsRepository
from app.database.session import SessionLocal
from app.services.billing import BillingService

router = Router()

@router.message(Command("add_reseller"))
async def add_reseller(message: Message, is_admin: bool) -> None:
    if not is_admin: return
    parts = (message.text or "").split(maxsplit=4)
    if len(parts) != 5:
        await message.answer("Usage: /add_reseller <telegram_id> <balance> <price_per_gb> <display_name>"); return
    async with SessionLocal() as session, session.begin():
        await ResellerRepository(session).add(int(parts[1]), parts[4], Decimal(parts[2]), Decimal(parts[3]))
    await message.answer("Reseller added.")

@router.message(Command("maintenance"))
async def maintenance(message: Message, is_admin: bool) -> None:
    if not is_admin: return
    parts = (message.text or "").split()
    enabled = len(parts) > 1 and parts[1].lower() in {"on", "enable", "1"}
    async with SessionLocal() as session, session.begin(): await SettingsRepository(session).set_bool("maintenance_mode", enabled)
    await message.answer(f"Maintenance mode {'enabled' if enabled else 'disabled'}.")


@router.callback_query(F.data.in_({"adm:resellers", "adm:tx", "adm:maintenance", "adm:inbounds"}))
async def admin_panel_action(callback: CallbackQuery, is_admin: bool) -> None:
    if not is_admin:
        await callback.answer("Admins only.", show_alert=True)
        return
    actions = {
        "adm:resellers": "Use /add_reseller <telegram_id> <balance> <price_per_gb> <display_name> to add a reseller.",
        "adm:tx": "Transaction browsing is not available from the inline panel yet.",
        "adm:maintenance": "Use /maintenance on or /maintenance off to change maintenance mode.",
        "adm:inbounds": "Inbound management is not available from the inline panel yet.",
    }
    await callback.message.answer(actions[callback.data])
    await callback.answer()

@router.callback_query(F.data.startswith("adm:recharge:"))
async def recharge_action(callback: CallbackQuery, is_admin: bool) -> None:
    if not is_admin: return
    _, _, action, req_id = callback.data.split(":")
    async with SessionLocal() as session, session.begin():
        req = await RechargeRepository(session).get(int(req_id))
        if req is None or req.status != RechargeStatus.pending:
            await callback.answer("Request not available", show_alert=True); return
        reseller = await ResellerRepository(session).get(req.reseller_id)
        if reseller is None: return
        if action == "approve":
            await BillingService(session).change_balance(reseller, req.amount, TransactionType.recharge, f"Recharge request #{req.id}", callback.from_user.id)
            req.status = RechargeStatus.approved
            await callback.bot.send_message(reseller.telegram_id, f"✅ Recharge approved: {req.amount}")
        else:
            req.status = RechargeStatus.rejected
            await callback.bot.send_message(reseller.telegram_id, "❌ Recharge rejected.")
    await callback.answer("Done")
