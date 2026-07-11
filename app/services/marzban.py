from __future__ import annotations
import asyncio, logging
from typing import Any
import aiohttp
from urllib.parse import urljoin

logger = logging.getLogger(__name__)

_SECRET_KEYS = {"token", "access_token", "authorization", "password", "passwd", "secret", "api_key", "apikey"}
_INTERNAL_CREATE_KEYS = {"validity_days"}
_SAFE_CREATE_KEYS = {"username", "status", "data_limit", "on_hold_expire_duration", "proxies", "inbounds", "data_limit_reset_strategy", "note"}
_ON_HOLD_ACTIVATION_KEYS = {"expire", "on_hold_timeout", "on_hold_timeout_duration", "activation_deadline", "activate_at", "active_at"}

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
                        text = await resp.text(); logger.warning("Marzban API error method=%s path=%s status=%s body=%s", method, path, resp.status, text)
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
            flattened: list[dict[str, Any]] = []
            for protocol, items in data.items():
                for item in (items if isinstance(items, list) else []):
                    if isinstance(item, dict):
                        flattened.append({"protocol": item.get("protocol") or protocol, **item})
                    else:
                        flattened.append({"protocol": protocol, "tag": str(item)})
            return flattened
        return data
    async def list_users(self, limit: int = 50) -> list[dict[str, Any]]:
        if not self._token: await self.login()
        data = await self._request("GET", f"/api/users?limit={limit}")
        if isinstance(data, dict):
            users = data.get("users") or data.get("items") or []
            return [user for user in users if isinstance(user, dict)]
        return [user for user in data if isinstance(user, dict)] if isinstance(data, list) else []
    def absolute_subscription_url(self, value: str | None) -> str | None:
        if not value or not value.strip():
            return None
        value = value.strip()
        if value.startswith(("http://", "https://")):
            return value
        return urljoin(f"{self.base_url}/", value.lstrip("/"))
    async def get_user(self, username: str) -> dict[str, Any]:
        if not self._token: await self.login()
        data = await self._request("GET", f"/api/user/{username}")
        if isinstance(data, dict):
            log_user_agent_debug(username, data)
        return data
    async def get_user_with_activity(self, username: str) -> dict[str, Any]:
        data = await self.get_user(username)
        if not isinstance(data, dict):
            return data
        # Marzban deployments differ; collect client/session details from optional endpoints when present.
        for label, path in {
            "usage_details": f"/api/user/{username}/usage",
            "online_clients": f"/api/user/{username}/online_clients",
            "statistics": f"/api/user/{username}/statistics",
        }.items():
            try:
                extra = await self._request("GET", path)
            except MarzbanError as exc:
                if exc.status in {404, 405}:
                    logger.debug("Marzban optional user-agent endpoint unavailable username=%s endpoint=%s status=%s", username, path, exc.status)
                    continue
                logger.warning("Marzban optional user-agent endpoint failed username=%s endpoint=%s status=%s", username, path, exc.status)
                continue
            data[label] = extra
        log_user_agent_debug(username, data)
        return data
    async def create_user(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self._token: await self.login()
        sanitized_payload = prepare_create_payload(payload, payload.get("validity_days"))
        logger.info("Marzban create-user sanitized payload summary: %s", create_payload_summary(sanitized_payload))
        logger.debug("Marzban create-user sanitized payload: %s", redact_secrets(sanitized_payload))
        logger.info("Marzban create-user attempt username=%s", sanitized_payload.get("username"))
        try:
            return await self._request("POST", "/api/user", json=sanitized_payload, retry_5xx=False)
        except MarzbanError as exc:
            if exc.status and exc.status >= 500:
                logger.error("Marzban create-user returned %s. This may be a Marzban schema/payload rejection or internal API failure. body=%s payload_summary=%s", exc.status, exc.message, create_payload_summary(sanitized_payload))
            raise
    async def modify_user(self, username: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self._token: await self.login()
        return await self._request("PUT", f"/api/user/{username}", json=payload)
    async def reset_user_usage(self, username: str) -> Any:
        """Reset one user's data usage via Marzban POST /api/user/{username}/reset."""
        if not self._token: await self.login()
        return await self._request("POST", f"/api/user/{username}/reset")
    async def disable_user(self, username: str) -> dict[str, Any]:
        # Marzban toggles user availability through PUT /api/user/{username};
        # the API status value for a temporarily inactive account is "disabled".
        return await self.modify_user(username, {"status": "disabled"})
    async def enable_user(self, username: str) -> dict[str, Any]:
        # Sending only the status preserves data_limit, expire, note, inbounds, proxies and other settings.
        return await self.modify_user(username, {"status": "active"})
    async def delete_user(self, username: str) -> Any:
        if not self._token: await self.login()
        return await self._request("DELETE", f"/api/user/{username}")
    async def build_create_payload(self, payload: dict[str, Any], allowed_inbound_tags: list[str] | None = None) -> dict[str, Any]:
        prepared = {key: value for key, value in payload.items() if key not in _INTERNAL_CREATE_KEYS}
        prepared.setdefault("data_limit_reset_strategy", "no_reset")
        if prepared.get("proxies") and prepared.get("inbounds"):
            return prepare_create_payload(prepared, payload.get("validity_days"))
        template = await self._create_template_from_existing_user(allowed_inbound_tags)
        if template is None:
            template = await self._create_template_from_inbounds(allowed_inbound_tags)
        prepared.update(template)
        return prepare_create_payload(prepared, payload.get("validity_days"))
    async def _create_template_from_existing_user(self, allowed_inbound_tags: list[str] | None = None) -> dict[str, Any] | None:
        try:
            users = await self.list_users(50)
        except MarzbanError as exc:
            logger.warning("Could not fetch Marzban sample users for create template status=%s", exc.status)
            return None
        allowed = set(allowed_inbound_tags or [])
        for user in users:
            proxies = user.get("proxies")
            inbounds = _filter_inbounds(user.get("inbounds"), allowed)
            if isinstance(proxies, dict) and proxies and inbounds:
                logger.info("Using Marzban user template from existing user username=%s payload_summary=%s", user.get("username"), create_payload_summary({"proxies": proxies, "inbounds": inbounds}))
                return {"proxies": proxies, "inbounds": inbounds}
        return None
    async def _create_template_from_inbounds(self, allowed_inbound_tags: list[str] | None = None) -> dict[str, Any]:
        inbounds = await self.get_inbounds()
        allowed = set(allowed_inbound_tags or [])
        grouped: dict[str, list[str]] = {}
        for inbound in inbounds:
            if not isinstance(inbound, dict):
                continue
            tag = inbound.get("tag") or inbound.get("remark")
            protocol = inbound.get("protocol") or inbound.get("type")
            if not tag or not protocol or (allowed and str(tag) not in allowed):
                continue
            grouped.setdefault(str(protocol), []).append(str(tag))
        if not grouped:
            raise MarzbanError("No Marzban inbounds are available to build create-user payload")
        proxies = {protocol: {} for protocol in grouped}
        return {"proxies": proxies, "inbounds": grouped}

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


def _filter_inbounds(value: Any, allowed: set[str]) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        return {}
    filtered: dict[str, list[str]] = {}
    for protocol, tags in value.items():
        if not isinstance(tags, list):
            continue
        selected = [str(tag) for tag in tags if not allowed or str(tag) in allowed]
        if selected:
            filtered[str(protocol)] = selected
    return filtered


def create_payload_summary(payload: dict[str, Any]) -> dict[str, Any]:
    inbounds = payload.get("inbounds") if isinstance(payload.get("inbounds"), dict) else {}
    inbound_counts = {str(protocol): len(tags) for protocol, tags in inbounds.items() if isinstance(tags, list)}
    return {
        "username": payload.get("username"),
        "status": payload.get("status"),
        "data_limit": payload.get("data_limit"),
        "expire": payload.get("expire"),
        "on_hold_expire_duration": payload.get("on_hold_expire_duration"),
        "proxies_keys": sorted((payload.get("proxies") or {}).keys()) if isinstance(payload.get("proxies"), dict) else [],
        "inbound_tags_count": sum(inbound_counts.values()),
        "inbound_counts": inbound_counts,
        "data_limit_reset_strategy": payload.get("data_limit_reset_strategy"),
        "note": payload.get("note"),
        "activation_keys_present": sorted(key for key in _ON_HOLD_ACTIVATION_KEYS if key in payload),
    }


def prepare_create_payload(payload: dict[str, Any], validity_days: int | None = None) -> dict[str, Any]:
    dropped_keys = sorted(key for key in payload if key not in _SAFE_CREATE_KEYS and key not in _INTERNAL_CREATE_KEYS)
    if dropped_keys:
        logger.warning("Dropping unsafe Marzban create-user payload keys username=%s keys=%s", payload.get("username"), dropped_keys)
    prepared = {key: value for key, value in payload.items() if key in _SAFE_CREATE_KEYS}
    prepared.setdefault("data_limit_reset_strategy", "no_reset")
    if not isinstance(prepared.get("proxies"), dict) or not prepared.get("proxies"):
        raise ValueError("Marzban create-user payload requires non-empty proxies")
    if not isinstance(prepared.get("inbounds"), dict) or not prepared.get("inbounds"):
        raise ValueError("Marzban create-user payload requires non-empty inbounds")
    if prepared.get("status") == "on_hold":
        for key in _ON_HOLD_ACTIVATION_KEYS:
            prepared.pop(key, None)
        prepared["status"] = "on_hold"
        if not prepared.get("on_hold_expire_duration"):
            prepared["on_hold_expire_duration"] = on_hold_expire_duration(validity_days or 1)
        prepared["on_hold_expire_duration"] = int(prepared["on_hold_expire_duration"])
        if prepared["on_hold_expire_duration"] <= 0:
            raise ValueError("on_hold_expire_duration must be greater than zero for on_hold users")
    return prepared


_UA_KEYS = (
    # Marzban's user endpoint can expose the latest subscription client directly.
    "sub_last_user_agent",
    # Marzban's user endpoint can expose recent app details in `user_agents`.
    "user_agents", "userAgents",
    "last_user_agent", "last_connected_user_agent", "user_agent", "userAgent", "user_agent_string",
    "userAgentString", "ua", "client_user_agent", "clientUserAgent", "client_ua", "app_user_agent",
)
_DIRECT_UA_KEYS = (
    "sub_last_user_agent",
    "last_user_agent",
    "last_connected_user_agent",
    "user_agent",
    "client_user_agent",
)
_DEVICE_KEYS = (
    "app", "application", "app_name", "app_version", "client", "client_name", "client_version",
    "client_type", "device", "device_name", "device_model", "platform", "os", "browser",
    "last_connected_device", "last_connected_client", "last_connected_app",
)
_ACTIVITY_KEYS = (
    "usages", "usage", "usage_details", "devices", "device", "online_clients", "online_client",
    "last_connected", "sessions", "session", "clients", "client", "activity", "activities", "statistics", "stats", "user_stats",
)
_TIME_KEYS = ("last_online", "online_at", "connected_at", "last_connected_at", "updated_at", "created_at", "time", "timestamp", "date")
_NON_UA_KEYS = {
    "username", "name", "email", "note", "subscription", "subscription_url", "subscription_path", "sub_url",
    "subscription_urls", "subscriptions", "link", "links", "proxy", "proxies", "protocol", "inbound",
    "inbounds", "inbound_tag", "inbound_tags", "tag", "remark", "ip", "ip_address", "address", "host",
    "last_online", "online_at", "port", "uuid", "id", "password",
}
_PROTOCOL_NAMES = {"vmess", "vless", "trojan", "shadowsocks", "ss", "http", "https", "socks", "socks5", "wireguard"}
_UA_MARKERS = ("/", "android", "ios", "iphone", "ipad", "windows", "linux", "mac", "chrome", "firefox", "safari", "v2ray", "nekobox", "hiddify", "streisand", "sing-box", "singbox", "clash", "xray", "foxray", "fair", "napsternet", "nekoray", "v2box", "karing")


def _looks_like_url_or_proxy(value: str) -> bool:
    lowered = value.lower()
    return lowered.startswith(("http://", "https://", "vmess://", "vless://", "trojan://", "ss://", "ssr://", "socks://", "socks5://")) or "://" in lowered


def _looks_like_ip(value: str) -> bool:
    import ipaddress
    try:
        ipaddress.ip_address(value.strip("[]"))
        return True
    except ValueError:
        return False



def _user_agent_rejection_reason(value: Any, key: str | None = None) -> str | None:
    text = str(value or "").strip()
    normalized_key = str(key or "").strip()
    lowered = text.lower()
    if not text:
        return "empty"
    if normalized_key and normalized_key in _NON_UA_KEYS:
        return "not_probable_user_agent"
    if _looks_like_url_or_proxy(text):
        return "looks_like_url"
    if _looks_like_ip(text):
        return "looks_like_ip"
    if lowered in _PROTOCOL_NAMES:
        return "not_probable_user_agent"
    if _is_probable_user_agent(value, key):
        return None
    return "not_probable_user_agent"

def _is_probable_user_agent(value: Any, key: str | None = None) -> bool:
    text = str(value or "").strip()
    normalized_key = str(key or "").strip()
    lowered = text.lower()
    if not text or (normalized_key and normalized_key in _NON_UA_KEYS):
        return False
    if _looks_like_url_or_proxy(text) or _looks_like_ip(text):
        return False
    if lowered in _PROTOCOL_NAMES:
        return False
    # User-Agent-specific fields are trusted after rejecting obvious secrets, links, protocols and IPs.
    if normalized_key in _UA_KEYS:
        return len(text) >= 2
    # App/client/device fields often contain just an app name such as "Hiddify" or "v2rayNG".
    if normalized_key in _DEVICE_KEYS:
        if any(mark in lowered for mark in _UA_MARKERS):
            return True
        if normalized_key.endswith("version") and any(ch.isdigit() for ch in text):
            return True
        return bool(any(ch.isalpha() for ch in text) and not any(sep in text for sep in ("://", "@")))
    return any(mark in lowered for mark in _UA_MARKERS)


def _timestamp_value(item: dict[str, Any]) -> float:
    from datetime import datetime
    for key in _TIME_KEYS:
        value = item.get(key)
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str) and value.strip():
            try:
                return float(value)
            except ValueError:
                try:
                    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
                except ValueError:
                    continue
    return 0.0


def _extract_from_mapping(data: dict[str, Any]) -> str | None:
    for key in _UA_KEYS:
        value = data.get(key)
        if isinstance(value, str) and _is_probable_user_agent(value, key):
            return value.strip()
        if isinstance(value, dict):
            if key in {"user_agents", "userAgents"}:
                for agent_text in value.keys():
                    if _is_probable_user_agent(agent_text, "user_agent"):
                        return str(agent_text).strip()
            for nested_key in ("value", "agent", "userAgent", "user_agent"):
                nested_value = value.get(nested_key)
                if isinstance(nested_value, str) and _is_probable_user_agent(nested_value, "user_agent"):
                    return nested_value.strip()
            nested = _extract_from_mapping(value)
            if nested:
                return nested
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str) and _is_probable_user_agent(item, "user_agent"):
                    return item.strip()
            nested_items = [item for item in _collect_activity_mappings(value, parent_key=key) if isinstance(item, dict)]
            if any(_timestamp_value(item) > 0 for item in nested_items):
                nested_items = sorted(nested_items, key=_timestamp_value, reverse=True)
            for item in nested_items:
                nested = _extract_from_mapping(item)
                if nested:
                    return nested
    parts = []
    for key in _DEVICE_KEYS:
        value = data.get(key)
        if isinstance(value, str) and value.strip() and _is_probable_user_agent(value, key):
            parts.append(value.strip())
    if parts:
        return " / ".join(dict.fromkeys(parts))
    return None


