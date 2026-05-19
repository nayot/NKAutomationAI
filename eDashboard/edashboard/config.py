import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

GMAIL_TOKEN_FILE = Path.home() / ".config" / "edashboard" / "gmail_token.json"


class ConfigError(Exception):
    pass


@dataclass
class Config:
    edoc_username: str
    edoc_password: str
    edoc_inbox: str
    esign_username: str
    esign_password: str
    fiori_username: str
    fiori_password: str
    google_client_id: str
    google_client_secret: str


def load_config() -> Config:
    load_dotenv()

    edoc_username = os.getenv("EDOC_USERNAME", "")
    edoc_password = os.getenv("EDOC_PASSWORD", "")
    edoc_inbox = os.getenv("INBOX", "")

    # eSign falls back to eDoc credentials if not set separately
    esign_username = os.getenv("ESIGN_USERNAME") or edoc_username
    esign_password = os.getenv("ESIGN_PASSWORD") or edoc_password

    fiori_username = os.getenv("FIORI_USERNAME", "")
    fiori_password = os.getenv("FIORI_PASSWORD", "")
    google_client_id = os.getenv("GOOGLE_CLIENT_ID", "")
    google_client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "")

    return Config(
        edoc_username=edoc_username,
        edoc_password=edoc_password,
        edoc_inbox=edoc_inbox,
        esign_username=esign_username,
        esign_password=esign_password,
        fiori_username=fiori_username,
        fiori_password=fiori_password,
        google_client_id=google_client_id,
        google_client_secret=google_client_secret,
    )
