import asyncio
import logging
import subprocess

from edoc.config import URL


def _detect_viewport() -> dict:
    """Return the primary display's logical resolution (macOS), falling back to 1440×900."""
    try:
        out = subprocess.run(
            ["osascript", "-e",
             'tell application "Finder" to get bounds of window of desktop'],
            capture_output=True, text=True, timeout=3,
        ).stdout.strip()
        # "0, 0, 2560, 1600" → width=parts[2], height=parts[3]
        parts = [int(x.strip()) for x in out.split(",")]
        return {"width": parts[2], "height": parts[3]}
    except Exception:
        return {"width": 1440, "height": 900}


# Realistic desktop fingerprint — without these, BUU's portal serves a different
# (non-functional) page to headless Chromium and #txtLogin never appears.
DESKTOP_VIEWPORT = _detect_viewport()
DESKTOP_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


async def open_page(playwright, headless: bool):
    """Launch chromium and return (browser, context, page) with a desktop fingerprint.
    Caller owns the browser lifecycle and must close it."""
    browser = await playwright.chromium.launch(headless=headless)
    context = await browser.new_context(
        viewport=DESKTOP_VIEWPORT,
        user_agent=DESKTOP_USER_AGENT,
    )
    page = await context.new_page()
    return browser, context, page


async def login(page, username: str, password: str) -> None:
    await page.goto(URL, wait_until="domcontentloaded")
    await page.screenshot(path="screenshots/login_page.png")
    try:
        await page.wait_for_selector("#txtLogin", state="visible", timeout=20000)
    except Exception:
        await page.screenshot(path="screenshots/login_failed.png")
        logging.error("Login form #txtLogin never appeared. URL=%s", page.url)
        raise
    await page.fill("#txtLogin", username)
    await page.fill("#txtPassword", password)
    async with page.expect_navigation(wait_until="networkidle"):
        await page.click("#btnLogin")
    logging.info("Logged in")


async def navigate_to_inbox(page, inbox_name: str) -> None:
    inner = page.frame_locator("#iframeHomeBody").frame_locator("#home_list_full")
    await inner.locator(".home-content-tab-shortcuts").click()
    await inner.get_by_role("link", name=inbox_name, exact=True).click()
    await page.wait_for_load_state("networkidle")
    logging.info("Navigated to inbox: %s", inbox_name)


async def get_inbox_frame(page):
    for frame in page.frames:
        if frame.name == "home_list":
            return frame
    return None


async def wait_for_content_frame(page, timeout: int = 15000):
    """Scan all frames for #btnSign, retrying until found or timeout."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout / 1000
    while loop.time() < deadline:
        for frame in page.frames:
            try:
                btn = await frame.query_selector("#btnSign")
                if btn:
                    return frame
            except Exception:
                continue
        await asyncio.sleep(0.3)
    return None
