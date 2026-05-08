import json
import logging
from typing import Callable, Optional

from edoc.browser import get_inbox_frame

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


async def read_document_content(page, doc: dict) -> dict:
    inbox_frame = await get_inbox_frame(page)
    await inbox_frame.click(f"a[data-id='{doc['data_id']}']", force=True)
    logging.info("Opened: %s", doc["title"])

    content_frame = page.frame(name="iframeContent0")
    try:
        await content_frame.wait_for_selector(".DocNoteContent", timeout=10000)
    except Exception:
        pass

    note_els = await content_frame.query_selector_all(".DocNoteContent")
    parts = [(await el.inner_text()).strip() for el in note_els]
    doc["notes"] = "\n---\n".join(p for p in parts if p)

    await page.screenshot(path=f"screenshots/phase3_doc_{doc['data_id']}.png")
    await page.evaluate("VN.V2.App.Home.Page.HideContentFrame()")
    await page.wait_for_load_state("networkidle")
    return doc


async def scrape_documents(
    page,
    limit: int | None = None,
    progress: Optional[ProgressCallback] = None,
) -> list[dict]:
    """Full scrape: list inbox + read each document's notes. Side effect: writes documents_data.json.
    If `progress` is given, it's invoked as progress(current_index, total, label) after each doc."""
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
