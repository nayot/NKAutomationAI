import base64
import io
import json
import logging
import os
import re
from collections import Counter
from collections.abc import Callable
from pathlib import Path

import openai
from json_repair import repair_json
from pypdf import PdfReader, PdfWriter

from edoc.config import (
    DEFAULT_AI_MAX_TOKENS,
    DEFAULT_AI_MODEL,
    DEFAULT_AI_PDF_ENGINE,
    DEFAULT_COMMAND,
    OPENROUTER_BASE_URL,
)

HISTORY_FILE = "signing_history.json"
ATTACHMENT_MAX_TOKENS = 512

SYSTEM_PROMPT_BASE = """\
You are an assistant helping a Thai university administrator prioritize and annotate document signing.
Given a list of documents with their titles and recommendation notes, return a JSON array (no prose, no markdown fences).
You MUST include every single document from the input — do not omit any.

Each element must have:
  "rank"    – integer, 1 = sign first
  "data_id" – string, copied from input
  "title"   – string, copied from input
  "summary" – one Thai sentence summarising the recommendation notes
  "reason"  – one Thai sentence explaining the rank
  "command" – the Thai "คำสั่งการ" phrase to write into the sign-confirm dialog (see guidance below)

Rank by:
1. Urgency (deadlines, time-sensitive language)
2. Seniority of sender
3. Topic importance (financial, legal, administrative)
4. Date received (older first as tiebreaker)

Command ("คำสั่งการ") guidance:
- Prefer one of the canonical short leading verbs when they fit:
  * "ดำเนินการตามเสนอ" – default; proceed as the proposer recommended
  * "ทราบ" – purely informational, no action needed
  * "อนุมัติ" – formally authorize (typically financial or HR approvals)
  * "พิจารณา" – delegate for further consideration
- HARD RULE: do NOT start a command with "เห็นชอบ". The eDoc system treats it as a
  forwarding workflow that opens an extra recipient dropdown this automation cannot fill,
  and the sign dialog will silently fail. If you would have written "เห็นชอบ…", rewrite
  it as "ทราบและ…" (or "ดำเนินการตามเสนอ" if no further routing is needed).
- When the notes call for delegation or naming people (e.g. nominating committee members,
  routing to a specific office), compose a custom command that combines a canonical leading
  verb (above) with the specifics, following the patterns in the user's history examples below.
- When uncertain, use "ดำเนินการตามเสนอ"."""


class AnalyzerError(Exception):
    pass


def load_history() -> list[dict]:
    if not os.path.exists(HISTORY_FILE):
        return []
    with open(HISTORY_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_history(signed_docs: list[dict], notes_map: dict[str, str]) -> None:
    history = load_history()
    for item in signed_docs:
        history.append({
            "title": item["title"],
            "notes": notes_map.get(item["data_id"], "")[:150],
            "command": item["command"],
        })
    history = history[-100:]
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    logging.info("Signing history updated (%d total entries)", len(history))


def _build_system_prompt(history: list[dict]) -> str:
    prompt = SYSTEM_PROMPT_BASE
    if history:
        examples = "\n".join(
            f'- "{h["title"][:60]}" | บันทึก: "{h["notes"][:80]}" → คำสั่ง: "{h["command"]}"'
            for h in history[-20:]
        )
        prompt += f"\n\nตัวอย่างคำสั่งการที่ผู้ใช้เคยอนุมัติไว้ (ใช้เป็นแนวทาง):\n{examples}"
    return prompt


_ATTACHMENT_PROMPT = (
    "สรุปเนื้อหาสำคัญของเอกสารแนบนี้เป็นภาษาไทย ไม่เกิน 3 ประโยค "
    "โดยเน้นประเด็นที่เกี่ยวข้องกับการลงนาม เช่น วัตถุประสงค์ งบประมาณ กำหนดเวลา"
)


def _slice_pdf_bytes(path: str, max_pages: int = 3) -> bytes:
    reader = PdfReader(path)
    writer = PdfWriter()
    for i, page in enumerate(reader.pages):
        if i >= max_pages:
            break
        writer.add_page(page)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def make_client(api_key: str, base_url: str = OPENROUTER_BASE_URL) -> openai.OpenAI:
    """OpenRouter speaks the OpenAI chat-completions protocol, so the openai SDK
    drives it with nothing but a different base_url. `api_key` is always passed
    explicitly — left to itself the SDK would silently pick up OPENAI_API_KEY
    from the environment and send the wrong credential to OpenRouter."""
    return openai.OpenAI(api_key=api_key, base_url=base_url, max_retries=3)


def _should_fallback(exc: BaseException) -> bool:
    """True for transient failures worth retrying on the fallback model."""
    if isinstance(exc, (openai.APIConnectionError, openai.APITimeoutError)):
        return True
    if isinstance(exc, openai.APIStatusError):
        return exc.status_code is None or exc.status_code >= 500 or exc.status_code == 429
    return False


def _summarize_attachment_call(
    client: openai.OpenAI, pdf_b64: str, model: str, pdf_engine: str | None
) -> str:
    # `plugins` is an OpenRouter-only field, so it rides along in extra_body.
    # Pinning the engine keeps PDF cost predictable: with no engine set,
    # OpenRouter bills per-page OCR for any model lacking native file input.
    extra_body = (
        {"plugins": [{"id": "file-parser", "pdf": {"engine": pdf_engine}}]}
        if pdf_engine
        else {}
    )
    response = client.chat.completions.create(
        model=model,
        max_tokens=ATTACHMENT_MAX_TOKENS,
        extra_body=extra_body,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "file",
                    "file": {
                        "filename": "attachment.pdf",
                        "file_data": f"data:application/pdf;base64,{pdf_b64}",
                    },
                },
                {"type": "text", "text": _ATTACHMENT_PROMPT},
            ],
        }],
    )
    return (response.choices[0].message.content or "").strip()


