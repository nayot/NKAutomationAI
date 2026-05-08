import asyncio
import os
import logging
from pathlib import Path
from dotenv import load_dotenv
from playwright.async_api import async_playwright

DRY_RUN = False

load_dotenv()
USERNAME = os.getenv("EDOC_USERNAME")
PASSWORD = os.getenv("EDOC_PASSWORD")

Path("screenshots").mkdir(exist_ok=True)
logging.basicConfig(
    filename="edoc_automation.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

URL = "https://doc.buu.ac.th/docweb/v2/"

async def login(page):
    await page.goto(URL)
    await page.fill("#txtLogin", USERNAME)
    await page.fill("#txtPassword", PASSWORD)
    async with page.expect_navigation(wait_until="networkidle"):
        await page.click("#btnLogin")
    logging.info("Logged in")

async def main():
    logging.info("Phase 2 — inbox navigation  DRY_RUN=%s", DRY_RUN)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()

        await login(page)
        await page.screenshot(path="screenshots/phase2_01_after_login.png")
        logging.info("Logged in, URL: %s", page.url)

        # Navigate into nested iframes
        outer = page.frame_locator("#iframeHomeBody")
        inner = outer.frame_locator("#home_list_full")

        # Click ทางลัด tab
        await inner.locator(".home-content-tab-shortcuts").click()
        logging.info("Clicked ทางลัด")
        await page.screenshot(path="screenshots/phase2_02_shortcut_menu.png")

        # Select target inbox (link text)
        INBOX = "ผศ. ดร. ณยศ คุรุกิจโกศล"
        await inner.get_by_role("link", name=INBOX, exact=True).click()
        logging.info("Selected inbox: %s", INBOX)
        await page.screenshot(path="screenshots/phase2_03_inbox.png")

        print(f"Inbox URL:   {page.url}")
        print(f"Inbox title: {await page.title()}")

        input("Press Enter to close browser…")
        await browser.close()
    logging.info("Phase 2 — done")

asyncio.run(main())