def _collect_activity_mappings(value: Any, *, parent_key: str | None = None) -> list[dict[str, Any]]:
    """Collect nested Marzban activity/client dicts without treating links or proxy config as clients."""
    if isinstance(value, dict):
        items = [value] if parent_key in _ACTIVITY_KEYS or any(key in value for key in (*_UA_KEYS, *_DEVICE_KEYS)) else []
        for key, child in value.items():
            key_text = str(key)
            if key_text in {"links", "subscription_urls", "subscriptions", "proxies", "inbounds"}:
                continue
            if key_text in _ACTIVITY_KEYS or isinstance(child, (dict, list)):
                items.extend(_collect_activity_mappings(child, parent_key=key_text))
        return items
    if isinstance(value, list):
        items: list[dict[str, Any]] = []
        for child in value:
            items.extend(_collect_activity_mappings(child, parent_key=parent_key))
        return items
    return []


def redact_user_agent_debug_fields(value: Any) -> Any:
    """Redact secrets and link-like values before logging Marzban payload snippets."""
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if lowered in _SECRET_KEYS or lowered in {"links", "link", "subscription", "subscription_url", "sub_url", "subscription_urls", "subscriptions"}:
                redacted[key] = "***"
            else:
                redacted[key] = redact_user_agent_debug_fields(item)
        return redacted
    if isinstance(value, list):
        return [redact_user_agent_debug_fields(item) for item in value]
    if isinstance(value, str) and _looks_like_url_or_proxy(value):
        return "***"
    return value


