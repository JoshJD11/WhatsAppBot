"""Settings loaded from environment variables.

Every secret and tunable lives here so nothing is hard-coded elsewhere.
See `.env.example` for the documented list.
"""

import os
from dataclasses import dataclass, field
from typing import Literal, Mapping, cast

BotMode = Literal["ai", "rule"]
ExcelSource = Literal["drive", "local"]


class ConfigError(ValueError):
    """Raised when a setting is missing or invalid."""


@dataclass(frozen=True)
class Settings:
    # WhatsApp Cloud API
    whatsapp_token: str
    whatsapp_phone_number_id: str
    meta_app_secret: str
    webhook_verify_token: str
    graph_api_version: str = "v26.0"

    # Gemini
    gemini_api_key: str = ""
    gemini_model: str = ""
    gemini_thinking_level: str = "low"
    gemini_timeout_seconds: float = 20.0

    # Excel
    excel_source: ExcelSource = "drive"
    drive_file_id: str = ""
    google_service_account_file: str = ""
    excel_local_path: str = ""
    excel_reload_minutes: int = 10

    # Behavior
    bot_mode: BotMode = "rule"
    admin_numbers: frozenset[str] = field(default_factory=frozenset)
    owner_number: str = ""
    handoff_pause_minutes: int = 60
    rate_limit_max_messages: int = 8
    rate_limit_window_seconds: int = 60
    ai_history_messages: int = 10
    ai_history_idle_minutes: int = 30
    timezone: str = "America/Costa_Rica"
    # Empty disables saving the state between restarts.
    state_file: str = "data/state.json"


def _require(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "").strip()
    if not value:
        raise ConfigError(f"Missing required setting: {name}")
    return value


def _int(env: Mapping[str, str], name: str, default: int, minimum: int = 1) -> int:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc
    if value < minimum:
        raise ConfigError(f"{name} must be at least {minimum}")
    return value


def _float(env: Mapping[str, str], name: str, default: float) -> float:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from exc
    if value <= 0:
        raise ConfigError(f"{name} must be greater than 0")
    return value


def _phone(value: str, name: str) -> str:
    digits = value.strip().lstrip("+").replace(" ", "")
    if not digits.isdigit():
        raise ConfigError(f"{name} must contain only digits with the country code, got {value!r}")
    return digits


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Build Settings from a mapping (defaults to os.environ) and validate them."""
    env = os.environ if env is None else env

    bot_mode = env.get("BOT_MODE", "rule").strip().lower()
    if bot_mode not in ("ai", "rule"):
        raise ConfigError("BOT_MODE must be 'ai' or 'rule'")

    excel_source = env.get("EXCEL_SOURCE", "drive").strip().lower()
    if excel_source not in ("drive", "local"):
        raise ConfigError("EXCEL_SOURCE must be 'drive' or 'local'")
    if excel_source == "drive":
        _require(env, "DRIVE_FILE_ID")
        _require(env, "GOOGLE_SERVICE_ACCOUNT_FILE")
    else:
        _require(env, "EXCEL_LOCAL_PATH")

    admin_raw = env.get("ADMIN_NUMBERS", "")
    admin_numbers = frozenset(
        _phone(part, "ADMIN_NUMBERS") for part in admin_raw.split(",") if part.strip()
    )
    owner_raw = env.get("OWNER_NUMBER", "").strip()
    owner_number = _phone(owner_raw, "OWNER_NUMBER") if owner_raw else ""

    thinking_level = env.get("GEMINI_THINKING_LEVEL", "low").strip().lower()
    if thinking_level not in ("minimal", "low", "medium", "high"):
        raise ConfigError("GEMINI_THINKING_LEVEL must be minimal, low, medium or high")

    return Settings(
        whatsapp_token=_require(env, "WHATSAPP_TOKEN"),
        whatsapp_phone_number_id=_require(env, "WHATSAPP_PHONE_NUMBER_ID"),
        meta_app_secret=_require(env, "META_APP_SECRET"),
        webhook_verify_token=_require(env, "WEBHOOK_VERIFY_TOKEN"),
        graph_api_version=env.get("GRAPH_API_VERSION", "v26.0").strip() or "v26.0",
        gemini_api_key=env.get("GEMINI_API_KEY", "").strip(),
        gemini_model=_require(env, "GEMINI_MODEL"),
        gemini_thinking_level=thinking_level,
        gemini_timeout_seconds=_float(env, "GEMINI_TIMEOUT_SECONDS", 20.0),
        excel_source=cast(ExcelSource, excel_source),
        drive_file_id=env.get("DRIVE_FILE_ID", "").strip(),
        google_service_account_file=env.get("GOOGLE_SERVICE_ACCOUNT_FILE", "").strip(),
        excel_local_path=env.get("EXCEL_LOCAL_PATH", "").strip(),
        excel_reload_minutes=_int(env, "EXCEL_RELOAD_MINUTES", 10),
        bot_mode=cast(BotMode, bot_mode),
        admin_numbers=admin_numbers,
        owner_number=owner_number,
        handoff_pause_minutes=_int(env, "HANDOFF_PAUSE_MINUTES", 60),
        rate_limit_max_messages=_int(env, "RATE_LIMIT_MAX_MESSAGES", 8),
        rate_limit_window_seconds=_int(env, "RATE_LIMIT_WINDOW_SECONDS", 60),
        ai_history_messages=_int(env, "AI_HISTORY_MESSAGES", 10, minimum=0),
        ai_history_idle_minutes=_int(env, "AI_HISTORY_IDLE_MINUTES", 30),
        timezone=env.get("TIMEZONE", "America/Costa_Rica").strip() or "America/Costa_Rica",
        state_file=env.get("STATE_FILE", "data/state.json").strip(),
    )
