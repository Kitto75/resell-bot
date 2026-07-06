import os
from decimal import Decimal
from types import SimpleNamespace

os.environ.setdefault("BOT_TOKEN", "123:test")
os.environ.setdefault("ADMIN_IDS", "1")
os.environ.setdefault("MARZBAN_BASE_URL", "https://marzban.example")
os.environ.setdefault("MARZBAN_USERNAME", "admin")
os.environ.setdefault("MARZBAN_PASSWORD", "password")

from app.database.models import OperationType
from app.services.reports import operation_report
from app.utils.formatting import format_toman
from app.handlers.reseller import primary_subscription_url


def test_format_toman_uses_grouping_without_decimals():
    assert format_toman(Decimal("150000.00")) == "150,000 تومان"
    assert format_toman("860000.00") == "860,000 تومان"


def test_operation_report_uses_short_date_and_formatted_money():
    reseller = SimpleNamespace(display_name="plex", telegram_id=123)
    log = SimpleNamespace(
        username="example_user",
        operation_type=OperationType.create,
        added_gb=10,
        added_days=30,
        charged_amount=Decimal("150000.00"),
        balance_before=Decimal("860000.00"),
        balance_after=Decimal("710000.00"),
    )

    report = operation_report(reseller, log)

    assert "هزینه: 150,000 تومان" in report
    assert "موجودی: 860,000 تومان → 710,000 تومان" in report
    assert "تاریخ:" in report
    assert "تاریخ شمسی:" not in report
    assert "منطقه زمانی" not in report


def test_primary_subscription_url_prefers_marzban_default_field():
    assert primary_subscription_url({"subscription_url": "https://example.test/sub"}) == "https://example.test/sub"
    assert primary_subscription_url({"subscriptions": [{"url": "https://example.test/one"}]}) == "https://example.test/one"
