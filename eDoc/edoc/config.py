import os
from dataclasses import dataclass

from dotenv import load_dotenv

URL = "https://doc.buu.ac.th/docweb/v2/"
DEFAULT_COMMAND = "ดำเนินการตามเสนอ"
DEFAULT_AI_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_AI_FALLBACK_MODEL = "gpt-4o-mini"


class ConfigError(Exception):
    pass


@dataclass
class Config:
    username: str
    password: str
    inbox: str
    anthropic_api_key: str
    headless: bool
    ai_model: str
    openai_api_key: str | None
    ai_fallback_model: str


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in ("1", "true", "yes", "on")


def load_config(headless_override: bool | None = None, inbox_override: str | None = None) -> Config:
    load_dotenv()

    username = os.getenv("EDOC_USERNAME")
    password = os.getenv("EDOC_PASSWORD")
    inbox = inbox_override or os.getenv("INBOX")
    api_key = os.getenv("ANTHROPIC_API_KEY")

    missing = [name for name, val in [
        ("EDOC_USERNAME", username),
        ("EDOC_PASSWORD", password),
        ("INBOX", inbox),
        ("ANTHROPIC_API_KEY", api_key),
    ] if not val]
    if missing:
        raise ConfigError(f"Missing required environment variables: {', '.join(missing)}")

    if headless_override is not None:
        headless = headless_override
    else:
        env_headless = os.getenv("HEADLESS")
        headless = _parse_bool(env_headless) if env_headless else False

    ai_model = os.getenv("EDOC_AI_MODEL", "").strip() or DEFAULT_AI_MODEL
    openai_api_key = os.getenv("OPENAI_API_KEY", "").strip() or None
    ai_fallback_model = os.getenv("EDOC_AI_FALLBACK_MODEL", "").strip() or DEFAULT_AI_FALLBACK_MODEL

    return Config(
        username=username,
        password=password,
        inbox=inbox,
        anthropic_api_key=api_key,
        headless=headless,
        ai_model=ai_model,
        openai_api_key=openai_api_key,
        ai_fallback_model=ai_fallback_model,
    )
