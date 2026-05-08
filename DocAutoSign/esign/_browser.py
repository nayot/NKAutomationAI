from contextlib import contextmanager
from typing import Iterator

from playwright.sync_api import BrowserContext, Page, sync_playwright


@contextmanager
def browser_session(
    headless: bool,
    viewport: dict,
    user_agent: str,
    default_timeout_ms: int = 30_000,
    navigation_timeout_ms: int | None = None,
) -> Iterator[tuple[Page, BrowserContext]]:
    """Yield (page, context). Context has accept_downloads=True for expect_download()."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            accept_downloads=True,
            viewport=viewport,
            user_agent=user_agent,
        )
        context.set_default_timeout(default_timeout_ms)
        # Navigations on slow VPN can take >> action timeout — give them headroom.
        context.set_default_navigation_timeout(navigation_timeout_ms or default_timeout_ms * 2)
        page = context.new_page()
        try:
            yield page, context
        finally:
            context.close()
            browser.close()
