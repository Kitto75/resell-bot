import asyncio
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from decimal import Decimal, InvalidOperation
import logging
from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery, FSInputFile, Message
from sqlalchemy.exc import IntegrityError
from app.config import get_settings
from app.database.models import RechargeStatus, ResellerStatus, TransactionType
from app.database.repositories import CreatedUserRepository, InboundRepository, RechargeRepository, ResellerRepository, SettingsRepository, TransactionRepository
from app.database.session import SessionLocal
from app.keyboards.admin import group_access_keyboard, reseller_card_keyboard, reseller_delete_keyboard, reseller_hard_delete_keyboard, reseller_list_keyboard, report_period_keyboard, report_scope_keyboard, admin_back_cancel, backup_keyboard, balance_action_keyboard, confirm_keyboard, destructive_confirm_keyboard, edit_field_keyboard, inbound_keyboard, maintenance_keyboard, panel, recharge_reject_keyboard, renewal_settings_keyboard, resellers_keyboard, resellers_menu, status_keyboard, reseller_bulk_actions_keyboard, reseller_bulk_confirm_keyboard, reseller_user_actions_keyboard, reseller_users_page_keyboard, telegram_account_keyboard, telegram_accounts_actions, tx_filter_keyboard, tx_page_keyboard
from app.services.qr import make_subscription_qr_png
from app.services.datetime import jalali_datetime_text, jalali_filename_datetime
from app.services.bulk_users import build_plan, execute_plan, fetch_plan
from app.services.reseller_view import PAGE_SIZE as RESELLER_PAGE_SIZE, ResellerRow, delete_choice_text, group_access_text, group_summary, hard_delete_confirm_text, reseller_card_text, reseller_list_text
from app.services.pdf_report import PdfFontError, PERIOD_LABELS, build_report_pdf, collect_report_data
from app.services.reports import transactions_page_text
from app.services.validators import valid_username
from app.services.backup import get_backup_status, send_database_backup, set_backup_enabled, set_backup_interval, sqlite_backup_supported
from app.services.billing import BYTES_PER_GB, BillingService
from app.services.marzban import MarzbanClient, MarzbanError, create_payload_summary, extract_last_user_agent, marzban_payload_debug_structure, on_hold_expire_duration
from app.services.renewal import RenewalMode, calculate_renewal, renewal_mode_confirmation_text, renewal_mode_fa
from app.utils.formatting import format_bytes_to_gb, format_remaining_time, format_toman, status_fa
from app.states.admin import AddReseller, AdminCreateMarzbanUser, AdminDeleteMarzbanUser, AdminDisableMarzbanUser, AdminEnableMarzbanUser, AdminRenewMarzbanUser, AdminResellerUsers, BackupSettings, BalanceEdit, EditReseller, InboundPermissions, MaintenanceMode, RechargeModeration, TelegramAccountManagement, TransactionBrowsing

router = Router()
PAGE_SIZE = 5
RESELLER_USERS_PAGE_SIZE = 10
RESELLER_USERS_BULK_BATCH_SIZE = 100
RESELLER_USERS_FAILED_SAMPLE_LIMIT = 10
logger = logging.getLogger(__name__)


def client() -> MarzbanClient:
    s = get_settings(); return MarzbanClient(s.marzban_base_url, s.marzban_username, s.marzban_password)

def money(text: str | None) -> Decimal | None:
    try: value = Decimal((text or '').strip())
    except InvalidOperation: return None
    return value if value >= 0 else None



def _primary_subscription_url(user: dict | None) -> str | None:
    if not isinstance(user, dict):
        return None
    for key in ("subscription_url", "subscription", "sub_url"):
        value = user.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for key in ("subscription_urls", "subscriptions"):
        value = user.get(key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str) and item.strip():
                    return item.strip()
                if isinstance(item, dict):
                    url = item.get("url") or item.get("subscription_url")
                    if isinstance(url, str) and url.strip():
                        return url.strip()
    return None


async def _send_admin_create_success(message: Message, username: str, subscription_url: str | None) -> None:
    if not subscription_url:
        await message.answer(
            f"✅ کاربر با موفقیت ساخته شد.\n\n👤 نام کاربری:\n{username}\n\nلینک اشتراک در پاسخ پنل پیدا نشد؛ لطفاً از پنل بررسی کنید.",
            reply_markup=panel(),
        )
        return
    await message.answer(
        f"✅ کاربر با موفقیت ساخته شد.\n\n👤 نام کاربری:\n{username}\n\n🔗 لینک اشتراک:\n{subscription_url}",
        reply_markup=panel(),
    )
    qr_path = None
    try:
        qr_path = make_subscription_qr_png(subscription_url, username)
        await message.answer_photo(FSInputFile(qr_path, filename=f"{username}_subscription.png"), caption="📱 QR Code\nکد را با کلاینت VPN اسکن کنید.")
    except Exception:
        logger.exception("Failed to generate/send admin subscription QR username=%s", username)
        await message.answer("لینک اشتراک ارسال شد، اما ساخت QR Code ناموفق بود.")
    finally:
        if qr_path is not None:
            qr_path.unlink(missing_ok=True)


def _admin_user_info_text(info: dict) -> str:
    limit = int(info.get("data_limit") or 0)
    used = int(info.get("used_traffic") or 0)
    return (
        f"اطلاعات اکانت\n"
        f"نام کاربری: {info.get('username') or 'نامشخص'}\n"
        f"حجم کل: {format_bytes_to_gb(limit)}\n"
        f"مصرف‌شده: {format_bytes_to_gb(used)}\n"
        f"باقی‌مانده: {format_bytes_to_gb(max(0, limit-used))}\n"
        f"زمان باقی‌مانده: {format_remaining_time(info.get('expire'), info.get('remaining_seconds'), info.get('remaining_days'))}\n"
        f"وضعیت: {status_fa(info.get('status'))}\n"
        f"آخرین برنامه / User-Agent: {extract_last_user_agent(info)}"
    )


def _safe_marzban_error_message(action: str, exc: MarzbanError) -> str:
    if exc.status == 404:
        return "کاربر موردنظر در پنل پیدا نشد. نام کاربری را بررسی کنید."
    return f"{action} در پنل ناموفق بود. جزئیات امن خطا در لاگ ثبت شد."

async def show_panel(message: Message) -> None:
    await message.answer("پنل مدیریت\nیک گزینه را انتخاب کنید.", reply_markup=panel())


@router.message(Command("debug_user_agent"))
async def debug_user_agent_command(message: Message, is_admin: bool) -> None:
    if not is_admin:
        return
    username = (message.text or "").replace("/debug_user_agent", "", 1).strip()
    if not username:
        await message.answer("Usage: /debug_user_agent username")
        return
    try:
        info = await client().get_user_with_activity(username)
    except MarzbanError:
        logger.exception("Admin Marzban user-agent debug fetch failed username=%s", username)
        await message.answer("دریافت اطلاعات کاربر از پنل ناموفق بود. لاگ‌ها را بررسی کنید.")
        return
    user_agent = extract_last_user_agent(info)
    logger.info(
        "Manual Marzban user-agent debug username=%s extracted=%s safe_payload_structure=%s",
        username,
        user_agent,
        marzban_payload_debug_structure(info),
    )
    await message.answer(
        "Debug logged safely.\n"
        f"username: {username}\n"
        f"extracted User-Agent: {user_agent}\n"
        "Check bot logs for: Manual Marzban user-agent debug"
    )

async def show_backup_menu(message: Message) -> None:
    if not sqlite_backup_supported():
        await message.answer("بکاپ خودکار فعلاً فقط برای SQLite پشتیبانی می‌شود.", reply_markup=panel())
        return
    enabled, interval, last_time = await get_backup_status()
    status = "فعال" if enabled else "غیرفعال"
    await message.answer(
        f"💾 بکاپ\n\nوضعیت فعلی: {status}\nفاصله زمانی فعلی: {interval} دقیقه\nآخرین بکاپ: {last_time or 'ثبت نشده'}",
        reply_markup=backup_keyboard(enabled),
    )

