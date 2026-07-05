from datetime import datetime, timezone
import logging
from decimal import Decimal, InvalidOperation
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from app.config import get_settings
from app.database.models import OperationType, Reseller
from app.database.repositories import InboundRepository, RechargeRepository
from app.database.session import SessionLocal
from app.keyboards.admin import recharge_actions
from app.keyboards.common import back_cancel, reseller_confirm
from app.keyboards.reseller import dashboard
from app.services.billing import BYTES_PER_GB, BillingService
from app.services.marzban import MarzbanClient, MarzbanError, create_payload_summary, extract_last_user_agent, on_hold_expire_duration, ownership_note, user_belongs_to_reseller
from app.services.reports import operation_report
from app.services.validators import valid_username
from app.states.reseller import CreateUser, Recharge, RenewUser
from app.utils.formatting import format_bytes_to_gb, format_remaining_time, format_toman, status_fa

router = Router()
logger = logging.getLogger(__name__)

USERNAME_EXISTS_OWN = "این نام کاربری قبلاً توسط شما ساخته شده است."
USERNAME_EXISTS_OTHER = "این نام کاربری از قبل وجود دارد. لطفاً نام دیگری انتخاب کنید."
USERNAME_EXISTS_NOT_YOURS = "این نام کاربری از قبل وجود دارد و متعلق به شما نیست."
MARZBAN_CREATE_FAILED = "ساخت اکانت در مرزبان ناموفق بود. لطفاً دوباره تلاش کنید یا با پشتیبانی تماس بگیرید."

def client() -> MarzbanClient:
    s = get_settings(); return MarzbanClient(s.marzban_base_url, s.marzban_username, s.marzban_password)

async def fetch_marzban_user(marzban: MarzbanClient, username: str) -> dict | None:
    try:
        user = await marzban.get_user(username)
        logger.info("Marzban fallback get_user found username=%s found=True", username)
        return user
    except MarzbanError as exc:
        if exc.status == 404:
            logger.info("Marzban fallback get_user found username=%s found=False", username)
            return None
        logger.warning("Marzban fallback get_user failed username=%s status=%s", username, exc.status)
        raise

async def create_user_safely(marzban: MarzbanClient, payload: dict, reseller_name: str) -> tuple[bool, str | None, MarzbanError | None]:
    username = str(payload["username"])
    existing = await fetch_marzban_user(marzban, username)
    if existing is not None:
        if user_belongs_to_reseller(existing, reseller_name):
            logger.info("Marzban create precheck username=%s result=exists_owned", username)
            return False, USERNAME_EXISTS_OWN, None
        logger.info("Marzban create precheck username=%s result=exists_other", username)
        return False, USERNAME_EXISTS_OTHER, None
    logger.info("Marzban create attempt username=%s", username)
    try:
        await marzban.create_user(payload)
        logger.info("Marzban create operation username=%s treated_as=success source=create_response", username)
        return True, None, None
    except MarzbanError as exc:
        logger.warning("Marzban create failed username=%s status=%s; checking created state", username, exc.status)
        try:
            created = await fetch_marzban_user(marzban, username)
        except MarzbanError:
            logger.info("Marzban create operation username=%s treated_as=failure source=fallback_error", username)
            return False, MARZBAN_CREATE_FAILED, exc
        if created is not None and user_belongs_to_reseller(created, reseller_name):
            logger.info("Marzban create operation username=%s treated_as=success source=fallback_get_user", username)
            return True, None, None
        if created is not None:
            logger.info("Marzban create operation username=%s treated_as=failure reason=exists_not_owned", username)
            return False, USERNAME_EXISTS_NOT_YOURS, exc
        logger.info("Marzban create operation username=%s treated_as=failure reason=not_found_after_failure", username)
        return False, MARZBAN_CREATE_FAILED, exc


