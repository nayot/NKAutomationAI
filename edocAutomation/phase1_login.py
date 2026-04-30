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

URL = "https://doc.buu.ac.th/docweb"

async def main():
    logging.info("Phase 1 — login test  DRY_RUN=%s", DRY_RUN)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()

        await page.goto(URL)
        await page.screenshot(path="screenshots/phase1_01_login_page.png")

        # Discover form elements
        inputs = await page.query_selector_all("input")
        print("\n=== Inputs ===")
        for el in inputs:
            print(f"  id={await el.get_attribute('id')!r}  "
                  f"name={await el.get_attribute('name')!r}  "
                  f"type={await el.get_attribute('type')!r}")

        buttons = await page.query_selector_all("button, input[type=submit], input[type=button], a[href*='login'], a[href*='Login']")
        print("\n=== Buttons / Links ===")
        for el in buttons:
            print(f"  id={await el.get_attribute('id')!r}  "
                  f"text={(await el.inner_text()).strip()!r}  "
                  f"value={await el.get_attribute('value')!r}")

        print(f"\nURL:   {page.url}")
        print(f"Title: {await page.title()}")

        if DRY_RUN:
            print("\n[DRY_RUN] Stopped before login. Review selectors above, fill them in, then set DRY_RUN=False.")
            logging.info("DRY_RUN stopped before login")
            input("Press Enter to close browser…")
            await browser.close()
            return

        USERNAME_SEL = "#txtLogin"
        PASSWORD_SEL = "#txtPassword"
        SUBMIT_SEL   = "#btnLogin"

        await page.fill(USERNAME_SEL, USERNAME)
        await page.fill(PASSWORD_SEL, PASSWORD)
        logging.info("Credentials filled")

        async with page.expect_navigation(wait_until="networkidle"):
            await page.click(SUBMIT_SEL)

        logging.info("Login submitted")
        await page.screenshot(path="screenshots/phase1_02_after_login.png")
        print(f"\nAfter login URL:   {page.url}")
        print(f"After login title: {await page.title()}")

        input("Press Enter to close browser…")
        await browser.close()
    logging.info("Phase 1 — done")

asyncio.run(main())