@router.callback_query(F.data == "adm:backup")
async def backup_menu_cb(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin:
        await cb.answer("فقط مدیر مجاز است.", show_alert=True); return
    await state.clear(); await show_backup_menu(cb.message); await cb.answer()

@router.callback_query(F.data == "adm:backup:enable")
async def backup_enable_cb(cb: CallbackQuery, is_admin: bool) -> None:
    if not is_admin:
        await cb.answer("فقط مدیر مجاز است.", show_alert=True); return
    if not sqlite_backup_supported():
        await cb.message.answer("بکاپ خودکار فعلاً فقط برای SQLite پشتیبانی می‌شود.", reply_markup=panel()); await cb.answer(); return
    await set_backup_enabled(True)
    from app.services.scheduler import get_scheduler, schedule_backup_job
    scheduler = get_scheduler()
    if scheduler is not None:
        _, interval, _ = await get_backup_status(); schedule_backup_job(scheduler, cb.bot, interval)
    await cb.message.answer("✅ بکاپ خودکار فعال شد.")
    await show_backup_menu(cb.message); await cb.answer()

@router.callback_query(F.data == "adm:backup:disable")
async def backup_disable_cb(cb: CallbackQuery, is_admin: bool) -> None:
    if not is_admin:
        await cb.answer("فقط مدیر مجاز است.", show_alert=True); return
    await set_backup_enabled(False)
    from app.services.scheduler import get_scheduler, remove_backup_job
    scheduler = get_scheduler()
    if scheduler is not None:
        remove_backup_job(scheduler)
    await cb.message.answer("✅ بکاپ خودکار غیرفعال شد.")
    await show_backup_menu(cb.message); await cb.answer()

@router.callback_query(F.data == "adm:backup:interval")
async def backup_interval_cb(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin:
        await cb.answer("فقط مدیر مجاز است.", show_alert=True); return
    await state.set_state(BackupSettings.interval)
    await cb.message.answer("فاصله زمانی بکاپ خودکار را به دقیقه وارد کنید.", reply_markup=admin_back_cancel("adm:backup")); await cb.answer()

@router.message(BackupSettings.interval)
async def backup_interval_value(message: Message, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    try:
        minutes = int((message.text or '').strip())
    except ValueError:
        await message.answer("یک عدد صحیح معتبر وارد کنید."); return
    if minutes < 1:
        await message.answer("فاصله زمانی باید حداقل ۱ دقیقه باشد."); return
    await set_backup_interval(minutes)
    enabled, _, _ = await get_backup_status()
    from app.services.scheduler import get_scheduler, schedule_backup_job
    scheduler = get_scheduler()
    if enabled and scheduler is not None:
        schedule_backup_job(scheduler, message.bot, minutes)
    await state.clear(); await message.answer(f"✅ فاصله زمانی بکاپ روی {minutes} دقیقه تنظیم شد.", reply_markup=panel())

@router.callback_query(F.data == "adm:backup:now")
async def backup_now_cb(cb: CallbackQuery, is_admin: bool) -> None:
    if not is_admin:
        await cb.answer("فقط مدیر مجاز است.", show_alert=True); return
    ok = await send_database_backup(cb.bot)
    await cb.message.answer("✅ بکاپ ارسال شد." if ok else "ارسال بکاپ ناموفق بود. مسیر پایگاه داده و لاگ‌ها را بررسی کنید.")
    await cb.answer()

@router.callback_query(F.data == "adm:panel")
async def panel_cb(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: await cb.answer("فقط مدیر مجاز است.", show_alert=True); return
    await state.clear(); await show_panel(cb.message); await cb.answer()


@router.callback_query(F.data == "adm:renewal_settings")
async def renewal_settings_cb(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: await cb.answer("فقط مدیر مجاز است.", show_alert=True); return
    async with SessionLocal() as session:
        mode = await SettingsRepository(session).get_renewal_mode()
    await state.clear()
    await cb.message.answer(
        f"⚙️ تنظیمات تمدید\n\nحالت فعلی: تمدید {renewal_mode_fa(mode)}\n\nدر حالت افزایشی، حجم و روز جدید به مقدار قبلی اضافه می‌شود.\n\nدر حالت ریست و جایگزینی، مصرف کاربر صفر می‌شود و حجم و روز جدید جایگزین دوره قبلی می‌شود.",
        reply_markup=renewal_settings_keyboard(),
    )
    await cb.answer()

@router.callback_query(F.data.startswith("adm:renewal:set:"))
async def renewal_settings_set_cb(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: await cb.answer("فقط مدیر مجاز است.", show_alert=True); return
    mode = cb.data.rsplit(":", 1)[1]
    async with SessionLocal() as session, session.begin():
        await SettingsRepository(session).set_renewal_mode(mode)
    await state.clear()
    await cb.message.answer(f"✅ حالت تمدید روی تمدید {renewal_mode_fa(mode)} تنظیم شد.", reply_markup=panel())
    await cb.answer()

@router.callback_query(F.data == "adm:mb:create")
async def admin_create_marzban_start(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin:
        await cb.answer("فقط مدیر مجاز است.", show_alert=True); return
    await state.clear(); await state.set_state(AdminCreateMarzbanUser.username)
    await cb.message.answer("ساخت کاربر (مدیر)\nنام کاربری را وارد کنید:", reply_markup=admin_back_cancel()); await cb.answer()


@router.message(AdminCreateMarzbanUser.username)
async def admin_create_marzban_username(message: Message, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    username = (message.text or "").strip()
    if not valid_username(username):
        await message.answer("نام کاربری نامعتبر است. فقط حروف کوچک انگلیسی، عدد و زیرخط مجاز است."); return
    await state.update_data(username=username); await state.set_state(AdminCreateMarzbanUser.gb)
    await message.answer("حجم را به گیگابایت وارد کنید:", reply_markup=admin_back_cancel("adm:mb:create"))


@router.message(AdminCreateMarzbanUser.gb)
async def admin_create_marzban_gb(message: Message, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    try: gb = int(message.text or "")
    except ValueError: await message.answer("یک عدد صحیح معتبر وارد کنید."); return
    if gb <= 0: await message.answer("حجم باید بیشتر از صفر باشد."); return
    await state.update_data(gb=gb); await state.set_state(AdminCreateMarzbanUser.days)
    await message.answer("مدت اعتبار را به روز وارد کنید:", reply_markup=admin_back_cancel("adm:mb:create"))


@router.message(AdminCreateMarzbanUser.days)
async def admin_create_marzban_days(message: Message, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    try: days = int(message.text or "")
    except ValueError: await message.answer("یک عدد صحیح معتبر وارد کنید."); return
    if days <= 0: await message.answer("مدت اعتبار باید بیشتر از صفر باشد."); return
    data = await state.update_data(days=days); await state.set_state(AdminCreateMarzbanUser.confirm)
    await message.answer(
        f"خلاصه ساخت کاربر (مدیر)\nنام کاربری: {data['username']}\nحجم: {data['gb']} گیگابایت\nمدت اعتبار پس از فعال‌سازی: {days} روز\nوضعیت اولیه: در انتظار اتصال\nهزینه/کسر موجودی: ندارد\nآیا تایید می‌کنید؟",
        reply_markup=confirm_keyboard("adm:mb:create:confirm", "adm:mb:create"),
    )


@router.callback_query(AdminCreateMarzbanUser.confirm, F.data == "adm:mb:create:confirm")
async def admin_create_marzban_confirm(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    data = await state.get_data(); username = data["username"]; gb = int(data["gb"]); days = int(data["days"])
    marzban = client()
    payload = {"username": username, "status": "on_hold", "data_limit": gb * BYTES_PER_GB, "on_hold_expire_duration": on_hold_expire_duration(days), "validity_days": days, "note": f"created by admin {cb.from_user.id}"}
    try:
        try:
            await marzban.get_user(username)
            await cb.message.answer("این نام کاربری از قبل در پنل وجود دارد. لطفاً نام دیگری انتخاب کنید.", reply_markup=panel()); await state.clear(); await cb.answer(); return
        except MarzbanError as exc:
            if exc.status != 404: raise
        payload = await marzban.build_create_payload(payload)
        logger.info("Admin Marzban create sanitized payload summary=%s", create_payload_summary(payload))
        await marzban.create_user(payload)
        created_user = await marzban.get_user(username)
    except (MarzbanError, ValueError) as exc:
        logger.exception("Admin Marzban create failed username=%s payload_summary=%s", username, create_payload_summary(payload))
        await cb.message.answer("ساخت کاربر در پنل ناموفق بود. جزئیات امن خطا در لاگ ثبت شد.", reply_markup=panel()); await state.clear(); await cb.answer(); return
    subscription_url = marzban.absolute_subscription_url(_primary_subscription_url(created_user))
    await state.clear(); await _send_admin_create_success(cb.message, username, subscription_url); await cb.answer()


@router.callback_query(F.data == "adm:mb:renew")
async def admin_renew_marzban_start(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin:
        await cb.answer("فقط مدیر مجاز است.", show_alert=True); return
    await state.clear(); await state.set_state(AdminRenewMarzbanUser.username)
    await cb.message.answer("تمدید کاربر (مدیر)\nنام کاربری اکانت را وارد کنید:", reply_markup=admin_back_cancel()); await cb.answer()


@router.message(AdminRenewMarzbanUser.username)
async def admin_renew_marzban_username(message: Message, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    username = (message.text or "").strip()
    try: info = await client().get_user_with_activity(username)
    except MarzbanError:
        logger.exception("Admin Marzban renew fetch failed username=%s", username)
        await message.answer("دریافت اطلاعات کاربر از پنل ممکن نشد. نام کاربری یا لاگ‌ها را بررسی کنید."); return
    await state.update_data(username=username, info=info); await state.set_state(AdminRenewMarzbanUser.confirm_user)
    await message.answer(_admin_user_info_text(info), reply_markup=confirm_keyboard("adm:mb:renew:user_confirm", "adm:mb:renew"))


@router.callback_query(AdminRenewMarzbanUser.confirm_user, F.data == "adm:mb:renew:user_confirm")
async def admin_renew_marzban_confirm_user(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    await state.set_state(AdminRenewMarzbanUser.gb); await cb.message.answer("حجم اضافه را به گیگابایت وارد کنید:", reply_markup=admin_back_cancel("adm:mb:renew")); await cb.answer()


@router.message(AdminRenewMarzbanUser.gb)
async def admin_renew_marzban_gb(message: Message, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    try: gb = int(message.text or "")
    except ValueError: await message.answer("یک عدد معتبر وارد کنید."); return
    if gb <= 0: await message.answer("حجم باید بیشتر از صفر باشد."); return
    await state.update_data(gb=gb); await state.set_state(AdminRenewMarzbanUser.days)
    await message.answer("روزهای اضافه را وارد کنید:", reply_markup=admin_back_cancel("adm:mb:renew"))


@router.message(AdminRenewMarzbanUser.days)
async def admin_renew_marzban_days(message: Message, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    try: days = int(message.text or "")
    except ValueError: await message.answer("یک عدد معتبر وارد کنید."); return
    if days <= 0: await message.answer("روز باید بیشتر از صفر باشد."); return
    data = await state.update_data(days=days); await state.set_state(AdminRenewMarzbanUser.confirm)
    async with SessionLocal() as session:
        mode = await SettingsRepository(session).get_renewal_mode()
    await message.answer(f"خلاصه تمدید توسط مدیر\nنام کاربری: {data['username']}\nحجم واردشده: {data['gb']} گیگابایت\nزمان واردشده: {days} روز\nهزینه/کسر موجودی: ندارد\n\n{renewal_mode_confirmation_text(mode)}\n\nآیا تمدید تایید شود؟", reply_markup=confirm_keyboard("adm:mb:renew:confirm", "adm:mb:renew"))


@router.callback_query(AdminRenewMarzbanUser.confirm, F.data == "adm:mb:renew:confirm")
async def admin_renew_marzban_confirm(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    data = await state.get_data(); username = data["username"]; gb = int(data["gb"]); days = int(data["days"])
    marzban = client()
    try:
        async with SessionLocal() as session:
            mode = await SettingsRepository(session).get_renewal_mode()
        user = await marzban.get_user(username)
        calc = calculate_renewal(user, gb, days, mode)
        reset_succeeded = False
        if calc.mode is RenewalMode.replace:
            await marzban.reset_user_usage(username)
            reset_succeeded = True
        try:
            await marzban.modify_user(username, {"data_limit": calc.resulting_data_limit, "expire": calc.resulting_expire})
        except MarzbanError:
            if reset_succeeded:
                logger.exception("Admin Marzban renewal partially applied: usage reset succeeded but update failed admin_id=%s username=%s", cb.from_user.id, username)
            raise
        logger.info("Admin Marzban renewal mode=%s admin_id=%s username=%s entered_gb=%s entered_days=%s previous_data_limit=%s previous_expire=%s resulting_data_limit=%s resulting_expire=%s usage_reset_succeeded=%s", calc.mode.value, cb.from_user.id, username, gb, days, calc.previous_data_limit, calc.previous_expire, calc.resulting_data_limit, calc.resulting_expire, reset_succeeded)
    except MarzbanError:
        logger.exception("Admin Marzban renew failed username=%s gb=%s days=%s", username, gb, days)
        await cb.message.answer("تمدید کاربر در پنل ناموفق بود. جزئیات امن خطا در لاگ ثبت شد.", reply_markup=panel()); await state.clear(); await cb.answer(); return
    await state.clear(); await cb.message.answer("✅ اکانت با موفقیت تمدید شد. هیچ موجودی ریسلری تغییر نکرد.", reply_markup=panel()); await cb.answer()


@router.callback_query(F.data == "adm:mb:disable")
async def admin_disable_marzban_start(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin:
        await cb.answer("فقط مدیر مجاز است.", show_alert=True); return
    await state.clear(); await state.set_state(AdminDisableMarzbanUser.username)
    await cb.message.answer("غیرفعال‌سازی موقت کاربر (مدیر)\nنام کاربری اکانت را وارد کنید:", reply_markup=admin_back_cancel()); await cb.answer()


@router.message(AdminDisableMarzbanUser.username)
async def admin_disable_marzban_username(message: Message, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    username = (message.text or "").strip()
    try:
        info = await client().get_user_with_activity(username)
    except MarzbanError as exc:
        logger.exception("Admin Marzban disable fetch failed username=%s status=%s", username, exc.status)
        await message.answer(_safe_marzban_error_message("دریافت اطلاعات کاربر", exc)); return
    await state.update_data(username=username, info=info); await state.set_state(AdminDisableMarzbanUser.confirm)
    await message.answer(_admin_user_info_text(info) + "\n\nآیا غیرفعال‌سازی موقت این کاربر را تایید می‌کنید؟\nهزینه/کسر موجودی: ندارد", reply_markup=confirm_keyboard("adm:mb:disable:confirm", "adm:mb:disable"))


@router.callback_query(AdminDisableMarzbanUser.confirm, F.data == "adm:mb:disable:confirm")
async def admin_disable_marzban_confirm(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    data = await state.get_data(); username = data["username"]
    try:
        await client().disable_user(username)
    except MarzbanError as exc:
        logger.exception("Admin Marzban disable failed admin_id=%s username=%s status=%s", cb.from_user.id, username, exc.status)
        await cb.message.answer(_safe_marzban_error_message("غیرفعال‌سازی کاربر", exc), reply_markup=panel()); await state.clear(); await cb.answer(); return
    logger.info("Admin disabled Marzban user admin_id=%s username=%s", cb.from_user.id, username)
    await state.clear(); await cb.message.answer("✅ کاربر با موفقیت به‌صورت موقت غیرفعال شد. هیچ موجودی ریسلری تغییر نکرد.", reply_markup=panel()); await cb.answer()


@router.callback_query(F.data == "adm:mb:enable")
async def admin_enable_marzban_start(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin:
        await cb.answer("فقط مدیر مجاز است.", show_alert=True); return
    await state.clear(); await state.set_state(AdminEnableMarzbanUser.username)
    await cb.message.answer("فعال‌سازی دوباره کاربر (مدیر)\nنام کاربری اکانت را وارد کنید:", reply_markup=admin_back_cancel()); await cb.answer()


@router.message(AdminEnableMarzbanUser.username)
async def admin_enable_marzban_username(message: Message, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    username = (message.text or "").strip()
    try:
        info = await client().get_user_with_activity(username)
    except MarzbanError as exc:
        logger.exception("Admin Marzban enable fetch failed username=%s status=%s", username, exc.status)
        await message.answer(_safe_marzban_error_message("دریافت اطلاعات کاربر", exc)); return
    await state.update_data(username=username, info=info); await state.set_state(AdminEnableMarzbanUser.confirm)
    await message.answer(_admin_user_info_text(info) + "\n\nآیا فعال‌سازی دوباره این کاربر را تایید می‌کنید؟\nهزینه/کسر موجودی: ندارد", reply_markup=confirm_keyboard("adm:mb:enable:confirm", "adm:mb:enable"))


@router.callback_query(AdminEnableMarzbanUser.confirm, F.data == "adm:mb:enable:confirm")
async def admin_enable_marzban_confirm(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    data = await state.get_data(); username = data["username"]
    try:
        await client().enable_user(username)
    except MarzbanError as exc:
        logger.exception("Admin Marzban enable failed admin_id=%s username=%s status=%s", cb.from_user.id, username, exc.status)
        await cb.message.answer(_safe_marzban_error_message("فعال‌سازی کاربر", exc), reply_markup=panel()); await state.clear(); await cb.answer(); return
    logger.info("Admin enabled Marzban user admin_id=%s username=%s", cb.from_user.id, username)
    await state.clear(); await cb.message.answer("✅ کاربر با موفقیت فعال شد. تنظیمات قبلی کاربر و موجودی ریسلرها تغییر نکرد.", reply_markup=panel()); await cb.answer()


@router.callback_query(F.data == "adm:mb:delete")
async def admin_delete_marzban_start(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin:
        await cb.answer("فقط مدیر مجاز است.", show_alert=True); return
    await state.clear(); await state.set_state(AdminDeleteMarzbanUser.username)
    await cb.message.answer("حذف کاربر (مدیر)\nنام کاربری اکانت را وارد کنید:", reply_markup=admin_back_cancel()); await cb.answer()


@router.message(AdminDeleteMarzbanUser.username)
async def admin_delete_marzban_username(message: Message, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    username = (message.text or "").strip()
    try:
        info = await client().get_user_with_activity(username)
    except MarzbanError as exc:
        logger.exception("Admin Marzban delete fetch failed username=%s status=%s", username, exc.status)
        await message.answer(_safe_marzban_error_message("دریافت اطلاعات کاربر", exc)); return
    await state.update_data(username=username, info=info); await state.set_state(AdminDeleteMarzbanUser.confirm)
    await message.answer(
        _admin_user_info_text(info)
        + "\n\n⚠️ هشدار مهم: حذف این کاربر دائمی است و از داخل ربات قابل بازگردانی نیست.\n"
        + "اگر مطمئن هستید دکمه «🗑 حذف قطعی» را بزنید.\nهزینه/کسر موجودی: ندارد",
        reply_markup=destructive_confirm_keyboard("adm:mb:delete:confirm", "adm:mb:delete"),
    )


@router.callback_query(AdminDeleteMarzbanUser.confirm, F.data == "adm:mb:delete:confirm")
async def admin_delete_marzban_confirm(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    data = await state.get_data(); username = data["username"]
    # Admin Marzban deletion is a management-only action: it must not refund,
    # recharge, create balance transactions, or mutate reseller balances.
    try:
        await client().delete_user(username)
    except MarzbanError as exc:
        logger.exception("Admin Marzban delete failed admin_id=%s username=%s status=%s", cb.from_user.id, username, exc.status)
        await cb.message.answer(_safe_marzban_error_message("حذف کاربر", exc), reply_markup=panel()); await state.clear(); await cb.answer(); return
    logger.info("Admin deleted Marzban user admin_id=%s username=%s", cb.from_user.id, username)
    await state.clear(); await cb.message.answer("✅ کاربر با موفقیت حذف شد. هیچ موجودی ریسلری تغییر نکرد.", reply_markup=panel()); await cb.answer()




STATUS_LINE_ICONS = {"active": "🟢", "on_hold": "🕒", "disabled": "⛔", "expired": "⌛", "limited": "📉"}
_BULK_RUNNING: set[int] = set()


async def _all_usernames(session, reseller_id: int) -> list[str]:
    repo, names, offset = CreatedUserRepository(session), [], 0
    while True:
        batch = await repo.list_usernames_by_reseller(reseller_id, limit=500, offset=offset)
        if not batch: return names
        names.extend(batch); offset += 500


def _status_breakdown_lines(by_status: dict[str, int], missing: int) -> list[str]:
    order = ["active", "on_hold", "disabled", "expired", "limited"]
    lines = [f"{STATUS_LINE_ICONS.get(st, '▫️')} {status_fa(st)}: {by_status[st]}" for st in order if by_status.get(st)]
    lines += [f"▫️ {st}: {n}" for st, n in by_status.items() if st not in order and n]
    if missing: lines.append(f"❓ در پنل پیدا نشد: {missing}")
    return lines


async def edit_or_answer(cb: CallbackQuery, text: str, reply_markup=None) -> None:
    """Navigate inside the same message when possible instead of flooding the chat."""
    try:
        await cb.message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as exc:
        if "not modified" in str(exc).lower(): return
        await cb.message.answer(text, reply_markup=reply_markup)


async def _show_reseller_users(message: Message, state: FSMContext, reseller_id: int, page: int = 0) -> None:
    async with SessionLocal() as session:
        reseller = await ResellerRepository(session).get(reseller_id)
        if reseller is None:
            await message.answer("ریسلر پیدا نشد یا حذف شده است.", reply_markup=panel())
            await state.clear()
            return
        usernames = await _all_usernames(session, reseller_id)
        name = reseller.display_name
    await state.set_state(AdminResellerUsers.browse)
    await state.update_data(reseller_id=reseller_id)
    if not usernames:
        await message.answer(f"👥 یوزرهای ریسلر\n\n👤 ریسلر: {name}\n\nاین ریسلر هنوز هیچ یوزری نساخته است.", reply_markup=admin_back_cancel("adm:reseller_users"))
        return
    lines = ["👥 یوزرهای ریسلر", "━━━━━━━━━━━━━━", f"👤 ریسلر: {name}", f"👥 اکانت‌های ثبت‌شده: {len(usernames)}", ""]
    disable_count = enable_count = None
    try:
        users = await client().list_users_by_usernames(usernames)
        plan_d, plan_e = build_plan("disable", usernames, users), build_plan("enable", usernames, users)
        lines += ["📊 وضعیت فعلی در پنل:"] + _status_breakdown_lines(plan_d.by_status, len(plan_d.missing))
        disable_count, enable_count = plan_d.change_count, plan_e.change_count
    except MarzbanError:
        logger.exception("Could not read reseller users status from panel reseller_id=%s", reseller_id)
        lines.append("⚠️ دریافت وضعیت اکانت‌ها از پنل ممکن نشد؛ عملیات گروهی همچنان قابل اجراست.")
    lines += ["", "اعداد داخل دکمه‌ها نشان می‌دهد هر عملیات روی چند اکانت اثر دارد."]
    await message.answer("\n".join(lines), reply_markup=reseller_bulk_actions_keyboard(reseller_id, disable_count, enable_count))


def _bulk_action_label(action: str) -> str:
    return "غیرفعال‌سازی همه یوزرها" if action == "disable" else "فعال‌سازی همه یوزرها"


def _parse_bulk_callback(data: str | None) -> tuple[int, str] | None:
    try:
        _, _, _, reseller_id_text, action = (data or "").split(":")
        reseller_id = int(reseller_id_text)
    except ValueError:
        return None
    return (reseller_id, action) if action in {"enable", "disable"} else None


@router.callback_query(F.data == "adm:reseller_users")
async def reseller_users_start(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin:
        await cb.answer("فقط مدیر مجاز است.", show_alert=True); return
    await select_reseller(cb.message, state, AdminResellerUsers.select_reseller, "adm:rusel", "ریسلر موردنظر برای مدیریت یوزرها را انتخاب کنید.")
    await cb.answer()


@router.callback_query(F.data.startswith("adm:rusel:"))
async def reseller_users_selected(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin:
        await cb.answer("فقط مدیر مجاز است.", show_alert=True); return
    try:
        reseller_id = int(cb.data.rsplit(":", 1)[1])
    except (ValueError, AttributeError):
        await cb.answer("داده نامعتبر است.", show_alert=True); return
    await cb.answer()
    await _show_reseller_users(cb.message, state, reseller_id, 0)


@router.callback_query(F.data.startswith("adm:ru:bulk:"))
async def reseller_users_bulk_action(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin:
        await cb.answer("فقط مدیر مجاز است.", show_alert=True); return
    parsed = _parse_bulk_callback(cb.data)
    if parsed is None:
        await cb.answer("داده نامعتبر است.", show_alert=True); return
    reseller_id, action = parsed
    await cb.answer()
    async with SessionLocal() as session:
        reseller = await ResellerRepository(session).get(reseller_id)
        if reseller is None:
            await cb.message.answer("ریسلر پیدا نشد یا حذف شده است.", reply_markup=panel()); await state.clear(); return
        usernames = await _all_usernames(session, reseller_id)
        name = reseller.display_name
    try:
        plan = await fetch_plan(client(), action, usernames)
    except MarzbanError:
        logger.exception("Bulk plan fetch failed reseller_id=%s action=%s", reseller_id, action)
        await cb.message.answer("❌ دریافت وضعیت اکانت‌ها از پنل ممکن نشد. کمی بعد دوباره تلاش کنید.", reply_markup=admin_back_cancel(f"adm:rusel:{reseller_id}")); return
    label = _bulk_action_label(action)
    lines = ["⚠️ تایید عملیات گروهی", "━━━━━━━━━━━━━━", f"👤 ریسلر: {name}", f"⚙️ عملیات: {label}", ""]
    if plan.change_count == 0:
        lines.append("✅ هیچ اکانتی نیاز به این تغییر ندارد." + (f"\n❓ {len(plan.missing)} اکانت در پنل پیدا نشد." if plan.missing else ""))
        await cb.message.answer("\n".join(lines), reply_markup=admin_back_cancel(f"adm:rusel:{reseller_id}")); return
    lines.append(f"🎯 تغییر می‌کند: {plan.change_count} اکانت")
    on_hold = sum(1 for u in plan.targets if str(getattr(u.get("status"), "value", u.get("status"))) == "on_hold")
    if action == "disable" and on_hold: lines.append(f"   (شامل {on_hold} اکانت «در انتظار اتصال»)")
    if plan.unchanged_count: lines.append(f"⏭ بدون تغییر: {plan.unchanged_count} (وضعیتشان با این عملیات نمی‌خواند)")
    if plan.missing: lines.append(f"❓ در پنل پیدا نشد: {len(plan.missing)}")
    lines += ["", "موجودی ریسلر تغییر نمی‌کند و تراکنش مالی ایجاد نمی‌شود."]
    await cb.message.answer("\n".join(lines), reply_markup=reseller_bulk_confirm_keyboard(reseller_id, action))


@router.callback_query(F.data.startswith("adm:ru:bulk_confirm:"))
async def reseller_users_bulk_confirm(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin:
        await cb.answer("فقط مدیر مجاز است.", show_alert=True); return
    parsed = _parse_bulk_callback(cb.data)
    if parsed is None:
        await cb.answer("داده نامعتبر است.", show_alert=True); return
    reseller_id, action = parsed
    if reseller_id in _BULK_RUNNING:
        await cb.answer("این عملیات همین حالا در حال انجام است.", show_alert=True); return
    _BULK_RUNNING.add(reseller_id)
    try:
        await cb.answer("⏳ در حال انجام...")
        async with SessionLocal() as session:
            reseller = await ResellerRepository(session).get(reseller_id)
            if reseller is None:
                await cb.message.answer("ریسلر پیدا نشد یا حذف شده است.", reply_markup=panel()); await state.clear(); return
            usernames = await _all_usernames(session, reseller_id)
            reseller_name = reseller.display_name
        progress = await cb.message.answer(f"⏳ در حال {_bulk_action_label(action)} برای {len(usernames)} اکانت...")
        try:
            plan = await fetch_plan(client(), action, usernames)
            result = await execute_plan(client(), plan)
        except MarzbanError:
            logger.exception("Admin reseller bulk action failed admin_id=%s reseller_id=%s action=%s", cb.from_user.id, reseller_id, action)
            await progress.edit_text("❌ ارتباط با پنل برقرار نشد. عملیات انجام نشد؛ کمی بعد دوباره تلاش کنید.", reply_markup=reseller_bulk_actions_keyboard(reseller_id)); return
        lines = ["✅ عملیات گروهی انجام شد", "━━━━━━━━━━━━━━", f"👤 ریسلر: {reseller_name}", f"⚙️ عملیات: {_bulk_action_label(action)}", "", f"🎯 تغییر کرد: {result.changed}"]
        if plan.unchanged_count: lines.append(f"⏭ نیاز به تغییر نداشت: {plan.unchanged_count}")
        if plan.missing: lines.append(f"❓ در پنل پیدا نشد: {len(plan.missing)} (احتمالاً از پنل حذف شده‌اند)")
        if result.failed: lines.append(f"⚠️ ناموفق: {len(result.failed)}")
        shown = (result.failed or [])[:RESELLER_USERS_FAILED_SAMPLE_LIMIT] if result.failed else plan.missing[:RESELLER_USERS_FAILED_SAMPLE_LIMIT]
        if shown: lines += ["", "نمونه:", *[f"- {name}" for name in shown]]
        lines += ["", "💰 موجودی ریسلر تغییر نکرد."]
        logger.info("Admin reseller bulk action completed admin_id=%s reseller_id=%s action=%s total=%s changed=%s missing=%s failed=%s", cb.from_user.id, reseller_id, action, plan.total, result.changed, len(plan.missing), len(result.failed))
        await state.clear()
        await progress.edit_text("\n".join(lines), reply_markup=reseller_bulk_actions_keyboard(reseller_id))
    finally:
        _BULK_RUNNING.discard(reseller_id)


@router.callback_query(F.data.startswith("adm:ru:page:"))
async def reseller_users_page(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin:
        await cb.answer("فقط مدیر مجاز است.", show_alert=True); return
    try:
        _, _, _, reseller_id_text, _page_text = cb.data.split(":")
        reseller_id = int(reseller_id_text)
    except (ValueError, AttributeError):
        await cb.answer("داده نامعتبر است.", show_alert=True); return
    await _show_reseller_users(cb.message, state, reseller_id, 0)
    await cb.answer("این بخش اکنون فقط عملیات گروهی دارد.")


@router.callback_query(F.data.startswith("adm:ru:user:"))
async def reseller_user_details(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin:
        await cb.answer("فقط مدیر مجاز است.", show_alert=True); return
    await cb.answer("در این بخش انتخاب تکی یوزر غیرفعال شده است.", show_alert=True)


@router.callback_query(F.data.startswith("adm:ru:act:"))
async def reseller_user_action(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin:
        await cb.answer("فقط مدیر مجاز است.", show_alert=True); return
    await cb.answer("در این بخش فقط عملیات گروهی مجاز است.", show_alert=True)

@router.callback_query(F.data == "adm:cancel")
async def cancel(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    await state.clear(); await cb.message.answer("لغو شد. به پنل مدیریت برگشتید.", reply_markup=panel()); await cb.answer()

@router.message(Command("add_reseller"))
async def add_reseller_cmd(message: Message, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    await state.clear(); await state.set_state(AddReseller.telegram_id)
    await message.answer("شناسه عددی تلگرام ریسلر را وارد کنید.", reply_markup=admin_back_cancel())

@router.callback_query(F.data == "adm:resellers")
async def resellers_menu_cb(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    await state.clear(); await cb.message.answer("مدیریت ریسلرها", reply_markup=resellers_menu()); await cb.answer()

@router.callback_query(F.data == "adm:add_reseller")
async def add_reseller_start(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: await cb.answer("فقط مدیر مجاز است.", show_alert=True); return
    await state.clear(); await state.set_state(AddReseller.telegram_id)
    await cb.message.answer("افزودن ریسلر\nشناسه عددی تلگرام ریسلر را وارد کنید.", reply_markup=admin_back_cancel()); await cb.answer()

@router.message(AddReseller.telegram_id)
async def add_tid(message: Message, state: FSMContext) -> None:
    try: telegram_id = int((message.text or '').strip())
    except ValueError: await message.answer("شناسه تلگرام باید عدد صحیح باشد. دوباره وارد کنید."); return
    await state.update_data(telegram_id=telegram_id); await state.set_state(AddReseller.balance)
    await message.answer("موجودی اولیه را به تومان وارد کنید.", reply_markup=admin_back_cancel("adm:add_reseller"))

@router.message(AddReseller.balance)
async def add_balance(message: Message, state: FSMContext) -> None:
    value = money(message.text)
    if value is None: await message.answer("موجودی اولیه باید عدد مثبت یا صفر باشد."); return
    await state.update_data(balance=str(value)); await state.set_state(AddReseller.price)
    await message.answer("قیمت هر گیگابایت را به تومان وارد کنید.", reply_markup=admin_back_cancel("adm:add_reseller"))

@router.message(AddReseller.price)
async def add_price(message: Message, state: FSMContext) -> None:
    value = money(message.text)
    if value is None or value <= 0: await message.answer("قیمت هر گیگابایت باید بیشتر از صفر باشد."); return
    await state.update_data(price=str(value)); await state.set_state(AddReseller.display_name)
    await message.answer("نام نمایشی را وارد کنید.", reply_markup=admin_back_cancel("adm:add_reseller"))

@router.message(AddReseller.display_name)
async def add_name(message: Message, state: FSMContext) -> None:
    name = (message.text or '').strip()
    if len(name) < 2: await message.answer("نام نمایشی باید حداقل ۲ کاراکتر باشد."); return
    data = await state.update_data(display_name=name); await state.set_state(AddReseller.confirm)
    await message.answer(f"تایید ریسلر جدید:\n\nشناسه تلگرام: {data['telegram_id']}\nموجودی اولیه: {format_toman(data['balance'])}\nقیمت هر گیگابایت: {format_toman(data['price'])}\nنام نمایشی: {data['display_name']}", reply_markup=confirm_keyboard("adm:add:confirm", "adm:add_reseller"))

@router.callback_query(AddReseller.confirm, F.data == "adm:add:confirm")
async def add_confirm(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    data = await state.get_data()
    try:
        async with SessionLocal() as session, session.begin():
            await ResellerRepository(session).add(int(data['telegram_id']), data['display_name'], Decimal(data['balance']), Decimal(data['price']))
    except IntegrityError:
        await cb.message.answer("ریسلری با این شناسه تلگرام وجود دارد. تغییری ذخیره نشد.", reply_markup=panel()); await state.clear(); await cb.answer(); return
    await state.clear(); await cb.message.answer("✅ ریسلر ساخته شد.", reply_markup=panel()); await cb.answer()



async def _reseller_row(session, reseller) -> ResellerRow:
    repo = ResellerRepository(session)
    accounts = await repo.telegram_accounts(reseller.id)
    return ResellerRow(
        id=reseller.id, name=reseller.display_name, status=str(getattr(reseller.status, "value", reseller.status)),
        balance=reseller.balance, price_per_gb=reseller.price_per_gb, users=await repo.count_users(reseller.id),
        groups=sorted(await InboundRepository(session).allowed_tags(reseller.id)),
        telegram_ids=[a.telegram_id for a in accounts] or [reseller.telegram_id],
        created_text=jalali_datetime_text(reseller.created_at, get_settings().timezone)[:10] if reseller.created_at else "",
    )


async def _show_reseller_list(cb: CallbackQuery, view: str, page: int) -> None:
    archived_view = view == "r"
    async with SessionLocal() as session:
        everyone = await ResellerRepository(session).list(include_archived=True)
        archived = [r for r in everyone if r.status == ResellerStatus.archived]
        current = archived if archived_view else [r for r in everyone if r.status != ResellerStatus.archived]
        page = max(0, min(page, (max(len(current), 1) - 1) // RESELLER_PAGE_SIZE))
        rows = [await _reseller_row(session, r) for r in current[page * RESELLER_PAGE_SIZE:(page + 1) * RESELLER_PAGE_SIZE]]
    await edit_or_answer(cb, reseller_list_text(rows, page, len(current), archived_view), reseller_list_keyboard(rows, page, len(current), archived_view, len(archived)))


async def _show_reseller_card(cb: CallbackQuery, reseller_id: int) -> None:
    async with SessionLocal() as session:
        reseller = await ResellerRepository(session).get(reseller_id)
        if reseller is None:
            await cb.answer("ریسلر پیدا نشد یا حذف شده است.", show_alert=True); return
        row = await _reseller_row(session, reseller)
    await edit_or_answer(cb, reseller_card_text(row), reseller_card_keyboard(row.id, row.status, "r" if row.status == "archived" else "a"))


@router.callback_query(F.data == "adm:reseller_list")
async def reseller_list_cb(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    await state.clear(); await _show_reseller_list(cb, "a", 0); await cb.answer()


@router.callback_query(F.data.regexp(r"^adm:rl:[ar]:\d+$"))
async def reseller_list_page(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    _, _, view, page = cb.data.split(":")
    await state.clear(); await _show_reseller_list(cb, view, int(page)); await cb.answer()


@router.callback_query(F.data.regexp(r"^adm:rc:\d+$"))
async def reseller_card_cb(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    await state.clear(); await _show_reseller_card(cb, int(cb.data.rsplit(":", 1)[1])); await cb.answer()


@router.callback_query(F.data.regexp(r"^adm:rc:st:\d+:(active|disabled)$"))
async def reseller_quick_status(cb: CallbackQuery, is_admin: bool) -> None:
    if not is_admin: return
    _, _, _, rid, status = cb.data.split(":")
    async with SessionLocal() as session, session.begin():
        reseller = await ResellerRepository(session).get(int(rid))
        if reseller is None:
            await cb.answer("ریسلر پیدا نشد.", show_alert=True); return
        reseller.status = ResellerStatus(status)
    logger.info("Admin changed reseller status admin_id=%s reseller_id=%s status=%s", cb.from_user.id, rid, status)
    await _show_reseller_card(cb, int(rid)); await cb.answer("✅ وضعیت ریسلر تغییر کرد.")


@router.callback_query(F.data.regexp(r"^adm:rdel:\d+$"))
async def reseller_delete_choice(cb: CallbackQuery, is_admin: bool) -> None:
    if not is_admin: return
    async with SessionLocal() as session:
        reseller = await ResellerRepository(session).get(int(cb.data.rsplit(":", 1)[1]))
        if reseller is None:
            await cb.answer("ریسلر پیدا نشد یا قبلاً حذف شده است.", show_alert=True); return
        row = await _reseller_row(session, reseller)
    await edit_or_answer(cb, delete_choice_text(row), reseller_delete_keyboard(row.id)); await cb.answer()


@router.callback_query(F.data.regexp(r"^adm:rdel:c:hard:\d+$"))
async def reseller_hard_delete_confirm(cb: CallbackQuery, is_admin: bool) -> None:
    if not is_admin: return
    async with SessionLocal() as session:
        repo = ResellerRepository(session)
        reseller = await repo.get(int(cb.data.rsplit(":", 1)[1]))
        if reseller is None:
            await cb.answer("ریسلر پیدا نشد یا قبلاً حذف شده است.", show_alert=True); return
        row, counts = await _reseller_row(session, reseller), await repo.record_counts(reseller.id)
    await edit_or_answer(cb, hard_delete_confirm_text(row, counts), reseller_hard_delete_keyboard(row.id)); await cb.answer()


@router.callback_query(F.data.regexp(r"^adm:rdel:do:(arch|hard):\d+$"))
async def reseller_delete_do(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    _, _, _, mode, rid = cb.data.split(":")
    async with SessionLocal() as session, session.begin():
        repo = ResellerRepository(session)
        reseller = await repo.get(int(rid))
        if reseller is None:
            await cb.answer("ریسلر پیدا نشد یا قبلاً حذف شده است.", show_alert=True); return
        name = reseller.display_name
        if mode == "arch": reseller.status = ResellerStatus.archived
        else: await repo.delete_permanently(int(rid))
    logger.warning("Admin deleted reseller admin_id=%s reseller_id=%s name=%s mode=%s", cb.from_user.id, rid, name, mode)
    await state.clear()
    text = f"📦 ریسلر «{name}» بایگانی شد. هر زمان خواستید از «📦 بایگانی‌شده‌ها» برش گردانید." if mode == "arch" else f"🗑 ریسلر «{name}» و همه سوابقش از ربات حذف شد."
    await cb.answer("✅ انجام شد.")
    await edit_or_answer(cb, text, resellers_menu())


@router.callback_query(F.data == "adm:edit_reseller")
async def edit_reseller_start(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    await select_reseller(cb.message, state, EditReseller.select, "adm:editsel", "ریسلر موردنظر برای ویرایش را انتخاب کنید."); await cb.answer()

@router.callback_query(F.data.startswith("adm:editsel:"))
async def edit_reseller_field(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    reseller_id = int(cb.data.rsplit(":", 1)[1]); await state.update_data(reseller_id=reseller_id); await state.set_state(EditReseller.field)
    await cb.message.answer("فیلد موردنظر برای ویرایش را انتخاب کنید.", reply_markup=edit_field_keyboard(reseller_id)); await cb.answer()

@router.callback_query(F.data.startswith("adm:editfield:"))
async def edit_field(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    _, _, rid, field = cb.data.split(":"); await state.update_data(reseller_id=int(rid), field=field); await state.set_state(EditReseller.value)
    if field == "status":
        await cb.message.answer("وضعیت جدید را انتخاب کنید.", reply_markup=status_keyboard())
    else:
        await cb.message.answer(f"مقدار جدید {'نام نمایشی' if field == 'display_name' else 'قیمت هر گیگابایت'} را وارد کنید.", reply_markup=admin_back_cancel(f"adm:editsel:{rid}"))
    await cb.answer()

@router.callback_query(EditReseller.value, F.data.startswith("adm:editstatus:"))
async def edit_status_value(cb: CallbackQuery, state: FSMContext) -> None:
    status = cb.data.rsplit(":", 1)[1]
    data = await state.update_data(value=status); await state.set_state(EditReseller.confirm)
    await cb.message.answer(f"تغییر وضعیت ریسلر به {status_fa(status)} را تایید می‌کنید؟", reply_markup=confirm_keyboard("adm:edit:confirm", f"adm:editsel:{data['reseller_id']}")); await cb.answer()

@router.message(EditReseller.value)
async def edit_text_value(message: Message, state: FSMContext) -> None:
    data = await state.get_data(); field = data['field']; value = (message.text or '').strip()
    if field == 'display_name' and len(value) < 2: await message.answer("نام نمایشی باید حداقل ۲ کاراکتر باشد."); return
    if field == 'price_per_gb':
        amount = money(value)
        if amount is None or amount <= 0: await message.answer("قیمت هر گیگابایت باید بیشتر از صفر باشد."); return
        value = str(amount)
    await state.update_data(value=value); await state.set_state(EditReseller.confirm)
    await message.answer(f"به‌روزرسانی {field} به {value} را تایید می‌کنید؟", reply_markup=confirm_keyboard("adm:edit:confirm", f"adm:editsel:{data['reseller_id']}"))

@router.callback_query(EditReseller.confirm, F.data == "adm:edit:confirm")
async def edit_confirm(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    data = await state.get_data()
    async with SessionLocal() as session, session.begin():
        reseller = await ResellerRepository(session).get(int(data['reseller_id']))
        if reseller is None: await cb.answer("ریسلر پیدا نشد", show_alert=True); return
        if data['field'] == 'display_name': reseller.display_name = data['value']
        elif data['field'] == 'price_per_gb': reseller.price_per_gb = Decimal(data['value'])
        elif data['field'] == 'status': reseller.status = ResellerStatus(data['value'])
    await state.clear(); await cb.message.answer("✅ ریسلر به‌روزرسانی شد.", reply_markup=panel()); await cb.answer()


@router.callback_query(F.data == "adm:tg_accounts")
async def telegram_accounts_start(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    await select_reseller(cb.message, state, TelegramAccountManagement.select_reseller, "adm:tgsel", "ریسلر موردنظر برای مدیریت اکانت‌های تلگرام را انتخاب کنید."); await cb.answer()

@router.callback_query(F.data.startswith("adm:tgsel:"))
async def telegram_accounts_menu(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    reseller_id = int(cb.data.rsplit(":", 1)[1])
    async with SessionLocal() as session:
        repo = ResellerRepository(session); reseller = await repo.get(reseller_id); accounts = await repo.telegram_accounts(reseller_id)
    lines = [f"👥 اکانت‌های تلگرام ریسلر {reseller.display_name if reseller else reseller_id}", ""]
    lines.extend([f"{'⭐ اصلی' if a.is_primary else 'ثانویه'}: {a.telegram_id}" for a in accounts] or ["اکانتی ثبت نشده است."])
    await state.update_data(reseller_id=reseller_id); await cb.message.answer("\n".join(lines), reply_markup=telegram_accounts_actions(reseller_id)); await cb.answer()

@router.callback_query(F.data.startswith("adm:tg:add:"))
async def telegram_account_add_start(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    reseller_id = int(cb.data.rsplit(":", 1)[1]); await state.update_data(reseller_id=reseller_id); await state.set_state(TelegramAccountManagement.add)
    await cb.message.answer("➕ افزودن آیدی تلگرام\nشناسه عددی تلگرام جدید را وارد کنید.", reply_markup=admin_back_cancel(f"adm:tgsel:{reseller_id}")); await cb.answer()

@router.message(TelegramAccountManagement.add)
async def telegram_account_add_value(message: Message, state: FSMContext) -> None:
    try: telegram_id = int((message.text or '').strip())
    except ValueError: await message.answer("شناسه تلگرام باید عدد صحیح باشد."); return
    data = await state.get_data(); reseller_id = int(data['reseller_id'])
    try:
        async with SessionLocal() as session, session.begin():
            await ResellerRepository(session).add_telegram_account(reseller_id, telegram_id, is_primary=False)
    except IntegrityError:
        await message.answer("این آیدی تلگرام قبلاً به یک ریسلر متصل شده است."); return
    await state.clear(); await message.answer("✅ آیدی تلگرام به ریسلر اضافه شد.", reply_markup=panel())

@router.callback_query(F.data.startswith("adm:tg:remove:"))
async def telegram_account_remove_list(cb: CallbackQuery, is_admin: bool) -> None:
    if not is_admin: return
    reseller_id = int(cb.data.rsplit(":", 1)[1])
    async with SessionLocal() as session: accounts = await ResellerRepository(session).telegram_accounts(reseller_id)
    await cb.message.answer("➖ حذف آیدی تلگرام\nآیدی موردنظر را انتخاب کنید. حذف آخرین آیدی مجاز نیست.", reply_markup=telegram_account_keyboard(accounts, "remove", reseller_id)); await cb.answer()

@router.callback_query(F.data.startswith("adm:tg:primary:"))
async def telegram_account_primary_list(cb: CallbackQuery, is_admin: bool) -> None:
    if not is_admin: return
    reseller_id = int(cb.data.rsplit(":", 1)[1])
    async with SessionLocal() as session: accounts = await ResellerRepository(session).telegram_accounts(reseller_id)
    await cb.message.answer("⭐ تنظیم به عنوان اصلی\nآیدی موردنظر را انتخاب کنید.", reply_markup=telegram_account_keyboard(accounts, "primary", reseller_id)); await cb.answer()

@router.callback_query(F.data.startswith("adm:tg:remove:acct:"))
async def telegram_account_remove(cb: CallbackQuery, is_admin: bool) -> None:
    if not is_admin: return
    account_id = int(cb.data.rsplit(":", 1)[1])
    async with SessionLocal() as session, session.begin(): ok = await ResellerRepository(session).remove_telegram_account(account_id)
    await cb.message.answer("✅ آیدی تلگرام حذف شد." if ok else "حذف ممکن نیست؛ آخرین آیدی تلگرام ریسلر را نمی‌توان حذف کرد.", reply_markup=panel()); await cb.answer()

@router.callback_query(F.data.startswith("adm:tg:primary:acct:"))
async def telegram_account_primary(cb: CallbackQuery, is_admin: bool) -> None:
    if not is_admin: return
    account_id = int(cb.data.rsplit(":", 1)[1])
    async with SessionLocal() as session, session.begin(): account = await ResellerRepository(session).set_primary_telegram_account(account_id)
    await cb.message.answer("✅ آیدی اصلی تلگرام تنظیم شد." if account else "آیدی تلگرام پیدا نشد.", reply_markup=panel()); await cb.answer()

@router.callback_query(F.data == "adm:balance")
async def balance_start(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    await select_reseller(cb.message, state, BalanceEdit.select, "adm:balsel", "ریسلر موردنظر برای ویرایش موجودی را انتخاب کنید."); await cb.answer()

@router.callback_query(F.data.startswith("adm:balsel:"))
async def balance_action(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    reseller_id = int(cb.data.rsplit(":",1)[1]); await state.update_data(reseller_id=reseller_id); await state.set_state(BalanceEdit.action)
    await cb.message.answer("نوع تغییر موجودی را انتخاب کنید.", reply_markup=balance_action_keyboard(reseller_id)); await cb.answer()

@router.callback_query(F.data.startswith("adm:balact:"))
async def balance_amount(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    _, _, rid, action = cb.data.split(":"); await state.update_data(reseller_id=int(rid), balance_action=action); await state.set_state(BalanceEdit.amount)
    await cb.message.answer("مبلغ را به تومان وارد کنید.", reply_markup=admin_back_cancel(f"adm:balsel:{rid}")); await cb.answer()

@router.message(BalanceEdit.amount)
async def balance_amount_msg(message: Message, state: FSMContext) -> None:
    amount = money(message.text)
    if amount is None: await message.answer("مبلغ باید عدد مثبت یا صفر باشد."); return
    data = await state.update_data(amount=str(amount)); await state.set_state(BalanceEdit.confirm)
    await message.answer(f"تغییر موجودی ({data['balance_action']}) به مبلغ {format_toman(amount)} را تایید می‌کنید؟", reply_markup=confirm_keyboard("adm:balance:confirm", f"adm:balsel:{data['reseller_id']}"))

@router.callback_query(BalanceEdit.confirm, F.data == "adm:balance:confirm")
async def balance_confirm(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    data = await state.get_data(); amount = Decimal(data['amount']); action = data['balance_action']
    async with SessionLocal() as session, session.begin():
        reseller = await ResellerRepository(session).get(int(data['reseller_id']))
        if reseller is None: await cb.answer("ریسلر پیدا نشد", show_alert=True); return
        if action == 'set_balance':
            delta = amount - reseller.balance
            await BillingService(session).change_balance(reseller, delta, TransactionType.set_balance, f"تنظیم موجودی توسط مدیر به {format_toman(amount)}", cb.from_user.id)
        else:
            delta = amount if action == 'increase' else -amount
            await BillingService(session).change_balance(reseller, delta, TransactionType(action), f"تغییر دستی موجودی توسط مدیر: {action}", cb.from_user.id)
    await state.clear(); await cb.message.answer("✅ موجودی به‌روزرسانی شد.", reply_markup=panel()); await cb.answer()

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
    await message.answer(f"حالت تعمیرات\nوضعیت فعلی: {'فعال' if enabled else 'غیرفعال'}", reply_markup=maintenance_keyboard())

@router.callback_query(F.data.startswith("adm:maint:set:"))
async def maintenance_set(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    enabled = cb.data.endswith(":on")
    await state.update_data(maintenance_enabled=enabled); await state.set_state(MaintenanceMode.confirm)
    await cb.message.answer(f"تغییر حالت تعمیرات به {'فعال' if enabled else 'غیرفعال'} را تایید می‌کنید؟", reply_markup=confirm_keyboard("adm:maint:confirm", "adm:maintenance")); await cb.answer()

@router.callback_query(MaintenanceMode.confirm, F.data == "adm:maint:confirm")
async def maintenance_confirm(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    data = await state.get_data(); enabled = bool(data.get('maintenance_enabled'))
    async with SessionLocal() as session, session.begin(): await SettingsRepository(session).set_bool("maintenance_mode", enabled)
    await state.clear(); await cb.message.answer(f"✅ حالت تعمیرات اکنون {'فعال' if enabled else 'غیرفعال'} است.", reply_markup=panel()); await cb.answer()

async def select_reseller(message: Message, state: FSMContext, target_state, prefix: str, title: str) -> None:
    async with SessionLocal() as session: resellers = await ResellerRepository(session).list()
    await state.set_state(target_state)
    await message.answer(title, reply_markup=resellers_keyboard(resellers, prefix))

def _group_label(tags: list[str]) -> str:
    return f"{len(tags)} گروه" if tags else "همه گروه‌ها"


def _group_view(data: dict, saved_now: bool = False):
    names, selected, mode, saved = data["names"], list(data.get("selected") or []), data["mode"], list(data.get("saved") or [])
    saved_selected = [t for t in saved if t in names]
    dirty = mode != ("all" if not saved else "custom") or (mode == "custom" and set(selected) != set(saved_selected))
    stale = [t for t in saved if t not in names]
    text = group_access_text(data["reseller_name"], names, selected, mode, group_summary(saved, 6), stale, data.get("disabled_count", 0), dirty, saved_now)
    return text, group_access_keyboard(names, selected, mode)


@router.callback_query(F.data == "adm:inbounds")
async def inbound_start(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    await state.set_state(InboundPermissions.select_reseller)
    async with SessionLocal() as session:
        resellers = await ResellerRepository(session).list()
        inbound_repo = InboundRepository(session)
        buttons = [[InlineKeyboardButton(text=f"{r.display_name} — {_group_label(await inbound_repo.allowed_tags(r.id))}", callback_data=f"adm:inbsel:{r.id}")] for r in resellers]
    buttons.append([InlineKeyboardButton(text="⬅️ برگشت", callback_data="adm:panel"), InlineKeyboardButton(text="❌ لغو", callback_data="adm:cancel")])
    await edit_or_answer(cb, "🌐 دسترسی گروه‌ها\nریسلر موردنظر را انتخاب کنید. کنار نام هر ریسلر وضعیت فعلی‌اش نوشته شده.", InlineKeyboardMarkup(inline_keyboard=buttons)); await cb.answer()


@router.callback_query(F.data.startswith("adm:inbsel:"))
async def inbound_reseller(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    reseller_id = int(cb.data.rsplit(":", 1)[1])
    try: groups = await client().get_inbounds()
    except MarzbanError as exc:
        logger.exception("Could not load groups from panel status=%s", exc.status)
        await cb.message.answer("❌ دریافت گروه‌ها از پنل ممکن نشد. اتصال پنل را بررسی کنید."); await cb.answer(); return
    names = sorted({g["tag"] for g in groups if not g.get("is_disabled")})
    if not names:
        await cb.message.answer("در پنل هنوز گروه فعالی وجود ندارد. اول در پنل یک گروه بسازید.", reply_markup=admin_back_cancel("adm:inbounds")); await cb.answer(); return
    async with SessionLocal() as session:
        reseller = await ResellerRepository(session).get(reseller_id)
        if reseller is None:
            await cb.answer("ریسلر پیدا نشد.", show_alert=True); return
        saved = sorted(await InboundRepository(session).allowed_tags(reseller_id))
    data = {"reseller_id": reseller_id, "reseller_name": reseller.display_name, "names": names, "saved": saved, "disabled_count": sum(1 for g in groups if g.get("is_disabled")),
            "mode": "all" if not saved else "custom", "selected": [t for t in saved if t in names]}
    await state.set_state(InboundPermissions.edit); await state.set_data(data)
    text, markup = _group_view(data)
    await edit_or_answer(cb, text, markup); await cb.answer()


@router.callback_query(InboundPermissions.edit, F.data == "adm:inb:all")
async def inbound_all(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.update_data(mode="all")
    text, markup = _group_view(data); await edit_or_answer(cb, text, markup); await cb.answer("همه گروه‌ها مجاز شد")


@router.callback_query(InboundPermissions.edit, F.data.regexp(r"^adm:inb:t:\d+$"))
async def inbound_toggle(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data(); names = data["names"]; index = int(cb.data.rsplit(":", 1)[1])
    if index >= len(names):
        await cb.answer("این گزینه دیگر معتبر نیست.", show_alert=True); return
    selected = set(names if data["mode"] == "all" else data.get("selected") or [])
    name = names[index]
    selected.symmetric_difference_update({name})
    data = await state.update_data(mode="custom", selected=[n for n in names if n in selected])
    text, markup = _group_view(data); await edit_or_answer(cb, text, markup); await cb.answer()


@router.callback_query(InboundPermissions.edit, F.data == "adm:inb:save")
async def inbound_save(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    data = await state.get_data()
    if data["mode"] == "custom" and not data.get("selected"):
        await cb.answer("حداقل یک گروه انتخاب کنید یا «همه گروه‌ها» را بزنید.", show_alert=True); return
    tags = [] if data["mode"] == "all" else list(data["selected"])
    async with SessionLocal() as session, session.begin(): await InboundRepository(session).set_allowed_tags(int(data["reseller_id"]), tags)
    logger.info("Admin saved reseller group access admin_id=%s reseller_id=%s groups=%s", cb.from_user.id, data["reseller_id"], tags or "ALL")
    data = await state.update_data(saved=sorted(tags))
    text, markup = _group_view(data, saved_now=True); await edit_or_answer(cb, text, markup); await cb.answer("💾 ذخیره شد")


@router.callback_query(F.data.startswith("adm:inb:"))
async def inbound_expired_session(cb: CallbackQuery, is_admin: bool) -> None:
    if not is_admin: return
    await cb.answer("این صفحه منقضی شده است. دوباره از «دسترسی گروه‌ها» شروع کنید.", show_alert=True)


@router.callback_query(F.data == "adm:tx")
async def tx_start(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    await select_reseller(cb.message, state, TransactionBrowsing.select_reseller, "adm:txsel", "ریسلر موردنظر برای مشاهده تراکنش‌ها را انتخاب کنید."); await cb.answer()

@router.callback_query(F.data.startswith("adm:txsel:"))
async def tx_select(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    reseller_id = int(cb.data.rsplit(":",1)[1]); await state.set_state(TransactionBrowsing.browse)
    await cb.message.answer("فیلتر نوع تراکنش را انتخاب کنید.", reply_markup=tx_filter_keyboard(reseller_id)); await cb.answer()

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
    text = transactions_page_text(reseller.display_name if reseller else str(reseller_id), tx_type, page, visible, get_settings().timezone)
    await message.answer(text, reply_markup=tx_page_keyboard(reseller_id, tx_type, page, has_next))

@router.callback_query(F.data == "adm:rpt")
async def report_start(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    await state.clear()
    async with SessionLocal() as session: resellers = await ResellerRepository(session).list()
    await cb.message.answer("📄 گزارش PDF دسته‌بندی‌شده\nمحدوده گزارش را انتخاب کنید.", reply_markup=report_scope_keyboard(resellers)); await cb.answer()

@router.callback_query(F.data.startswith("adm:rpt:s:"))
async def report_scope(cb: CallbackQuery, is_admin: bool) -> None:
    if not is_admin: return
    scope = cb.data.rsplit(":", 1)[1]
    await cb.message.answer("بازه زمانی گزارش را انتخاب کنید.", reply_markup=report_period_keyboard(scope)); await cb.answer()

@router.callback_query(F.data.startswith("adm:rpt:go:"))
async def report_generate(cb: CallbackQuery, is_admin: bool) -> None:
    if not is_admin: return
    try:
        _, _, _, scope, period = cb.data.split(":")
        reseller_id = None if scope == "all" else int(scope)
    except ValueError:
        await cb.answer("داده نامعتبر است.", show_alert=True); return
    if period not in PERIOD_LABELS:
        await cb.answer("بازه نامعتبر است.", show_alert=True); return
    await cb.answer("در حال ساخت گزارش...")
    settings = get_settings()
    try:
        async with SessionLocal() as session:
            data = await collect_report_data(session, reseller_id, period, settings.timezone)
        with tempfile.TemporaryDirectory() as tmp:
            name = f"report-{'all' if reseller_id is None else f'reseller-{reseller_id}'}-{period}-{jalali_filename_datetime(settings.timezone)}.pdf"
            path = await asyncio.to_thread(build_report_pdf, data, Path(tmp) / name, settings.pdf_font_path)
            await cb.message.answer_document(FSInputFile(path, filename=name), caption=f"📄 گزارش دسته‌بندی‌شده\nمحدوده: {data.scope_label}\nبازه: {data.period_label}")
    except PdfFontError:
        logger.exception("PDF report font problem")
        await cb.message.answer("❌ فونت فارسی روی سرور پیدا نشد.\nدستور زیر را روی سرور اجرا کنید و ربات را ریستارت کنید:\napt install -y fonts-vazirmatn", reply_markup=panel())
    except Exception:
        logger.exception("Failed to build PDF report scope=%s period=%s", scope, period)
        await cb.message.answer("❌ ساخت گزارش PDF ناموفق بود. جزئیات در لاگ ثبت شد.", reply_markup=panel())

def parse_recharge_callback(data: str | None) -> tuple[str, int] | None:
    parts = (data or "").split(":")
    if len(parts) != 3 or parts[0] != "recharge":
        return None
    action, raw_req_id = parts[1], parts[2]
    if action not in {"approve", "reject", "reject_no_reason", "cancel"}:
        return None
    try:
        req_id = int(raw_req_id)
    except ValueError:
        return None
    return action, req_id


async def safe_notify_reseller(bot, telegram_id: int, text: str) -> None:
    try:
        await bot.send_message(telegram_id, text)
    except Exception:
        logger.exception("Failed to notify reseller %s", telegram_id)


@router.callback_query(F.data.startswith("adm:recharge:"))
async def legacy_recharge_action(callback: CallbackQuery) -> None:
    logger.warning("Legacy recharge callback received: %s", callback.data)
    await callback.answer("داده نامعتبر است. لطفاً از پیام جدید درخواست شارژ استفاده کنید.", show_alert=True)


@router.callback_query(F.data.startswith("recharge:"))
async def recharge_action(callback: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin:
        await callback.answer("فقط مدیر مجاز است.", show_alert=True)
        return
    parsed = parse_recharge_callback(callback.data)
    if parsed is None:
        logger.warning("Invalid recharge callback data: %s", callback.data)
        await callback.answer("داده نامعتبر است.", show_alert=True)
        return

    action, req_id = parsed
    if action == "cancel":
        await state.clear()
        await callback.message.answer("عملیات رد درخواست شارژ لغو شد.", reply_markup=panel())
        await callback.answer()
        return
    if action == "reject":
        async with SessionLocal() as session:
            req = await RechargeRepository(session).get(req_id)
            if req is None:
                await callback.answer("درخواست شارژ پیدا نشد.", show_alert=True)
                return
            if req.status != RechargeStatus.pending:
                await callback.answer("این درخواست قبلاً پردازش شده است.", show_alert=True)
                return
        await state.update_data(recharge_id=req_id)
        await state.set_state(RechargeModeration.reject_reason)
        await callback.message.answer(
            f"دلیل رد درخواست شارژ #{req_id} را وارد کنید. اگر دلیل ندارید، دکمه «رد بدون دلیل» را بزنید.",
            reply_markup=recharge_reject_keyboard(req_id),
        )
        await callback.answer()
        return
    if action == "reject_no_reason":
        await process_recharge(callback, state, req_id, "reject", None)
        return
    if action == "approve":
        await process_recharge(callback, state, req_id, "approve", None)
        return

    await callback.answer("داده نامعتبر است.", show_alert=True)


@router.message(RechargeModeration.reject_reason)
async def reject_reason(message: Message, state: FSMContext) -> None:
    reason = (message.text or '').strip() or None
    data = await state.get_data()
    req_id = data.get('recharge_id')
    if req_id is None:
        await state.clear()
        await message.answer("داده درخواست شارژ پیدا نشد. لطفاً دوباره تلاش کنید.", reply_markup=panel())
        return
    try:
        async with SessionLocal() as session, session.begin():
            req = await RechargeRepository(session).get(int(req_id))
            if req is None:
                await state.clear()
                await message.answer("درخواست شارژ پیدا نشد.", reply_markup=panel())
                return
            if req.status != RechargeStatus.pending:
                await state.clear()
                await message.answer("این درخواست قبلاً پردازش شده است.", reply_markup=panel())
                return
            reseller = await ResellerRepository(session).get(req.reseller_id)
            if reseller is None:
                await state.clear()
                await message.answer("ریسلر مربوط به این درخواست پیدا نشد.", reply_markup=panel())
                return
            req.status = RechargeStatus.rejected
            req.admin_reason = reason
            req.processed_by_admin_id = message.from_user.id if message.from_user else None
            req.processed_at = datetime.now(timezone.utc)
            telegram_id = reseller.telegram_id
            amount = req.amount
    except Exception:
        logger.exception("Failed to reject recharge request %s", req_id)
        await message.answer("خطا در پردازش درخواست شارژ. لطفاً دوباره تلاش کنید.", reply_markup=panel())
        return
    await state.clear()
    reason_line = f"\nدلیل: {reason}" if reason else ""
    await safe_notify_reseller(message.bot, telegram_id, f"❌ درخواست شارژ شما رد شد.\nمبلغ: {format_toman(amount)}{reason_line}")
    await message.answer("✅ درخواست شارژ رد شد و به ریسلر اطلاع داده شد.", reply_markup=panel())


async def process_recharge(callback: CallbackQuery, state: FSMContext, req_id: int, action: str, reason: str | None) -> None:
    try:
        async with SessionLocal() as session, session.begin():
            req = await RechargeRepository(session).get(req_id)
            if req is None:
                await callback.answer("درخواست شارژ پیدا نشد.", show_alert=True)
                return
            if req.status != RechargeStatus.pending:
                await callback.answer("این درخواست قبلاً پردازش شده است.", show_alert=True)
                return
            reseller = await ResellerRepository(session).get(req.reseller_id)
            if reseller is None:
                await callback.answer("ریسلر مربوط به این درخواست پیدا نشد.", show_alert=True)
                return
            if action == "approve":
                await BillingService(session).change_balance(reseller, req.amount, TransactionType.recharge, f"تایید درخواست شارژ #{req.id}", callback.from_user.id)
                req.status = RechargeStatus.approved
            elif action == "reject":
                req.status = RechargeStatus.rejected
                req.admin_reason = reason
            else:
                await callback.answer("داده نامعتبر است.", show_alert=True)
                return
            req.processed_by_admin_id = callback.from_user.id
            req.processed_at = datetime.now(timezone.utc)
            telegram_id = reseller.telegram_id
            amount = req.amount
    except Exception:
        logger.exception("Failed to process recharge request %s with action %s", req_id, action)
        await callback.answer("خطا در پردازش درخواست شارژ. لطفاً دوباره تلاش کنید.", show_alert=True)
        return

    await state.clear()
    if action == "approve":
        await safe_notify_reseller(callback.bot, telegram_id, f"✅ درخواست شارژ شما تایید شد.\nمبلغ: {format_toman(amount)}")
        await callback.message.answer(f"✅ درخواست شارژ #{req_id} تایید شد و موجودی ریسلر افزایش یافت.", reply_markup=panel())
    else:
        reason_line = f"\nدلیل: {reason}" if reason else ""
        await safe_notify_reseller(callback.bot, telegram_id, f"❌ درخواست شارژ شما رد شد.\nمبلغ: {format_toman(amount)}{reason_line}")
        await callback.message.answer(f"✅ درخواست شارژ #{req_id} رد شد و به ریسلر اطلاع داده شد.", reply_markup=panel())
    await callback.answer()
