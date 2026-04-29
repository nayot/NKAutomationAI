"""
Test 01 — Login
---------------
Verifies that we can authenticate with the BUU e-Doc system.

Run:
    pytest tests/test_01_login.py -v
    HEADLESS=false pytest tests/test_01_login.py -v   # watch in browser

Screenshots saved to: screenshots/
    01_login_page.png   — the login form before filling
    02_login_filled.png — credentials filled in
    03_after_login.png  — page after clicking Sign In
"""
import pytest
import pytest_asyncio
from pathlib import Path

from tests.conftest import HEADLESS
from src.edoc_client import EdocClient, SCREENSHOT_DIR


@pytest.mark.asyncio
async def test_login_succeeds(edoc_secrets):
    """Login with valid credentials should land on the home/inbox page."""
    async with EdocClient(headless=HEADLESS) as client:
        result = await client.login(
            username=edoc_secrets["EDOC_USERNAME"],
            password=edoc_secrets["EDOC_PASSWORD"],
        )

    assert result is True, "login() should return True on success"

    # Verify screenshots were created
    for name in ["01_login_page", "02_login_filled", "03_after_login"]:
        path = SCREENSHOT_DIR / f"{name}.png"
        assert path.exists(), f"Expected screenshot {path} was not created"

    print(f"\nScreenshots saved to: {SCREENSHOT_DIR}")
    print("Inspect 03_after_login.png to confirm the home page loaded correctly.")


@pytest.mark.asyncio
async def test_login_fails_with_wrong_password(edoc_secrets):
    """Login with a wrong password should raise RuntimeError."""
    async with EdocClient(headless=HEADLESS) as client:
        with pytest.raises(RuntimeError, match="Login failed"):
            await client.login(
                username=edoc_secrets["EDOC_USERNAME"],
                password="WRONG_PASSWORD_FOR_TESTING",
            )
