from playwright.async_api import async_playwright, TimeoutError as PwTimeout

from edashboard.models import CheckResult

EDOC_URL = "https://doc.buu.ac.th/docweb/v2/"
VIEWPORT = {"width": 1440, "height": 900}
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
MAX_ITEMS = 10


async def check_edoc(username: str, password: str, inbox: str) -> CheckResult:
    if not username or not password:
        return CheckResult(name="eDoc", count=0, error="EDOC_USERNAME / EDOC_PASSWORD not set")
    if not inbox:
        return CheckResult(name="eDoc", count=0, error="INBOX not set")

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(viewport=VIEWPORT, user_agent=USER_AGENT)
            page = await context.new_page()

            await page.goto(EDOC_URL, wait_until="domcontentloaded")
            await page.wait_for_selector("#txtLogin", state="visible", timeout=20000)
            await page.fill("#txtLogin", username)
            await page.fill("#txtPassword", password)
            async with page.expect_navigation(wait_until="networkidle"):
                await page.click("#btnLogin")

            inner = page.frame_locator("#iframeHomeBody").frame_locator("#home_list_full")
            await inner.locator(".home-content-tab-shortcuts").click()
            inbox_link = inner.get_by_role("link", name=inbox, exact=True)
            try:
                await inbox_link.wait_for(state="visible", timeout=5000)
            except PwTimeout:
                await browser.close()
                return CheckResult(name="eDoc", count=0, items=[])

            await inbox_link.click()
            await page.wait_for_load_state("networkidle")

            frame = next((f for f in page.frames if f.name == "home_list"), None)
            if frame is None:
                await browser.close()
                return CheckResult(name="eDoc", count=0, error="Inbox frame not found after navigation")

            try:
                await frame.wait_for_selector("a.home-list-open-item", timeout=10000)
                elements = await frame.query_selector_all("a.home-list-open-item")
                titles = []
                for el in elements[:MAX_ITEMS]:
                    titles.append((await el.inner_text()).strip())
                count = len(elements)
            except PwTimeout:
                count = 0
                titles = []

            await browser.close()
            return CheckResult(name="eDoc", count=count, items=titles)

    except Exception as e:
        return CheckResult(name="eDoc", count=0, error=str(e))
