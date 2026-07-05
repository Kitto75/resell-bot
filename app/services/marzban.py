from __future__ import annotations
import asyncio, logging
from typing import Any
import aiohttp

logger = logging.getLogger(__name__)

_SECRET_KEYS = {"token", "access_token", "authorization", "password", "passwd", "secret", "api_key", "apikey"}
_INTERNAL_CREATE_KEYS = {"validity_days"}

class MarzbanError(RuntimeError):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.message = message

class MarzbanClient:
    def __init__(self, base_url: str, username: str, password: str) -> None:
        self.base_url = base_url.rstrip("/"); self.username = username; self.password = password; self._token: str | None = None
    async def _request(self, method: str, path: str, *, retry_5xx: bool = True, **kwargs: Any) -> Any:
        headers = kwargs.pop("headers", {})
        if self._token: headers["Authorization"] = f"Bearer {self._token}"
        max_attempts = 3 if retry_5xx else 1
        for attempt in range(max_attempts):
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
                async with session.request(method, f"{self.base_url}{path}", headers=headers, **kwargs) as resp:
                    logger.info("Marzban API response status method=%s path=%s status=%s attempt=%s", method, path, resp.status, attempt + 1)
                    if resp.status == 401 and path != "/api/admin/token":
                        self._token = None; await self.login(); continue
                    if resp.status >= 400:
                        text = await resp.text(); logger.warning("Marzban API error %s: %s", resp.status, text)
                        if retry_5xx and attempt < max_attempts - 1 and resp.status >= 500: await asyncio.sleep(1 + attempt); continue
                        raise MarzbanError(text, resp.status)
                    if resp.content_type == "application/json": return await resp.json()
                    return await resp.text()
        raise MarzbanError("Marzban request failed after retries")
    async def login(self) -> None:
        data = {"username": self.username, "password": self.password}
        result = await self._request("POST", "/api/admin/token", data=data)
        self._token = result.get("access_token")
    async def get_inbounds(self) -> list[dict[str, Any]]:
        if not self._token: await self.login()
        data = await self._request("GET", "/api/inbounds")
        if isinstance(data, dict):
            return [item for items in data.values() for item in (items if isinstance(items, list) else [])]
        return data
    async def get_user(self, username: str) -> dict[str, Any]:
        if not self._token: await self.login()
        return await self._request("GET", f"/api/user/{username}")
    async def create_user(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self._token: await self.login()
        sanitized_payload = prepare_create_payload(payload, payload.get("validity_days"))
        logger.info("Sending sanitized Marzban create-user payload: %s", redact_secrets(sanitized_payload))
        logger.info("Marzban create-user attempt username=%s", sanitized_payload.get("username"))
        return await self._request("POST", "/api/user", json=sanitized_payload, retry_5xx=False)
    async def modify_user(self, username: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self._token: await self.login()
        return await self._request("PUT", f"/api/user/{username}", json=payload)

def ownership_note(display_name: str) -> str:
    return f"belongs to {display_name}"


def user_belongs_to_reseller(user_data: dict[str, Any], display_name: str) -> bool:
    return str(user_data.get("note") or "").strip() == ownership_note(display_name)


def on_hold_expire_duration(days: int) -> int:
    # Marzban expects on-hold duration in seconds; account validity `expire` remains separate.
    return max(1, int(days)) * 86400


def redact_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: ("***" if str(key).lower() in _SECRET_KEYS else redact_secrets(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    return value


def prepare_create_payload(payload: dict[str, Any], validity_days: int | None = None) -> dict[str, Any]:
    prepared = {key: value for key, value in payload.items() if key not in _INTERNAL_CREATE_KEYS}
    if prepared.get("status") == "on_hold":
        prepared.pop("expire", None)
        prepared["status"] = "on_hold"
        if not prepared.get("on_hold_expire_duration"):
            prepared["on_hold_expire_duration"] = on_hold_expire_duration(validity_days or 1)
        prepared["on_hold_expire_duration"] = int(prepared["on_hold_expire_duration"])
        if prepared["on_hold_expire_duration"] <= 0:
            raise ValueError("on_hold_expire_duration must be greater than zero for on_hold users")
    return prepared


def extract_last_user_agent(user_data: dict[str, Any]) -> str:
    for key in ("last_connected_user_agent", "last_user_agent", "user_agent", "last_connected_device", "last_connected", "last_online", "online_at"):
        value = user_data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            for nested in ("user_agent", "agent", "app", "device", "name"):
                nested_value = value.get(nested)
                if nested_value:
                    return str(nested_value)
    for key in ("devices", "usages"):
        values = user_data.get(key)
        if isinstance(values, list):
            for item in reversed(values):
                if isinstance(item, dict):
                    found = extract_last_user_agent(item)
                    if found != "نامشخص":
                        return found
    return "نامشخص"
