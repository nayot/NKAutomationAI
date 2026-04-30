import json
import os
import logging
from dotenv import load_dotenv
import anthropic
from json_repair import repair_json

load_dotenv()

logging.basicConfig(
    filename="edoc_automation.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

HISTORY_FILE = "signing_history.json"
DEFAULT_COMMAND = "ดำเนินการตามเสนอ"

SYSTEM_PROMPT_BASE = """\
You are an assistant helping a Thai university administrator prioritize document signing.
Given a list of documents with their titles and recommendation notes, return a JSON array (no prose, no markdown fences).

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

def load_history():
    if not os.path.exists(HISTORY_FILE):
        return []
    with open(HISTORY_FILE, encoding="utf-8") as f:
        return json.load(f)

def save_history(approved, notes_map):
    history = load_history()
    for item in approved:
        history.append({
            "title":   item["title"],
            "notes":   notes_map.get(item["data_id"], "")[:150],
            "command": item["final_command"],
        })
    history = history[-100:]  # keep last 100 decisions
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    logging.info("Signing history updated (%d total entries)", len(history))

def build_system_prompt(history):
    prompt = SYSTEM_PROMPT_BASE
    if history:
        examples = "\n".join(
            f'- "{h["title"][:60]}" | บันทึก: "{h["notes"][:80]}" → คำสั่ง: "{h["command"]}"'
            for h in history[-20:]
        )
        prompt += f"\n\nตัวอย่างคำสั่งการที่ผู้ใช้เคยอนุมัติไว้ (ใช้เป็นแนวทาง):\n{examples}"
    return prompt

def build_prompt(docs):
    lines = []
    for d in docs:
        lines.append(f"data_id: {d['data_id']}")
        lines.append(f"title: {d['title']}")
        if d.get("notes"):
            lines.append(f"notes: {d['notes'][:150]}")
        lines.append("")
    return "\n".join(lines)

def main():
    with open("documents_data.json", encoding="utf-8") as f:
        docs = json.load(f)

    notes_map = {d["data_id"]: d.get("notes", "") for d in docs}

    print(f"Analyzing {len(docs)} documents…\n")
    logging.info("Phase 4 — AI analysis of %d documents", len(docs))

    TEST_LIMIT = 10  # Set to None to analyze all documents
    sample = docs[:TEST_LIMIT] if TEST_LIMIT else docs
    print(f"Sending {len(sample)} of {len(docs)} documents to AI…\n")

    history = load_history()
    if history:
        print(f"(ใช้ประวัติการลงนาม {len(history)} รายการเป็นแนวทาง)\n")

    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=8192,
        system=build_system_prompt(history),
        messages=[{"role": "user", "content": build_prompt(sample)}],
    )

    raw = response.content[0].text.strip()
    logging.info("AI response received (%d chars)", len(raw))

    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
        raw = raw.rsplit("```", 1)[0].strip()

    start, end = raw.find("["), raw.rfind("]")
    if start != -1 and end != -1:
        raw = raw[start:end + 1]

    try:
        parsed = json.loads(repair_json(raw))
        for item in parsed:
            item["data_id"] = str(item["data_id"])
        suggested = sorted(parsed, key=lambda x: x["rank"])
    except Exception as e:
        print(f"ERROR: could not parse AI response ({e}).")
        print(f"First 300 chars: {raw[:300]!r}")
        with open("ai_response_raw.txt", "w", encoding="utf-8") as f:
            f.write(raw)
        return

    print("=== ลำดับการลงนามที่แนะนำ ===\n")
    for item in suggested:
        print(f"[{item['rank']}] {item['title']}")
        if item.get("summary"):
            print(f"     สรุป:   {item['summary']}")
        print(f"     เหตุผล: {item['reason']}")
        print()

    print("=" * 50)
    print(f"ยืนยันคำสั่งการ (Enter = \"{DEFAULT_COMMAND}\", พิมพ์ใหม่ = กำหนดเอง, 's' = ข้าม)\n")

    approved = []
    for item in suggested:
        print(f"[{item['rank']}] {item['title'][:80]}")
        if item.get("summary"):
            print(f"     สรุป:   {item['summary']}")
        user_input = input(f"     คำสั่งการ [{DEFAULT_COMMAND}]: ").strip()
        if user_input.lower() == "s":
            print("     → ข้ามเอกสารนี้\n")
            logging.info("Skipped: %s", item['title'])
            continue
        final_command = user_input if user_input else DEFAULT_COMMAND
        item["final_command"] = final_command
        approved.append(item)
        print(f"     → ยืนยัน: \"{final_command}\"\n")
        logging.info("Approved doc %s with command: %s", item['data_id'], final_command)

    if not approved:
        print("ไม่มีเอกสารที่อนุมัติ")
        return

    save_history(approved, notes_map)

    with open("approved_order.json", "w", encoding="utf-8") as f:
        json.dump(approved, f, ensure_ascii=False, indent=2)

    print(f"บันทึก {len(approved)} เอกสารที่อนุมัติแล้ว → approved_order.json")
    print("พร้อมสำหรับ Phase 5 (ลงนาม)")
    logging.info("Saved approved order: %d documents", len(approved))

if __name__ == "__main__":
    main()

