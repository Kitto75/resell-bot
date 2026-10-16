"""Admin extras: limits, disable-with-message, /reseller, status PDF, report scope by name, backup bot.

Included BEFORE admin.router so that /reseller can interrupt any running flow (like /start does)."""
import asyncio
import logging
import tempfile
from pathlib import Path

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.config import get_settings
from app.database.models import ResellerStatus
from app.database.repositories import ResellerRepository, SettingsRepository
from app.database.session import SessionLocal
from app.handlers.admin import answer_card, build_reseller_list, client, edit_or_answer
from app.keyboards.admin import (admin_back_cancel, backup_bot_keyboard, disable_prompt_keyboard, limit_value_keyboard, limits_keyboard, panel,
                                 report_period_keyboard, reseller_matches_keyboard)
from app.services import limits as lim
from app.services.backup import (get_backup_bot_token, send_backup_bot_test, set_backup_bot_token, validate_backup_bot_token)
from app.services.datetime import jalali_filename_datetime
from app.services.pdf_report import PdfFontError, build_report_pdf, collect_snapshot_data
from app.services.tg_resolve import find_resellers
from app.states.admin import BackupSettings, DisableReseller, EditReseller, LimitEdit, ReportScope

logger = logging.getLogger(__name__)
router = Router()
BACKUP_BOT_USERNAME_KEY = "backup_bot_username"
MAX_DISABLED_MESSAGE = 1000
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def _parse_int(text: str | None) -> int | None:
    value = (text or "").strip().translate(_DIGITS)
    return int(value) if value.isdigit() and len(value) <= 9 else None


# ======================================================================= limits
def _limits_text(title: str, detail: dict, scope_is_global: bool) -> str:
    lines = [title, "━━━━━━━━━━━━━━"]
    for field in lim.FIELDS:
        value, source = detail[field]
        tag = "" if scope_is_global else ("  (اختصاصی)" if source == "custom" else "  (همگانی)")
        lines.append(f"{lim.FIELD_LABELS[field]}: {lim.describe(value, field)}{tag}")
    lines.append("")
    if scope_is_global:
        lines += [
            "• این محدودیت‌ها روی ساخت و تمدید اکانت همه ریسلرها اعمال می‌شود.",
            "• ریسلر می‌تواند روز کمتر از حداکثر، و حجمی داخل بازه‌ی مجاز انتخاب کند.",
            "• با هر ذخیره‌ی همگانی، همان مورد برای همه ریسلرها یکسان می‌شود و مقدار اختصاصی قبلی‌شان پاک می‌شود.",
            "• برای تنظیم اختصاصی یک ریسلر: کارت ریسلر ← 🚦 محدودیت‌ها",
        ]
    else:
        lines += ["«همگانی» یعنی از تنظیمات همگانی پیروی می‌کند و «اختصاصی» یعنی فقط برای همین ریسلر تغییر کرده است."]
    return "\n".join(lines)


async def _show_limits(message: Message, scope: str, note: str | None = None, cb: CallbackQuery | None = None) -> None:
    async with SessionLocal() as session:
        if scope == "g":
            detail = lim.merge(await lim.load_global(session), {})
            text, markup = _limits_text("🚦 محدودیت‌های همگانی", detail, True), limits_keyboard("g")
        else:
            reseller = await ResellerRepository(session).get(int(scope))
            if reseller is None:
                await message.answer("ریسلر پیدا نشد.", reply_markup=panel()); return
            overrides = await lim.load_overrides(session, reseller.id)
            detail = lim.merge(await lim.load_global(session), overrides)
            text, markup = _limits_text(f"🚦 محدودیت‌های «{reseller.display_name}»", detail, False), limits_keyboard(scope, has_custom=bool(overrides))
    text = f"{note}\n\n{text}" if note else text
    if cb is not None: await edit_or_answer(cb, text, markup)
    else: await message.answer(text, reply_markup=markup)


