# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the app

```bash
# From the NK-Automation root (where pyproject.toml lives)
uv run python DocAutoSign/main.py

# Or from inside DocAutoSign/
cd DocAutoSign
uv run python main.py
```

Dependencies are managed by `uv` at the repo root (`../pyproject.toml` + `../uv.lock`). There is no separate `requirements.txt`.

## Configuration

**`config.yaml`** — edit before each run:
```yaml
signee:
  first_name: ณยศ
  last_name: คุรุกิจโกศล
input_dir: ~/Downloads/CWIE-Pending   # PDFs to process
download_dir: ~/Downloads/CWIE-Signed # where signed PDFs land
```

**`.env`** — credentials (permissions `600`, never commit):
```
USERNAME=user
PASSWORD=your_password
```
Copy from `.env.example` to create it.

## Pipeline (in order)

| Step | Module | What it does |
|---|---|---|
| 1 | `esign/files.py` | Generates `YYYYMMDD_HHMMSS` batch ID; renames all PDFs in `input_dir` in-place with that prefix |
| 2 | `esign/session.py` | Launches Chrome, logs in to `https://e-sign.buu.ac.th`, handles optional SSO Authorize button |
| 3 | `esign/upload.py` | Uploads each renamed PDF via `/addDocument` |
| 4 | `esign/assign.py` | Paginates `/manageDocument` (25 per page) to collect unassigned batch docs, then assigns the configured signee to each |
| 5 | `esign/sign.py` | Navigates dashboard, signs docs in batches of 10 (reloads page list every 10), then handles any remainder |
| 6 | `esign/download.py` | Navigates `/successfullySigned`, clicks "รายการเพิ่มเติม" until all records load, downloads batch docs, strips prefix and removes duplicate `.pdf.pdf` extension |

`main.py` is the single entry point that wires these steps together sequentially.

## Key design details

**Batch ID** — `YYYYMMDD_HHMMSS` (e.g. `20260428_145018`). The e-sign system does not allow deleting uploaded documents, so each run must use a unique prefix. All files in one run share the same timestamp (generated once at startup).

**Already-prefixed files are skipped** — `files.py` uses `re.compile(r'^\d{8}(_\d{6})?_')` to detect files that already carry a batch prefix (old or new format) and skips them, preventing double-prefixing from aborted previous runs.

**Retry wrapper** — every module has a local `_retry(fn, max_attempts=3, delay=2.0)` with linear backoff. The e-sign server is unreliable; most Selenium interactions are wrapped in it.

**JS click over `.click()`** — the e-sign UI frequently has overlapping elements. All button clicks use `driver.execute_script("arguments[0].click();", btn)` to bypass `ElementClickInterceptedException`.

**Sign pagination** — the dashboard shows only 10 pending docs at a time. `sign.py` reloads the dashboard twice (`driver.get(BASE_URL)` × 2) after every 10 docs to get a fresh list. The notebook pattern using `counter == 9` as the reset trigger is preserved exactly.

**Assign pagination** — `/manageDocument` shows 25 docs per page. `n_pages = (n_files + 24) // 25` determines how many pages to walk. Only records where `num_signees == '0'` AND `title.startswith(batch_id)` are collected.

**Download load-more** — `/successfullySigned` paginates via a "รายการเพิ่มเติม" button. `download.py` clicks it in a loop until it disappears before scraping the table.

## e-sign system URLs

| URL | Purpose |
|---|---|
| `https://e-sign.buu.ac.th` | Dashboard — shows pending docs as `<a class="btn btn-outline-success">` |
| `/addDocument` | Upload form |
| `/manageDocument` | Manage/assign signees (table id=`manageDocument`) |
| `/manageAssign/{id}` | Per-document assignment page (`#searchPerson` → `#userFirstName`/`#userLastName` → `#search` → assign button) |
| `/successfullySigned` | Signed documents list (table class=`sign-document table`) |
