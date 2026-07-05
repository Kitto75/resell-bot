import unittest

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
