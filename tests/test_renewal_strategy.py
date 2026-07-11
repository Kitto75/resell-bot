from app.services.renewal import BYTES_PER_GB, RenewalMode, calculate_renewal, normalize_renewal_mode


def test_missing_setting_defaults_to_additive():
    assert normalize_renewal_mode(None) is RenewalMode.additive


def test_invalid_setting_defaults_to_additive():
    assert normalize_renewal_mode("bad") is RenewalMode.additive


def test_additive_data_limit_adds_entered_gb():
    calc = calculate_renewal({"data_limit": 50 * BYTES_PER_GB, "expire": 1_000}, 60, 31, "additive", now_ts=500)
    assert calc.resulting_data_limit == 110 * BYTES_PER_GB
    assert calc.reset_required is False


def test_additive_expire_adds_days_to_current_expire_when_future():
    now = 1_700_000_000
    calc = calculate_renewal({"data_limit": 0, "expire": now + 10 * 86400}, 1, 31, "additive", now_ts=now)
    assert calc.resulting_expire == now + 41 * 86400


def test_replace_data_limit_replaces_entered_gb():
    calc = calculate_renewal({"data_limit": 50 * BYTES_PER_GB, "used_traffic": 20 * BYTES_PER_GB, "expire": 1_000}, 60, 31, "replace", now_ts=500)
    assert calc.resulting_data_limit == 60 * BYTES_PER_GB


def test_replace_expire_uses_now_plus_entered_days():
    now = 1_700_000_000
    calc = calculate_renewal({"data_limit": 0, "expire": now + 10 * 86400}, 1, 31, "replace", now_ts=now)
    assert calc.resulting_expire == now + 31 * 86400
    assert calc.reset_required is True


def test_replace_mode_requires_usage_reset():
    calc = calculate_renewal({"data_limit": 50 * BYTES_PER_GB, "used_traffic": 20 * BYTES_PER_GB}, 60, 31, "replace", now_ts=500)
    assert calc.reset_required is True
