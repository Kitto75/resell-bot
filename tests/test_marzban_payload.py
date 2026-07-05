import unittest

from app.services.marzban import on_hold_expire_duration, prepare_create_payload, redact_secrets


class MarzbanCreatePayloadTests(unittest.TestCase):
    def test_on_hold_user_uses_on_hold_duration_without_expire(self):
        payload = {
            "username": "test_user",
            "status": "on_hold",
            "data_limit": 1024,
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
            {"username": "test_user", "status": "on_hold", "expire": 1, "on_hold_expire_duration": 86_400},
            validity_days=30,
        )

        self.assertNotIn("expire", prepared)
        self.assertEqual(prepared["on_hold_expire_duration"], 86_400)

    def test_on_hold_duration_must_be_positive(self):
        with self.assertRaises(ValueError):
            prepare_create_payload({"username": "test_user", "status": "on_hold", "on_hold_expire_duration": -1})

    def test_on_hold_expire_duration_converts_days_to_seconds(self):
        self.assertEqual(on_hold_expire_duration(30), 2_592_000)

    def test_redact_secrets_for_logging(self):
        redacted = redact_secrets({"username": "u", "password": "p", "nested": {"access_token": "secret"}})

        self.assertEqual(redacted["username"], "u")
        self.assertEqual(redacted["password"], "***")
        self.assertEqual(redacted["nested"]["access_token"], "***")


if __name__ == "__main__":
    unittest.main()
