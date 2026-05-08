import json
import logging
import os

import anthropic
from json_repair import repair_json

from edoc.config import DEFAULT_COMMAND

HISTORY_FILE = "signing_history.json"
AI_MODEL = "claude-sonnet-4-6"
AI_MAX_TOKENS = 64000

SYSTEM_PROMPT_BASE = """\
You are an assistant helping a Thai university administrator prioritize document signing.
Given a list of documents with their titles and recommendation notes, return a JSON array (no prose, no markdown fences).
You MUST include every single document from the input — do not omit any.

Each element must have:
  "rank"    – integer, 1 = sign first
  "data_id" – string, copied from input
  "title"   – string, copied from input
  "summary" – one Thai sentence summarising the recommendation notes
  "reason"  – one Thai sentence explaining the rank

Rank by:
1. Urgency (deadlines, time-sensitive language)
2. Seniority of sender
3. Topic importance (financial, legal, administrative)
4. Date received (older first as tiebreaker)"""


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


def _build_user_prompt(docs: list[dict]) -> str:
    lines = []
    for d in docs:
        lines.append(f"data_id: {d['data_id']}")
        lines.append(f"title: {d['title']}")
        if d.get("notes"):
            lines.append(f"notes: {d['notes'][:150]}")
        lines.append("")
    return "\n".join(lines)


def analyze(docs: list[dict]) -> list[dict]:
    """Send docs to Claude, return ranked list with rank/data_id/title/summary/reason/command.
    Each item's `command` defaults to DEFAULT_COMMAND; user edits via documents.md."""
    history = load_history()
    logging.info("AI analysis: %d docs, %d history entries", len(docs), len(history))

    client = anthropic.Anthropic()
    with client.messages.stream(
        model=AI_MODEL,
        max_tokens=AI_MAX_TOKENS,
        system=_build_system_prompt(history),
        messages=[{"role": "user", "content": _build_user_prompt(docs)}],
    ) as stream:
        raw = stream.get_final_text().strip()
    logging.info("AI response received (%d chars)", len(raw))

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
        item.setdefault("command", DEFAULT_COMMAND)

    suggested = sorted(parsed, key=lambda x: x["rank"])
    if len(suggested) != len(docs):
        logging.warning("AI returned %d of %d documents", len(suggested), len(docs))
    return suggested
