import asyncio
import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from pydantic import BaseModel
from playwright.async_api import async_playwright

from phase3_read_docs import (
    login,
    navigate_to_inbox,
    get_document_list,
    read_document_content,
    get_inbox_frame,
)
from phase4_ai_analysis import (
    load_history,
    save_history,
    build_system_prompt,
    build_prompt,
    DEFAULT_COMMAND,
)
from edoc.browser import login as edoc_login
from edoc.browser import navigate_to_inbox as edoc_navigate_to_inbox
from edoc.browser import open_page as edoc_open_page
from edoc.signer import (
    open_and_fill_form,
    confirm_sign,
    dismiss_form,
)
import anthropic
from json_repair import repair_json

load_dotenv()
Path("screenshots").mkdir(exist_ok=True)

logging.basicConfig(
    filename="edoc_automation.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

app = FastAPI()
app.mount("/screenshots", StaticFiles(directory="screenshots"), name="screenshots")
templates = Jinja2Templates(directory="templates")

# ── Shared state ────────────────────────────────────────────────────────────

phase3_state: dict = {"running": False, "done": False, "task": None, "sse_queue": None}
phase4_state: dict = {"running": False, "done": False, "task": None, "sse_queue": None, "results": None}
phase5_state: dict = {
    "running": False, "done": False, "task": None, "sse_queue": None,
    "current_doc": None, "decision_event": None, "decision_value": None,
}

# ── Pydantic models ─────────────────────────────────────────────────────────

class StartBody(BaseModel):
    dry_run: bool = True

class Decision(BaseModel):
    data_id: str
    command: str
    approved: bool

class SubmitBody(BaseModel):
    decisions: list[Decision]

class DecisionBody(BaseModel):
    action: str  # "go" or "skip"

# ── Utility ──────────────────────────────────────────────────────────────────

async def sse_stream(queue: asyncio.Queue):
    while True:
        event = await queue.get()
        yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        if event.get("type") in ("done", "all_done", "error", "stopped"):
            break

# ── Routes ───────────────────────────────────────────────────────────────────

@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html")

@app.get("/api/status")
async def status():
    return {
        "phase3": {"running": phase3_state["running"], "done": phase3_state["done"]},
        "phase4": {"running": phase4_state["running"], "done": phase4_state["done"]},
        "phase5": {"running": phase5_state["running"], "done": phase5_state["done"]},
    }

# ── Phase 3 ──────────────────────────────────────────────────────────────────

async def run_phase3(dry_run: bool):
    q = phase3_state["sse_queue"]
    browser = None
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            page = await browser.new_page()
            await login(page)
            await navigate_to_inbox(page)
            docs = await get_document_list(page)
            await q.put({"type": "start", "total": len(docs)})
            logging.info("Phase 3 web — %d documents found", len(docs))

            for doc in docs:
                doc = await read_document_content(page, doc)
                await q.put({
                    "type": "progress",
                    "index": doc["index"],
                    "total": len(docs),
                    "data_id": doc["data_id"],
                    "title": doc["title"],
                    "notes_preview": doc.get("notes", "")[:80],
                })

            Path("documents_data.json").write_text(
                json.dumps(docs, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            phase3_state["done"] = True
            await q.put({"type": "done", "total": len(docs)})
            logging.info("Phase 3 web — saved documents_data.json")

    except asyncio.CancelledError:
        await q.put({"type": "stopped"})
        logging.info("Phase 3 cancelled")
    except Exception as e:
        await q.put({"type": "error", "message": str(e)})
        logging.exception("Phase 3 error")
    finally:
        phase3_state["running"] = False
        if browser:
            try:
                await browser.close()
            except Exception:
                pass

@app.post("/api/phase3/start")
async def phase3_start(body: StartBody):
    if phase3_state["running"]:
        raise HTTPException(400, "Phase 3 already running")
    phase3_state["running"] = True
    phase3_state["done"] = False
    phase3_state["sse_queue"] = asyncio.Queue()
    phase3_state["task"] = asyncio.create_task(run_phase3(body.dry_run))
    return {"ok": True}

@app.post("/api/phase3/stop")
async def phase3_stop():
    if phase3_state["task"]:
        phase3_state["task"].cancel()
    return {"ok": True}

@app.get("/api/phase3/stream")
async def phase3_stream():
    if phase3_state["sse_queue"] is None:
        phase3_state["sse_queue"] = asyncio.Queue()
    return StreamingResponse(
        sse_stream(phase3_state["sse_queue"]),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

# ── Phase 4 ──────────────────────────────────────────────────────────────────

async def run_phase4():
    q = phase4_state["sse_queue"]
    try:
        with open("documents_data.json", encoding="utf-8") as f:
            docs = json.load(f)

        await q.put({"type": "start", "doc_count": len(docs)})
        await q.put({"type": "thinking"})
        logging.info("Phase 4 web — calling AI for %d docs", len(docs))

        history = load_history()

        def _call_api():
            client = anthropic.Anthropic()
            sample = docs[:10]
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=8192,
                system=build_system_prompt(history),
                messages=[{"role": "user", "content": build_prompt(sample)}],
            )
            return response.content[0].text.strip()

        raw = await asyncio.to_thread(_call_api)

        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        start, end = raw.find("["), raw.rfind("]")
        if start != -1 and end != -1:
            raw = raw[start:end + 1]

        parsed = json.loads(repair_json(raw))
        for item in parsed:
            item["data_id"] = str(item["data_id"])
        suggested = sorted(parsed, key=lambda x: x["rank"])

        phase4_state["results"] = suggested
        phase4_state["done"] = True
        await q.put({"type": "done", "ranked_count": len(suggested)})
        logging.info("Phase 4 web — AI returned %d ranked docs", len(suggested))

    except Exception as e:
        await q.put({"type": "error", "message": str(e)})
        logging.exception("Phase 4 error")
    finally:
        phase4_state["running"] = False

@app.post("/api/phase4/start")
async def phase4_start():
    if phase4_state["running"]:
        raise HTTPException(400, "Phase 4 already running")
    if not Path("documents_data.json").exists():
        raise HTTPException(400, "documents_data.json not found — run Phase 3 first")
    phase4_state["running"] = True
    phase4_state["done"] = False
    phase4_state["results"] = None
    phase4_state["sse_queue"] = asyncio.Queue()
    phase4_state["task"] = asyncio.create_task(run_phase4())
    return {"ok": True}

@app.get("/api/phase4/stream")
async def phase4_stream():
    if phase4_state["sse_queue"] is None:
        phase4_state["sse_queue"] = asyncio.Queue()
    return StreamingResponse(
        sse_stream(phase4_state["sse_queue"]),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

@app.get("/api/documents")
async def documents():
    p = Path("documents_data.json")
    if not p.exists():
        raise HTTPException(404, "documents_data.json not found")
    return json.loads(p.read_text(encoding="utf-8"))

@app.get("/api/phase4/results")
async def phase4_results():
    if phase4_state["results"] is None:
        raise HTTPException(404, "No results yet — run Phase 4 first")
    return phase4_state["results"]

@app.post("/api/phase4/submit")
async def phase4_submit(body: SubmitBody):
    approved = []
    results_map = {r["data_id"]: r for r in (phase4_state["results"] or [])}

    for d in body.decisions:
        if not d.approved:
            continue
        item = dict(results_map.get(d.data_id, {"data_id": d.data_id, "title": "", "rank": 0}))
        item["final_command"] = d.command
        approved.append(item)

    Path("approved_order.json").write_text(
        json.dumps(approved, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Update signing history
    with open("documents_data.json", encoding="utf-8") as f:
        docs = json.load(f)
    notes_map = {d["data_id"]: d.get("notes", "") for d in docs}
    save_history(approved, notes_map)

    logging.info("Phase 4 web — saved %d approved docs", len(approved))
    return {"saved": len(approved)}

# ── Phase 5 ──────────────────────────────────────────────────────────────────

async def run_phase5(dry_run: bool):
    q = phase5_state["sse_queue"]
    browser = None
    try:
        with open("approved_order.json", encoding="utf-8") as f:
            approved = json.load(f)

        username = os.getenv("EDOC_USERNAME")
        password = os.getenv("EDOC_PASSWORD")
        inbox_name = os.getenv("INBOX")
        missing = [
            name for name, value in (
                ("EDOC_USERNAME", username),
                ("EDOC_PASSWORD", password),
                ("INBOX", inbox_name),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")

        await q.put({"type": "start", "total": len(approved), "dry_run": dry_run})
        logging.info("Phase 5 web — DRY_RUN=%s, %d docs", dry_run, len(approved))

        async with async_playwright() as p:
            browser, _, page = await edoc_open_page(p, headless=False)
            await edoc_login(page, username, password)
            await edoc_navigate_to_inbox(page, inbox_name)

            for i, doc in enumerate(approved, 1):
                if "command" not in doc:
                    doc["command"] = doc.get("final_command", "")
                # Fill form and get screenshot before pausing for user decision
                ctx = await open_and_fill_form(page, doc, inbox_name)

                event = asyncio.Event()
                phase5_state["decision_event"] = event
                phase5_state["decision_value"] = None
                phase5_state["current_doc"] = doc

                await q.put({
                    "type": "await_decision",
                    "index": i,
                    "total": len(approved),
                    "doc": doc,
                    "form_screenshot": Path(ctx["form_screenshot"]).name,
                })

                await event.wait()  # pause — unblocked by POST /api/phase5/decision/{data_id}

                action = phase5_state["decision_value"]
                if action == "go":
                    after_path = await confirm_sign(page, dry_run, ctx["data_id"], ctx["ts"])
                    logging.info("Phase 5 web — signed %s (dry=%s)", ctx["data_id"], dry_run)
                else:
                    await dismiss_form(page)
                    after_path = None
                    logging.info("Phase 5 web — skipped %s", ctx["data_id"])

                await q.put({
                    "type": "doc_done",
                    "index": i,
                    "total": len(approved),
                    "data_id": ctx["data_id"],
                    "title": doc["title"],
                    "action": action,
                    "after_screenshot": Path(after_path).name if after_path else None,
                })

            phase5_state["done"] = True
            await q.put({"type": "all_done", "total": len(approved)})

    except asyncio.CancelledError:
        await q.put({"type": "stopped"})
        logging.info("Phase 5 cancelled")
    except Exception as e:
        await q.put({"type": "error", "message": str(e)})
        logging.exception("Phase 5 error")
    finally:
        phase5_state["running"] = False
        phase5_state["current_doc"] = None
        if browser:
            try:
                await browser.close()
            except Exception:
                pass

@app.post("/api/phase5/start")
async def phase5_start(body: StartBody):
    if phase5_state["running"]:
        raise HTTPException(400, "Phase 5 already running")
    if not Path("approved_order.json").exists():
        raise HTTPException(400, "approved_order.json not found — run Phase 4 first")
    phase5_state["running"] = True
    phase5_state["done"] = False
    phase5_state["sse_queue"] = asyncio.Queue()
    phase5_state["task"] = asyncio.create_task(run_phase5(body.dry_run))
    return {"ok": True}

@app.post("/api/phase5/stop")
async def phase5_stop():
    if phase5_state["task"]:
        phase5_state["task"].cancel()
    return {"ok": True}

@app.get("/api/phase5/stream")
async def phase5_stream():
    if phase5_state["sse_queue"] is None:
        phase5_state["sse_queue"] = asyncio.Queue()
    return StreamingResponse(
        sse_stream(phase5_state["sse_queue"]),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

@app.post("/api/phase5/decision/{data_id}")
async def phase5_decision(data_id: str, body: DecisionBody):
    current = phase5_state.get("current_doc")
    if not phase5_state["running"] or current is None or current["data_id"] != data_id:
        raise HTTPException(400, f"No pending decision for doc {data_id}")
    if body.action not in ("go", "skip"):
        raise HTTPException(400, "action must be 'go' or 'skip'")
    phase5_state["decision_value"] = body.action
    phase5_state["decision_event"].set()
    return {"ok": True}
