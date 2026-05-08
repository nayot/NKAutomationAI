# eSign

Automates PDF upload, e-signing, and download via [e-sign.buu.ac.th](https://e-sign.buu.ac.th) — the Burapha University electronic signature portal.

Given a folder of PDFs, the tool stamps them with a unique batch ID, uploads them to the portal, assigns a signee, signs all documents, then downloads the signed copies — hands-free.

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- Chromium (installed automatically by Playwright)

## Setup

```bash
# 1. Clone and enter the repo
git clone <repo-url>
cd NKAutomationAI/eSign

# 2. Install deps (uv) and the Chromium browser
uv sync
uv run playwright install chromium

# 3. Copy and fill in credentials
cp .env.example .env
# edit .env: set USERNAME and PASSWORD

# 4. Edit config.yaml (see Configuration below)
```

## Configuration

**`config.yaml`**

```yaml
signee:
  first_name: ณยศ          # Signee first name (Thai or English)
  last_name: คุรุกิจโกศล    # Signee last name

input_dir: ~/Downloads/CWIE-Pending   # Folder containing PDFs to sign
download_dir: ~/Downloads/CWIE-Signed # Destination for signed PDFs

browser:
  headless: true                       # default; override with --headless / --headful
  viewport: { width: 1920, height: 1080 }
  user_agent: "Mozilla/5.0 ... Chrome/131.0.0.0 ..."

timing:
  default_timeout_ms: 15000
  short_sleep: 1.0
  long_sleep: 2.0
```

**`.env`** (never commit)

```
USERNAME=your_username
PASSWORD=your_password
```

## Running

```bash
# Default (uses config.yaml; runs the full pipeline)
uv run esign

# Equivalent to
uv run esign run

# Override headless default at the CLI
uv run esign run --headful
uv run esign run --headless

# Skip the pre-flight confirmation (for automation)
uv run esign run --yes

# Override paths from the CLI
uv run esign run --input-dir /path/to/pdfs --download-dir /path/to/out

# Print/write the OpenCLI manifest
uv run esign cli-manifest                # to stdout
uv run esign cli-manifest -o opencli.json
```

The CLI shows a Rich pre-flight summary (batch ID, signee, input/output paths, file count, browser mode) and asks for `y/N` confirmation before starting. A unified Rich progress bar tracks the overall pipeline plus each phase (upload → assign → sign → download).

## Pre-flight checks

The CLI refuses to start if any of these fail:

| Check | Exit code |
|---|---|
| `.env` missing or `USERNAME` / `PASSWORD` blank | 2 |
| `input_dir` doesn't exist or contains no PDFs | 2 |
| `download_dir` already contains `.pdf` files | 2 |
| Browser/login failure | 3 |
| Other failure | 1 |

`download_dir` is created if it doesn't exist.

## OpenCLI manifest

`opencli.json` describes the CLI surface in the [OpenCLI](https://github.com/) format so external orchestrators can discover and drive it. Regenerate / inspect with:

```bash
uv run esign cli-manifest
```

## Pipeline

| Phase | Module | Description |
|-------|--------|-------------|
| 1 | `esign/files.py` | Generates a `YYYYMMDD_HHMMSS` batch ID; renames all PDFs in `input_dir` with that prefix |
| 2 | `esign/session.py` | Logs in to e-sign.buu.ac.th, handles optional SSO Authorize prompt |
| 3 | `esign/upload.py` | Uploads each renamed PDF via `/addDocument` |
| 4 | `esign/assign.py` | Paginates `/manageDocument` and assigns the configured signee to each batch document |
| 5 | `esign/sign.py` | Signs all pending documents in groups of 10 |
| 6 | `esign/download.py` | Downloads signed PDFs from `/successfullySigned` via Playwright `expect_download`, strips the batch prefix from filenames |

## Project Structure

```
eSign/
├── cli.py             # Typer + Rich CLI (entry: docautosign)
├── main.py            # Thin entry that delegates to cli:app
├── config.yaml        # Signee, paths, browser, timing
├── opencli.json       # OpenCLI manifest
├── .env               # Credentials (not committed)
├── .env.example       # Credentials template
└── esign/
    ├── _browser.py    # Playwright session context manager
    ├── _retry.py      # Shared linear-backoff retry helper
    ├── files.py       # Batch ID generation and file renaming
    ├── session.py     # Login (replaces driver creation)
    ├── upload.py      # PDF upload
    ├── assign.py      # Signee assignment
    ├── sign.py        # Document signing
    ├── download.py    # Signed PDF download (uses page.expect_download)
    ├── preflight.py   # Validation + Rich summary panel
    └── progress.py    # Rich Progress factory
```

## Design Notes

- **Batch ID** — `YYYYMMDD_HHMMSS` generated once at startup and shared across all files in a run. The portal does not support deleting uploaded documents, so the unique prefix prevents collisions between runs.
- **Skip already-prefixed files** — `files.py` detects files that already carry a batch prefix (pattern `^\d{8}(_\d{6})?_`) and skips them, making interrupted runs safe to resume.
- **Playwright sync API** — pipeline is sequential, so the sync API keeps `cli.py` orchestration simple. A single `Page` is passed through all phases.
- **Downloads** — `context.new_context(accept_downloads=True)` plus `page.expect_download()` replaces the old `.crdownload` polling loop.
- **JS click hold-overs** — most clicks use Playwright's auto-waited `locator.click()`. Two spots still use `locator.evaluate("el => el.click()")`: the SSO Authorize button and the sign modal confirm, where overlays still intercept normal clicks.
- **Retry wrapper** — `esign/_retry.py` wraps interactions with three attempts and linear backoff for the unreliable e-sign server.
- **Sign pagination** — the dashboard shows 10 pending docs at a time. `sign.py` reloads the dashboard twice (page reload × 2) after every 10 docs. The original `counter == 9` reset trigger is preserved exactly.
- **Assign pagination** — `/manageDocument` shows 25 docs per page. `n_pages = (n_files + 24) // 25` determines how many pages to walk.
- **Headless detection** — Playwright contexts always set viewport `1920×1080` and a real Chrome user-agent string (preserves the fix from commit `e6cca68`).
