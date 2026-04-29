"""
edocAutomation — Main entry point.

Usage:
    python main.py --scan           # scan inbox, AI triage, send email
    python main.py --serve          # start localhost:8080 approval server
    python main.py --scan --serve   # scan then keep server running
"""
import argparse
import asyncio
import json
import os
from dataclasses import asdict
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

from src.edoc_client import EdocClient, TARGET_SUB_INBOXES
from src.ai_analyzer import AiAnalyzer
from src.email_sender import send_summary
from src.models import Document, Recommendation
from src.web_server import app, set_shutdown_event, PENDING_FILE


async def scan() -> list[Recommendation]:
    username = os.environ["EDOC_USERNAME"]
    password = os.environ["EDOC_PASSWORD"]
    api_key = os.environ["ANTHROPIC_API_KEY"]

    analyzer = AiAnalyzer(api_key=api_key)
    recommendations: list[Recommendation] = []

    async with EdocClient(headless=True) as client:
        print("Logging in to BUU e-Doc...")
        await client.login(username, password)
        print("Login successful.")

        for sub_inbox in TARGET_SUB_INBOXES:
            print(f"Scanning {sub_inbox}...")
            docs = await client.get_inbox_items(sub_inbox)
            print(f"  Found {len(docs)} new document(s)")

            for doc in docs:
                detailed = await client.get_document_detail(doc)
                print(f"  Analyzing: {detailed.subject[:60]}")
                rec = analyzer.analyze(detailed)
                recommendations.append(rec)
                print(f"    → {rec.action}")

    # Persist pending approvals for the web server
    pending = {
        r.doc.doc_id: {"doc": asdict(r.doc), "action": r.action, "token": r.token}
        for r in recommendations
        if r.is_auto_approvable
    }
    PENDING_FILE.write_text(json.dumps(pending, ensure_ascii=False, indent=2))
    print(f"\nPending approvals saved ({len(pending)} documents).")

    # Send email
    print("Sending summary email...")
    send_summary(
        recommendations=recommendations,
        gmail_from=os.environ["GMAIL_FROM"],
        gmail_app_password=os.environ["GMAIL_APP_PASSWORD"],
        notify_email=os.environ["NOTIFY_EMAIL"],
    )
    print(f"Email sent to {os.environ['NOTIFY_EMAIL']}.")
    return recommendations


def serve():
    shutdown = asyncio.Event()
    set_shutdown_event(shutdown)

    config = uvicorn.Config(app, host="127.0.0.1", port=8080, log_level="info")
    server = uvicorn.Server(config)

    print("Approval server running at http://localhost:8080")
    print("Click the links in your email to approve documents.")
    print("Go to http://localhost:8080/done to shut down.")

    async def run():
        task = asyncio.create_task(server.serve())
        await shutdown.wait()
        server.should_exit = True
        await task

    asyncio.run(run())


async def scan_then_serve():
    await scan()
    serve()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="BUU e-Doc Automation")
    parser.add_argument("--scan", action="store_true", help="Scan inbox and send email")
    parser.add_argument("--serve", action="store_true", help="Start approval web server")
    args = parser.parse_args()

    if args.scan and args.serve:
        asyncio.run(scan_then_serve())
    elif args.scan:
        asyncio.run(scan())
    elif args.serve:
        serve()
    else:
        parser.print_help()
