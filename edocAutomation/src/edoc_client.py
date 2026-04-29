"""
Playwright-based automation client for BUU e-Document system.
https://doc.buu.ac.th/docweb/v2/

Navigation paths and selectors are discovered incrementally — each method
saves debug screenshots to ./screenshots/ on key steps and on failure.
"""
import asyncio
import os
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright, Page, Browser, BrowserContext

from .models import Document

BASE_URL = "https://doc.buu.ac.th/docweb/v2/"
SCREENSHOT_DIR = Path(__file__).parent.parent / "screenshots"
SCREENSHOT_DIR.mkdir(exist_ok=True)

# Inboxes to scan (Dean of Engineering)
TARGET_INBOX_NAME = "คณบดีคณะวิศวกรรมศาสตร์"
TARGET_SUB_INBOXES = ["หนังสือเข้าภายนอก", "หนังสือเข้าภายใน"]
EXCLUDE_TAG = "ส่งต่อ"


class EdocClient:
    def __init__(self, headless: bool = True):
        self.headless = headless
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

    async def __aenter__(self):
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self.headless)
        self._context = await self._browser.new_context(
            locale="th-TH",
            timezone_id="Asia/Bangkok",
        )
        self.page = await self._context.new_page()
        return self

    async def __aexit__(self, *_):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def _screenshot(self, name: str):
        path = SCREENSHOT_DIR / f"{name}.png"
        await self.page.screenshot(path=str(path), full_page=True)
        return path

    async def login(self, username: str, password: str) -> bool:
        """Log in to the e-Doc web app. Returns True on success."""
        await self.page.goto(BASE_URL, wait_until="networkidle")
        await self._screenshot("01_login_page")

        await self.page.fill("#txtLogin", username)
        await self.page.fill("#txtPassword", password)
        await self._screenshot("02_login_filled")

        await self.page.click("#btnLogin")
        await self.page.wait_for_load_state("networkidle")
        await self._screenshot("03_after_login")

        # Detect login failure: login form still present
        login_form = await self.page.query_selector("#PnlLoginForm")
        if login_form and await login_form.is_visible():
            error_el = await self.page.query_selector(".error, .alert, [class*=error]")
            error_text = await error_el.inner_text() if error_el else "unknown"
            raise RuntimeError(f"Login failed: {error_text}")

        return True

    # ---------------------------------------------------------------------------
    # Inbox navigation (stubs — selectors TBD from screenshot inspection)
    # ---------------------------------------------------------------------------

    async def get_inbox_items(self, sub_inbox: str) -> list[Document]:
        """
        Navigate to TARGET_INBOX_NAME → sub_inbox and return new documents
        that do NOT have the EXCLUDE_TAG tag.

        Selector paths are TODO — discovered by running test_02_inbox.py and
        inspecting the saved screenshots.
        """
        raise NotImplementedError(
            "Inbox navigation selectors not yet mapped. "
            "Run test_02_inbox.py with headless=False to inspect the UI."
        )

    async def get_document_detail(self, doc: Document) -> Document:
        """
        Open a document and extract the 'ข้อความแนบท้าย/สั่งการ' field text.
        Returns the same Document with attachment_note populated.

        Selector paths are TODO — discovered by running test_03_document.py.
        """
        raise NotImplementedError(
            "Document detail selectors not yet mapped. "
            "Run test_03_document.py with headless=False to inspect the UI."
        )

    async def submit_order(self, doc: Document, order_text: str, dry_run: bool = False) -> bool:
        """
        Open a document and submit the order (สั่งการ) field.
        If dry_run=True, fills the field and takes a screenshot but does NOT submit.

        Selector paths are TODO — discovered by running test_06_submit.py.
        """
        raise NotImplementedError(
            "Order submission selectors not yet mapped. "
            "Run test_06_submit.py with headless=False to inspect the UI."
        )