def _summarize_attachment(
    client: openai.OpenAI,
    doc: dict,
    model: str,
    fallback_model: str | None,
    pdf_engine: str | None,
    on_status: Callable[[str], None],
    record_used: Callable[[str], None],
    status_prefix: str,
) -> str | None:
    path = doc.get("attachment_path")
    if not path or not Path(path).exists():
        return None
    try:
        pdf_bytes = _slice_pdf_bytes(path)
    except Exception as e:
        logging.warning("Could not slice PDF %s: %s", path, e)
        return None

    pdf_b64 = base64.standard_b64encode(pdf_bytes).decode()
    on_status(f"{status_prefix} · {model}")
    try:
        result = _summarize_attachment_call(client, pdf_b64, model, pdf_engine)
        record_used(model)
        return result
    except Exception as e:
        if not _should_fallback(e) or not fallback_model:
            logging.warning("Attachment summary failed (no fallback): %s", e)
            return None
        logging.warning("%s unavailable (%s); falling back to %s", model, e, fallback_model)
        on_status(f"{status_prefix} · {fallback_model} ({model} unavailable)")
        try:
            result = _summarize_attachment_call(client, pdf_b64, fallback_model, pdf_engine)
            record_used(fallback_model)
            return result
        except Exception as e2:
            logging.warning("Fallback model %s also failed: %s", fallback_model, e2)
            return None


_GENERIC_ROUTING_STAMPS = {
    "นำเสนอผู้บริหารเพื่อพิจารณา",
    "นำเสนอผู้บริหารเพื่อพิจารณาลงนาม",
    "นำเสนอผู้บริหารเพื่อโปรดพิจารณา",
    "นำเสนอผู้บริหารเพื่อโปรดพิจารณาลงนาม",
}
_NUMBERED_LINE_START_RE = re.compile(r"^\s*\d+[.)]\s*")


def _split_numbered_items(block: str) -> list[str]:
    """Split a 'เรียน ...' memo block into its numbered items ('1. ...', '2. ...'),
    joining any wrapped continuation lines back into each item."""
    items: list[str] = []
    current: list[str] = []
    for line in block.splitlines():
        if _NUMBERED_LINE_START_RE.match(line):
            if current:
                items.append(" ".join(current).strip())
            current = [_NUMBERED_LINE_START_RE.sub("", line)]
        elif current:
            current.append(line.strip())
    if current:
        items.append(" ".join(current).strip())
    return items


def _extract_staff_opinion(notes: str) -> str:
    """Pull the literal comments staff wrote while routing this document — a short
    routing note (e.g. "ทราบ") plus every numbered item inside the formal memo (e.g.
    "1. ... เรื่อง <topic>" and "2. เห็นสมควร...") — verbatim. Computed deterministically
    (no AI) so the admin sees exactly what staff wrote, not a paraphrase that risks
    drifting into a generic restatement of the document.

    Item 1 is kept (not just the final recommendation item) because it's usually the
    only part of the memo that names the specific document/topic — dropping it made
    two different documents that share the same generic closing instruction (e.g.
    "เห็นสมควรมอบ งานบริหารวิจัย ทำหนังสือนำส่ง...ผ่านระบบ e-Sign ต่อไป") render with
    byte-identical opinion text, which read as a duplication bug."""
    if not notes:
        return ""
    candidates: list[str] = []
    for block in notes.split("\n---\n"):
        block = block.strip()
        if not block:
            continue
        if block.startswith("เรียน"):
            for item in _split_numbered_items(block):
                if item:
                    candidates.append(item)
            continue
        if block in _GENERIC_ROUTING_STAMPS:
            continue
        if len(block) <= 80:
            candidates.append(block)
    seen: set[str] = set()
    out: list[str] = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return " / ".join(out)


def _build_user_prompt(docs: list[dict]) -> str:
    lines = []
    for d in docs:
        lines.append(f"data_id: {d['data_id']}")
        lines.append(f"title: {d['title']}")
        if d.get("notes"):
            lines.append(f"notes: {d['notes'][:500]}")
        if d.get("attachment_summary"):
            lines.append(f"attachment_summary: {d['attachment_summary']}")
        lines.append("")
    return "\n".join(lines)


