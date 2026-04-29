"""
Gmail SMTP email sender for the edocAutomation notification.
Sends an HTML summary email with per-doc approval links pointing to localhost:8080.
"""
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from .models import Recommendation

APPROVAL_BASE_URL = "http://localhost:8080"


def _row_html(rec: Recommendation, idx: int) -> str:
    color = "#d4edda" if rec.is_auto_approvable else "#fff3cd"
    action_label = rec.action
    if rec.is_auto_approvable:
        approve_url = f"{APPROVAL_BASE_URL}/approve/{rec.doc.doc_id}?token={rec.token}"
        action_cell = (
            f'<span style="color:#155724;font-weight:bold;">✅ {action_label}</span><br>'
            f'<a href="{approve_url}" style="font-size:12px;">[อนุมัติเอกสารนี้]</a>'
        )
    else:
        action_cell = f'<span style="color:#856404;font-weight:bold;">⚠️ {action_label}</span>'

    view_url = rec.doc.url or "#"
    return f"""
    <tr style="background:{color};">
      <td style="padding:6px;border:1px solid #ccc;">{idx}</td>
      <td style="padding:6px;border:1px solid #ccc;">{rec.doc.inbox}</td>
      <td style="padding:6px;border:1px solid #ccc;">{rec.doc.doc_number}</td>
      <td style="padding:6px;border:1px solid #ccc;"><a href="{view_url}">{rec.doc.subject}</a></td>
      <td style="padding:6px;border:1px solid #ccc;">{rec.doc.from_org}</td>
      <td style="padding:6px;border:1px solid #ccc;">{rec.doc.date}</td>
      <td style="padding:6px;border:1px solid #ccc;">{action_cell}</td>
      <td style="padding:6px;border:1px solid #ccc;font-size:12px;">{rec.reason}</td>
    </tr>"""


def build_html(recommendations: list[Recommendation]) -> str:
    rows = "".join(_row_html(r, i + 1) for i, r in enumerate(recommendations))
    approvable = [r for r in recommendations if r.is_auto_approvable]

    bulk_section = ""
    if approvable:
        tokens = ",".join(f"{r.doc.doc_id}:{r.token}" for r in approvable)
        bulk_url = f"{APPROVAL_BASE_URL}/approve?tokens={tokens}"
        bulk_section = f"""
        <p style="margin-top:20px;">
          <a href="{bulk_url}"
             style="background:#28a745;color:white;padding:10px 20px;
                    text-decoration:none;border-radius:4px;font-size:16px;">
            ✅ อนุมัติทั้งหมด {len(approvable)} เอกสาร (ทราบ/ดำเนินการตามเสนอ)
          </a>
        </p>
        <p style="font-size:12px;color:#666;">
          ⚠️ ต้องเปิดแอปไว้ก่อนคลิกลิงก์: <code>python main.py --serve</code>
        </p>"""

    return f"""
    <html><body style="font-family:sans-serif;font-size:14px;">
    <h2>📄 หนังสือเข้าใหม่ — คณบดีคณะวิศวกรรมศาสตร์</h2>
    <p>พบหนังสือเข้าใหม่ <strong>{len(recommendations)}</strong> ฉบับ
       ({len(approvable)} ฉบับแนะนำ <em>ทราบ/ดำเนินการตามเสนอ</em>)</p>

    <table style="border-collapse:collapse;width:100%;">
      <thead style="background:#343a40;color:white;">
        <tr>
          <th style="padding:6px;border:1px solid #ccc;">#</th>
          <th style="padding:6px;border:1px solid #ccc;">ประเภท</th>
          <th style="padding:6px;border:1px solid #ccc;">เลขที่</th>
          <th style="padding:6px;border:1px solid #ccc;">เรื่อง</th>
          <th style="padding:6px;border:1px solid #ccc;">จาก</th>
          <th style="padding:6px;border:1px solid #ccc;">วันที่</th>
          <th style="padding:6px;border:1px solid #ccc;">คำแนะนำ</th>
          <th style="padding:6px;border:1px solid #ccc;">เหตุผล</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
    {bulk_section}
    </body></html>"""


def send_summary(
    recommendations: list[Recommendation],
    gmail_from: str,
    gmail_app_password: str,
    notify_email: str,
) -> None:
    """Send the triage summary email via Gmail SMTP."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"📄 หนังสือเข้าใหม่ {len(recommendations)} ฉบับ — รอการสั่งการ"
    msg["From"] = gmail_from
    msg["To"] = notify_email

    html = build_html(recommendations)
    msg.attach(MIMEText(html, "html", "utf-8"))

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.ehlo()
        server.starttls()
        server.login(gmail_from, gmail_app_password)
        server.sendmail(gmail_from, notify_email, msg.as_string())
