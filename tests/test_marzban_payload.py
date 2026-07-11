import os
import unittest

os.environ.setdefault("BOT_TOKEN", "123:test")
os.environ.setdefault("ADMIN_IDS", "1")
os.environ.setdefault("MARZBAN_BASE_URL", "https://example.test")
os.environ.setdefault("MARZBAN_USERNAME", "admin")
os.environ.setdefault("MARZBAN_PASSWORD", "pass")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from app.services.marzban import create_payload_summary, on_hold_expire_duration, prepare_create_payload, redact_secrets


class MarzbanCreatePayloadTests(unittest.TestCase):
    def test_on_hold_user_uses_on_hold_duration_without_expire(self):
        payload = {
            "username": "test_user",
            "status": "on_hold",
            "data_limit": 1024,
            "proxies": {"vless": {}},
            "inbounds": {"vless": ["VLESS TCP"]},
            "expire": 1_720_000_000,
            "validity_days": 30,
        }

        prepared = prepare_create_payload(payload, payload["validity_days"])

        self.assertEqual(prepared["status"], "on_hold")
        self.assertNotIn("expire", prepared)
        self.assertNotIn("validity_days", prepared)
        self.assertEqual(prepared["on_hold_expire_duration"], 2_592_000)

    def test_existing_on_hold_duration_is_preserved_and_expire_removed(self):
        prepared = prepare_create_payload(
            {"username": "test_user", "status": "on_hold", "expire": 1, "on_hold_expire_duration": 86_400, "proxies": {"vless": {}}, "inbounds": {"vless": ["VLESS TCP"]}},
            validity_days=30,
        )

        self.assertNotIn("expire", prepared)
        self.assertEqual(prepared["on_hold_expire_duration"], 86_400)

    def test_on_hold_duration_must_be_positive(self):
        with self.assertRaises(ValueError):
            prepare_create_payload({"username": "test_user", "status": "on_hold", "on_hold_expire_duration": -1, "proxies": {"vless": {}}, "inbounds": {"vless": ["VLESS TCP"]}})

    def test_on_hold_expire_duration_converts_days_to_seconds(self):
        self.assertEqual(on_hold_expire_duration(30), 2_592_000)

    def test_payload_requires_proxy_template(self):
        with self.assertRaises(ValueError):
            prepare_create_payload({"username": "test_user", "status": "active"})

    def test_payload_summary_includes_schema_keys(self):
        summary = create_payload_summary({"username": "u", "status": "on_hold", "data_limit": 1, "on_hold_expire_duration": 86400, "proxies": {"vless": {}, "vmess": {}}, "inbounds": {"vless": ["a", "b"]}, "data_limit_reset_strategy": "no_reset", "note": "belongs to r"})

        self.assertEqual(summary["proxies_keys"], ["vless", "vmess"])
        self.assertEqual(summary["inbound_tags_count"], 2)
        self.assertEqual(summary["data_limit_reset_strategy"], "no_reset")

    def test_redact_secrets_for_logging(self):
        redacted = redact_secrets({"username": "u", "password": "p", "nested": {"access_token": "secret"}})

        self.assertEqual(redacted["username"], "u")
        self.assertEqual(redacted["password"], "***")
        self.assertEqual(redacted["nested"]["access_token"], "***")


if __name__ == "__main__":
    unittest.main()

class MarzbanErrorTests(unittest.TestCase):
    def test_error_keeps_status_code(self):
        from app.services.marzban import MarzbanError

        exc = MarzbanError("Internal Server Error", 500)

        self.assertEqual(exc.status, 500)
        self.assertEqual(str(exc), "Internal Server Error")


class MarzbanCreateUserTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_user_disables_5xx_retry(self):
        from app.services.marzban import MarzbanClient

        captured = {}

        class FakeClient(MarzbanClient):
            async def login(self):
                self._token = "token"

            async def _request(self, method, path, *, retry_5xx=True, **kwargs):
                captured["method"] = method
                captured["path"] = path
                captured["retry_5xx"] = retry_5xx
                captured["json"] = kwargs["json"]
                return {"ok": True}

        await FakeClient("https://example.test", "admin", "pass").create_user({"username": "u", "status": "active", "proxies": {"vless": {}}, "inbounds": {"vless": ["VLESS TCP"]}})

        self.assertEqual(captured["method"], "POST")
        self.assertEqual(captured["path"], "/api/user")
        self.assertFalse(captured["retry_5xx"])
        self.assertEqual(captured["json"]["username"], "u")

    async def test_admin_user_management_methods_use_expected_endpoints_and_payloads(self):
        from app.services.marzban import MarzbanClient

        calls = []

        class FakeClient(MarzbanClient):
            async def login(self):
                self._token = "token"

            async def _request(self, method, path, *, retry_5xx=True, **kwargs):
                calls.append((method, path, kwargs.get("json")))
                return {"ok": True}

        client = FakeClient("https://example.test", "admin", "pass")

        await client.disable_user("u")
        await client.enable_user("u")
        await client.delete_user("u")

        self.assertEqual(calls[0], ("PUT", "/api/user/u", {"status": "disabled"}))
        self.assertEqual(calls[1], ("PUT", "/api/user/u", {"status": "active"}))
        self.assertEqual(calls[2], ("DELETE", "/api/user/u", None))


class MarzbanTemplateTests(unittest.IsolatedAsyncioTestCase):
    async def test_build_create_payload_uses_existing_user_template(self):
        from app.services.marzban import MarzbanClient

        class FakeClient(MarzbanClient):
            async def login(self):
                self._token = "token"

            async def list_users(self, limit=50):
                return [{"username": "sample", "proxies": {"vless": {"flow": ""}}, "inbounds": {"vless": ["VLESS TCP", "VLESS WS"]}}]

        payload = await FakeClient("https://example.test", "admin", "pass").build_create_payload({"username": "new", "status": "on_hold", "validity_days": 15}, ["VLESS TCP"])

        self.assertEqual(payload["proxies"], {"vless": {"flow": ""}})
        self.assertEqual(payload["inbounds"], {"vless": ["VLESS TCP"]})
        self.assertEqual(payload["data_limit_reset_strategy"], "no_reset")
        self.assertNotIn("expire", payload)

    async def test_build_create_payload_falls_back_to_inbounds(self):
        from app.services.marzban import MarzbanClient

        class FakeClient(MarzbanClient):
            async def login(self):
                self._token = "token"

            async def list_users(self, limit=50):
                return []

            async def get_inbounds(self):
                return [{"protocol": "vless", "tag": "VLESS TCP"}, {"protocol": "vmess", "tag": "VMess TCP"}]

        payload = await FakeClient("https://example.test", "admin", "pass").build_create_payload({"username": "new", "status": "on_hold", "validity_days": 1}, [])

        self.assertEqual(payload["proxies"], {"vless": {}, "vmess": {}})
        self.assertEqual(payload["inbounds"], {"vless": ["VLESS TCP"], "vmess": ["VMess TCP"]})

class MarzbanOnHoldSafetyTests(unittest.TestCase):
    def test_on_hold_payload_removes_activation_fields(self):
        prepared = prepare_create_payload(
            {
                "username": "test_user",
                "status": "on_hold",
                "expire": 1_720_000_000,
                "on_hold_timeout": 123,
                "activation_deadline": 456,
                "on_hold_expire_duration": 86_400,
                "proxies": {"vless": {}},
                "inbounds": {"vless": ["VLESS TCP"]},
            },
            validity_days=1,
        )

        self.assertEqual(prepared["status"], "on_hold")
        self.assertEqual(prepared["on_hold_expire_duration"], 86_400)
        self.assertNotIn("expire", prepared)
        self.assertNotIn("on_hold_timeout", prepared)
        self.assertNotIn("activation_deadline", prepared)

    def test_on_hold_payload_drops_usage_state_and_link_fields(self):
        prepared = prepare_create_payload(
            {
                "username": "test_user",
                "status": "on_hold",
                "data_limit": 1024,
                "used_traffic": 99,
                "lifetime_used_traffic": 100,
                "online_at": "now",
                "last_connected": "client",
                "links": ["https://example.test/sub"],
                "subscription_url": "https://example.test/sub",
                "on_hold_expire_duration": 86_400,
                "proxies": {"vless": {}},
                "inbounds": {"vless": ["VLESS TCP"]},
            },
            validity_days=1,
        )

        self.assertEqual(set(prepared), {"username", "status", "data_limit", "on_hold_expire_duration", "proxies", "inbounds", "data_limit_reset_strategy"})
        self.assertEqual(prepared["status"], "on_hold")


class MarzbanCreateSafetyFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_user_safely_fetches_created_user_without_subscription(self):
        from app.handlers import reseller as reseller_handler
        from app.handlers.reseller import create_user_safely
        from app.services.marzban import ownership_note

        calls = []

        class FakeClient:
            async def get_user(self, username):
                calls.append(("get_user", username))
                if calls.count(("get_user", username)) == 1:
                    from app.services.marzban import MarzbanError
                    raise MarzbanError("not found", 404)
                return {"username": username, "status": "on_hold", "used_traffic": 0, "online": False, "expire": None, "note": ownership_note("reseller")}

            async def create_user(self, payload):
                calls.append(("create_user", payload["username"]))
                return {"ok": True}

            async def modify_user(self, username, payload):  # pragma: no cover - must not be called
                calls.append(("modify_user", username))

        reseller_handler.POST_CREATE_VERIFY_DELAY_SECONDS = 0
        ok, message, error, created = await create_user_safely(FakeClient(), {"username": "new_user"}, "reseller")

        self.assertTrue(ok)
        self.assertIsNone(message)
        self.assertIsNone(error)
        self.assertEqual(created["status"], "on_hold")
        self.assertEqual([call[0] for call in calls], ["get_user", "create_user", "get_user", "get_user"])

    async def test_create_user_safely_does_not_modify_active_user_after_create(self):
        from app.handlers import reseller as reseller_handler
        from app.handlers.reseller import create_user_safely
        from app.services.marzban import MarzbanError, ownership_note

        class FakeClient:
            def __init__(self):
                self.gets = 0
                self.modified = False

            async def get_user(self, username):
                self.gets += 1
                if self.gets == 1:
                    raise MarzbanError("not found", 404)
                return {"username": username, "status": "active", "used_traffic": 0, "online": False, "expire": 123, "note": ownership_note("reseller")}

            async def create_user(self, payload):
                return {"ok": True}

            async def modify_user(self, username, payload):
                self.modified = True
                return {"ok": True}

        fake = FakeClient()
        reseller_handler.POST_CREATE_VERIFY_DELAY_SECONDS = 0
        ok, _, _, created = await create_user_safely(fake, {"username": "new_user"}, "reseller")

        self.assertTrue(ok)
        self.assertFalse(fake.modified)
        self.assertEqual(created["status"], "active")