def log_user_agent_debug(username: str, user_data: dict[str, Any]) -> None:
    interesting_keys = (*_UA_KEYS, *_DEVICE_KEYS, *_TIME_KEYS, *_ACTIVITY_KEYS, "links", "subscription_url", "subscription", "sub_url", "configs")
    interesting = {key: redact_user_agent_debug_fields(user_data.get(key)) for key in interesting_keys if key in user_data}
    logger.debug("Marzban user-agent fields username=%s fields=%s", username, interesting)
    if extract_last_user_agent(user_data) == "نامشخص":
        sub_value = user_data.get("sub_last_user_agent") if isinstance(user_data, dict) else None
        sub_exists = isinstance(user_data, dict) and "sub_last_user_agent" in user_data
        sub_rejection_reason = _user_agent_rejection_reason(sub_value, "sub_last_user_agent") if sub_exists else None
        logger.info(
            "Marzban user-agent not found username=%s sub_last_user_agent_exists=%s sub_last_user_agent_rejected_reason=%s safe_payload_structure=%s",
            username,
            sub_exists,
            sub_rejection_reason,
            marzban_payload_debug_structure(user_data),
        )


def marzban_payload_debug_structure(value: Any, *, max_depth: int = 4, max_list_items: int = 3) -> Any:
    """Return a token-safe payload key/type preview for live Marzban debugging."""
    if max_depth < 0:
        return "..."
    if isinstance(value, dict):
        preview = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if lowered in _SECRET_KEYS or lowered in {"links", "link", "subscription", "subscription_url", "sub_url", "subscription_urls", "subscriptions", "configs"}:
                preview[key] = "***"
            elif isinstance(item, (dict, list)):
                preview[key] = marzban_payload_debug_structure(item, max_depth=max_depth - 1, max_list_items=max_list_items)
            else:
                preview[key] = type(item).__name__
        return preview
    if isinstance(value, list):
        return [marzban_payload_debug_structure(item, max_depth=max_depth - 1, max_list_items=max_list_items) for item in value[:max_list_items]]
    return type(value).__name__


def extract_last_user_agent(user_data: dict[str, Any]) -> str:
    """Return latest real client/app User-Agent from a Marzban user payload."""
    if not isinstance(user_data, dict):
        return "نامشخص"

    for key in _DIRECT_UA_KEYS:
        value = user_data.get(key)
        if isinstance(value, str) and _is_probable_user_agent(value, key):
            return value.strip()

    candidates = _collect_activity_mappings(user_data)
    if any(_timestamp_value(item) > 0 for item in candidates):
        for item in sorted(candidates, key=_timestamp_value, reverse=True):
            found = _extract_from_mapping(item)
            if found:
                return found

    found = _extract_from_mapping(user_data)
    if found:
        return found

    for item in candidates:
        found = _extract_from_mapping(item)
        if found:
            return found
    return "نامشخص"
