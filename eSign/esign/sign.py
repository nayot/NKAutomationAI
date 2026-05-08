import time

from bs4 import BeautifulSoup
from playwright.sync_api import Page
from rich.progress import Progress, TaskID

from esign._retry import retry

BASE_URL = 'https://e-sign.buu.ac.th'


def _get_tags(page: Page) -> list:
    soup = BeautifulSoup(page.content(), 'html.parser')
    return soup.find_all('a', class_='btn btn-outline-success')


def _reload_dashboard(page: Page, time_sleep: float) -> list:
    """Double-load the dashboard to force a fresh pending-docs list."""
    retry(lambda: page.goto(BASE_URL), delay=time_sleep)
    time.sleep(time_sleep)
    retry(lambda: page.goto(BASE_URL), delay=time_sleep)
    time.sleep(time_sleep)
    return _get_tags(page)


def _confirm(page: Page, time_sleep: float) -> None:
    def _do():
        page.locator('#confirmDocument').click()
        time.sleep(time_sleep)
        # Hard-coded XPath — modal confirm. Modal overlay still intercepts normal clicks,
        # so use evaluate-click as the original Selenium code did.
        page.locator(
            'xpath=/html/body/div[3]/div[2]/div/div/div/div/div/div/div/div[4]/button[1]'
        ).evaluate("el => el.click()")
        time.sleep(time_sleep)

    retry(_do, delay=time_sleep)


def sign_all(
    page: Page,
    n_docs: int,
    time_sleep: float = 2.0,
    progress: Progress | None = None,
    task_id: TaskID | None = None,
    overall_task_id: TaskID | None = None,
) -> None:
    tags = _reload_dashboard(page, time_sleep)

    counter = 0
    for _ in range(n_docs):
        href = tags[counter]['href']
        retry(lambda h=href: page.goto(h), delay=time_sleep)
        time.sleep(time_sleep)
        _confirm(page, time_sleep)

        if counter == 9:
            # Page shows 10 docs at a time — reload to get the next batch
            tags = _reload_dashboard(page, time_sleep)
            counter = 0
            continue

        if progress is not None and task_id is not None:
            progress.advance(task_id)
        if progress is not None and overall_task_id is not None:
            progress.advance(overall_task_id)
        counter += 1

    # Handle any docs that remain after the main loop
    tags = _reload_dashboard(page, time_sleep)
    if tags:
        for tag in tags:
            href = tag['href']
            retry(lambda h=href: page.goto(h), delay=time_sleep)
            time.sleep(time_sleep)
            _confirm(page, time_sleep)
            if progress is not None and task_id is not None:
                progress.advance(task_id)
            if progress is not None and overall_task_id is not None:
                progress.advance(overall_task_id)
