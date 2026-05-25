# eDashboard

CLI dashboard that checks pending tasks across **Gmail**, **eDoc**, **eSign**, and **Fiori** simultaneously and lets you act on them from a single terminal.

## What it does

Running `edashboard` will:

1. Check all four systems in parallel with a live spinner.
2. Print a Rich dashboard showing how many items are pending in each system.
3. If anything is pending, drop into an interactive action menu where you can open each system directly.

```
──────────────────── eDashboard   2026-05-25  09:00 ────────────────────

╭─ 📧 Gmail   3 pending ──────────────────────────────────────────────╮
│    Meeting notes from ...                                            │
│    Invoice #1234 ...                                                 │
│    … and 1 more                                                      │
╰──────────────────────────────────────────────────────────────────────╯
╭─ 📄 eDoc   0 pending ───────────────────────────────────────────────╮
│  ✓  Nothing pending                                                  │
╰──────────────────────────────────────────────────────────────────────╯
```

### Action menu navigation

| Key | Action |
|-----|--------|
| `↑` / `k` | Move up |
| `↓` / `j` | Move down |
| `Enter` | Select |
| `q` / `Esc` | Quit |

**Gmail** — opens Gmail in the default browser.  
**eDoc** — opens a new terminal window and runs `uv run edoc --force` inside the `eDoc` project.  
**eSign** — opens the eSign website in the default browser.  
**Fiori** — launches a Chromium window and logs in automatically using your configured credentials.

## Requirements

- Python 3.11+
- [`uv`](https://github.com/astral-sh/uv) package manager

## Installation

```bash
git clone <repo-url>
cd eDashboard
uv sync
uv run playwright install chromium   # first time only
```

## Configuration

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
```

| Variable | System | Notes |
|----------|--------|-------|
| `EDOC_USERNAME` | eDoc | BUU login username |
| `EDOC_PASSWORD` | eDoc | BUU login password |
| `INBOX` | eDoc | Exact inbox link text shown after login (e.g. `ผศ. ดร. ณยศ ...`) |
| `ESIGN_USERNAME` | eSign | Defaults to `EDOC_USERNAME` if blank |
| `ESIGN_PASSWORD` | eSign | Defaults to `EDOC_PASSWORD` if blank |
| `FIORI_USERNAME` | Fiori | SAP username |
| `FIORI_PASSWORD` | Fiori | SAP password |
| `GOOGLE_CLIENT_ID` | Gmail | OAuth2 Desktop app Client ID |
| `GOOGLE_CLIENT_SECRET` | Gmail | OAuth2 Desktop app Client Secret |

### Gmail OAuth setup (first run only)

1. Go to [Google Cloud Console](https://console.cloud.google.com) → APIs & Services → Credentials.
2. Create an **OAuth 2.0 Client ID** of type **Desktop app**.
3. Copy the Client ID and Client Secret into `.env`.
4. On the first `edashboard` run a browser window will open for Google OAuth consent — approve it once.
5. The token is saved to `~/.config/edashboard/gmail_token.json` and reused automatically.

## Usage

```bash
cd eDashboard
uv run edashboard
```

## AI agent / machine-readable output

Pass `--json` to suppress all interactive UI and print a single JSON object to stdout:

```bash
edashboard --json
```

Output schema:

```json
{
  "ok": true,
  "total_pending": 7,
  "checked_at": "2026-05-25T14:32:01",
  "systems": [
    {
      "name": "Gmail",
      "pending": 3,
      "error": null,
      "items": [
        {"subject": "Meeting notes", "from": "alice@example.com"},
        {"subject": "Invoice #1234", "from": "finance@vendor.com"}
      ]
    },
    {
      "name": "eDoc",
      "pending": 2,
      "error": null,
      "items": [
        {"title": "Purchase Order #2024-001"},
        {"title": "Travel Request Form"}
      ]
    },
    {
      "name": "eSign",
      "pending": 0,
      "error": null,
      "items": []
    },
    {
      "name": "Fiori",
      "pending": 2,
      "error": null,
      "items": [
        {"category": "My Tasks", "count": 2}
      ]
    }
  ]
}
```

- `ok` is `false` only when all four systems errored.
- `total_pending` is the sum across non-errored systems.
- Each system's `items` contains up to 10 entries. When more exist, `items_truncated: true` and `items_shown: N` are added to that system entry.
- Exit code is `0` on success or partial success; `1` if every system failed.

Filter with `jq`:

```bash
edashboard --json | jq '.systems[] | select(.pending > 0)'
```

Gmail OAuth must already be authorized (token file present) before using `--json` in an automated context. See the Gmail OAuth setup section above.

## Supported terminal emulators (for eDoc action)

When you select the eDoc action, eDashboard opens a new terminal window. It tries the following emulators in order and uses the first one found in `PATH`:

kitty · alacritty · wezterm · foot · gnome-terminal · konsole · xterm
