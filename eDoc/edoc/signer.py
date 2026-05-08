import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime

from edoc.browser import get_inbox_frame, navigate_to_inbox, wait_for_content_frame


@dataclass
class SignResult:
    data_id: str
    title: str
    command: str
    signed: bool      # True if OK clicked, False if Cancel/dry-run/skip
    error: str | None = None


async def _open_and_fill_form(page, doc: dict, inbox_name: str) -> dict:
    data_id = doc["data_id"]
    command = doc["command"]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    content_frame = None
    for attempt in range(3):
        if attempt > 0:
            logging.warning("Retry %d — re-navigating to inbox for %s", attempt, data_id)
            await navigate_to_inbox(page, inbox_name)
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
        raise RuntimeError(f"Content frame missing for {doc['title']}")

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

    await page.click("#optSignConfirmOptions0")
    await page.fill("#txtTargetTypeNote", command)
    await page.screenshot(path=f"screenshots/phase5_form_{data_id}_{ts}.png")
    return {"data_id": data_id, "ts": ts}


async def _confirm(page, dry_run: bool, data_id: str, ts: str) -> None:
    if dry_run:
        await page.click("#btnSignConfirmCancel")
        logging.info("[DRY_RUN] Cancelled signing for %s", data_id)
    else:
        await page.click("#btnSignConfirmOK")
        logging.info("Signed %s", data_id)
    await page.wait_for_load_state("networkidle")
    await page.screenshot(path=f"screenshots/phase5_after_{data_id}_{ts}.png")
    await page.evaluate("VN.V2.App.Home.Page.HideContentFrame()")
    await page.wait_for_load_state("networkidle")
    await asyncio.sleep(1.5)


async def sign_one(page, doc: dict, inbox_name: str, dry_run: bool) -> SignResult:
    try:
        ctx = await _open_and_fill_form(page, doc, inbox_name)
        await _confirm(page, dry_run, ctx["data_id"], ctx["ts"])
        return SignResult(
            data_id=doc["data_id"],
            title=doc["title"],
            command=doc["command"],
            signed=not dry_run,
        )
    except Exception as e:
        logging.exception("Sign failed for %s", doc.get("data_id"))
        return SignResult(
            data_id=doc.get("data_id", "?"),
            title=doc.get("title", "?"),
            command=doc.get("command", ""),
            signed=False,
            error=str(e),
        )
