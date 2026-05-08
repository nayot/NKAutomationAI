import asyncio
import os
import json
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

URL   = "https://doc.buu.ac.th/docweb/v2/"
INBOX = os.getenv("INBOX")

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
    logging.info("Navigated to inbox: %s", INBOX)
    await page.wait_for_load_state("networkidle")
    await page.screenshot(path="screenshots/phase3_01_inbox.png")

async def get_inbox_frame(page):
    for frame in page.frames:
        if frame.name == "home_list":
            return frame
    return None

async def get_document_list(page):
    frame = await get_inbox_frame(page)
    if frame is None:
        print("ERROR: home_list frame not found")
        print("Available frames:", [f.name for f in page.frames])
        return []

    await frame.wait_for_selector("a.home-list-open-item", timeout=15000)
    elements = await frame.query_selector_all("a.home-list-open-item")

    docs = []
    for i, el in enumerate(elements):
        docs.append({
            "index":   i + 1,
            "data_id": await el.get_attribute("data-id"),
            "doc_id":  await el.get_attribute("id"),
            "title":   (await el.inner_text()).strip(),
        })
    return docs

async def read_document_content(page, doc):
    inbox_frame = await get_inbox_frame(page)
    # force=True bypasses iframeContent0 overlapping the list after first doc opens
    await inbox_frame.click(f"a[data-id='{doc['data_id']}']", force=True)
    logging.info("Opened: %s", doc['title'])

    content_frame = page.frame(name="iframeContent0")
    # Wait for the document content to load inside the frame
    try:
        await content_frame.wait_for_selector(".DocNoteContent", timeout=10000)
    except Exception:
        pass  # some documents have no notes

    note_els = await content_frame.query_selector_all(".DocNoteContent")
    parts = [(await el.inner_text()).strip() for el in note_els]
    doc["notes"] = "\n---\n".join(p for p in parts if p)

    await page.screenshot(path=f"screenshots/phase3_doc_{doc['data_id']}.png")

    # Close the document tab by calling the page's own hide function directly
    await page.evaluate("VN.V2.App.Home.Page.HideContentFrame()")
    await page.wait_for_load_state("networkidle")

    return doc

async def main():
    logging.info("Phase 3 — read documents  DRY_RUN=%s", DRY_RUN)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()

        await login(page)
        await navigate_to_inbox(page)

        docs = await get_document_list(page)
        print(f"\nFound {len(docs)} document(s):")
        for d in docs:
            print(f"  [{d['index']}] data_id={d['data_id']}  {d['title']}")

        if DRY_RUN:
            print("\n[DRY_RUN] Document list only. Set DRY_RUN=False to read content.")
            logging.info("DRY_RUN: listed %d documents", len(docs))
            input("Press Enter to close…")
            await browser.close()
            return

        TEST_LIMIT = None  # Set to an integer to limit for testing
        if TEST_LIMIT:
            docs = docs[:TEST_LIMIT]
            print(f"\nTEST_LIMIT={TEST_LIMIT}: reading first {len(docs)} documents only.")

        print("\nReading document content…")
        for doc in docs:
            doc = await read_document_content(page, doc)
            print(f"  Read [{doc['index']}]: {doc['title'][:70]}")
            print(f"    notes preview: {doc['notes'][:120]}")

        with open("documents_data.json", "w", encoding="utf-8") as f:
            json.dump(docs, f, ensure_ascii=False, indent=2)
        print(f"\nSaved {len(docs)} documents → documents_data.json")
        logging.info("Saved %d documents to documents_data.json", len(docs))

        input("Press Enter to close…")
        await browser.close()
    logging.info("Phase 3 — done")

if __name__ == "__main__":
    asyncio.run(main())
