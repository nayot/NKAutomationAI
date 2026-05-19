# CLAUDE.md — eDashboard

CLI tool that checks pending tasks across Gmail, eDoc, eSign, and Fiori simultaneously.

## Running

```bash
# From inside eDashboard/
uv sync
uv run playwright install chromium   # one-time
uv run edashboard
```

## Configuration — `.env`

Copy `.env.example` → `.env` and fill in credentials:

| Variable | System | Notes |
|---|---|---|
| `EDOC_USERNAME` / `EDOC_PASSWORD` | eDoc | BUU login |
| `INBOX` | eDoc | Exact inbox link text shown after login |
| `ESIGN_USERNAME` / `ESIGN_PASSWORD` | eSign | Falls back to EDOC creds if blank |
| `FIORI_USERNAME` / `FIORI_PASSWORD` | Fiori | SAP credentials |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Gmail | OAuth2 Desktop app from Google Cloud Console |

## Gmail OAuth first-run

On the first run, a browser window opens for Google OAuth consent.
Approve it once; the token is saved to `~/.config/edashboard/gmail_token.json`
and reused automatically on subsequent runs.

## Architecture

All four checks run concurrently via `asyncio.gather()`:
- **Gmail** (`gmail_checker.py`) — `google-api-python-client` in a thread
- **eDoc** (`edoc_checker.py`) — async Playwright, headless Chromium; reuses selectors from `/eDoc`
- **eSign** (`esign_checker.py`) — async Playwright, headless Chromium; reads `#totalNotBeenSigned` badge
- **Fiori** (`fiori_checker.py`) — async httpx OData call to `IWPGW/TASKPROCESSING;mo;v=2/TaskCollection`

## Known selectors (update as discovered)

| System | Element | Selector |
|---|---|---|
| eDoc | Login | `#txtLogin`, `#txtPassword`, `#btnLogin` |
| eDoc | Inbox frame | `#iframeHomeBody > #home_list_full > home_list` |
| eDoc | Doc items | `a.home-list-open-item` |
| eSign | Sign badge | `#totalNotBeenSigned[data-count]` |
| eSign | Sign buttons | `a.btn.btn-outline-success` |
| Fiori | OData endpoint | `/sap/opu/odata/IWPGW/TASKPROCESSING;mo;v=2/TaskCollection` |

## File structure

```
eDashboard/
├── .env                  ← credentials (never commit)
├── .env.example
├── pyproject.toml
├── CLAUDE.md
└── edashboard/
    ├── cli.py            ← typer entry point
    ├── config.py         ← load_config() from .env
    ├── models.py         ← CheckResult dataclass
    ├── display.py        ← Rich terminal rendering
    ├── gmail_checker.py  ← Gmail API
    ├── edoc_checker.py   ← Playwright (eDoc)
    ├── esign_checker.py  ← Playwright (eSign)
    └── fiori_checker.py  ← httpx OData (Fiori)
```