class MarzbanUserAgentExtractorTests(unittest.TestCase):
    def test_no_connection_history_is_unknown(self):
        from app.services.marzban import extract_last_user_agent
        self.assertEqual(extract_last_user_agent({"username": "u", "ip": "1.2.3.4"}), "نامشخص")

    def test_top_level_user_agent_exact(self):
        from app.services.marzban import extract_last_user_agent
        self.assertEqual(extract_last_user_agent({"user_agent": "Hiddify/2.0 Android"}), "Hiddify/2.0 Android")

    def test_multiple_devices_uses_latest_timestamp(self):
        from app.services.marzban import extract_last_user_agent
        data = {"devices": [{"user_agent": "OldApp/1.0", "last_online": 10}, {"user_agent": "NewApp/2.0", "last_online": 20}]}
        self.assertEqual(extract_last_user_agent(data), "NewApp/2.0")

    def test_sub_last_user_agent_exact(self):
        from app.services.marzban import extract_last_user_agent
        self.assertEqual(extract_last_user_agent({"sub_last_user_agent": "HiddifyNext/2.5.7 (Android)"}), "HiddifyNext/2.5.7 (Android)")

    def test_sub_last_user_agent_rejects_proxy_link(self):
        from app.services.marzban import extract_last_user_agent
        self.assertEqual(extract_last_user_agent({"sub_last_user_agent": "vless://example"}), "نامشخص")

    def test_sub_last_user_agent_empty_is_unknown(self):
        from app.services.marzban import extract_last_user_agent
        self.assertEqual(extract_last_user_agent({"sub_last_user_agent": ""}), "نامشخص")

    def test_sub_last_user_agent_preferred_over_nested_fallback(self):
        from app.services.marzban import extract_last_user_agent
        data = {"sub_last_user_agent": "HiddifyNext/2.5.7 (Android)", "devices": [{"user_agent": "NestedApp/9.9", "last_online": 999}]}
        self.assertEqual(extract_last_user_agent(data), "HiddifyNext/2.5.7 (Android)")

    def test_missing_and_unexpected_format_no_crash(self):
        from app.services.marzban import extract_last_user_agent
        self.assertEqual(extract_last_user_agent({"usages": ["bad", {"ip": "1.2.3.4"}], "links": ["https://example.test/sub"]}), "نامشخص")

    def test_direct_last_user_agent(self):
        from app.services.marzban import extract_last_user_agent
        self.assertEqual(extract_last_user_agent({"last_user_agent": "v2rayNG/1.8.19 Android"}), "v2rayNG/1.8.19 Android")

    def test_nested_online_clients_dict_uses_latest_timestamp(self):
        from app.services.marzban import extract_last_user_agent
        data = {
            "online_clients": {
                "1.2.3.4": {"ip": "1.2.3.4", "app": "OldApp", "last_online": 100},
                "5.6.7.8": {"ip": "5.6.7.8", "user_agent": "Hiddify/2.5 iOS", "last_online": 200},
            }
        }
        self.assertEqual(extract_last_user_agent(data), "Hiddify/2.5 iOS")

    def test_nested_usages_app_device_fields(self):
        from app.services.marzban import extract_last_user_agent
        data = {"usages": {"vless-in": [{"device": "Android", "client_name": "v2rayNG", "updated_at": "2026-07-07T10:00:00Z"}]}}
        self.assertEqual(extract_last_user_agent(data), "v2rayNG / Android")

    def test_nested_sessions_client_fields(self):
        from app.services.marzban import extract_last_user_agent
        data = {"sessions": [{"client": {"app_name": "NekoBox", "app_version": "1.3.4"}, "connected_at": 12345}]}
        self.assertEqual(extract_last_user_agent(data), "NekoBox / 1.3.4")

    def test_marzban_user_agents_list_uses_latest_timestamp(self):
        from app.services.marzban import extract_last_user_agent
        data = {
            "username": "u",
            "status": "active",
            "data_limit": 10_000,
            "used_traffic": 5_000,
            "expire": 1_800_000_000,
            "user_agents": [
                {"user_agent": "v2rayNG/1.8.17 Android", "last_online": 100},
                {"user_agent": "Hiddify/2.0.5 iOS", "last_online": 200},
            ],
        }
        self.assertEqual(extract_last_user_agent(data), "Hiddify/2.0.5 iOS")

    def test_nested_user_agent_object(self):
        from app.services.marzban import extract_last_user_agent
        data = {"user_agent": {"value": "Streisand/1.6.8 iOS", "last_connected_at": "2026-07-07T10:00:00Z"}}
        self.assertEqual(extract_last_user_agent(data), "Streisand/1.6.8 iOS")

    def test_marzban_user_agents_mapping_key(self):
        from app.services.marzban import extract_last_user_agent
        data = {"user_agents": {"v2rayNG/1.8.19 Android": 3}}
        self.assertEqual(extract_last_user_agent(data), "v2rayNG/1.8.19 Android")

    def test_activity_data_with_traffic_and_expire_fields(self):
        from app.services.marzban import extract_last_user_agent
        data = {
            "data_limit": 100,
            "used_traffic": 50,
            "expire": 1_800_000_000,
            "activity": [{"client_name": "Karing", "platform": "Android", "timestamp": 10}],
        }
        self.assertEqual(extract_last_user_agent(data), "Karing / Android")

    def test_rejects_subscription_links_protocols_usernames_and_ips(self):
        from app.services.marzban import extract_last_user_agent
        bad_values = [
            {"last_user_agent": "https://example.test/sub/u"},
            {"online_clients": [{"client": "vless", "ip": "192.0.2.1"}]},
            {"usages": {"vless": [{"user_agent": "203.0.113.9"}]}},
            {"sessions": [{"username": "alice", "link": "vmess://secret"}]},
            {"user_agents": ["vless://example", "trojan://example", "https://example.test/sub/u"]},
        ]
        for payload in bad_values:
            with self.subTest(payload=payload):
                self.assertEqual(extract_last_user_agent(payload), "نامشخص")

class MarzbanResetUsageTests(unittest.IsolatedAsyncioTestCase):
    async def test_reset_user_usage_uses_single_user_reset_endpoint(self):
        from app.services.marzban import MarzbanClient

        calls = []

        class FakeClient(MarzbanClient):
            async def login(self):
                self._token = "token"
            async def _request(self, method, path, **kwargs):
                calls.append((method, path, kwargs))
                return {"ok": True}

        client = FakeClient("https://example.test", "admin", "password")
        await client.reset_user_usage("alice")
        self.assertEqual(calls[0][0], "POST")
        self.assertEqual(calls[0][1], "/api/user/alice/reset")
