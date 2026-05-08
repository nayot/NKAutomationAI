import time

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

from esign._retry import retry

BASE_URL = 'https://e-sign.buu.ac.th'


def login(page: Page, username: str, password: str) -> None:
    retry(lambda: page.goto(BASE_URL))
    page.locator('[name="username"]').fill(username)
    page.locator('[name="password"]').fill(password)
    page.locator("button[type='submit']").click()
    page.wait_for_load_state('networkidle')
    time.sleep(1)

    # Authorize button only appears on first SSO visit
    auth = page.locator(
        "xpath=//button[contains(text(),'Authorize')] | //a[contains(text(),'Authorize')]"
    )
    try:
        auth.first.wait_for(state='visible', timeout=5000)
        auth.first.evaluate("el => el.click()")
        page.wait_for_load_state('networkidle')
        time.sleep(1)
    except PlaywrightTimeoutError:
        pass

    print('Logged in successfully.')
