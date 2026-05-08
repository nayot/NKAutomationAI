# DocAutoSign

Automates PDF upload, e-signing, and download via [e-sign.buu.ac.th](https://e-sign.buu.ac.th) — the Burapha University electronic signature portal.

Given a folder of PDFs, the tool stamps them with a unique batch ID, uploads them to the portal, assigns a signee, signs all documents, then downloads the signed copies — hands-free.

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- Google Chrome + matching [ChromeDriver](https://chromedriver.chromium.org/)

## Setup

```bash
# 1. Clone and enter the repo
git clone <repo-url>
cd NKAutomationAI

# 2. Copy and fill in credentials
cp DocAutoSign/.env.example DocAutoSign/.env
# edit .env: set USERNAME and PASSWORD

# 3. Edit config.yaml (see Configuration below)
```

## Configuration

**`DocAutoSign/config.yaml`**

```yaml
signee:
  first_name: ณยศ          # Signee first name (Thai or English)
  last_name: คุรุกิจโกศล    # Signee last name

input_dir: ~/Downloads/CWIE-Pending   # Folder containing PDFs to sign
download_dir: ~/Downloads/CWIE-Signed # Destination for signed PDFs
```

**`DocAutoSign/.env`** (never commit this file)

```
USERNAME=your_username@eng.buu.ac.th
PASSWORD=your_password
```

## Running

```bash
# From the repo root (where pyproject.toml lives)
uv run python DocAutoSign/main.py
```

Chrome will open, log in, and process all PDFs automatically. The terminal shows progress for each phase.

## Pipeline

| Phase | Module | Description |
|-------|--------|-------------|
| 1 | `esign/files.py` | Generates a `YYYYMMDD_HHMMSS` batch ID; renames all PDFs in `input_dir` with that prefix |
| 2 | `esign/session.py` | Launches Chrome, logs in, handles optional SSO Authorize prompt |
| 3 | `esign/upload.py` | Uploads each renamed PDF via `/addDocument` |
| 4 | `esign/assign.py` | Paginates `/manageDocument` and assigns the configured signee to each batch document |
| 5 | `esign/sign.py` | Signs all pending documents in groups of 10 |
| 6 | `esign/download.py` | Downloads signed PDFs from `/successfullySigned`, strips the batch prefix from filenames |

## Project Structure

```
DocAutoSign/
├── main.py          # Entry point — wires all phases together
├── config.yaml      # Signee name and directory paths
├── .env             # Credentials (not committed)
├── .env.example     # Credentials template
└── esign/
    ├── files.py     # Batch ID generation and file renaming
    ├── session.py   # Chrome driver setup and login
    ├── upload.py    # PDF upload
    ├── assign.py    # Signee assignment
    ├── sign.py      # Document signing
    └── download.py  # Signed PDF download
```

## Design Notes

- **Batch ID** — `YYYYMMDD_HHMMSS` generated once at startup and shared across all files in a run. The portal does not support deleting uploaded documents, so the unique prefix prevents collisions between runs.
- **Skip already-prefixed files** — `files.py` detects files that already carry a batch prefix (pattern `^\d{8}(_\d{6})?_`) and skips them, making interrupted runs safe to resume.
- **JS click** — all button clicks use `driver.execute_script("arguments[0].click()", btn)` to avoid `ElementClickInterceptedException` from overlapping UI elements.
- **Retry wrapper** — each module retries Selenium interactions up to 3 times with linear back-off to handle server instability.
- **Sign pagination** — the dashboard shows 10 pending docs at a time; `sign.py` reloads the page after every 10 signatures.
- **Assign pagination** — `/manageDocument` shows 25 docs per page; `assign.py` walks `ceil(n / 25)` pages.
- **Download load-more** — `download.py` clicks "รายการเพิ่มเติม" until the button disappears before scraping the results table.