async def send_create_debug_report(cb: CallbackQuery, username: str, reseller_name: str, exc: MarzbanError, payload: dict) -> None:
    summary = create_payload_summary(payload)
    logger.error("Marzban create failed after fallback username=%s reseller=%s status=%s body=%s payload_summary=%s. Create and get_user both failed when applicable; possible schema/payload rejection or Marzban internal API failure.", username, reseller_name, exc.status, exc.message, summary)
    text = (
        "گزارش دیباگ خطای ساخت مرزبان\n"
        f"نام کاربری: {username}\n"
        f"ریسلر: {reseller_name}\n"
        f"کد وضعیت: {exc.status}\n"
        f"پاسخ مرزبان: {str(exc.message)[:1500]}\n"
        f"خلاصه payload: {summary}\n"
        "پیشنهاد: مرزبان payload ساخت کاربر را رد کرده یا API مرزبان خطای داخلی داده است. ساخت و سپس بررسی کاربر را در پنل/API مرزبان مقایسه کنید."
    )
    for admin_id in get_settings().admin_ids:
        await cb.bot.send_message(admin_id, text)

@router.callback_query(F.data == "back")
async def back_to_dashboard(cb: CallbackQuery, state: FSMContext, reseller: Reseller | None) -> None:
    await state.clear()
    if reseller is None: await cb.answer("حساب ریسلری پیدا نشد.", show_alert=True); return
    await cb.message.answer("داشبورد", reply_markup=dashboard()); await cb.answer()

@router.callback_query(F.data == "res:help")
async def help_start(cb: CallbackQuery, reseller: Reseller | None) -> None:
    if reseller is None: await cb.answer("حساب ریسلری پیدا نشد.", show_alert=True); return
    await cb.message.answer("راهنما\n• ساخت کاربر: ساخت اکانت مرزبان و کسر هزینه از موجودی.\n• تمدید کاربر: افزودن حجم و زمان به اکانت متعلق به شما.\n• درخواست شارژ: ارسال مبلغ و رسید برای مدیر.\nبرای خروج از فرم‌ها از دکمه‌های لغو یا برگشت استفاده کنید."); await cb.answer()

