"""
test_attachment_download.py
Smoke test: login → inbox → open first doc → find PDF in td.picture → download to tmp/

Does NOT sign anything. DRY_RUN guard is kept for safety even though this script
never reaches sign logic.
"""

import asyncio
import os
import logging
from pathlib import Path
from dotenv import load_dotenv
from playwright.async_api import async_playwright

load_dotenv()
USERNAME = os.getenv("EDOC_USERNAME")
PASSWORD = os.getenv("EDOC_PASSWORD")
INBOX    = os.getenv("INBOX")

URL = "https://doc.buu.ac.th/docweb/v2/"

Path("screenshots").mkdir(exist_ok=True)
Path("tmp").mkdir(exist_ok=True)

logging.basicConfig(
    filename="edoc_automation.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

# ── helpers ──────────────────────────────────────────────────────────────────

async def login(page):
    await page.goto(URL)
    await page.fill("#txtLogin", USERNAME)
    await page.fill("#txtPassword", PASSWORD)
    async with page.expect_navigation(wait_until="networkidle"):
        await page.click("#btnLogin")
    logging.info("Logged in")
    print("✓ Logged in")

async def navigate_to_inbox(page):
    inner = page.frame_locator("#iframeHomeBody").frame_locator("#home_list_full")
    await inner.locator(".home-content-tab-shortcuts").click()
    await inner.get_by_role("link", name=INBOX, exact=True).click()
    await page.wait_for_load_state("networkidle")
    await page.screenshot(path="screenshots/test_attach_01_inbox.png")
    print("✓ Navigated to inbox")

async def get_inbox_frame(page):
    for frame in page.frames:
        if frame.name == "home_list":
            return frame
    return None

async def open_first_document(page):
    frame = await get_inbox_frame(page)
    if frame is None:
        raise RuntimeError("home_list frame not found")
    await frame.wait_for_selector("a.home-list-open-item", timeout=15000)
    links = await frame.query_selector_all("a.home-list-open-item")
    if not links:
        raise RuntimeError("No documents in inbox")
    first = links[0]
    title = (await first.inner_text()).strip()
    data_id = await first.get_attribute("data-id")
    print(f"✓ Opening first document: [{data_id}] {title[:80]}")
    await frame.click(f"a[data-id='{data_id}']", force=True)
    logging.info("Opened doc %s: %s", data_id, title)
    return data_id, title

async def find_attachments(page):
    """
    Inspect td.picture inside iframeContent0 and return all anchor hrefs found.
    Also prints the raw HTML of td.picture for debugging.
    """
    content_frame = page.frame(name="iframeContent0")
    if content_frame is None:
        print("ERROR: iframeContent0 not found")
        return []

    # Wait briefly for the frame to load
    try:
        await content_frame.wait_for_selector("td.picture", timeout=10000)
    except Exception:
        print("⚠  td.picture not found within timeout — dumping frame body for inspection")
        body_html = await content_frame.inner_html("body")
        print(body_html[:2000])
        await page.screenshot(path="screenshots/test_attach_02_nodoc.png")
        return []

    # Dump raw HTML of the picture cell for inspection
    cells = await content_frame.query_selector_all("td.picture")
    print(f"\n── td.picture cells found: {len(cells)} ──")
    for i, cell in enumerate(cells):
        html = await cell.inner_html()
        print(f"\n[cell {i}] raw HTML:\n{html[:800]}")

    # Collect all anchors inside any td.picture
    anchors = await content_frame.query_selector_all("td.picture a")
    hrefs = []
    for a in anchors:
        href = await a.get_attribute("href")
        text = (await a.inner_text()).strip()
        if href:
            hrefs.append((href, text))
            print(f"  anchor: {text!r} → {href}")

    await page.screenshot(path="screenshots/test_attach_02_doc.png")
    return hrefs

async def download_first_attachment(page, hrefs):
    """Download the first PDF-looking link using the authenticated browser session."""
    if not hrefs:
        print("No attachment links found — nothing to download.")
        return None

    # Pick the first entry; prefer an explicit .pdf link if present
    target_href, target_text = hrefs[0]
    for href, text in hrefs:
        if ".pdf" in href.lower() or "pdf" in text.lower():
            target_href, target_text = href, text
            break

    # Resolve relative URLs against the base URL
    if target_href.startswith("/"):
        base = "https://doc.buu.ac.th"
        download_url = base + target_href
    elif target_href.startswith("http"):
        download_url = target_href
    else:
        # relative to the frame URL
        frame = page.frame(name="iframeContent0")
        frame_url = frame.url
        base = frame_url.rsplit("/", 1)[0]
        download_url = base + "/" + target_href

    print(f"\n── Downloading: {target_text!r}\n   URL: {download_url}")
    logging.info("Downloading attachment: %s", download_url)

    # Use Playwright's API request context (shares cookies with the browser session)
    response = await page.context.request.get(download_url)
    if not response.ok:
        print(f"ERROR: HTTP {response.status} for {download_url}")
        return None

    content_type = response.headers.get("content-type", "")
    print(f"   Content-Type: {content_type}")
    print(f"   Content-Length: {response.headers.get('content-length', 'unknown')} bytes")

    # Determine filename
    disposition = response.headers.get("content-disposition", "")
    filename = None
    if "filename=" in disposition:
        filename = disposition.split("filename=")[-1].strip().strip('"').strip("'")
    if not filename:
        filename = target_href.split("/")[-1].split("?")[0] or "attachment"
    if not filename.endswith(".pdf") and "pdf" in content_type.lower():
        filename += ".pdf"

    out_path = Path("tmp") / filename
    body = await response.body()
    out_path.write_bytes(body)
    print(f"\n✓ Saved attachment → {out_path}  ({len(body):,} bytes)")
    logging.info("Saved attachment to %s (%d bytes)", out_path, len(body))
    return out_path

# ── main ─────────────────────────────────────────────────────────────────────

async def main():
    print("=== Attachment Download Test ===\n")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()

        await login(page)
        await navigate_to_inbox(page)
        data_id, title = await open_first_document(page)

        # Give the content frame a moment to render
        await page.wait_for_timeout(2000)

        hrefs = await find_attachments(page)
        saved = await download_first_attachment(page, hrefs)

        if saved:
            print(f"\nSUCCESS — attachment ready at: {saved}")
        else:
            print("\nFAILED — no attachment downloaded. Check output above and screenshot.")

        input("\nPress Enter to close…")
        await browser.close()
    print("Done.")

if __name__ == "__main__":
    asyncio.run(main())
