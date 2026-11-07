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
from app.services.keyboard_state import mark_reply_keyboard_sent, needs_reply_keyboard
from app.utils.formatting import format_toman, status_fa

router = Router()
DASHBOARD_BUTTON_TEXT = "🏠 داشبورد"


async def send_main_menu(message: Message, is_admin: bool, reseller: Reseller | None) -> None:
    """ONE message per /start or dashboard press. (The reply keyboard used to be re-sent each time as a separate
    near-empty message because it cannot share a message with the inline panel.)"""
    if is_admin:
        await message.answer("پنل مدیریت", reply_markup=panel())
        return
    if reseller is None:
        await message.answer("شما به عنوان ریسلر ثبت نشده‌اید.", reply_markup=dashboard_keyboard())
        return
    if reseller.status != ResellerStatus.active:
        await message.answer("حساب ریسلری شما غیرفعال است.", reply_markup=dashboard_keyboard())
        return
    user_id = message.from_user.id
    async with SessionLocal() as session, session.begin():
        count = await ResellerRepository(session).count_users(reseller.id)
        first_time = await needs_reply_keyboard(session, user_id, getattr(reseller, "created_at", None))
    if first_time:  # only a brand-new reseller needs the persistent «🏠 داشبورد» button, and only once
        await message.answer("🏠 دکمه‌ی «داشبورد» پایین صفحه فعال شد؛ هر زمان خواستید با آن به این منو برگردید.", reply_markup=dashboard_keyboard())
        async with SessionLocal() as session, session.begin():
            await mark_reply_keyboard_sent(session, user_id)
    await message.answer(f"داشبورد\nموجودی: {format_toman(reseller.balance)}\nقیمت هر گیگابایت: {format_toman(reseller.price_per_gb)}\nوضعیت: {status_fa(reseller.status)}\nکاربران ساخته‌شده: {count}", reply_markup=dashboard())


@router.message(CommandStart())
async def start(message: Message, state: FSMContext, is_admin: bool, reseller: Reseller | None) -> None:
    await state.clear()
    await send_main_menu(message, is_admin, reseller)


@router.message(F.text == DASHBOARD_BUTTON_TEXT)
async def dashboard_button(message: Message, state: FSMContext, is_admin: bool, reseller: Reseller | None) -> None:
    await state.clear()
    await send_main_menu(message, is_admin, reseller)
