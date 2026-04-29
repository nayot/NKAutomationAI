# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup

```bash
uv sync
uv run playwright install chromium
cp .secrets.example .secrets   # then fill in real values
```

All commands below use `uv run` to execute within the managed environment.

## Commands

```bash
# Run all tests (secrets-dependent tests auto-skip if .secrets is incomplete)
uv run pytest tests/ -v

# Run a single test file
uv run pytest tests/test_01_login.py -v

# Run with visible browser (useful for debugging Playwright selectors)
HEADLESS=false uv run pytest tests/test_02_inbox.py -v

# Full scan + email
uv run python main.py --scan

# Start approval server (run after --scan, then click links in email)
uv run python main.py --serve

# Scan and keep server running
uv run python main.py --scan --serve
```

## Architecture

The app automates the BUU e-Doc web system (`https://doc.buu.ac.th/docweb/v2/`) for the Dean of Engineering. The pipeline is:

```
EdocClient (Playwright) → AiAnalyzer (Claude API) → email_sender (Gmail SMTP)
                                                          ↓
                                              User clicks link in Gmail
                                                          ↓
                                         web_server (FastAPI localhost:8080)
                                                          ↓
                                         EdocClient.submit_order() × N
```

**`src/edoc_client.py`** — All browser automation. Uses Playwright headless Chromium with `locale=th-TH`. The target system is ASP.NET WebForms with `__VIEWSTATE`; Playwright handles this transparently. `login()` is implemented. `get_inbox_items()`, `get_document_detail()`, and `submit_order()` are **stubs** — selectors must be discovered by running tests with `HEADLESS=false` and inspecting screenshots saved to `screenshots/`.

**`src/ai_analyzer.py`** — Synchronous Claude API wrapper (`claude-sonnet-4-6`). Uses prompt caching on the Thai-language system prompt. Returns `Recommendation.action` as either `"ทราบ / ดำเนินการตามเสนอ"` or `"สั่งการด้วยตนเอง"`. Generates HMAC-SHA256 tokens per `doc_id` to authenticate approval URLs.

**`src/web_server.py`** — FastAPI app on `localhost:8080`. Reads pending approvals from `/tmp/edoc_pending.json` (written by `main.py --scan`). Validates HMAC tokens before calling `EdocClient.submit_order()`. Shuts down via `/done` or after all approvals are processed.

**`src/email_sender.py`** — Builds an HTML email with a table of documents. Green rows = auto-approvable with `[อนุมัติ]` links to `localhost:8080`. Yellow rows = require manual attention. Includes a bulk-approve button.

**`src/models.py`** — Two dataclasses: `Document` (fields from inbox list + `attachment_note` for ข้อความแนบท้าย/สั่งการ) and `Recommendation` (wraps `Document` with `action`, `reason`, `token`).

## Test Strategy

Tests are numbered 01–06 and must be run in order — each depends on the previous step working. Tests auto-skip when required secrets are absent rather than fail.

| Test | Dependency | Status |
|------|-----------|--------|
| test_01_login | EDOC_USERNAME, EDOC_PASSWORD | Login implemented |
| test_02_inbox | test_01 passing | `get_inbox_items()` is a stub |
| test_03_document | test_02 passing | `get_document_detail()` is a stub |
| test_04_ai_analyze | ANTHROPIC_API_KEY | Implemented |
| test_05_email | GMAIL_* secrets | HTML builder test runs without secrets |
| test_06_submit | test_03 passing | `submit_order()` is a stub |

## Implementing the Stubs

When implementing `get_inbox_items()`, `get_document_detail()`, or `submit_order()`:

1. Run the relevant test with `HEADLESS=false`
2. Inspect screenshots in `screenshots/` at each step
3. Use browser DevTools (the visible Chromium window) to identify CSS selectors
4. The system uses jQuery — check for `id` attributes prefixed with `ctl00$body$` in form POSTs

## Secrets

All secrets are loaded from `.secrets` (dotenv format, gitignored). See `.secrets.example` for required keys. `APPROVAL_SECRET` is optional — auto-generated per-run if absent (tokens won't survive server restarts without it set explicitly).