@router.callback_query(F.data == "adm:lim")
async def limits_global(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    await state.clear(); await _show_limits(cb.message, "g", cb=cb); await cb.answer()


@router.callback_query(F.data.regexp(r"^adm:lim:r:\d+$"))
async def limits_reseller(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    await state.clear(); await _show_limits(cb.message, cb.data.rsplit(":", 1)[1], cb=cb); await cb.answer()


@router.callback_query(F.data.regexp(r"^adm:lim:f:(g|\d+):(max_days|min_gb|max_gb)$"))
async def limits_field(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    _, _, _, scope, field = cb.data.split(":")
    await state.set_state(LimitEdit.value); await state.update_data(scope=scope, field=field)
    where = "همه ریسلرها" if scope == "g" else "این ریسلر"
    await cb.message.answer(f"{lim.FIELD_LABELS[field]} برای {where}\nمقدار جدید را به‌صورت عدد ({lim.FIELD_UNITS[field]}) بفرستید.\nبرای برداشتن محدودیت، دکمه‌ی «بدون محدودیت» را بزنید.", reply_markup=limit_value_keyboard(scope, field)); await cb.answer()


async def _apply_limit(message: Message, state: FSMContext, scope: str, field: str, value: int) -> None:
    async with SessionLocal() as session, session.begin():
        if scope == "g":
            everyone = await ResellerRepository(session).list(include_archived=True)
            error, cleared = await lim.set_global_field(session, field, value, [r.id for r in everyone])
            conflicts = await lim.conflicting_resellers(session, everyone) if not error else []
        else:
            error, cleared, conflicts = await lim.set_reseller_field(session, int(scope), field, value), 0, []
    if error:
        await message.answer(f"❌ {error}\nمقدار دیگری بفرستید.", reply_markup=limit_value_keyboard(scope, field)); return
    await state.clear()
    note = "✅ ذخیره شد."
    if scope == "g" and cleared: note += f"\n↻ برای {cleared} ریسلر مقدار اختصاصی این مورد پاک شد و همگانی اعمال شد."
    if conflicts: note += f"\n⚠️ برای این ریسلرها بازه‌ی حجم ناسازگار شده است (حداقل بیشتر از حداکثر): {'، '.join(conflicts)}"
    logger.info("Admin changed limits scope=%s field=%s value=%s", scope, field, value)
    await _show_limits(message, scope, note)


@router.message(LimitEdit.value, F.text, ~F.text.startswith("/"))
async def limits_value(message: Message, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    value = _parse_int(message.text)
    if value is None:
        await message.answer("یک عدد صحیح (مثل 31) بفرستید؛ یا «بدون محدودیت» را بزنید."); return
    data = await state.get_data()
    await _apply_limit(message, state, data["scope"], data["field"], value)


@router.callback_query(F.data.regexp(r"^adm:lim:none:(g|\d+):(max_days|min_gb|max_gb)$"))
async def limits_none(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    _, _, _, scope, field = cb.data.split(":")
    await cb.answer(); await _apply_limit(cb.message, state, scope, field, 0)


@router.callback_query(F.data.regexp(r"^adm:lim:reset:\d+$"))
async def limits_reset(cb: CallbackQuery, is_admin: bool) -> None:
    if not is_admin: return
    rid = int(cb.data.rsplit(":", 1)[1])
    async with SessionLocal() as session, session.begin(): await lim.reset_reseller(session, rid)
    await cb.answer("به تنظیمات همگانی برگشت."); await _show_limits(cb.message, str(rid), "↩️ محدودیت‌های اختصاصی پاک شد.", cb=cb)


# ======================================================================= disable reseller (+ optional message)
async def _prompt_disable(message: Message, state: FSMContext, reseller_id: int) -> None:
    async with SessionLocal() as session: reseller = await ResellerRepository(session).get(reseller_id)
    if reseller is None:
        await message.answer("ریسلر پیدا نشد.", reply_markup=panel()); return
    await state.clear(); await state.set_state(DisableReseller.message); await state.update_data(reseller_id=reseller_id)
    await message.answer(
        f"⏸ غیرفعال‌سازی «{reseller.display_name}»\n\n"
        "می‌خواهید وقتی این ریسلر به ربات پیام می‌دهد، پیامی برایش نمایش داده شود؟\n"
        "• متن پیام را همین حالا بفرستید تا هر بار همان را جواب بدهم.\n"
        "• یا «بدون پیام» را بزنید؛ آن‌وقت ربات به پیام‌هایش اصلاً واکنشی نشان نمی‌دهد.",
        reply_markup=disable_prompt_keyboard(reseller_id))


async def _disable(message: Message, state: FSMContext, reseller_id: int, text: str) -> None:
    async with SessionLocal() as session, session.begin():
        reseller = await ResellerRepository(session).get(reseller_id)
        if reseller is None:
            await message.answer("ریسلر پیدا نشد.", reply_markup=panel()); await state.clear(); return
        reseller.status = ResellerStatus.disabled
        await SettingsRepository(session).set(lim.message_key(reseller_id), text)
    await state.clear()
    note = "✅ ریسلر غیرفعال شد.\n" + (f"پیامی که به او نشان داده می‌شود:\n«{text}»" if text else "بدون پیام: ربات به پیام‌های او واکنشی نشان نمی‌دهد.")
    logger.info("Admin disabled reseller reseller_id=%s custom_message=%s", reseller_id, bool(text))
    await answer_card(message, reseller_id, note)


@router.callback_query(F.data.regexp(r"^adm:rc:st:\d+:disabled$"))
async def disable_start(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    await cb.answer(); await _prompt_disable(cb.message, state, int(cb.data.split(":")[3]))


@router.callback_query(EditReseller.value, F.data == "adm:editstatus:disabled")
async def disable_from_edit(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    data = await state.get_data()
    await cb.answer(); await _prompt_disable(cb.message, state, int(data["reseller_id"]))


@router.callback_query(F.data.regexp(r"^adm:rc:dis:\d+$"))
async def disable_silent(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    await cb.answer(); await _disable(cb.message, state, int(cb.data.rsplit(":", 1)[1]), "")


@router.message(DisableReseller.message, F.text, ~F.text.startswith("/"))
async def disable_with_message(message: Message, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    text = (message.text or "").strip()
    if len(text) > MAX_DISABLED_MESSAGE:
        await message.answer(f"پیام خیلی بلند است (حداکثر {MAX_DISABLED_MESSAGE} کاراکتر). کوتاه‌ترش کنید."); return
    data = await state.get_data()
    await _disable(message, state, int(data["reseller_id"]), text)


# ======================================================================= /reseller <name>
@router.message(Command("reseller"))
async def reseller_command(message: Message, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    await state.clear()
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        text, markup = await build_reseller_list("a", 0)
        await message.answer("برای باز کردن مستقیم یک ریسلر بنویسید: /reseller نام\n\n" + text, reply_markup=markup); return
    async with SessionLocal() as session: found = await find_resellers(session, parts[1])
    if not found:
        await message.answer(f"ریسلری با «{parts[1].strip()}» پیدا نشد. نام، آیدی عددی یا یوزرنیم تلگرام او را بفرستید.", reply_markup=reseller_matches_keyboard([])); return
    if len(found) == 1:
        await answer_card(message, found[0].id); return
    await message.answer("چند ریسلر پیدا شد؛ یکی را انتخاب کنید:", reply_markup=reseller_matches_keyboard(found))


# ======================================================================= PDF: single reseller by name
@router.message(ReportScope.reseller, F.text, ~F.text.startswith("/"))
async def report_scope_by_name(message: Message, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    query = (message.text or "").strip()
    async with SessionLocal() as session: found = await find_resellers(session, query)
    if not found:
        await message.answer(f"ریسلری با «{query}» پیدا نشد. دوباره یوزرنیم یا نام را بفرستید، یا «همه ریسلرها» را بزنید."); return
    if len(found) == 1:
        await state.clear()
        await message.answer(f"گزارش «{found[0].display_name}»\nبازه زمانی را انتخاب کنید.", reply_markup=report_period_keyboard(str(found[0].id))); return
    rows = [[InlineKeyboardButton(text=r.display_name, callback_data=f"adm:rpt:s:{r.id}")] for r in found]
    await message.answer("چند ریسلر پیدا شد؛ یکی را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


# ======================================================================= PDF: status snapshot of all resellers
@router.callback_query(F.data == "adm:rsnap")
async def reseller_snapshot(cb: CallbackQuery, is_admin: bool) -> None:
    if not is_admin: return
    await cb.answer("در حال ساخت گزارش...")
    settings = get_settings()
    try:
        async with SessionLocal() as session:
            data = await collect_snapshot_data(session, client(), settings.timezone)
        with tempfile.TemporaryDirectory() as tmp:
            name = f"resellers-status-{jalali_filename_datetime(settings.timezone)}.pdf"
            path = await asyncio.to_thread(build_report_pdf, data, Path(tmp) / name, settings.pdf_font_path)
            await cb.message.answer_document(FSInputFile(path, filename=name), caption="📊 وضعیت لحظه‌ای همه ریسلرها")
    except PdfFontError:
        logger.exception("PDF font problem")
        await cb.message.answer("❌ فونت فارسی روی سرور پیدا نشد.\nاین دستور را روی سرور اجرا کنید و ربات را ریستارت کنید:\napt install -y fonts-vazirmatn", reply_markup=panel())
    except Exception:
        logger.exception("Failed to build the reseller status PDF")
        await cb.message.answer("❌ ساخت گزارش ناموفق بود. جزئیات در لاگ ثبت شد.", reply_markup=panel())


# ======================================================================= backup via a separate bot
async def _backup_bot_screen(message: Message, cb: CallbackQuery | None = None, note: str | None = None) -> None:
    token = await get_backup_bot_token()
    async with SessionLocal() as session: username = await SettingsRepository(session).get(BACKUP_BOT_USERNAME_KEY)
    if token:
        status = f"✅ بکاپ‌ها با بات @{username or '؟'} ارسال می‌شوند."
    else:
        status = "اکنون بکاپ‌ها با همین بات اصلی ارسال می‌شوند."
    text = (f"{note}\n\n" if note else "") + (
        "🤖 بات بکاپ\n━━━━━━━━━━━━━━\n" + status + "\n\n"
        "اگر بات اصلی شلوغ است، یک بات جداگانه بسازید (از BotFather) و توکنش را اینجا بدهید تا فایل بکاپ فقط از آن ارسال شود.\n"
        "⚠️ قبلش داخل آن بات یک‌بار /start بزنید؛ وگرنه تلگرام اجازه‌ی پیام دادنش به شما را نمی‌دهد (در این صورت بکاپ به‌طور خودکار با بات اصلی می‌آید).")
    markup = backup_bot_keyboard(bool(token))
    if cb is not None: await edit_or_answer(cb, text, markup)
    else: await message.answer(text, reply_markup=markup)


@router.callback_query(F.data == "adm:backup:bot")
async def backup_bot_menu(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    await state.clear(); await _backup_bot_screen(cb.message, cb); await cb.answer()


@router.callback_query(F.data == "adm:backup:bot:set")
async def backup_bot_set(cb: CallbackQuery, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    await state.set_state(BackupSettings.bot_token)
    await cb.message.answer("توکن بات بکاپ را از BotFather بفرستید.\n🔒 پیام شما بلافاصله بعد از دریافت حذف می‌شود.", reply_markup=admin_back_cancel("adm:backup:bot")); await cb.answer()


@router.message(BackupSettings.bot_token, F.text, ~F.text.startswith("/"))
async def backup_bot_token_value(message: Message, state: FSMContext, is_admin: bool) -> None:
    if not is_admin: return
    token = (message.text or "").strip()
    try: await message.delete()  # the token is a secret: don't leave it in the chat history
    except Exception: pass
    if token == message.bot.token:
        await message.answer("این همان بات اصلی است. توکن یک بات دیگر را بفرستید."); return
    try: username = await validate_backup_bot_token(token)
    except ValueError as exc:
        await message.answer(f"❌ {exc}"); return
    await set_backup_bot_token(token)
    async with SessionLocal() as session, session.begin(): await SettingsRepository(session).set(BACKUP_BOT_USERNAME_KEY, username)
    await state.clear()
    logger.info("Admin set a separate backup bot username=%s", username)
    await _backup_bot_screen(message, note=f"✅ توکن ثبت شد (@{username}).\nحالا داخل آن بات /start بزنید و «ارسال پیام تست» را امتحان کنید.")


@router.callback_query(F.data == "adm:backup:bot:test")
async def backup_bot_test(cb: CallbackQuery, is_admin: bool) -> None:
    if not is_admin: return
    ok, error = await send_backup_bot_test(cb.bot, cb.from_user.id)
    await cb.answer("✅ پیام تست ارسال شد." if ok else error, show_alert=not ok)


@router.callback_query(F.data == "adm:backup:bot:clear")
async def backup_bot_clear(cb: CallbackQuery, is_admin: bool) -> None:
    if not is_admin: return
    await set_backup_bot_token(None)
    await cb.answer("به بات اصلی برگشت."); await _backup_bot_screen(cb.message, cb, note="🗑 توکن حذف شد.")
