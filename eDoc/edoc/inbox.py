import asyncio
import json
import logging
from pathlib import Path
from typing import Callable, Optional

from edoc.browser import get_inbox_frame

TMP_DIR = Path("tmp")

ProgressCallback = Callable[[int, int, str], None]

DOCUMENTS_DATA_FILE = "documents_data.json"


async def list_documents(page) -> list[dict]:
    frame = await get_inbox_frame(page)
    if frame is None:
        logging.error("home_list frame not found; available: %s", [f.name for f in page.frames])
        return []

    await frame.wait_for_selector("a.home-list-open-item", timeout=15000)
    elements = await frame.query_selector_all("a.home-list-open-item")

    docs = []
    for i, el in enumerate(elements):
        docs.append({
            "index": i + 1,
            "data_id": await el.get_attribute("data-id"),
            "doc_id": await el.get_attribute("id"),
            "title": (await el.inner_text()).strip(),
        })
    return docs


async def download_attachment(page, doc: dict) -> str | None:
    """Download the first link from td.picture in iframeContent0 to tmp/<data_id>.pdf."""
    content_frame = page.frame(name="iframeContent0")
    if content_frame is None:
        return None
    try:
        await content_frame.wait_for_selector("td.picture a", timeout=5000)
    except Exception:
        return None

    anchors = await content_frame.query_selector_all("td.picture a")
    if not anchors:
        return None

    href = await anchors[0].get_attribute("href")
    if not href:
        return None

    if href.startswith("/"):
        download_url = "https://doc.buu.ac.th" + href
    elif href.startswith("http"):
        download_url = href
    else:
        download_url = content_frame.url.rsplit("/", 1)[0] + "/" + href

    response = await page.context.request.get(download_url)
    if not response.ok:
        logging.warning("Attachment HTTP %d: %s", response.status, download_url)
        return None

    out_path = TMP_DIR / f"{doc['data_id']}.pdf"
    out_path.write_bytes(await response.body())
    logging.info("Attachment saved: %s (%d bytes)", out_path, out_path.stat().st_size)
    return str(out_path)


async def read_document_content(page, doc: dict) -> dict:
    inbox_frame = await get_inbox_frame(page)
    await inbox_frame.click(f"a[data-id='{doc['data_id']}']", force=True)
    logging.info("Opened: %s", doc["title"])

    # The .NET app sometimes re-renders iframeContent0 mid-read, destroying its
    # execution context and invalidating any ElementHandles. Retry a few times and
    # use locator.all_inner_texts() — it resolves+reads atomically in the browser,
    # so stale handles can't leak out between Playwright calls.
    notes = ""
    last_err: Exception | None = None
    for attempt in range(3):
        try:
            content_frame = page.frame(name="iframeContent0")
            if content_frame is None:
                await asyncio.sleep(0.5)
                continue
            try:
                await content_frame.wait_for_selector(".DocNoteContent", timeout=10000)
            except Exception:
                pass
            parts = await content_frame.locator(".DocNoteContent").all_inner_texts()
            notes = "\n---\n".join(p.strip() for p in parts if p.strip())
            last_err = None
            break
        except Exception as e:
            last_err = e
            logging.warning(
                "Note read attempt %d failed for %s: %s", attempt + 1, doc["data_id"], e
            )
            await asyncio.sleep(0.5 + attempt * 0.5)
    if last_err is not None:
        logging.error("Gave up reading notes for %s: %s", doc["data_id"], last_err)
    doc["notes"] = notes
    doc["attachment_path"] = await download_attachment(page, doc)

    await page.screenshot(path=f"screenshots/phase3_doc_{doc['data_id']}.png")
    await page.evaluate("VN.V2.App.Home.Page.HideContentFrame()")
    # Don't wait_for_load_state("networkidle"): the .NET keepalive/long-poll stream
    # never settles on some docs and burns the 30s timeout (same fix as signer.py
    # in 2dd6b37). A short sleep lets HideContentFrame finish before the next click.
    await asyncio.sleep(0.5)
    return doc


async def scrape_documents(
    page,
    limit: int | None = None,
    progress: Optional[ProgressCallback] = None,
) -> list[dict]:
    """Full scrape: list inbox + read each document's notes + download attachments.
    Side effect: writes documents_data.json.
    If `progress` is given, it's invoked as progress(current_index, total, label) after each doc."""
    TMP_DIR.mkdir(exist_ok=True)
    await page.screenshot(path="screenshots/phase3_01_inbox.png")
    docs = await list_documents(page)
    logging.info("Inbox lists %d documents", len(docs))

    if limit:
        docs = docs[:limit]

    total = len(docs)
    for i, doc in enumerate(docs, 1):
        await read_document_content(page, doc)
        if progress:
            progress(i, total, doc["title"][:50])

    with open(DOCUMENTS_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(docs, f, ensure_ascii=False, indent=2)
    logging.info("Saved %d documents → %s", len(docs), DOCUMENTS_DATA_FILE)
    return docs


def load_cached_documents() -> list[dict]:
    with open(DOCUMENTS_DATA_FILE, encoding="utf-8") as f:
        return json.load(f)
