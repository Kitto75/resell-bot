import re
USERNAME_RE = re.compile(r"^[a-z0-9_]+$")

def valid_username(username: str) -> bool:
    return bool(USERNAME_RE.fullmatch(username))


# Names of accounts that ALREADY exist in the panel (lookup / renew / toggle / QR). The panel also allows - . @ and capitals,
# so this is deliberately wider than valid_username(), which only decides what the bot lets people CREATE.
EXISTING_USERNAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.@-]{2,127}$")


def valid_existing_username(value: str | None) -> bool:
    return bool(EXISTING_USERNAME_RE.fullmatch((value or "").strip()))


def username_candidates(value: str) -> list[str]:
    """The name as typed first, then its lowercase form (the panel may store either)."""
    typed = value.strip()
    return [typed] if typed == typed.lower() else [typed, typed.lower()]


async def fetch_user_by_name(fetch, value: str):
    """Call `await fetch(name)` for each candidate until the panel knows the name. Returns (name, result).
    Only a 404 moves on to the next candidate; any other panel error is raised immediately."""
    from app.services.marzban import MarzbanError

    last: MarzbanError | None = None
    for candidate in username_candidates(value):
        try:
            return candidate, await fetch(candidate)
        except MarzbanError as exc:
            if exc.status != 404:
                raise
            last = exc
    assert last is not None
    raise last


# ---- volume (GB): decimals like 1.5 or 12.6 are allowed, at most two digits after the separator
_GB_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_GB_RE = re.compile(r"^\d{1,6}(?:\.\d{1,2})?$")
MAX_GB = 100_000
GB_FORMAT_HELP = "یک عدد معتبر وارد کنید (اعشار مجاز است، مثل 10 یا 1.5)."


def parse_gb(text: str | None):
    """'1.5' / '۱٫۵' / '12,6' -> Decimal. Raises ValueError with a message that can be shown to the user."""
    from decimal import Decimal

    raw = (text or "").strip().translate(_GB_DIGITS).replace("٫", ".").replace(",", ".")
    if re.fullmatch(r"\d+\.\d{3,}", raw):
        raise ValueError("حداکثر دو رقم اعشار مجاز است (مثل 1.25).")
    if not _GB_RE.fullmatch(raw):
        raise ValueError(GB_FORMAT_HELP)
    value = Decimal(raw)
    if value <= 0:
        raise ValueError("حجم باید بیشتر از صفر باشد.")
    if value > MAX_GB:
        raise ValueError(f"حجم نمی‌تواند بیشتر از {MAX_GB} گیگابایت باشد.")
    return value


# The note admin-created accounts carry. "admin" is reserved: no reseller may use it as a display name,
# otherwise it would "own" every admin-created account.
ADMIN_OWNER_NAME = "admin"
ADMIN_OWNER_NOTE = f"belongs to {ADMIN_OWNER_NAME}"


def is_reserved_reseller_name(name: str | None) -> bool:
    return (name or "").strip().lower() == ADMIN_OWNER_NAME
