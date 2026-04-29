"""
Test 04 — AI Analyzer
----------------------
Verifies the Claude-based triage logic with real and mock documents.

Run:
    pytest tests/test_04_ai_analyze.py -v
    (requires ANTHROPIC_API_KEY in .secrets)
"""
import os
import pytest
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent.parent / ".secrets")

from src.models import Document
from src.ai_analyzer import AiAnalyzer


def _make_doc(subject: str, note: str, inbox: str = "หนังสือเข้าภายนอก") -> Document:
    return Document(
        doc_id="TEST001",
        subject=subject,
        from_org="สำนักงานอธิการบดี",
        date="28/04/2568",
        inbox=inbox,
        attachment_note=note,
    )


@pytest.fixture
def analyzer():
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        pytest.skip("ANTHROPIC_API_KEY not set in .secrets")
    return AiAnalyzer(api_key=api_key)


def test_routine_circular_gets_trab(analyzer):
    """An informational circular should be recommended as ทราบ/ดำเนินการตามเสนอ."""
    doc = _make_doc(
        subject="ขอส่งสำเนาคำสั่งแต่งตั้งคณะกรรมการ",
        note="เรียน คณบดีทุกคณะ\nขอส่งสำเนาคำสั่งแต่งตั้งคณะกรรมการดังแนบเพื่อทราบ",
    )
    rec = analyzer.analyze(doc)
    assert rec.action == "ทราบ / ดำเนินการตามเสนอ", f"Expected ทราบ but got: {rec.action}\nReason: {rec.reason}"
    assert rec.reason, "reason should not be empty"
    assert rec.token, "token should be set"
    print(f"\nAction: {rec.action}\nReason: {rec.reason}")


def test_disciplinary_matter_gets_manual(analyzer):
    """A disciplinary matter should require manual attention."""
    doc = _make_doc(
        subject="ขอให้พิจารณาดำเนินการทางวินัยนักศึกษา",
        note="เรียน คณบดี\nขอให้คณบดีพิจารณาดำเนินการทางวินัยนักศึกษา รหัส 65XXXXXXX ซึ่งกระทำผิดระเบียบ...",
    )
    rec = analyzer.analyze(doc)
    assert rec.action == "สั่งการด้วยตนเอง", f"Expected สั่งการด้วยตนเอง but got: {rec.action}\nReason: {rec.reason}"
    print(f"\nAction: {rec.action}\nReason: {rec.reason}")


def test_token_verification(analyzer):
    """Approval tokens should be verifiable and non-forgeable."""
    doc = _make_doc("test", "test")
    rec = analyzer.analyze(doc)
    assert analyzer.verify_token(doc.doc_id, rec.token)
    assert not analyzer.verify_token(doc.doc_id, "bad_token")
    assert not analyzer.verify_token("WRONG_ID", rec.token)
