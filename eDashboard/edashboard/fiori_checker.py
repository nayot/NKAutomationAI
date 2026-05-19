import asyncio

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, TimeoutError as PwTimeout

from edashboard.models import CheckResult

FIORI_URL = (
    "https://buusapwdpap00.buu.ac.th:44301"
    "/sap/bc/ui2/flp?sap-client=900&sap-language=EN#Shell-home"
)
VIEWPORT = {"width": 1920, "height": 1080}
MAX_ITEMS = 10


async def check_fiori(username: str, password: str) -> CheckResult:
    if not username or not password:
        return CheckResult(name="Fiori", count=0, error="FIORI_USERNAME / FIORI_PASSWORD not set")

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                viewport=VIEWPORT,
                ignore_https_errors=True,
            )
            page = await context.new_page()

            # Fiori uses form-based login
            await page.goto(FIORI_URL, wait_until="domcontentloaded", timeout=60000)
            await page.fill('[name="sap-user"]', username)
            await page.fill('[name="sap-password"]', password)
            async with page.expect_navigation(wait_until="networkidle", timeout=60000):
                await page.click("#LOGIN_LINK")

            # Wait for SAPUI5 tile counts to render asynchronously
            try:
                await page.wait_for_selector("span.sapMNCLargeFontSize", timeout=30000)
            except PwTimeout:
                pass

            html = await page.content()
            await browser.close()

        soup = BeautifulSoup(html, "html.parser")

        # Each tile has two sapMNCLargeFontSize spans: empty icon + digit count.
        # Filter to digit-only spans to get the real counts.
        tiles: list[tuple[int, str]] = []
        for span in soup.select("span.sapMNCLargeFontSize"):
            val = span.get_text(strip=True)
            if not val.isdigit():
                continue
            n = int(val)
            # Walk up to find this tile's header text
            el = span
            title = "(untitled)"
            for _ in range(15):
                el = el.parent
                if el is None:
                    break
                h = el.select_one(".sapMGTHdrTxt")
                if h:
                    title = h.get_text(strip=True)
                    break
            tiles.append((n, title))

        total = sum(n for n, _ in tiles)
        items = [f"{title}  ({n})" for n, title in tiles[:MAX_ITEMS] if n > 0]

        return CheckResult(name="Fiori", count=total, items=items)

    except Exception as e:
        return CheckResult(name="Fiori", count=0, error=str(e))
