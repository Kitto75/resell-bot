from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from app.database.models import Reseller, ResellerStatus
from app.database.repositories import ResellerRepository
from app.database.session import SessionLocal
from app.keyboards.admin import panel
from app.keyboards.common import dashboard_keyboard
from app.keyboards.reseller import dashboard
from app.utils.formatting import format_toman, status_fa

router = Router()
DASHBOARD_BUTTON_TEXT = "🏠 داشبورد"


async def send_main_menu(message: Message, is_admin: bool, reseller: Reseller | None) -> None:
    if is_admin:
        await message.answer("پنل مدیریت", reply_markup=dashboard_keyboard())
        await message.answer("پنل مدیریت", reply_markup=panel())
        return
    if reseller is None:
        await message.answer("شما به عنوان ریسلر ثبت نشده‌اید.", reply_markup=dashboard_keyboard())
        return
    if reseller.status != ResellerStatus.active:
        await message.answer("حساب ریسلری شما غیرفعال است.", reply_markup=dashboard_keyboard())
        return
    async with SessionLocal() as session:
        count = await ResellerRepository(session).count_users(reseller.id)
    await message.answer("داشبورد", reply_markup=dashboard_keyboard())
    await message.answer(f"داشبورد\nموجودی: {format_toman(reseller.balance)}\nقیمت هر گیگابایت: {format_toman(reseller.price_per_gb)}\nوضعیت: {status_fa(reseller.status)}\nکاربران ساخته‌شده: {count}", reply_markup=dashboard())


@router.message(CommandStart())
async def start(message: Message, state: FSMContext, is_admin: bool, reseller: Reseller | None) -> None:
    await state.clear()
    await send_main_menu(message, is_admin, reseller)


@router.message(F.text == DASHBOARD_BUTTON_TEXT)
async def dashboard_button(message: Message, state: FSMContext, is_admin: bool, reseller: Reseller | None) -> None:
    await state.clear()
    await send_main_menu(message, is_admin, reseller)
