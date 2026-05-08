import asyncio
import logging

from edoc.config import URL


async def login(page, username: str, password: str) -> None:
    await page.goto(URL)
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