def _rank_call(
    client: openai.OpenAI, system_prompt: str, user_prompt: str, model: str, max_tokens: int
) -> str:
    # No response_format={"type": "json_object"} here: it is not supported across
    # every OpenRouter model, and it forbids the bare JSON array the system prompt
    # asks for. The caller's fence-strip + json_repair pass handles the raw text.
    response = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    return (response.choices[0].message.content or "").strip()


def analyze(
    docs: list[dict],
    api_key: str,
    model: str = DEFAULT_AI_MODEL,
    fallback_model: str | None = None,
    base_url: str = OPENROUTER_BASE_URL,
    max_tokens: int = DEFAULT_AI_MAX_TOKENS,
    pdf_engine: str | None = DEFAULT_AI_PDF_ENGINE,
    on_status: Callable[[str], None] | None = None,
) -> list[dict]:
    """Send docs to the model chosen in .env (via OpenRouter), return ranked list with
    rank/data_id/title/summary/reason/command.
    `model` and `fallback_model` are OpenRouter slugs (e.g. "anthropic/claude-haiku-4.5");
    the fallback is retried on 5xx/429/connection errors and is skipped when falsy.
    The AI suggests `command` per document; falls back to DEFAULT_COMMAND if omitted.
    `on_status(msg)` is invoked before each API call so callers (the CLI progress bar) can
    show the model actually in use, including mid-run fallbacks."""
    history = load_history()
    logging.info(
        "AI analysis: %d docs, %d history entries, model=%s, fallback=%s, max_tokens=%d, pdf_engine=%s",
        len(docs), len(history), model, fallback_model or "disabled", max_tokens,
        pdf_engine or "openrouter-default",
    )

    client = make_client(api_key, base_url)

    usage: Counter[str] = Counter()
    _status = on_status or (lambda _msg: None)

    def _record(used_model: str) -> None:
        usage[used_model] += 1

    # Summarize PDF attachments and enrich each doc before ranking
    docs_with_att = [d for d in docs if d.get("attachment_path")]
    if docs_with_att:
        print(f"\n── Attachment analysis ({len(docs_with_att)} file(s), first 3 pages each) ──")
        for i, doc in enumerate(docs_with_att, 1):
            prefix = f"[cyan]Step 3/4 — Summarizing PDF {i}/{len(docs_with_att)}"
            summary = _summarize_attachment(
                client, doc, model, fallback_model, pdf_engine,
                _status, _record, prefix,
            )
            doc["attachment_summary"] = summary
            if summary:
                print(f"[{doc['data_id']}] {doc['title'][:60]}")
                print(f"  PDF: {summary}\n")
                logging.info("Attachment summary %s: %s", doc["data_id"], summary[:100])
            else:
                print(f"[{doc['data_id']}] attachment could not be read\n")

    system_prompt = _build_system_prompt(history)
    user_prompt = _build_user_prompt(docs)

    rank_prefix = f"[cyan]Step 4/4 — Ranking {len(docs)} docs"
    _status(f"{rank_prefix} · {model}")
    try:
        raw = _rank_call(client, system_prompt, user_prompt, model, max_tokens)
        _record(model)
    except Exception as e:
        if not _should_fallback(e) or not fallback_model:
            raise
        logging.warning("Ranking on %s failed (%s); falling back to %s", model, e, fallback_model)
        print(f"\n[!] {model} unavailable; retrying ranking on {fallback_model}")
        _status(f"{rank_prefix} · {fallback_model} ({model} unavailable)")
        raw = _rank_call(client, system_prompt, user_prompt, fallback_model, max_tokens)
        _record(fallback_model)

    logging.info("AI response received (%d chars)", len(raw))
    usage_str = ", ".join(f"{m} ×{n}" for m, n in usage.most_common()) or "none"
    print(f"\nModel usage: {usage_str}")
    logging.info("Model usage: %s", usage_str)

    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
        raw = raw.rsplit("```", 1)[0].strip()
    start = raw.find("[")
    if start != -1:
        raw = raw[start:]

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        try:
            parsed = json.loads(repair_json(raw))
        except Exception as e:
            with open("ai_response_raw.txt", "w", encoding="utf-8") as f:
                f.write(raw)
            raise AnalyzerError(f"Could not parse AI response: {e}. Raw saved to ai_response_raw.txt.") from e

    for item in parsed:
        item["data_id"] = str(item["data_id"])
        cmd = (item.get("command") or "").strip()
        if not cmd:
            logging.warning("AI omitted command for %s; falling back to default", item["data_id"])
            cmd = DEFAULT_COMMAND
        item["command"] = cmd

    suggested = sorted(parsed, key=lambda x: x["rank"])
    if len(suggested) != len(docs):
        logging.warning("AI returned %d of %d documents", len(suggested), len(docs))

    # Re-attach fields the model doesn't echo back. "opinion" is computed
    # deterministically (not by the AI) so it faithfully quotes what staff wrote.
    att_map = {d["data_id"]: d.get("attachment_path") for d in docs}
    opinion_map = {d["data_id"]: _extract_staff_opinion(d.get("notes", "")) for d in docs}
    for item in suggested:
        path = att_map.get(item["data_id"])
        if path:
            item["attachment_path"] = path
        item["opinion"] = opinion_map.get(item["data_id"], "")

    return suggested
