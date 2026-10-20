"""State + rules of the checkbox group picker used when adding a reseller and for the global group assignment.

Default = NOTHING selected. The admin must either press "all groups" or pick at least one group."""
from __future__ import annotations

from typing import Any

from app.services.marzban import MarzbanError


async def load_group_picker(client) -> dict[str, Any] | None:
    """Enabled panel groups as picker state. Returns None when the panel has no enabled group.
    Raises MarzbanError when the panel can't be read."""
    groups = await client.get_inbounds()
    names = sorted({g["tag"] for g in groups if not g.get("is_disabled")})
    if not names:
        return None
    return {"names": names, "selected": [], "mode": "custom", "disabled": sum(1 for g in groups if g.get("is_disabled"))}


def set_all(picker: dict[str, Any]) -> dict[str, Any]:
    return {**picker, "mode": "all"}


def toggle(picker: dict[str, Any], index: int) -> dict[str, Any] | None:
    names = picker["names"]
    if not 0 <= index < len(names):
        return None
    current = set(names if picker["mode"] == "all" else picker.get("selected") or [])
    current.symmetric_difference_update({names[index]})
    return {**picker, "mode": "custom", "selected": [n for n in names if n in current]}


def validate(picker: dict[str, Any]) -> str | None:
    if picker["mode"] == "custom" and not picker.get("selected"):
        return "حداقل یک گروه انتخاب کنید یا «همه گروه‌ها» را بزنید."
    return None


def result_tags(picker: dict[str, Any]) -> list[str]:
    """[] means "all groups" (no restriction) - the same meaning the rest of the bot uses."""
    return [] if picker["mode"] == "all" else list(picker["selected"])


__all__ = ["MarzbanError", "load_group_picker", "set_all", "toggle", "validate", "result_tags"]
