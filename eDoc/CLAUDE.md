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

## AI Provider
- All AI calls go through **OpenRouter** (`https://openrouter.ai/api/v1`) using the
  `openai` SDK with a custom `base_url` — OpenRouter is OpenAI-protocol compatible.
- One key: `OPENROUTER_API_KEY` (required).
- Model is chosen in `.env`, never in code: `EDOC_AI_MODEL` (default
  `anthropic/claude-haiku-4.5`), `EDOC_AI_FALLBACK_MODEL` (default
  `openai/gpt-4o-mini`, empty value disables), `EDOC_AI_MAX_TOKENS` (default 16000).
- The fallback model is retried on 5xx / 429 / connection errors — plus, for
  attachment summaries only, on a 4xx (`_should_fallback(..., on_client_error=True)`),
  because a 400/422 there means the primary model has no file input, not a bad request.
  Account-level 4xx (401/402/403) never fall back.
- `EDOC_AI_PDF_ENGINE` is sent as OpenRouter's `plugins: [{id: "file-parser", ...}]`
  via `extra_body`. Keep it pinned: with no engine set, OpenRouter silently bills
  per-page `mistral-ocr` for any model that lacks native PDF input.
  **Match the engine to the model** — `native` requires a model listing `file` among
  its input modalities, and a text-only model fails either loudly (400/422 "Input
  should be a valid string") or *silently* (200 with empty content). `.env` uses
  `native` because both configured models are file-capable; switch it to
  `cloudflare-ai` (free, but text-layer only — scans come back empty) or
  `mistral-ocr` (paid per page) if `EDOC_AI_MODEL` becomes a text-only model.
  Check a candidate model with OpenRouter's `/api/v1/models`: it needs **`file`** in
  `architecture.input_modalities`, plus `image` to handle scanned pages. Beware
  models that list `image` but not `file` (`z-ai/glm-*`, `deepseek/*`) — vision
  alone does not make a model able to accept a PDF.
- An attachment call that returns an empty 200 is logged as a WARNING with its
  `finish_reason` and `completion_tokens`, since it otherwise looks identical to a
  rejected request.
- `ATTACHMENT_MAX_TOKENS` (in [edoc/analyzer.py](edoc/analyzer.py)) must leave room
  for **reasoning** tokens: OpenRouter bills them as output tokens from the same
  `max_tokens` pool, so a reasoning model on a small cap returns
  `finish_reason="length"` with empty content. 512 did exactly that on
  `z-ai/glm-5.3-flash`; it is now 3000. Don't shrink it back.
- `ATTACHMENT_REASONING_EFFORT` bounds the reasoning half of that budget (sent as
  OpenRouter's `reasoning: {effort}` in `extra_body`); raising the total alone is
  whack-a-mole, since a dense document just reasons past the new cap too. It is `""`
  (unset) while the configured models are non-reasoning — OpenRouter forwards
  unrecognised params to the provider, so sending it to a non-reasoning model risks a
  400 that the 4xx fallback would answer by rerouting every attachment to the pricier
  fallback model. Set it to `"low"` when `EDOC_AI_MODEL` is a reasoning model.
- An empty attachment summary now retries on the fallback model, same as a 4xx.
- Do NOT re-add `response_format={"type": "json_object"}` — it is unsupported on
  some OpenRouter models and forbids the bare JSON array the prompt asks for; the
  fence-strip + `json_repair` pass in `analyze()` handles the raw text instead.
- Legacy `app.py` and `phase4_ai_analysis.py` still call the Anthropic SDK directly
  and were intentionally left on it.

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
4. Use AI (any model, via OpenRouter) to analyze all documents and suggest a **signing order with reasoning**
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
- Pass all extracted document data to the model configured in `.env` (via OpenRouter)
- Ask it to suggest a signing order based on urgency, sender, topic, and date
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
├── phase4_ai_analysis.py   ← legacy analysis, still on the Anthropic SDK (Phase 5)
├── phase5_sign.py          ← Sign documents with approval gate (Phase 6)
├── documents_data.json     ← Extracted document content
├── edoc_automation.log     ← Action log
└── screenshots/            ← All screenshots saved here
```

---

## AI Analysis Prompt (Phase 5)
The AI also suggests the per-document `คำสั่งการ` (command), grounded in the few-shot
history of past user-approved commands. Model is configurable via `EDOC_AI_MODEL` in `.env`
(default: `anthropic/claude-haiku-4.5`). Live system prompt lives in
[edoc/analyzer.py](edoc/analyzer.py) — edit there, not here.

When calling the model for document analysis, use this system prompt:

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
| 2026-09-10 | Model pair settled | `EDOC_AI_MODEL=openai/gpt-4o-mini`, `EDOC_AI_FALLBACK_MODEL=anthropic/claude-haiku-4.5`, `EDOC_AI_PDF_ENGINE=native`. Both models list `file` + `image` on OpenRouter, so each reads text *and* scanned PDFs directly, no OCR fee. Neither reasons by default, so `ATTACHMENT_REASONING_EFFORT` is back to `""`. gpt-4o-mini output is $0.60/MTok vs Haiku's $5.00. |
| 2026-09-10 | Attachment summary fix | Real cause of "attachment could not be read" on `z-ai/glm-5.3-flash`: `ATTACHMENT_MAX_TOKENS = 512` was entirely consumed by reasoning tokens, so every call returned `finish_reason="length"` with empty content. Raised to 3000 → 18/19 docs summarised; the one holdout (30914458, a พ.ร.บ. nomination memo) ate 3000/3000, so reasoning is now bounded with `reasoning: {effort: "low"}` and an empty summary retries on the fallback model. PDF reading itself was never the problem for this model. |
| 2026-09-10 | PDF engine fix | `EDOC_AI_PDF_ENGINE=native` + a text-only `EDOC_AI_MODEL` was the cause of "attachment could not be read": `deepseek/deepseek-v4.1-flash` returned 400/422, `z-ai/glm-5.3-flash` returned an empty 200. Switched `.env` to `cloudflare-ai`, made attachment summaries fall back on 4xx, and added a WARNING for empty 200s. Ranking-path fallback behaviour deliberately unchanged. |
| 2026-09-10 | AI provider migration | Swapped Anthropic+OpenAI for OpenRouter (`openai` SDK + custom `base_url`). Model now chosen in `.env` via `EDOC_AI_MODEL`. Dropped `response_format`; pinned `EDOC_AI_PDF_ENGINE=native` to avoid OpenRouter's paid OCR default. Verified against a local OpenAI-protocol stub, not yet against live OpenRouter. |
