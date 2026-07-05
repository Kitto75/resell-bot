import re
USERNAME_RE = re.compile(r"^[a-z0-9_]+$")

def valid_username(username: str) -> bool:
    return bool(USERNAME_RE.fullmatch(username))
