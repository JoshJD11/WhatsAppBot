import pytest

from bot.config import ConfigError, load_settings

BASE_ENV = {
    "WHATSAPP_TOKEN": "token",
    "WHATSAPP_PHONE_NUMBER_ID": "123",
    "META_APP_SECRET": "secret",
    "WEBHOOK_VERIFY_TOKEN": "verify",
    "GEMINI_MODEL": "some-model",
    "EXCEL_SOURCE": "local",
    "EXCEL_LOCAL_PATH": "data/bosca_bot.xlsx",
}


def test_load_settings_with_minimal_env_uses_defaults():
    settings = load_settings(BASE_ENV)
    assert settings.bot_mode == "rule"
    assert settings.handoff_pause_minutes == 60
    assert settings.graph_api_version == "v26.0"
    assert settings.admin_numbers == frozenset()
    assert settings.state_file == "data/state.json"


def test_load_settings_empty_state_file_disables_saving():
    assert load_settings({**BASE_ENV, "STATE_FILE": ""}).state_file == ""


def test_load_settings_parses_numbers_and_mode():
    env = {**BASE_ENV, "BOT_MODE": "AI", "ADMIN_NUMBERS": "+506 7141 3393, 50611112222", "OWNER_NUMBER": "+50671413393"}
    settings = load_settings(env)
    assert settings.bot_mode == "ai"
    assert settings.admin_numbers == frozenset({"50671413393", "50611112222"})
    assert settings.owner_number == "50671413393"


@pytest.mark.parametrize("missing", ["WHATSAPP_TOKEN", "META_APP_SECRET", "WEBHOOK_VERIFY_TOKEN", "GEMINI_MODEL"])
def test_load_settings_missing_required_raises(missing):
    env = {key: value for key, value in BASE_ENV.items() if key != missing}
    with pytest.raises(ConfigError, match=missing):
        load_settings(env)


def test_load_settings_drive_source_requires_file_id_and_credentials():
    env = {**BASE_ENV, "EXCEL_SOURCE": "drive"}
    with pytest.raises(ConfigError, match="DRIVE_FILE_ID"):
        load_settings(env)


@pytest.mark.parametrize(
    "key,value",
    [
        ("BOT_MODE", "auto"),
        ("EXCEL_SOURCE", "dropbox"),
        ("HANDOFF_PAUSE_MINUTES", "soon"),
        ("HANDOFF_PAUSE_MINUTES", "0"),
        ("GEMINI_TIMEOUT_SECONDS", "-1"),
        ("GEMINI_THINKING_LEVEL", "extreme"),
        ("ADMIN_NUMBERS", "owner"),
    ],
)
def test_load_settings_invalid_value_raises(key, value):
    with pytest.raises(ConfigError):
        load_settings({**BASE_ENV, key: value})


def test_signup_is_disabled_by_default():
    assert load_settings(BASE_ENV).signup_enabled is False


def test_signup_is_enabled_when_all_settings_are_present():
    env = {**BASE_ENV, "META_APP_ID": "1", "SIGNUP_CONFIG_ID": "2", "SIGNUP_KEY": "k" * 32}
    assert load_settings(env).signup_enabled is True


def test_short_signup_key_is_rejected():
    with pytest.raises(ConfigError, match="SIGNUP_KEY"):
        load_settings({**BASE_ENV, "SIGNUP_KEY": "short"})
