from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Document:
    doc_id: str
    subject: str
    from_org: str
    date: str
    inbox: str  # "หนังสือเข้าภายนอก" | "หนังสือเข้าภายใน"
    doc_number: str = ""
    attachment_note: str = ""  # ข้อความแนบท้าย/สั่งการ
    url: str = ""
    tags: list[str] = field(default_factory=list)


@dataclass
class Recommendation:
    doc: Document
    action: str  # "ทราบ / ดำเนินการตามเสนอ" | "สั่งการด้วยตนเอง"
    reason: str  # AI explanation in Thai
    token: str = ""  # HMAC token for approval URL

    @property
    def is_auto_approvable(self) -> bool:
        return self.action == "ทราบ / ดำเนินการตามเสนอ"
