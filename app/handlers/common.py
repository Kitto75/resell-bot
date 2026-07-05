from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message
from app.database.models import Reseller, ResellerStatus
from app.database.repositories import ResellerRepository
from app.database.session import SessionLocal
from app.keyboards.admin import panel
from app.keyboards.reseller import dashboard
from app.utils.formatting import format_toman, status_fa

router = Router()

@router.message(CommandStart())
async def start(message: Message, is_admin: bool, reseller: Reseller | None) -> None:
    if is_admin:
        await message.answer("پنل مدیریت", reply_markup=panel()); return
    if reseller is None:
        await message.answer("شما به عنوان ریسلر ثبت نشده‌اید."); return
    if reseller.status != ResellerStatus.active:
        await message.answer("حساب ریسلری شما غیرفعال است."); return
    async with SessionLocal() as session:
        count = await ResellerRepository(session).count_users(reseller.id)
    await message.answer(f"داشبورد\nموجودی: {format_toman(reseller.balance)}\nقیمت هر گیگابایت: {format_toman(reseller.price_per_gb)}\nوضعیت: {status_fa(reseller.status)}\nکاربران ساخته‌شده: {count}", reply_markup=dashboard())
