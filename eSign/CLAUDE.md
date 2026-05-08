# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the app

```bash
# From inside eSign/
cd eSign
uv run esign                    # default = `run` subcommand
uv run esign run --headful      # override headless from config
uv run esign run --yes          # skip confirmation prompt
uv run esign cli-manifest       # emit OpenCLI manifest

# First-time setup
uv sync
uv run playwright install chromium
```

The CLI is built with **Typer + Rich**. Default subcommand is `run`. Pre-flight summary + `y/N` confirmation runs before the pipeline starts (`--yes` / `-y` skips it).

Dependencies are managed by `uv` from this directory's own `pyproject.toml`.

## Configuration

**`config.yaml`** — edit before each run:

```yaml
signee: { first_name: ณยศ, last_name: คุรุกิจโกศล }
input_dir: ~/Downloads/CWIE-Pending
download_dir: ~/Downloads/CWIE-Signed
browser:
  headless: true                          # CLI --headless / --headful overrides
  viewport: { width: 1920, height: 1080 } # preserves headless fix from e6cca68
  user_agent: "Mozilla/5.0 ... Chrome/131.0.0.0 ..."
timing:
  default_timeout_ms: 15000
  short_sleep: 1.0
  long_sleep: 2.0
```

**`.env`** (permissions `600`, never commit):
```
USERNAME=user
PASSWORD=your_password
```

## Pre-flight gates (exit 2)

`esign/preflight.py` refuses to start if:
1. `.env` missing or `USERNAME` / `PASSWORD` blank.
2. `input_dir` doesn't exist or has no `*.pdf`.
3. `download_dir` already contains any `*.pdf` (must be clear of PDFs to keep batches unmixed). The dir is created if missing.

Exit codes: `0` ok, `1` generic, `2` preflight, `3` browser/login.

## Pipeline (in order)

| Step | Module | What it does |
|---|---|---|
| 1 | `esign/files.py` | Generates `YYYYMMDD_HHMMSS` batch ID; renames PDFs in-place |
| 2 | `esign/session.py` | `login(page, username, password)` — fills creds, handles optional SSO Authorize |
| 3 | `esign/upload.py` | `upload_files(page, dir, filenames, ...)` — uploads each PDF via `/addDocument` |
| 4 | `esign/assign.py` | `assign_signee(page, first_name, last_name, batch_id, n_files, ...)` — paginates `/manageDocument`, assigns signee |
| 5 | `esign/sign.py` | `sign_all(page, n_docs, ...)` — signs in batches of 10 (counter==9 reset), then handles remainder |
| 6 | `esign/download.py` | `download_signed(page, batch_id, download_dir, ...)` — uses `page.expect_download()`, strips prefix |

`cli.py` wires all steps; `main.py` is now a 3-line shim that calls `cli:app`.

## Browser layer

- **Playwright sync API** (`from playwright.sync_api import ...`).
- `esign/_browser.py` exposes `browser_session(headless, viewport, user_agent, default_timeout_ms)` as a context manager yielding `(page, context)`. The context is created with `accept_downloads=True`.
- Selectors port 1:1 from the old Selenium code; XPaths use `page.locator('xpath=...')`.
- BS4 still parses table rows for `assign.py` and `download.py` — feed it `page.content()` instead of `driver.page_source`.

## Key design details

**Batch ID** — `YYYYMMDD_HHMMSS`. Single timestamp generated once at startup; the e-sign system can't delete uploads, so the unique prefix avoids collisions.

**Already-prefixed files are skipped** — `files.py` regex `^\d{8}(_\d{6})?_` prevents double-prefixing on resumed runs.

**Retry wrapper** — `esign/_retry.py` (single shared module, replaces the old per-module `_retry`) wraps Selenium-style interactions with 3 attempts × linear backoff.

**JS click fallback** — Playwright auto-waits, so `locator.click()` is the default. The two spots that still need `locator.evaluate("el => el.click()")` are: SSO Authorize button (only on first SSO visit) and the sign modal confirm at `xpath=/html/body/div[3]/div[2]/div/div/div/div/div/div/div/div[4]/button[1]`.

**Sign pagination** — dashboard shows 10 pending docs at a time. `sign.py` reloads the dashboard twice (`page.goto(BASE_URL)` × 2) after counter==9. The original notebook reset pattern is preserved exactly.

**Assign pagination** — `/manageDocument` shows 25/page. `n_pages = (n_files + 24) // 25`. Filter: `num_signees == '0'` AND `title.startswith(batch_id)` AND `title.endswith('.pdf')`.

**Download** — `page.expect_download()` replaces the previous `.crdownload`-polling helper. After downloads, `_cleanup_filenames` strips the `{batch_id}_` prefix and collapses duplicate `.pdf.pdf` extensions.

**Headless mode** — viewport `1920×1080` + Chrome desktop user-agent are required for the e-sign portal not to bounce headless sessions (commit `e6cca68`). Both are threaded through `browser_session()`.

## e-sign system URLs

| URL | Purpose |
|---|---|
| `https://e-sign.buu.ac.th` | Dashboard — pending docs as `<a class="btn btn-outline-success">` |
| `/addDocument` | Upload form (`[name="DOC_NAME"]`, `input[type='file']`, `.btn-success`) |
| `/manageDocument` | Manage/assign signees (table id=`manageDocument`, next-page `xpath=//*[@id="manageDocument_next"]/a`) |
| `/manageAssign/{id}` | Per-doc assign page (`#searchPerson` → `#userFirstName`/`#userLastName` → `#search` → `xpath=//*[@id="listAssign"]/tbody/tr/td[5]/a/button`) |
| `/successfullySigned` | Signed list (table class=`sign-document table`, load-more button `xpath=//button[contains(text(), 'รายการเพิ่มเติม')]`) |

## OpenCLI manifest

`opencli.json` (repo root) describes commands/options/exit codes. `cli-manifest` subcommand prints it to stdout (or writes via `-o path`). Hand-written for now; auto-generation from Typer introspection is a future improvement.
