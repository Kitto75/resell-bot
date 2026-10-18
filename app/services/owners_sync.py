"""Link panel users to resellers by the ownership note ("belongs to <reseller name>").

Users created before the bot existed (or directly in the panel) are unknown to the bot's local created_users table,
so "my accounts", the bulk enable/disable and similar features cannot see them. This adds / corrects those rows."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timezone
from typing import Any

from sqlalchemy import select

from app.database.models import CreatedUser
from app.database.repositories import ResellerRepository
from app.services.user_info import parse_panel_datetime

OWNER_PREFIX = "belongs to "
BYTES_PER_GB = 1024 ** 3


def parse_owner(note: Any) -> str | None:
    text = note.strip() if isinstance(note, str) else ""
    if not text.startswith(OWNER_PREFIX):
        return None
    name = text[len(OWNER_PREFIX):].strip()
    return name or None


@dataclass
class SyncResult:
    scanned: int = 0
    no_owner: int = 0
    unchanged: int = 0
    added: dict[str, int] = field(default_factory=dict)
    moved: dict[str, int] = field(default_factory=dict)
    unknown_owners: dict[str, int] = field(default_factory=dict)
    missing_in_panel: int = 0

    @property
    def added_total(self) -> int: return sum(self.added.values())

    @property
    def moved_total(self) -> int: return sum(self.moved.values())


def _row_values(user: dict[str, Any]) -> dict[str, Any]:
    limit = int(user.get("data_limit") or 0)
    created = parse_panel_datetime(user.get("created_at"))
    expire = int(user.get("expire") or 0)
    on_hold_seconds = int(user.get("on_hold_expire_duration") or 0)
    if on_hold_seconds: days = on_hold_seconds // 86400
    elif expire and created: days = max(0, (expire - int(created.timestamp())) // 86400)
    else: days = 0
    values: dict[str, Any] = {"marzban_status": str(getattr(user.get("status"), "value", user.get("status")) or "active"), "total_gb": round(limit / BYTES_PER_GB), "total_days": days}
    if created: values["created_at"] = created.astimezone(timezone.utc).replace(tzinfo=None)  # same naive-UTC form the database default produces
    return values


async def sync_owners(session, panel_users: list[dict[str, Any]]) -> SyncResult:
    """Caller owns the transaction. Never deletes anything; only adds rows and fixes the owner of existing ones."""
    result = SyncResult(scanned=len(panel_users))
    by_name = {r.display_name: r for r in await ResellerRepository(session).list(include_archived=True)}
    existing = {row.username: row for row in (await session.scalars(select(CreatedUser))).all()}
    seen: set[str] = set()
    for user in panel_users:
        username = str(user.get("username") or "")
        if not username: continue
        seen.add(username)
        owner = parse_owner(user.get("note"))
        if owner is None:
            result.no_owner += 1; continue
        reseller = by_name.get(owner)
        if reseller is None:
            result.unknown_owners[owner] = result.unknown_owners.get(owner, 0) + 1; continue
        row = existing.get(username)
        if row is None:
            session.add(CreatedUser(reseller_id=reseller.id, username=username, **_row_values(user)))
            result.added[reseller.display_name] = result.added.get(reseller.display_name, 0) + 1
        elif row.reseller_id != reseller.id:
            row.reseller_id = reseller.id
            result.moved[reseller.display_name] = result.moved.get(reseller.display_name, 0) + 1
        else:
            result.unchanged += 1
    result.missing_in_panel = sum(1 for name in existing if name not in seen)
    return result


def report_text(result: SyncResult, sample: int = 8) -> str:
    lines = ["✅ Sync users owners انجام شد", "━━━━━━━━━━━━━━",
             f"🔎 کاربران بررسی‌شده در پنل: {result.scanned}",
             f"➕ به لیست ریسلرها اضافه شد: {result.added_total}",
             f"🔁 مالک اصلاح شد: {result.moved_total}",
             f"✔️ از قبل درست بود: {result.unchanged}",
             f"➖ بدون note مالکیت: {result.no_owner}"]
    if result.unknown_owners:
        names = "، ".join(f"{name} ({count})" for name, count in sorted(result.unknown_owners.items(), key=lambda kv: -kv[1])[:sample])
        lines.append(f"❓ مالک ناشناس: {sum(result.unknown_owners.values())} → {names}")
    if result.missing_in_panel:
        lines.append(f"🗂 رکورد محلی که دیگر در پنل نیست: {result.missing_in_panel} (حذف نشد)")
    if result.added:
        lines += ["", "اضافه‌شده به تفکیک ریسلر:"] + [f"• {name}: {count}" for name, count in sorted(result.added.items(), key=lambda kv: -kv[1])[:sample]]
    if result.moved:
        lines += ["", "مالک اصلاح‌شده به تفکیک ریسلر:"] + [f"• {name}: {count}" for name, count in sorted(result.moved.items(), key=lambda kv: -kv[1])[:sample]]
    if result.unknown_owners:
        lines += ["", "ℹ️ «مالک ناشناس» یعنی نامِ داخل note با نام نمایشی هیچ ریسلری یکی نیست (مثلاً نام ریسلر بعداً عوض شده)."]
    return "\n".join(lines)
