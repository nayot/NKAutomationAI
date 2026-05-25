import asyncio
import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from edashboard.config import GMAIL_TOKEN_FILE
from edashboard.models import CheckResult

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
MAX_ITEMS = 10


AUTH_PORT = 8765


def _make_client_config(client_id: str, client_secret: str, port: int = AUTH_PORT) -> dict:
    return {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uris": [f"http://localhost:{port}"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }


def run_gmail_auth(client_id: str, client_secret: str) -> None:
    """Run the OAuth2 flow for headless servers via copy-paste redirect URL."""
    flow = InstalledAppFlow.from_client_config(
        _make_client_config(client_id, client_secret), SCOPES
    )
    flow.redirect_uri = f"http://localhost:{AUTH_PORT}"
    auth_url, _ = flow.authorization_url(prompt="consent")

    print(f"\nOpen this URL in your browser:\n\n  {auth_url}\n")
    print("After authorizing, your browser will show 'Unable to connect' — that is expected.")
    print("Copy the full URL from the browser address bar and paste it below.\n")

    redirect_response = input("Paste redirect URL: ").strip()
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
    flow.fetch_token(authorization_response=redirect_response)
    del os.environ["OAUTHLIB_INSECURE_TRANSPORT"]

    GMAIL_TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    GMAIL_TOKEN_FILE.write_text(flow.credentials.to_json())


def _get_service(client_id: str, client_secret: str):
    creds = None
    if GMAIL_TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(GMAIL_TOKEN_FILE), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            raise RuntimeError(
                f"Gmail not authenticated. Run:  uv run edashboard auth-gmail"
            )

        GMAIL_TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        GMAIL_TOKEN_FILE.write_text(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def _check_sync(client_id: str, client_secret: str) -> CheckResult:
    try:
        service = _get_service(client_id, client_secret)

        result = (
            service.users()
            .threads()
            .list(
                userId="me",
                q="is:unread in:inbox category:primary",
                maxResults=MAX_ITEMS,
            )
            .execute()
        )

        threads = result.get("threads", [])
        total = result.get("resultSizeEstimate", len(threads))

        items = []
        for thread in threads[:MAX_ITEMS]:
            try:
                msg = (
                    service.users()
                    .messages()
                    .get(
                        userId="me",
                        id=thread["id"],
                        format="metadata",
                        metadataHeaders=["Subject", "From"],
                    )
                    .execute()
                )
            except HttpError as e:
                if e.resp.status == 404:
                    continue
                raise
            headers = {
                h["name"]: h["value"]
                for h in msg.get("payload", {}).get("headers", [])
            }
            subject = headers.get("Subject", "(no subject)")
            sender = headers.get("From", "")
            items.append(f"{subject}  ·  {sender}")

        return CheckResult(name="Gmail", count=total, items=items)
    except Exception as e:
        return CheckResult(name="Gmail", count=0, error=str(e))


async def check_gmail(client_id: str, client_secret: str) -> CheckResult:
    if not client_id or not client_secret:
        return CheckResult(name="Gmail", count=0, error="GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET not set")
    return await asyncio.to_thread(_check_sync, client_id, client_secret)
