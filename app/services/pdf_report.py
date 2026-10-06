"""Categorized PDF report (Persian / RTL) built with reportlab."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import jdatetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import BalanceTransaction, OperationLog, OperationType, Reseller, ResellerStatus, TransactionType
from app.services.datetime import jalali_datetime_text, tehran_now
from app.services.reports import clean_tx_description, tx_type_label
from app.utils.formatting import format_toman

logger = logging.getLogger(__name__)
MAX_ROWS_PER_SECTION = 2000

PERIOD_LABELS = {"7d": "۷ روز اخیر", "30d": "۳۰ روز اخیر", "cur": "ماه شمسی جاری", "all": "کل سوابق"}

_FONT_CANDIDATES = [
    ("/usr/share/fonts/truetype/vazirmatn/Vazirmatn-Regular.ttf", "/usr/share/fonts/truetype/vazirmatn/Vazirmatn-Bold.ttf"),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ("/usr/share/fonts/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"),
    ("/usr/share/fonts/TTF/DejaVuSans.ttf", "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf"),
]


class PdfFontError(RuntimeError):
    pass


@dataclass
class Section:
    title: str
    headers: list[str]
    rows: list[list[str]]
    footer: str = ""
    note: str = ""


@dataclass
class ReportData:
    scope_label: str
    period_label: str
    generated_text: str
    summary: Section
    sections: list[Section] = field(default_factory=list)


# ---------------------------------------------------------------- data collection
def period_start(period: str, tz_name: str) -> datetime | None:
    """Naive UTC datetime (how SQLite stores created_at) or None for the whole history."""
    now = tehran_now(tz_name)
    if period == "7d":
        start = now - timedelta(days=7)
    elif period == "30d":
        start = now - timedelta(days=30)
    elif period == "cur":
        j = jdatetime.datetime.fromgregorian(datetime=now).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        start = j.togregorian().replace(tzinfo=now.tzinfo)
    else:
        return None
    return start.astimezone(timezone.utc).replace(tzinfo=None)


def _sum(values) -> Decimal:
    return sum((Decimal(v) for v in values), Decimal("0"))


def _capped(rows: list[list[str]]) -> tuple[list[list[str]], str]:
    if len(rows) <= MAX_ROWS_PER_SECTION:
        return rows, ""
    return rows[:MAX_ROWS_PER_SECTION], f"فقط {MAX_ROWS_PER_SECTION} ردیف اول (جدیدترین‌ها) از {len(rows)} ردیف نمایش داده شده است."


async def collect_report_data(session: AsyncSession, reseller_id: int | None, period: str, tz_name: str) -> ReportData:
    since = period_start(period, tz_name)
    if reseller_id is None:
        resellers = list((await session.scalars(select(Reseller).where(Reseller.status != ResellerStatus.archived).order_by(Reseller.display_name))).all())
        scope_label = "همه ریسلرها"
    else:
        reseller = await session.get(Reseller, reseller_id)
        resellers = [reseller] if reseller else []
        scope_label = reseller.display_name if reseller else str(reseller_id)
    ids = [r.id for r in resellers]
    names = {r.id: r.display_name for r in resellers}

    tx_stmt = select(BalanceTransaction).where(BalanceTransaction.reseller_id.in_(ids))
    log_stmt = select(OperationLog).where(OperationLog.reseller_id.in_(ids))
    if since is not None:
        tx_stmt = tx_stmt.where(BalanceTransaction.created_at >= since)
        log_stmt = log_stmt.where(OperationLog.created_at >= since)
    txs = list((await session.scalars(tx_stmt.order_by(BalanceTransaction.created_at.desc(), BalanceTransaction.id.desc()))).all())
    logs = list((await session.scalars(log_stmt.order_by(OperationLog.created_at.desc(), OperationLog.id.desc()))).all())

    credits = [t for t in txs if t.type in (TransactionType.recharge, TransactionType.increase)]
    debits = [t for t in txs if t.type in (TransactionType.decrease, TransactionType.set_balance)]
    creates = [l for l in logs if l.operation_type == OperationType.create]
    renews = [l for l in logs if l.operation_type == OperationType.renew]

    summary_rows = []
    for r in resellers:
        r_credit = _sum(t.amount for t in credits if t.reseller_id == r.id)
        r_debit = _sum(t.amount for t in txs if t.reseller_id == r.id and t.type == TransactionType.decrease)
        r_creates = [l for l in creates if l.reseller_id == r.id]
        r_renews = [l for l in renews if l.reseller_id == r.id]
        spent = _sum(l.charged_amount for l in r_creates + r_renews)
        summary_rows.append([r.display_name, format_toman(r.balance), format_toman(r_credit), format_toman(abs(r_debit)), str(len(r_creates)), str(len(r_renews)), format_toman(spent)])
    summary = Section(
        "خلاصه وضعیت ریسلرها",
        ["ریسلر", "موجودی فعلی", "مجموع شارژ و افزایش", "مجموع کاهش دستی", "تعداد ساخت", "تعداد تمدید", "مجموع مصرف"],
        summary_rows,
        footer=f"مجموع مصرف همه: {format_toman(_sum(l.charged_amount for l in creates + renews))}  |  مجموع شارژ و افزایش: {format_toman(_sum(t.amount for t in credits))}",
    )

    def tx_rows(items):
        return [[names.get(t.reseller_id, "-"), jalali_datetime_text(t.created_at, tz_name), tx_type_label(t.type), format_toman(abs(t.amount)), format_toman(t.balance_before), format_toman(t.balance_after), clean_tx_description(t.description)] for t in items]

    def log_rows(items):
        return [[names.get(l.reseller_id, "-"), jalali_datetime_text(l.created_at, tz_name), l.username, f"{l.added_gb} GB", f"{l.added_days} روز", format_toman(l.charged_amount), format_toman(l.balance_after)] for l in items]

    tx_headers = ["ریسلر", "تاریخ", "نوع", "مبلغ", "موجودی قبل", "موجودی بعد", "توضیح"]
    log_headers = ["ریسلر", "تاریخ", "نام کاربری", "حجم", "مدت", "هزینه", "موجودی بعد"]
    sections = []
    for title, headers, rows_all, footer in [
        ("شارژ و افزایش موجودی", tx_headers, tx_rows(credits), f"تعداد: {len(credits)}  |  جمع کل: {format_toman(_sum(t.amount for t in credits))}"),
        ("کاهش و تنظیم موجودی", tx_headers, tx_rows(debits), f"تعداد: {len(debits)}  |  جمع کاهش‌ها: {format_toman(abs(_sum(t.amount for t in debits if t.type == TransactionType.decrease)))}"),
        ("ساخت کاربر", log_headers, log_rows(creates), f"تعداد: {len(creates)}  |  جمع هزینه: {format_toman(_sum(l.charged_amount for l in creates))}  |  جمع حجم: {sum(l.added_gb for l in creates)} GB"),
        ("تمدید کاربر", log_headers, log_rows(renews), f"تعداد: {len(renews)}  |  جمع هزینه: {format_toman(_sum(l.charged_amount for l in renews))}  |  جمع حجم: {sum(l.added_gb for l in renews)} GB"),
    ]:
        rows, note = _capped(rows_all)
        sections.append(Section(title, headers, rows, footer, note))

    return ReportData(scope_label, PERIOD_LABELS.get(period, period), jalali_datetime_text(datetime.now(timezone.utc), tz_name), summary, sections)


# ---------------------------------------------------------------- rendering
def _find_fonts(custom_path: str | None) -> tuple[str, str]:
    if custom_path:
        path = Path(custom_path).expanduser()
        if not path.is_file():
            raise PdfFontError(f"PDF_FONT_PATH does not exist: {custom_path}")
        bold = path.with_name(path.name.replace("Regular", "Bold")) if "Regular" in path.name else path
        return str(path), str(bold if bold.is_file() else path)
    for regular, bold in _FONT_CANDIDATES:
        if Path(regular).is_file():
            return regular, bold if Path(bold).is_file() else regular
    raise PdfFontError("No Persian-capable TTF font found. Install one: apt install fonts-vazirmatn (or set PDF_FONT_PATH).")


def shape(text: str) -> str:
    """Join Arabic letters and reorder for visual RTL output (reportlab has no bidi support)."""
    import arabic_reshaper
    from bidi.algorithm import get_display

    text = str(text)
    if not any("\u0600" <= ch <= "\u06ff" for ch in text):
        return text
    return get_display(arabic_reshaper.reshape(text), base_dir="R")


def build_report_pdf(data: ReportData, output_path: str | Path, font_path: str | None = None) -> Path:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    regular, bold = _find_fonts(font_path)
    if "ReportFont" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("ReportFont", regular))
        pdfmetrics.registerFont(TTFont("ReportFont-Bold", bold))

    title_style = ParagraphStyle("t", fontName="ReportFont-Bold", fontSize=18, leading=26, alignment=2, textColor=colors.HexColor("#1f2937"))
    meta_style = ParagraphStyle("m", fontName="ReportFont", fontSize=10, leading=16, alignment=2, textColor=colors.HexColor("#4b5563"))
    h_style = ParagraphStyle("h", fontName="ReportFont-Bold", fontSize=13, leading=20, alignment=2, textColor=colors.HexColor("#111827"), spaceBefore=6, spaceAfter=4, keepWithNext=1)
    foot_style = ParagraphStyle("f", fontName="ReportFont", fontSize=9, leading=14, alignment=2, textColor=colors.HexColor("#374151"), spaceBefore=4)
    empty_style = ParagraphStyle("e", fontName="ReportFont", fontSize=10, leading=16, alignment=2, textColor=colors.HexColor("#6b7280"))

    page = landscape(A4)
    doc = SimpleDocTemplate(str(output_path), pagesize=page, leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm, bottomMargin=14 * mm, title="Report")
    width = page[0] - 24 * mm

    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont("ReportFont", 8)
        canvas.setFillColor(colors.HexColor("#6b7280"))
        canvas.drawCentredString(page[0] / 2, 7 * mm, shape(f"صفحه {document.page}"))
        canvas.restoreState()

    def table(section: Section):
        # RTL: first logical column goes to the right edge, so reverse every row.
        rows = [[shape(c) for c in reversed(section.headers)]] + [[shape(c[:60]) for c in reversed(r)] for r in section.rows]
        weights = [2.4 if h == "توضیح" else 1.0 for h in section.headers]
        widths = [width * w / sum(weights) for w in reversed(weights)]
        t = Table(rows, colWidths=widths, repeatRows=1)
        t.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), "ReportFont"), ("FONTNAME", (0, 0), (-1, 0), "ReportFont-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8.5), ("ALIGN", (0, 0), (-1, -1), "CENTER"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e5e7eb")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f9fafb")]),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d1d5db")),
            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        return t

    story = [
        Paragraph(shape("گزارش مالی و عملیات ریسلرها"), title_style),
        Paragraph(shape(f"محدوده: {data.scope_label}   |   بازه: {data.period_label}   |   تاریخ تهیه: {data.generated_text}"), meta_style),
        Spacer(1, 6 * mm),
    ]
    for index, section in enumerate([data.summary] + data.sections):
        if index:
            story.append(Spacer(1, 6 * mm))
        story.append(Paragraph(shape(section.title), h_style))
        if section.rows:
            story.append(table(section))
        else:
            story.append(Paragraph(shape("موردی در این بازه ثبت نشده است."), empty_style))
        if section.footer:
            story.append(Paragraph(shape(section.footer), foot_style))
        if section.note:
            story.append(Paragraph(shape(section.note), foot_style))
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return Path(output_path)
