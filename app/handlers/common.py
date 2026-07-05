from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message
from app.database.models import Reseller, ResellerStatus
from app.database.repositories import ResellerRepository
from app.database.session import SessionLocal
from app.keyboards.admin import panel
from app.keyboards.reseller import dashboard

router = Router()

@router.message(CommandStart())
async def start(message: Message, is_admin: bool, reseller: Reseller | None) -> None:
    if is_admin:
        await message.answer("Admin panel", reply_markup=panel()); return
    if reseller is None:
        await message.answer("You are not registered as a reseller."); return
    if reseller.status != ResellerStatus.active:
        await message.answer("Your reseller account is disabled."); return
    async with SessionLocal() as session:
        count = await ResellerRepository(session).count_users(reseller.id)
    await message.answer(f"Dashboard\nBalance: {reseller.balance}\nPrice/GB: {reseller.price_per_gb}\nStatus: {reseller.status.value}\nCreated users: {count}", reply_markup=dashboard())
