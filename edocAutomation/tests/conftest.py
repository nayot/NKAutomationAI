"""Shared pytest fixtures for edocAutomation tests."""
import os
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from dotenv import load_dotenv

# Make src importable from tests/
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load .secrets from project root
load_dotenv(Path(__file__).parent.parent / ".secrets")


def secrets() -> dict:
    """Return required secrets, failing clearly if any are missing."""
    required = ["EDOC_USERNAME", "EDOC_PASSWORD"]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        pytest.skip(f"Missing secrets: {', '.join(missing)}. Copy .secrets.example → .secrets and fill in values.")
    return {k: os.environ[k] for k in required}


@pytest.fixture
def edoc_secrets():
    return secrets()


# Controls whether Playwright runs headless. Set HEADLESS=false to watch.
HEADLESS = os.getenv("HEADLESS", "true").lower() != "false"
