# CLAUDE.md — eDoc Project

## Goal
Automate document review and signing on the BUU e-Document system at https://doc.buu.ac.th/docweb
using Playwright (Python, async). The automation should read each document, suggest a signing order
based on content analysis, and require explicit human approval before executing any signature action.

---

## Ground Rules
- Work **one phase at a time**. Stop and ask for approval before moving to the next phase.
- Always **show me the script** before running it.
- **Never click "ลงนาม" (sign)** unless I explicitly type "go ahead" or "approve" for that specific document.
- If a selector looks auto-generated or fragile, flag it and ask me to verify before using it.
- Save a screenshot after every major step into the `/screenshots/` folder.
- All scripts must have `DRY_RUN = True` at the top until I confirm otherwise.
- Log every action to `edoc_automation.log` with timestamps.

---

## Target System
- **URL:** https://doc.buu.ac.th/docweb
- **Platform:** Legacy ASP.NET WebForms (.NET Framework)
- **Language:** Thai UI
- **Auth:** Forms-based login (username + password)

---

## Credentials
- **Username:** `<FILL_IN>`
- **Password:** `<FILL_IN>`
> ⚠️ Never hardcode credentials in scripts. Load from environment variables or a `.env` file.

```python
import os
from dotenv import load_dotenv
load_dotenv()
USERNAME = os.getenv("EDOC_USERNAME")
PASSWORD = os.getenv("EDOC_PASSWORD")
```

---

## Workflow (Human Steps Being Automated)
1. Navigate to https://doc.buu.ac.th/docweb
2. Login with username and password
3. Click the shortcut to the desired inbox
4. For each document: read content, then click **"ลงนาม"** (sign)

---

## Automation Workflow (What This Bot Does)
1. Login and navigate to the inbox
2. Collect all documents in the inbox (title, sender, date, preview)
3. Read the content of each document
4. Use AI (Claude) to analyze all documents and suggest a **signing order with reasoning**
5. Present the suggested order to the user for review
6. **Wait for explicit approval** before signing any document
7. Upon approval, sign documents one by one in the approved order
8. Take a screenshot after each signing action as confirmation

---

## Phases

### Phase 1 — Recon (No actions)
- Navigate to login page
- Take a screenshot
- Print all form field IDs, button texts, and visible element labels
- Do NOT log in yet

### Phase 2 — Login
- Log in using credentials from `.env`
- Take a screenshot of the page after login
- Print the current URL and page title
- Identify the inbox shortcut button/link

### Phase 3 — Navigate to Inbox
- Click the shortcut to the inbox (to be identified in Phase 2)
- Take a screenshot of the inbox
- Print the number of documents visible and their titles/dates

### Phase 4 — Read All Documents
- For each document in the inbox:
  - Click to open it
  - Extract the document title, sender, date, and full body text
  - Save extracted content to `documents_data.json`
  - Navigate back to the inbox
- Do NOT click "ลงนาม" at this stage

### Phase 5 — AI Analysis & Suggested Order
- Pass all extracted document data to Claude API
- Ask Claude to suggest a signing order based on urgency, sender, topic, and date
- Print the suggested order with reasoning for each document
- **Wait for user approval before proceeding**

### Phase 6 — Sign Documents (Approval Required)
- `DRY_RUN = True` by default
- When `DRY_RUN = False` AND user has approved the order:
  - Sign each document one by one in the approved order
  - After each signing, take a screenshot named `signed_[doc_title]_[timestamp].png`
  - Log the result

---

## Known .NET WebForms Quirks (Update as Discovered)
- Element IDs are likely auto-generated (e.g., `ctl00_ContentPlaceHolder1_btnLogin`)
- Form submissions may use ViewState — always `page.goto()` before filling forms
- Buttons may trigger postbacks — use `page.expect_navigation()` after clicks
- Session may expire — monitor for redirect back to login page
- Thai characters in selectors — use `get_by_text()` where possible
- **Post-login content is inside nested iframes** — always switch frames before interacting:
  ```python
  outer = page.frame_locator("#iframeHomeBody")
  inner = outer.frame_locator("#home_list_full")
  ```

---

## Discovered Selectors
| Element              | Selector / Notes                                      |
|----------------------|-------------------------------------------------------|
| Username field       | `#txtLogin`                                           |
| Password field       | `#txtPassword`                                        |
| Login button         | `#btnLogin`                                           |
| Outer iframe         | `#iframeHomeBody`                                     |
| Inner iframe         | `id="home_list_full"`, `name="home_list"` (inside `#iframeHomeBody`); use `frame_locator("#home_list_full")` for clicks, `page.frame(name="home_list")` to get the Frame object |
| ทางลัด tab           | `.home-content-tab-shortcuts` (inside inner iframe)   |
| Inbox link           | `get_by_text("ผศ. ดร. ณยศ ...")` (inside inner iframe)|
| Document list items  | `a.home-list-open-item` in `home_list` frame; use `force=True` to click after first doc opens |
| Notes/recommendation | `.DocNoteContent` inside `iframeContent0`             |
| Close document tab   | `page.evaluate("VN.V2.App.Home.Page.HideContentFrame()")` — more reliable than clicking the close button, which is sometimes hidden |
| Sign button          | `#btnSign` inside `iframeContent0`                    |
| Sign option radio    | `#optSignConfirmOptions0` (main page)                 |
| คำสั่งการ field      | `#txtTargetTypeNote` (main page)                      |
| Confirm sign button  | `#btnSignConfirmOK` (main page)                       |

---

## Project File Structure
```
eDoc/
├── CLAUDE.md               ← This file
├── .env                    ← Credentials (never commit to git)
├── .env.example
├── pyproject.toml          ← uv-managed dependencies (playwright, python-dotenv)
├── phase1_login.py         ← Login + selector recon (Phases 1 & 2 combined)
├── phase2_inbox.py         ← Navigate to inbox via ทางลัด shortcut (Phase 3)
├── phase3_read_docs.py     ← Read all documents, save to JSON (Phase 4)
├── phase4_ai_analysis.py   ← Claude API analysis + suggested order (Phase 5)
├── phase5_sign.py          ← Sign documents with approval gate (Phase 6)
├── documents_data.json     ← Extracted document content
├── edoc_automation.log     ← Action log
└── screenshots/            ← All screenshots saved here
```

---

## AI Analysis Prompt (Phase 5)
The AI also suggests the per-document `คำสั่งการ` (command), grounded in the few-shot
history of past user-approved commands. Model is configurable via `EDOC_AI_MODEL` in `.env`
(default: `claude-haiku-4-5-20251001`). Live system prompt lives in
[edoc/analyzer.py](edoc/analyzer.py) — edit there, not here.

When calling Claude API for document analysis, use this system prompt:

```
You are an assistant helping a Thai university administrator prioritize document signing.
Given a list of documents with their titles, senders, dates, and content,
suggest the optimal signing order based on:
1. Urgency (deadlines, time-sensitive language)
2. Seniority of sender
3. Topic importance (financial, legal, administrative)
4. Date received (older first as tiebreaker)

Respond in Thai. For each document, provide:
- Recommended rank
- One-sentence reason for the ranking
- Suggested คำสั่งการ
```

---

## Safety Checklist Before Running Phase 6
- [ ] `DRY_RUN = False` confirmed by user
- [ ] Suggested signing order reviewed and approved
- [ ] Screenshots folder is writable
- [ ] `.env` file has correct credentials
- [ ] Session is still active (not timed out)

---

## Session Notes (Update After Each Session)
| Date | Phase Completed | Notes |
|------|----------------|-------|
|      |                |       |
