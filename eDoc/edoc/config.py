import os
from dataclasses import dataclass

from dotenv import load_dotenv

URL = "https://doc.buu.ac.th/docweb/v2/"
DEFAULT_COMMAND = "ดำเนินการตามเสนอ"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
# OpenRouter model slugs (see https://openrouter.ai/models). Any slug works —
# these two are only the defaults when .env leaves them unset.
DEFAULT_AI_MODEL = "anthropic/claude-haiku-4.5"
DEFAULT_AI_FALLBACK_MODEL = "openai/gpt-4o-mini"
# Conservative output cap: many OpenRouter models top out well below Claude's
# 64k, and an over-large max_tokens is a hard 400 rather than a silent clamp.
DEFAULT_AI_MAX_TOKENS = 16000
# PDF handling engine for attachment summaries. "native" hands the PDF straight
# to the model (billed as input tokens) and is pinned deliberately: left unset,
# OpenRouter silently falls back to the paid per-page mistral-ocr engine for any
# model without native file support. See .env.example for the alternatives.
DEFAULT_AI_PDF_ENGINE = "native"


class ConfigError(Exception):
    pass


@dataclass
class Config:
    username: str
    password: str
    inbox: str
    openrouter_api_key: str
    openrouter_base_url: str
    headless: bool
    ai_model: str
    ai_fallback_model: str | None
    ai_max_tokens: int
    ai_pdf_engine: str | None


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in ("1", "true", "yes", "on")


def load_config(headless_override: bool | None = None, inbox_override: str | None = None) -> Config:
    load_dotenv()

    username = os.getenv("EDOC_USERNAME")
    password = os.getenv("EDOC_PASSWORD")
    inbox = inbox_override or os.getenv("INBOX")
    api_key = os.getenv("OPENROUTER_API_KEY")

    missing = [name for name, val in [
        ("EDOC_USERNAME", username),
        ("EDOC_PASSWORD", password),
        ("INBOX", inbox),
        ("OPENROUTER_API_KEY", api_key),
    ] if not val]
    if missing:
        raise ConfigError(f"Missing required environment variables: {', '.join(missing)}")

    if headless_override is not None:
        headless = headless_override
    else:
        env_headless = os.getenv("HEADLESS")
        headless = _parse_bool(env_headless) if env_headless else False

    ai_model = os.getenv("EDOC_AI_MODEL", "").strip() or DEFAULT_AI_MODEL
    base_url = os.getenv("OPENROUTER_BASE_URL", "").strip() or OPENROUTER_BASE_URL

    # An unset EDOC_AI_FALLBACK_MODEL gets the default; setting it empty
    # ("EDOC_AI_FALLBACK_MODEL=") disables the fallback entirely.
    env_fallback = os.getenv("EDOC_AI_FALLBACK_MODEL")
    if env_fallback is None:
        ai_fallback_model: str | None = DEFAULT_AI_FALLBACK_MODEL
    else:
        ai_fallback_model = env_fallback.strip() or None

    env_max_tokens = os.getenv("EDOC_AI_MAX_TOKENS", "").strip()
    if env_max_tokens:
        try:
            ai_max_tokens = int(env_max_tokens)
        except ValueError as e:
            raise ConfigError(f"EDOC_AI_MAX_TOKENS must be an integer, got {env_max_tokens!r}") from e
    else:
        ai_max_tokens = DEFAULT_AI_MAX_TOKENS

    # Empty value ("EDOC_AI_PDF_ENGINE=") sends no plugin config, letting
    # OpenRouter choose the engine — including the paid OCR one.
    env_pdf_engine = os.getenv("EDOC_AI_PDF_ENGINE")
    if env_pdf_engine is None:
        ai_pdf_engine: str | None = DEFAULT_AI_PDF_ENGINE
    else:
        ai_pdf_engine = env_pdf_engine.strip() or None

    return Config(
        username=username,
        password=password,
        inbox=inbox,
        openrouter_api_key=api_key,
        openrouter_base_url=base_url,
        headless=headless,
        ai_model=ai_model,
        ai_fallback_model=ai_fallback_model,
        ai_max_tokens=ai_max_tokens,
        ai_pdf_engine=ai_pdf_engine,
    )
