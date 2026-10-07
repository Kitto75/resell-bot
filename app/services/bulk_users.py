"""Enable / disable all panel users of a reseller, quickly and without touching accounts that don't need it."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from app.services.marzban import MarzbanClient, MarzbanError

logger = logging.getLogger(__name__)

# disable: only accounts that are currently usable.  enable: only accounts that are currently disabled.
# Expired / limited accounts are never touched: "enabling" them would not renew them and could
# silently change their state (and on_hold accounts must not be flipped by an enable-all).
TARGET_STATUSES = {"disable": {"active", "on_hold"}, "enable": {"disabled"}}
BULK_CHUNK = 200
FALLBACK_CONCURRENCY = 5


def panel_status(user: dict[str, Any]) -> str:
    return str(getattr(user.get("status"), "value", user.get("status")) or "unknown")


@dataclass
class BulkPlan:
    action: str
    total: int
    by_status: dict[str, int] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    targets: list[dict[str, Any]] = field(default_factory=list)

    @property
    def change_count(self) -> int:
        return len(self.targets)

    @property
    def unchanged_count(self) -> int:
        return self.total - len(self.missing) - len(self.targets)


@dataclass
class BulkResult:
    plan: BulkPlan
    changed: int = 0
    failed: list[str] = field(default_factory=list)


def build_plan(action: str, usernames: list[str], panel_users: list[dict[str, Any]]) -> BulkPlan:
    by_name = {str(u.get("username")): u for u in panel_users if u.get("username")}
    plan = BulkPlan(action=action, total=len(usernames))
    for name in usernames:
        user = by_name.get(name)
        if user is None:
            plan.missing.append(name)
            continue
        status = panel_status(user)
        plan.by_status[status] = plan.by_status.get(status, 0) + 1
        if status in TARGET_STATUSES[action] and isinstance(user.get("id"), int):
            plan.targets.append(user)
    return plan


async def fetch_plan(client: MarzbanClient, action: str, usernames: list[str]) -> BulkPlan:
    return build_plan(action, usernames, await client.list_users_by_usernames(usernames))


async def execute_plan(client: MarzbanClient, plan: BulkPlan) -> BulkResult:
    disabled = plan.action == "disable"
    result = BulkResult(plan=plan)
    semaphore = asyncio.Semaphore(FALLBACK_CONCURRENCY)

    async def one_by_one(user: dict[str, Any]) -> tuple[str, bool]:
        async with semaphore:
            try:
                await (client.disable_user if disabled else client.enable_user)(user["username"])
                return user["username"], True
            except MarzbanError as exc:
                logger.warning("Bulk %s failed username=%s status=%s", plan.action, user["username"], exc.status)
                return user["username"], False

    for start in range(0, len(plan.targets), BULK_CHUNK):
        chunk = plan.targets[start:start + BULK_CHUNK]
        done: set[str] = set()
        try:
            done = set(await client.bulk_set_disabled([u["id"] for u in chunk], disabled))
        except MarzbanError as exc:
            logger.warning("Panel bulk %s endpoint failed status=%s; falling back to per-user calls", plan.action, exc.status)
        remaining = [u for u in chunk if u["username"] not in done]
        outcomes = await asyncio.gather(*(one_by_one(u) for u in remaining)) if remaining else []
        result.changed += len(done) + sum(1 for _, ok in outcomes if ok)
        result.failed.extend(name for name, ok in outcomes if not ok)
    return result
