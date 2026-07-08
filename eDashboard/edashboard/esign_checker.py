from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, TimeoutError as PwTimeout

from edashboard.models import CheckResult

ESIGN_URL = "https://e-sign.buu.ac.th"
VIEWPORT = {"width": 1920, "height": 1080}
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
MAX_ITEMS = 10


async def check_esign(username: str, password: str) -> CheckResult:
    if not username or not password:
        return CheckResult(name="eSign", count=0, error="ESIGN_USERNAME / ESIGN_PASSWORD not set")

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(viewport=VIEWPORT, user_agent=USER_AGENT)
            page = await context.new_page()

            await page.goto(ESIGN_URL)
            await page.locator('[name="username"]').fill(username)
            await page.locator('[name="password"]').fill(password)
            await page.locator("button[type='submit']").click()
            await page.wait_for_load_state("networkidle")

            # SSO Authorize button only appears on first login
            auth = page.locator(
                "xpath=//button[contains(text(),'Authorize')] | //a[contains(text(),'Authorize')]"
            )
            try:
                await auth.first.wait_for(state="visible", timeout=3000)
                await auth.first.evaluate("el => el.click()")
                await page.wait_for_load_state("networkidle")
            except PwTimeout:
                pass

            # Count from badges. The page reuses the same id="totalNotBeenSigned"
            # for both the "รอลงนาม" (pending signature) badge and the
            # "เอกสารลับ" (secret documents) badge, so each must be scoped to
            # its own sidebar <li> to avoid reading the wrong one.
            async def _badge_count(li_selector: str) -> int:
                try:
                    badge = page.locator(f"{li_selector} span#totalNotBeenSigned").first
                    await badge.wait_for(state="attached", timeout=5000)
                    raw = await badge.get_attribute("data-count") or "0"
                    return int(raw) if raw.isdigit() else 0
                except PwTimeout:
                    return 0

            pending_count = await _badge_count(
                'li.list-group-item:has(a[href="https://e-sign.buu.ac.th/signDocument"])'
            )
            secret_count = await _badge_count(
                'li.list-group-item:has(a[href^="https://e-sign.buu.ac.th/secretDocument/"])'
                ":has(span#totalNotBeenSigned)"
            )
            count = pending_count + secret_count

            # Extract document titles from page HTML
            items = []
            try:
                soup = BeautifulSoup(await page.content(), "html.parser")
                for row in soup.select("tr"):
                    if not row.find("a", class_=lambda c: c and "btn-outline-success" in c):
                        continue
                    title_link = row.find("a", class_="title-document")
                    if title_link:
                        text = title_link.get_text(strip=True)
                        if text:
                            items.append(text[:100])
                items = items[:MAX_ITEMS]
            except Exception:
                pass

            await browser.close()
            return CheckResult(name="eSign", count=count, items=items)

    except Exception as e:
        return CheckResult(name="eSign", count=0, error=str(e))
