import base64
import io
import json
import logging
import os
import re
from collections import Counter
from collections.abc import Callable
from pathlib import Path

import anthropic
import openai
from json_repair import repair_json
from pypdf import PdfReader, PdfWriter

from edoc.config import DEFAULT_COMMAND

HISTORY_FILE = "signing_history.json"
AI_MAX_TOKENS = 64000

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


def _should_fallback(exc: BaseException) -> bool:
    """True for transient Anthropic failures worth retrying on OpenAI."""
    if isinstance(exc, (anthropic.APIConnectionError, anthropic.APITimeoutError)):
        return True
    if isinstance(exc, anthropic.APIStatusError):
        return exc.status_code is None or exc.status_code >= 500
    return False


def _summarize_attachment_anthropic(
    client: anthropic.Anthropic, pdf_b64: str, model: str
) -> str:
    response = client.messages.create(
        model=model,
        max_tokens=512,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "document",
                    "source": {"type": "base64", "media_type": "application/pdf", "data": pdf_b64},
                },
                {"type": "text", "text": _ATTACHMENT_PROMPT},
            ],
        }],
    )
    return response.content[0].text.strip()


def _summarize_attachment_openai(
    client: openai.OpenAI, pdf_b64: str, model: str
) -> str:
    response = client.chat.completions.create(
        model=model,
        max_tokens=512,
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
    anth_client: anthropic.Anthropic,
    oai_client: openai.OpenAI | None,
    doc: dict,
    model: str,
    fallback_model: str,
    on_status: Callable[[str], None],
    record_used: Callable[[str, str], None],
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
    on_status(f"{status_prefix} · anthropic {model}")
    try:
        result = _summarize_attachment_anthropic(anth_client, pdf_b64, model)
        record_used("anthropic", model)
        return result
    except Exception as e:
        if not _should_fallback(e) or oai_client is None:
            logging.warning("Attachment summary failed (no fallback): %s", e)
            return None
        logging.warning("Anthropic overload (%s); falling back to OpenAI %s", e, fallback_model)
        on_status(f"{status_prefix} · openai {fallback_model} (anthropic overloaded)")
        try:
            result = _summarize_attachment_openai(oai_client, pdf_b64, fallback_model)
            record_used("openai", fallback_model)
            return result
        except Exception as e2:
            logging.warning("OpenAI fallback also failed: %s", e2)
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


def _rank_anthropic(
    client: anthropic.Anthropic, system_prompt: str, user_prompt: str, model: str
) -> str:
    with client.messages.stream(
        model=model,
        max_tokens=AI_MAX_TOKENS,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    ) as stream:
        return stream.get_final_text().strip()


def _rank_openai(
    client: openai.OpenAI, system_prompt: str, user_prompt: str, model: str
) -> str:
    # OpenAI's json_object response_format requires an object root, so we wrap the
    # array under "ranking" and unwrap before returning.
    wrapped_system = system_prompt + (
        '\n\nIMPORTANT: Return a JSON object with a single key "ranking" whose value is the array described above.'
    )
    response = client.chat.completions.create(
        model=model,
        max_tokens=AI_MAX_TOKENS,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": wrapped_system},
            {"role": "user", "content": user_prompt},
        ],
    )
    raw = (response.choices[0].message.content or "").strip()
    parsed = json.loads(raw)
    if isinstance(parsed, dict) and "ranking" in parsed:
        return json.dumps(parsed["ranking"], ensure_ascii=False)
    return raw


def analyze(
    docs: list[dict],
    model: str,
    fallback_model: str = "gpt-4o-mini",
    openai_api_key: str | None = None,
    on_status: Callable[[str], None] | None = None,
) -> list[dict]:
    """Send docs to Claude, return ranked list with rank/data_id/title/summary/reason/command.
    Falls back to OpenAI (`fallback_model`) on Anthropic overload/5xx/connection errors when
    `openai_api_key` is configured. The AI suggests `command` per document; falls back to
    DEFAULT_COMMAND if omitted.
    `on_status(msg)` is invoked before each API call so callers (the CLI progress bar) can
    show the provider+model actually in use, including mid-run fallbacks."""
    history = load_history()
    logging.info(
        "AI analysis: %d docs, %d history entries, model=%s, fallback=%s",
        len(docs), len(history), model, fallback_model if openai_api_key else "disabled",
    )

    anth_client = anthropic.Anthropic(max_retries=3)
    oai_client = openai.OpenAI(api_key=openai_api_key) if openai_api_key else None

    usage: Counter[tuple[str, str]] = Counter()
    _status = on_status or (lambda _msg: None)

    def _record(provider: str, used_model: str) -> None:
        usage[(provider, used_model)] += 1

    # Summarize PDF attachments and enrich each doc before ranking
    docs_with_att = [d for d in docs if d.get("attachment_path")]
    if docs_with_att:
        print(f"\n── Attachment analysis ({len(docs_with_att)} file(s), first 3 pages each) ──")
        for i, doc in enumerate(docs_with_att, 1):
            prefix = f"[cyan]Step 3/4 — Summarizing PDF {i}/{len(docs_with_att)}"
            summary = _summarize_attachment(
                anth_client, oai_client, doc, model, fallback_model,
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
    _status(f"{rank_prefix} · anthropic {model}")
    try:
        raw = _rank_anthropic(anth_client, system_prompt, user_prompt, model)
        _record("anthropic", model)
    except Exception as e:
        if not _should_fallback(e) or oai_client is None:
            raise
        logging.warning("Anthropic ranking overload (%s); falling back to OpenAI %s", e, fallback_model)
        print(f"\n[!] Anthropic overloaded; retrying ranking on OpenAI {fallback_model}")
        _status(f"{rank_prefix} · openai {fallback_model} (anthropic overloaded)")
        raw = _rank_openai(oai_client, system_prompt, user_prompt, fallback_model)
        _record("openai", fallback_model)

    logging.info("AI response received (%d chars)", len(raw))
    usage_str = ", ".join(f"{p} {m} ×{n}" for (p, m), n in usage.most_common()) or "none"
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

    # Re-attach fields that Claude doesn't echo back. "opinion" is computed
    # deterministically (not by the AI) so it faithfully quotes what staff wrote.
    att_map = {d["data_id"]: d.get("attachment_path") for d in docs}
    opinion_map = {d["data_id"]: _extract_staff_opinion(d.get("notes", "")) for d in docs}
    for item in suggested:
        path = att_map.get(item["data_id"])
        if path:
            item["attachment_path"] = path
        item["opinion"] = opinion_map.get(item["data_id"], "")

    return suggested
