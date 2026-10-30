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

