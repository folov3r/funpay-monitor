from app.config import Settings


def test_default_settings() -> None:
    settings = Settings(_env_file=None)

    assert settings.log_level == "INFO"
    assert settings.vk_group_token == ""
    assert settings.vk_group_id == 0
    assert settings.parse_interval_minutes == 15
    assert settings.request_delay_seconds == 3.0
    assert settings.alert_cooldown_hours == 6


def test_settings_from_env(monkeypatch) -> None:
    monkeypatch.setenv("VK_GROUP_TOKEN", "test-token")
    monkeypatch.setenv("PARSE_INTERVAL_MINUTES", "5")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")

    settings = Settings(_env_file=None)

    assert settings.vk_group_token == "test-token"
    assert settings.parse_interval_minutes == 5
    assert settings.log_level == "DEBUG"
