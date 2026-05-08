import asyncio
import os
import json
import logging
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from playwright.async_api import async_playwright

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
    data_id = doc["data_id"]
    command = doc["final_command"]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    content_frame = None
    for attempt in range(3):
        if attempt > 0:
            logging.warning("Retry %d — re-navigating to inbox for %s", attempt, data_id)
            await navigate_to_inbox(page)
            await asyncio.sleep(1.5)

        inbox_frame = await get_inbox_frame(page)
        if not inbox_frame:
            logging.warning("Inbox frame not found on attempt %d", attempt + 1)
            await asyncio.sleep(2)
            continue

        await inbox_frame.click(f"a[data-id='{data_id}']", force=True)
        await page.wait_for_load_state("networkidle")

        if attempt == 0:
            await page.screenshot(path=f"screenshots/phase5_before_{data_id}_{ts}.png")
        logging.info("Clicked doc link (attempt %d): %s", attempt + 1, doc["title"])

        content_frame = await wait_for_content_frame(page)
        if content_frame:
            break

        logging.warning("Content frame not found on attempt %d — saving debug screenshot", attempt + 1)
        await page.screenshot(path=f"screenshots/phase5_debug_{data_id}_{ts}_attempt{attempt + 1}.png")

    if not content_frame:
        logging.error("Content frame missing after retries: %s", doc["title"])
        raise RuntimeError("Content frame missing")

    for sign_attempt in range(3):
        await content_frame.evaluate("document.getElementById('btnSign').click()")
        logging.info("Clicked btnSign (attempt %d): %s", sign_attempt + 1, data_id)
        try:
            await page.wait_for_selector("#optSignConfirmOptions0", state="visible", timeout=8000)
            break
        except Exception:
            if sign_attempt == 2:
                await page.screenshot(path=f"screenshots/phase5_nodialog_{data_id}_{ts}.png")
                raise RuntimeError(f"Sign dialog never appeared for {doc['title']}")
            logging.warning("Sign dialog not visible, retrying btnSign click")
    else:
        pass  # unreachable but keeps linter happy

    await page.click("#optSignConfirmOptions0")
    await page.fill("#txtTargetTypeNote", command)

    form_path = f"screenshots/phase5_form_{data_id}_{ts}.png"
    await page.screenshot(path=form_path)
    return {"form_screenshot": form_path, "data_id": data_id, "ts": ts}

async def confirm_sign(page, dry_run: bool, data_id: str, ts: str) -> str:
    """Click OK (or Cancel if dry_run), take after-screenshot, hide frame. Returns screenshot path."""
    if dry_run:
        await page.click("#btnSignConfirmCancel")
        logging.info("[DRY_RUN] Cancelled signing for %s", data_id)
    else:
        await page.click("#btnSignConfirmOK")
        logging.info("Signed %s", data_id)

    await page.wait_for_load_state("networkidle")
    after_path = f"screenshots/phase5_after_{data_id}_{ts}.png"
    await page.screenshot(path=after_path)
    await page.evaluate("VN.V2.App.Home.Page.HideContentFrame()")
    await page.wait_for_load_state("networkidle")
    await asyncio.sleep(1.5)
    return after_path

async def dismiss_form(page):
    """Cancel the sign form and hide frame. Used when user skips in the web UI."""
    await page.click("#btnSignConfirmCancel")
    await page.wait_for_load_state("networkidle")
    await page.evaluate("VN.V2.App.Home.Page.HideContentFrame()")
    await page.wait_for_load_state("networkidle")

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
