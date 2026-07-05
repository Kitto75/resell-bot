from __future__ import annotations
import asyncio, logging
from typing import Any
import aiohttp

logger = logging.getLogger(__name__)

class MarzbanError(RuntimeError): pass

class MarzbanClient:
    def __init__(self, base_url: str, username: str, password: str) -> None:
        self.base_url = base_url.rstrip("/"); self.username = username; self.password = password; self._token: str | None = None
    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        headers = kwargs.pop("headers", {})
        if self._token: headers["Authorization"] = f"Bearer {self._token}"
        for attempt in range(3):
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
                async with session.request(method, f"{self.base_url}{path}", headers=headers, **kwargs) as resp:
                    if resp.status == 401 and path != "/api/admin/token":
                        self._token = None; await self.login(); continue
                    if resp.status >= 400:
                        text = await resp.text(); logger.warning("Marzban API error %s: %s", resp.status, text)
                        if attempt < 2 and resp.status >= 500: await asyncio.sleep(1 + attempt); continue
                        raise MarzbanError(text)
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
        return await self._request("POST", "/api/user", json=payload)
    async def modify_user(self, username: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self._token: await self.login()
        return await self._request("PUT", f"/api/user/{username}", json=payload)
