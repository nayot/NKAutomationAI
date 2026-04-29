"""
Test 05 — Email Sender
-----------------------
Sends a test email with mock recommendation data to NOTIFY_EMAIL.
Verify the email arrives and the HTML renders correctly.

Run:
    pytest tests/test_05_email.py -v
    (requires GMAIL_FROM, GMAIL_APP_PASSWORD, NOTIFY_EMAIL in .env)
"""
import os
import pytest
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent.parent / ".env")

from src.models import Document, Recommendation
from src.email_sender import send_summary, build_html


def _mock_recommendations() -> list[Recommendation]:
    doc1 = Document(
        doc_id="EXT001",
        subject="ส่งสำเนาคำสั่งแต่งตั้งคณะกรรมการ (ทดสอบ)",
        from_org="สำนักงานอธิการบดี",
        date="28/04/2568",
        inbox="หนังสือเข้าภายนอก",
        doc_number="อว 0601/1234",
        url="https://doc.buu.ac.th/docweb/v2/",
    )
    doc2 = Document(
        doc_id="INT001",
        subject="ขอให้พิจารณาดำเนินการทางวินัย (ทดสอบ)",
        from_org="กองกิจการนิสิต",
        date="28/04/2568",
        inbox="หนังสือเข้าภายใน",
        doc_number="มบ วศ 0001/0001",
        url="https://doc.buu.ac.th/docweb/v2/",
    )
    return [
        Recommendation(doc=doc1, action="ทราบ / ดำเนินการตามเสนอ", reason="เป็นหนังสือส่งสำเนาเพื่อทราบทั่วไป", token="mock_token_001"),
        Recommendation(doc=doc2, action="สั่งการด้วยตนเอง", reason="เกี่ยวกับการดำเนินการทางวินัยซึ่งต้องการการตัดสินใจของคณบดีโดยตรง", token="mock_token_002"),
    ]


def test_build_html_contains_required_elements():
    """HTML output should contain doc subjects and action labels."""
    recs = _mock_recommendations()
    html = build_html(recs)

    assert "ส่งสำเนาคำสั่งแต่งตั้งคณะกรรมการ" in html
    assert "ขอให้พิจารณาดำเนินการทางวินัย" in html
    assert "ทราบ / ดำเนินการตามเสนอ" in html
    assert "สั่งการด้วยตนเอง" in html
    assert "localhost:8080/approve" in html
    assert "อนุมัติทั้งหมด" in html


def test_send_email_to_notify_address():
    """Actually send a test email (skipped if Gmail secrets are missing)."""
    required = ["GMAIL_FROM", "GMAIL_APP_PASSWORD", "NOTIFY_EMAIL"]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        pytest.skip(f"Missing: {', '.join(missing)}")

    recs = _mock_recommendations()
    send_summary(
        recommendations=recs,
        gmail_from=os.environ["GMAIL_FROM"],
        gmail_app_password=os.environ["GMAIL_APP_PASSWORD"],
        notify_email=os.environ["NOTIFY_EMAIL"],
    )
    print(f"\nTest email sent to {os.environ['NOTIFY_EMAIL']} — check inbox.")