@router.callback_query(F.data == "cancel")
async def cancel(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear(); await cb.message.answer("لغو شد."); await cb.answer()

@router.callback_query(F.data == "res:create")
async def create_start(cb: CallbackQuery, state: FSMContext, reseller: Reseller | None) -> None:
    if reseller is None: return
    await state.set_state(CreateUser.username); await cb.message.answer("نام کاربری را وارد کنید:", reply_markup=back_cancel()); await cb.answer()

@router.message(CreateUser.username)
async def create_username(message: Message, state: FSMContext) -> None:
    username = (message.text or "").strip()
    if not valid_username(username): await message.answer("نام کاربری نامعتبر است. فقط حروف کوچک انگلیسی، عدد و زیرخط مجاز است."); return
    await state.update_data(username=username); await state.set_state(CreateUser.gb); await message.answer("حجم را به گیگابایت وارد کنید:", reply_markup=back_cancel())

@router.message(CreateUser.gb)
async def create_gb(message: Message, state: FSMContext, reseller: Reseller) -> None:
    try: gb = int(message.text or "")
    except ValueError: await message.answer("یک عدد صحیح معتبر وارد کنید."); return
    if gb <= 0: await message.answer("حجم باید بیشتر از صفر باشد."); return
    cost = Decimal(gb) * reseller.price_per_gb
    await state.update_data(gb=gb, cost=str(cost)); await state.set_state(CreateUser.days); await message.answer("مدت اعتبار را به روز وارد کنید:", reply_markup=back_cancel())

@router.message(CreateUser.days)
async def create_days(message: Message, state: FSMContext) -> None:
    try: days = int(message.text or "")
    except ValueError: await message.answer("یک عدد صحیح معتبر وارد کنید."); return
    if days <= 0: await message.answer("مدت اعتبار باید بیشتر از صفر باشد."); return
    data = await state.update_data(days=days); await state.set_state(CreateUser.confirm)
    await message.answer(f"خلاصه ساخت اکانت\nنام کاربری: {data['username']}\nحجم: {data['gb']} گیگابایت\nمدت اعتبار پس از فعال‌سازی: {days} روز\nوضعیت اولیه: در انتظار اتصال\nهزینه: {format_toman(data['cost'])}\nآیا تایید می‌کنید؟", reply_markup=reseller_confirm("res:create:confirm", "res:create"))

@router.callback_query(CreateUser.confirm, F.data == "res:create:confirm")
async def create_confirm(cb: CallbackQuery, state: FSMContext, reseller: Reseller) -> None:
    data = await state.get_data(); username = data["username"]; gb = int(data["gb"]); days = int(data["days"])
    report = None
    async with SessionLocal() as session:
        async with session.begin():
            db_reseller = await session.get(type(reseller), reseller.id)
            cost = BillingService(session).calculate_cost(gb, db_reseller.price_per_gb)
            if db_reseller.balance < cost: await cb.message.answer("موجودی کافی نیست."); await state.clear(); await cb.answer(); return
            payload = {"username": username, "status": "on_hold", "data_limit": gb * BYTES_PER_GB, "on_hold_expire_duration": on_hold_expire_duration(days), "validity_days": days, "note": ownership_note(db_reseller.display_name)}
            marzban = client()
            allowed_tags = await InboundRepository(session).allowed_tags(db_reseller.id)
            try:
                payload = await marzban.build_create_payload(payload, allowed_tags)
                ok, error_message, create_error = await create_user_safely(marzban, payload, db_reseller.display_name)
            except (MarzbanError, ValueError):
                logger.exception("Marzban create preparation/precheck failed username=%s", username)
                await cb.message.answer(MARZBAN_CREATE_FAILED); await state.clear(); await cb.answer(); return
            if not ok:
                if create_error is not None:
                    await send_create_debug_report(cb, username, db_reseller.display_name, create_error, payload)
                await cb.message.answer(error_message or MARZBAN_CREATE_FAILED); await state.clear(); await cb.answer(); return
            log = await BillingService(session).charge_for_create_once(db_reseller, username, gb, days)
            if log is None:
                logger.info("Create charge skipped username=%s reseller_id=%s reason=already_recorded", username, db_reseller.id)
            else:
                logger.info("Create charge applied username=%s reseller_id=%s", username, db_reseller.id)
                report = operation_report(db_reseller, log)
    if report:
        for admin_id in get_settings().admin_ids: await cb.bot.send_message(admin_id, report)
    await state.clear(); await cb.message.answer(f"✅ اکانت با موفقیت ساخته شد.\nنام کاربری: {username}\nحجم: {format_bytes_to_gb(gb * BYTES_PER_GB)}\nمدت: {days} روز\nهزینه: {format_toman(cost)}"); await cb.answer()

@router.callback_query(F.data == "res:renew")
async def renew_start(cb: CallbackQuery, state: FSMContext, reseller: Reseller | None) -> None:
    if reseller is None: return
    await state.set_state(RenewUser.username); await cb.message.answer("نام کاربری اکانت برای تمدید را وارد کنید:", reply_markup=back_cancel()); await cb.answer()

@router.message(RenewUser.username)
async def renew_username(message: Message, state: FSMContext, reseller: Reseller) -> None:
    username = (message.text or "").strip()
    try: info = await client().get_user(username)
    except MarzbanError as exc: await message.answer(f"دریافت اطلاعات کاربر ممکن نشد: {exc}"); return
    if not user_belongs_to_reseller(info, reseller.display_name): await message.answer("این اکانت متعلق به شما نیست."); return
    await state.update_data(username=username, info=info); await state.set_state(RenewUser.confirm_user)
    await message.answer(f"اطلاعات اکانت\nنام کاربری: {username}\nحجم کل: {format_bytes_to_gb(info.get('data_limit'))}\nمصرف‌شده: {format_bytes_to_gb(info.get('used_traffic'))}\nباقی‌مانده: {format_bytes_to_gb(max(0, int(info.get('data_limit') or 0)-int(info.get('used_traffic') or 0)))}\nزمان باقی‌مانده: {format_remaining_time(info.get('expire'), info.get('remaining_seconds'), info.get('remaining_days'))}\nوضعیت: {status_fa(info.get('status'))}\nآخرین برنامه / User-Agent: {extract_last_user_agent(info)}", reply_markup=reseller_confirm("res:renew:user_confirm", "res:renew", "✅ تایید تمدید"))

@router.callback_query(RenewUser.confirm_user, F.data == "res:renew:user_confirm")
async def renew_confirm_user(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(RenewUser.gb); await cb.message.answer("حجم اضافه را به گیگابایت وارد کنید:", reply_markup=back_cancel()); await cb.answer()

@router.message(RenewUser.gb)
async def renew_gb(message: Message, state: FSMContext) -> None:
    try: gb = int(message.text or "")
    except ValueError: await message.answer("یک عدد معتبر وارد کنید."); return
    if gb <= 0: await message.answer("حجم باید بیشتر از صفر باشد."); return
    await state.update_data(gb=gb); await state.set_state(RenewUser.days); await message.answer("روزهای اضافه را وارد کنید:", reply_markup=back_cancel())

@router.message(RenewUser.days)
async def renew_days(message: Message, state: FSMContext, reseller: Reseller) -> None:
    try: days = int(message.text or "")
    except ValueError: await message.answer("یک عدد معتبر وارد کنید."); return
    if days <= 0: await message.answer("روز باید بیشتر از صفر باشد."); return
    data = await state.update_data(days=days); cost = Decimal(data["gb"]) * reseller.price_per_gb
    await state.set_state(RenewUser.confirm); await message.answer(f"خلاصه تمدید\nنام کاربری: {data['username']}\nحجم اضافه: {data['gb']} گیگابایت\nزمان اضافه: {days} روز\nهزینه: {format_toman(cost)}\nآیا تمدید تایید شود؟", reply_markup=reseller_confirm("res:renew:confirm", "res:renew", "✅ تایید تمدید"))

@router.callback_query(RenewUser.confirm, F.data == "res:renew:confirm")
async def renew_confirm(cb: CallbackQuery, state: FSMContext, reseller: Reseller) -> None:
    data = await state.get_data(); username = data["username"]; gb = int(data["gb"]); days = int(data["days"])
    async with SessionLocal() as session, session.begin():
        db_reseller = await session.get(type(reseller), reseller.id); cost = BillingService(session).calculate_cost(gb, db_reseller.price_per_gb)
        if db_reseller.balance < cost: await cb.message.answer("موجودی کافی نیست."); await state.clear(); await cb.answer(); return
        try:
            user = await client().get_user(username)
            if not user_belongs_to_reseller(user, db_reseller.display_name): await cb.message.answer("این اکانت متعلق به شما نیست."); await state.clear(); await cb.answer(); return
            base_expire = max(int(user.get("expire") or 0), int(datetime.now(timezone.utc).timestamp()))
            await client().modify_user(username, {"data_limit": int(user.get("data_limit") or 0) + gb * BYTES_PER_GB, "expire": base_expire + days * 86400})
        except MarzbanError as exc: await cb.message.answer(f"خطای مرزبان: {exc}"); await state.clear(); await cb.answer(); return
        log = await BillingService(session).charge_for_operation(db_reseller, username, OperationType.renew, gb, days); report = operation_report(db_reseller, log)
    for admin_id in get_settings().admin_ids: await cb.bot.send_message(admin_id, report)
    await state.clear(); await cb.message.answer("✅ اکانت با موفقیت تمدید شد."); await cb.answer()

@router.callback_query(F.data == "res:recharge")
async def recharge_start(cb: CallbackQuery, state: FSMContext, reseller: Reseller | None) -> None:
    if reseller is None: return
    await state.set_state(Recharge.amount); await cb.message.answer("مبلغ شارژ را به تومان وارد کنید:", reply_markup=back_cancel()); await cb.answer()

@router.message(Recharge.amount)
async def recharge_amount(message: Message, state: FSMContext) -> None:
    try: amount = Decimal(message.text or "")
    except InvalidOperation: await message.answer("مبلغ معتبر وارد کنید."); return
    await state.update_data(amount=str(amount)); await state.set_state(Recharge.receipt); await message.answer("رسید پرداخت را به صورت عکس یا متن ارسال کنید:", reply_markup=back_cancel())

@router.message(Recharge.receipt)
async def recharge_receipt(message: Message, state: FSMContext, reseller: Reseller) -> None:
    data = await state.get_data(); file_id = message.photo[-1].file_id if message.photo else None; text = message.caption or message.text
    async with SessionLocal() as session, session.begin(): req = await RechargeRepository(session).create(reseller.id, Decimal(data["amount"]), file_id, text)
    caption = f"درخواست شارژ #{req.id}\nریسلر: {reseller.display_name}\nمبلغ: {format_toman(req.amount)}\nرسید: {text or 'تصویر'}"
    for admin_id in get_settings().admin_ids:
        if file_id: await message.bot.send_photo(admin_id, file_id, caption=caption, reply_markup=recharge_actions(req.id))
        else: await message.bot.send_message(admin_id, caption, reply_markup=recharge_actions(req.id))
    await state.clear(); await message.answer("درخواست شارژ برای مدیر ارسال شد.")
