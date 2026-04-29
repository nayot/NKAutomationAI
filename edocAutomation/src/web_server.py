"""
FastAPI localhost approval server.
Start with: python main.py --serve  (or uvicorn src.web_server:app --port 8080)

Endpoints:
  GET /approve?tokens=ID1:TOKEN1,ID2:TOKEN2   — bulk approve
  GET /approve/{doc_id}?token=TOKEN           — single approve
  GET /done                                   — graceful shutdown
"""
import json
import os
import asyncio
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import HTMLResponse

PENDING_FILE = Path("/tmp/edoc_pending.json")

app = FastAPI(title="edocAutomation Approval Server")
_shutdown_event: Optional[asyncio.Event] = None


def set_shutdown_event(event: asyncio.Event):
    global _shutdown_event
    _shutdown_event = event


def load_pending() -> dict:
    if PENDING_FILE.exists():
        return json.loads(PENDING_FILE.read_text())
    return {}


def save_pending(data: dict):
    PENDING_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def _success_html(approved: list[str], failed: list[str]) -> str:
    ok_rows = "".join(f"<li>✅ {d}</li>" for d in approved)
    fail_rows = "".join(f"<li>❌ {d}</li>" for d in failed)
    return f"""
    <html><body style="font-family:sans-serif;padding:40px;">
    <h2>ผลการสั่งการอัตโนมัติ</h2>
    <ul>{ok_rows}</ul>
    {"<h3>ล้มเหลว</h3><ul>" + fail_rows + "</ul>" if failed else ""}
    <p><a href="/done">ปิดเซิร์ฟเวอร์</a></p>
    </body></html>"""


@app.get("/approve/{doc_id}", response_class=HTMLResponse)
async def approve_single(doc_id: str, token: str = Query(...)):
    """Approve a single document by doc_id."""
    from .ai_analyzer import AiAnalyzer
    analyzer = AiAnalyzer()

    if not analyzer.verify_token(doc_id, token):
        raise HTTPException(status_code=403, detail="Invalid approval token")

    pending = load_pending()
    if doc_id not in pending:
        return HTMLResponse("<html><body><p>เอกสารนี้ถูกสั่งการไปแล้ว หรือไม่พบในรายการรอ</p></body></html>")

    rec_data = pending[doc_id]
    from .models import Document
    from .edoc_client import EdocClient

    doc = Document(**rec_data["doc"])
    approved, failed = [], []

    async with EdocClient(headless=True) as client:
        edoc_user = os.environ.get("EDOC_USERNAME", "")
        edoc_pass = os.environ.get("EDOC_PASSWORD", "")
        await client.login(edoc_user, edoc_pass)
        success = await client.submit_order(doc, "ทราบ / ดำเนินการตามเสนอ")
        (approved if success else failed).append(doc.subject)

    if approved:
        del pending[doc_id]
        save_pending(pending)

    return HTMLResponse(_success_html(approved, failed))


@app.get("/approve", response_class=HTMLResponse)
async def approve_bulk(tokens: str = Query(...)):
    """
    Bulk approve.
    tokens format: doc_id1:token1,doc_id2:token2,...
    """
    from .ai_analyzer import AiAnalyzer
    from .models import Document
    from .edoc_client import EdocClient

    analyzer = AiAnalyzer()
    pairs = [t.split(":", 1) for t in tokens.split(",") if ":" in t]

    invalid = [doc_id for doc_id, tok in pairs if not analyzer.verify_token(doc_id, tok)]
    if invalid:
        raise HTTPException(status_code=403, detail=f"Invalid tokens for: {invalid}")

    pending = load_pending()
    approved, failed = [], []

    async with EdocClient(headless=True) as client:
        edoc_user = os.environ.get("EDOC_USERNAME", "")
        edoc_pass = os.environ.get("EDOC_PASSWORD", "")
        await client.login(edoc_user, edoc_pass)

        for doc_id, _tok in pairs:
            if doc_id not in pending:
                continue
            rec_data = pending[doc_id]
            doc = Document(**rec_data["doc"])
            success = await client.submit_order(doc, "ทราบ / ดำเนินการตามเสนอ")
            (approved if success else failed).append(doc.subject)
            if success:
                del pending[doc_id]

    save_pending(pending)
    return HTMLResponse(_success_html(approved, failed))


@app.get("/done", response_class=HTMLResponse)
async def shutdown():
    """Graceful server shutdown after all approvals done."""
    if _shutdown_event:
        _shutdown_event.set()
    return HTMLResponse("<html><body><h2>เซิร์ฟเวอร์ปิดแล้ว ขอบคุณ</h2></body></html>")
