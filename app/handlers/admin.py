from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import logging
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.exc import IntegrityError
from app.config import get_settings
from app.database.models import RechargeStatus, ResellerStatus, TransactionType
from app.database.repositories import InboundRepository, RechargeRepository, ResellerRepository, SettingsRepository, TransactionRepository
from app.database.session import SessionLocal
from app.keyboards.admin import admin_back_cancel, backup_keyboard, balance_action_keyboard, confirm_keyboard, edit_field_keyboard, inbound_keyboard, maintenance_keyboard, panel, recharge_reject_keyboard, resellers_keyboard, resellers_menu, status_keyboard, telegram_account_keyboard, telegram_accounts_actions, tx_filter_keyboard, tx_page_keyboard
from app.services.backup import get_backup_status, send_database_backup, set_backup_enabled, set_backup_interval, sqlite_backup_supported
from app.services.billing import BillingService
from app.services.marzban import MarzbanClient, MarzbanError
from app.utils.formatting import format_toman, status_fa
from app.states.admin import AddReseller, BackupSettings, BalanceEdit, EditReseller, InboundPermissions, MaintenanceMode, RechargeModeration, TelegramAccountManagement, TransactionBrowsing

router = Router()
PAGE_SIZE = 5
logger = logging.getLogger(__name__)


def client() -> MarzbanClient:
    s = get_settings(); return MarzbanClient(s.marzban_base_url, s.marzban_username, s.marzban_password)

def money(text: str | None) -> Decimal | None:
    try: value = Decimal((text or '').strip())
    except InvalidOperation: return None
    return value if value >= 0 else None

async def show_panel(message: Message) -> None:
    await message.answer("پنل مدیریت\nیک گزینه را انتخاب کنید.", reply_markup=panel())

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



@router.callback_query(F.data == "adm:reseller_list")
async def reseller_list_cb(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    async with SessionLocal() as session:
        resellers = await ResellerRepository(session).list(include_archived=True)
        inbound_repo = InboundRepository(session)
        lines = ["📋 لیست کامل ریسلرها", ""]
        if not resellers:
            lines.append("هیچ ریسلری ثبت نشده است.")
        for idx, item in enumerate(resellers, 1):
            count = await ResellerRepository(session).count_users(item.id)
            allowed = await inbound_repo.allowed_tags(item.id)
            inbound_mode = "همه اینباندها" if not allowed else "اینباندهای اختصاصی"
            lines.append(
                f"{idx}. {item.display_name}\n"
                f"آیدی اصلی تلگرام: {await ResellerRepository(session).primary_telegram_id(item)}\n"
                f"موجودی: {format_toman(item.balance)}\n"
                f"قیمت هر گیگابایت: {format_toman(item.price_per_gb)}\n"
                f"وضعیت: {status_fa(item.status)}\n"
                f"تعداد کاربران ساخته‌شده: {count}\n"
                f"دسترسی اینباند: {inbound_mode}"
            )
            lines.append("")
    await cb.message.answer("\n".join(lines), reply_markup=resellers_menu()); await cb.answer()

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

@router.callback_query(F.data == "adm:inbounds")
async def inbound_start(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    await select_reseller(cb.message, state, InboundPermissions.select_reseller, "adm:inbsel", "ریسلر موردنظر برای مدیریت دسترسی اینباند را انتخاب کنید."); await cb.answer()

@router.callback_query(F.data.startswith("adm:inbsel:"))
async def inbound_reseller(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    reseller_id = int(cb.data.rsplit(":",1)[1])
    try: inbounds = await client().get_inbounds()
    except MarzbanError as exc: await cb.message.answer(f"دریافت اینباندها ممکن نشد: {exc}"); await cb.answer(); return
    tags = sorted({str(i.get('tag') or i.get('remark') or i.get('protocol') or i) for i in inbounds})
    async with SessionLocal() as session: allowed = await InboundRepository(session).allowed_tags(reseller_id)
    all_allowed = len(allowed) == 0
    await state.update_data(reseller_id=reseller_id, tags=tags, selected=allowed, all_allowed=all_allowed); await state.set_state(InboundPermissions.edit)
    await cb.message.answer("دسترسی اینباندها\nپیش‌فرض همه اینباندها است. موارد اختصاصی را انتخاب یا ذخیره کنید.", reply_markup=inbound_keyboard(tags, allowed, all_allowed)); await cb.answer()

@router.callback_query(InboundPermissions.edit, F.data == "adm:inb:all")
async def inbound_all(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.update_data(selected=[], all_allowed=True)
    await cb.message.answer("همه اینباندها انتخاب شد. برای اعمال، ذخیره کنید.", reply_markup=inbound_keyboard(data['tags'], [], True)); await cb.answer()

@router.callback_query(InboundPermissions.edit, F.data.startswith("adm:inb:toggle:"))
async def inbound_toggle(cb: CallbackQuery, state: FSMContext) -> None:
    tag = cb.data.split(":",3)[3]; data = await state.get_data(); selected = set(data.get('selected') or [])
    if data.get('all_allowed'): selected = set(data.get('tags') or [])
    selected.remove(tag) if tag in selected else selected.add(tag)
    data = await state.update_data(selected=list(selected), all_allowed=False)
    await cb.message.answer("انتخاب اینباندهای اختصاصی به‌روزرسانی شد. برای اعمال، ذخیره کنید.", reply_markup=inbound_keyboard(data['tags'], list(selected), False)); await cb.answer()

@router.callback_query(InboundPermissions.edit, F.data == "adm:inb:save")
async def inbound_save(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(InboundPermissions.confirm)
    await cb.message.answer("ذخیره تغییرات دسترسی اینباند را تایید می‌کنید؟", reply_markup=confirm_keyboard("adm:inb:confirm", "adm:inbounds")); await cb.answer()

@router.callback_query(InboundPermissions.confirm, F.data == "adm:inb:confirm")
async def inbound_confirm(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    data = await state.get_data(); tags = [] if data.get('all_allowed') else list(data.get('selected') or [])
    async with SessionLocal() as session, session.begin(): await InboundRepository(session).set_allowed_tags(int(data['reseller_id']), tags)
    await state.clear(); await cb.message.answer("✅ دسترسی اینباندها ذخیره شد.", reply_markup=panel()); await cb.answer()

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
    lines = [f"تراکنش‌های {reseller.display_name if reseller else reseller_id}", f"فیلتر: {tx_type}", f"صفحه: {page + 1}", ""]
    if not visible: lines.append("تراکنشی برای این انتخاب پیدا نشد.")
    for tx in visible:
        lines.append(f"#{tx.id} • {tx.type.value} • {format_toman(tx.amount)} • {format_toman(tx.balance_before)} → {format_toman(tx.balance_after)}\n{tx.created_at} • {tx.description or 'بدون توضیح'}")
    await message.answer("\n".join(lines), reply_markup=tx_page_keyboard(reseller_id, tx_type, page, has_next))

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
