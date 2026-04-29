"""
AI document triage using the Claude API (claude-sonnet-4-6).
Reads 'ข้อความแนบท้าย/สั่งการ' and recommends one of two actions for the Dean.
"""
import hashlib
import hmac
import json
import os
import secrets as _secrets

import anthropic

from .models import Document, Recommendation

MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = """คุณเป็นผู้ช่วยของคณบดีคณะวิศวกรรมศาสตร์ มหาวิทยาลัยบูรพา
หน้าที่ของคุณคือช่วยคัดกรองหนังสือราชการที่เข้ามาในกล่องหนังสือเข้า และแนะนำวิธีการสั่งการ

กฎการแนะนำ:
- "ทราบ / ดำเนินการตามเสนอ" สำหรับหนังสือที่:
  • เป็นหนังสือแจ้งเพื่อทราบทั่วไป
  • เป็นประกาศ คำสั่ง ระเบียบ ที่ไม่ต้องการการตัดสินใจพิเศษ
  • เป็นหนังสือขอความร่วมมือที่ปฏิบัติตามได้ตามปกติ
  • เป็นหนังสือส่งสำเนาเพื่อทราบ
  • งบประมาณหรือเรื่องทางการเงินที่อยู่ในอำนาจและเป็นไปตามขั้นตอนปกติ

- "สั่งการด้วยตนเอง" สำหรับหนังสือที่:
  • ต้องการการตัดสินใจเชิงนโยบาย
  • เกี่ยวกับการลงโทษทางวินัยหรือการดำเนินการทางกฎหมาย
  • ต้องการลายมือชื่อหรือการรับรองส่วนตัว
  • เป็นเรื่องร้องเรียนหรือข้อพิพาท
  • เกี่ยวกับงบประมาณขนาดใหญ่หรือเกินอำนาจปกติ
  • มีความคลุมเครือหรือไม่แน่ใจในการปฏิบัติ

ตอบในรูปแบบ JSON เท่านั้น:
{
  "action": "ทราบ / ดำเนินการตามเสนอ" หรือ "สั่งการด้วยตนเอง",
  "reason": "เหตุผลสั้น ๆ เป็นภาษาไทย (ไม่เกิน 2 ประโยค)"
}"""


class AiAnalyzer:
    def __init__(self, api_key: str | None = None, approval_secret: str | None = None):
        self._client = anthropic.Anthropic(api_key=api_key or os.environ["ANTHROPIC_API_KEY"])
        self._secret = (approval_secret or os.getenv("APPROVAL_SECRET") or _secrets.token_hex(32)).encode()

    def _make_token(self, doc_id: str) -> str:
        return hmac.new(self._secret, doc_id.encode(), hashlib.sha256).hexdigest()

    def verify_token(self, doc_id: str, token: str) -> bool:
        expected = self._make_token(doc_id)
        return hmac.compare_digest(expected, token)

    def analyze(self, doc: Document) -> Recommendation:
        """Analyze a document synchronously and return a Recommendation."""
        user_content = (
            f"เรื่อง: {doc.subject}\n"
            f"จาก: {doc.from_org}\n"
            f"วันที่: {doc.date}\n"
            f"ประเภท: {doc.inbox}\n"
            f"\nข้อความแนบท้าย/สั่งการ:\n{doc.attachment_note or '(ไม่มีข้อความ)'}"
        )

        response = self._client.messages.create(
            model=MODEL,
            max_tokens=256,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_content}],
        )

        raw = response.content[0].text.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]

        data = json.loads(raw)
        action = data.get("action", "สั่งการด้วยตนเอง")
        reason = data.get("reason", "")

        # Normalise — any unexpected value defaults to manual review
        if action not in ("ทราบ / ดำเนินการตามเสนอ", "สั่งการด้วยตนเอง"):
            action = "สั่งการด้วยตนเอง"

        token = self._make_token(doc.doc_id)
        return Recommendation(doc=doc, action=action, reason=reason, token=token)
