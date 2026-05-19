import asyncio
import os
import json
import logging
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from playwright.async_api import async_playwright
from edoc.signer import confirm_sign as hardened_confirm_sign
from edoc.signer import dismiss_form as hardened_dismiss_form
from edoc.signer import open_and_fill_form as hardened_open_and_fill_form

DRY_RUN = False # set False only after confirming DRY_RUN output looks correct

load_dotenv()
USERNAME = os.getenv("EDOC_USERNAME")
PASSWORD = os.getenv("EDOC_PASSWORD")
INBOX    = os.getenv("INBOX")

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

async def navigate_to_inbox(page):
    inner = page.frame_locator("#iframeHomeBody").frame_locator("#home_list_full")
    await inner.locator(".home-content-tab-shortcuts").click()
    await inner.get_by_role("link", name=INBOX, exact=True).click()
    await page.wait_for_load_state("networkidle")
    logging.info("Navigated to inbox: %s", INBOX)

async def get_inbox_frame(page):
    for frame in page.frames:
        if frame.name == "home_list":
            return frame
    return None

async def wait_for_content_frame(page, timeout=15000):
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

async def open_and_fill_form(page, doc) -> dict:
    """Open doc, click btnSign, select option, fill command. Returns {form_screenshot, data_id, ts}."""
    if "command" not in doc:
        doc["command"] = doc.get("final_command", "")
    return await hardened_open_and_fill_form(page, doc, INBOX)

async def confirm_sign(page, dry_run: bool, data_id: str, ts: str) -> str:
    """Click OK (or Cancel if dry_run), take after-screenshot, hide frame. Returns screenshot path."""
    return await hardened_confirm_sign(page, dry_run, data_id, ts)

async def dismiss_form(page):
    """Cancel the sign form and hide frame. Used when user skips in the web UI."""
    await hardened_dismiss_form(page)

async def sign_document(page, doc):
    """CLI helper: calls open_and_fill_form then confirm_sign in one shot."""
    ctx = await open_and_fill_form(page, doc)
    await confirm_sign(page, DRY_RUN, ctx["data_id"], ctx["ts"])

async def main():
    with open("approved_order.json", encoding="utf-8") as f:
        approved = json.load(f)

    print(f"Loaded {len(approved)} document(s) to sign.")
    print("DRY_RUN=True — previewing only.\n" if DRY_RUN else "DRY_RUN=False — WILL SIGN.\n")
    logging.info("Phase 5 — DRY_RUN=%s, %d docs", DRY_RUN, len(approved))

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()

        await login(page)
        await navigate_to_inbox(page)

        for i, doc in enumerate(approved, 1):
            print(f"\n[{i}/{len(approved)}] {doc['title']}")
            print(f"     คำสั่งการ: {doc['final_command']}")

            await sign_document(page, doc)
            label = "[DRY_RUN] ยกเลิกหลังกรอกฟอร์ม" if DRY_RUN else "ลงนามสำเร็จ ✓"
            print(f"     → {label}")

        print("\nเสร็จสิ้น")
        input("Press Enter to close…")
        await browser.close()

    logging.info("Phase 5 — done")

if __name__ == "__main__":
    asyncio.run(main())
