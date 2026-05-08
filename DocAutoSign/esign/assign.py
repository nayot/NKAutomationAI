import time
from dataclasses import dataclass

from bs4 import BeautifulSoup
from playwright.sync_api import Page
from rich.progress import Progress, TaskID

from esign._retry import retry

BASE_URL = 'https://e-sign.buu.ac.th'


@dataclass
class Record:
    title: str
    link: str


def _collect_batch_records(page: Page, batch_id: str, n_files: int) -> list[Record]:
    """Paginate through manageDocument and collect unassigned records for this batch."""
    retry(lambda: page.goto(f'{BASE_URL}/manageDocument'))
    page.wait_for_load_state('networkidle')
    time.sleep(2)
    records: list[Record] = []
    n_pages = (n_files + 24) // 25

    for _ in range(n_pages):
        soup = BeautifulSoup(page.content(), 'lxml')
        tag = soup.find('table', id='manageDocument')
        if tag is None:
            break
        for row in tag.find_all('tr')[1:]:
            try:
                link = row.find('a', class_='card-table')['href']
                title = row.find('a', class_='title-document').text
                num_signees = row.find('h3', class_='m-b-0 text-success').text
            except (TypeError, KeyError):
                continue
            if num_signees == '0' and title.startswith(batch_id) and title.endswith('.pdf'):
                records.append(Record(title=title, link=link))
        # Advance to next page; break silently when no next link
        next_link = page.locator('xpath=//*[@id="manageDocument_next"]/a')
        try:
            if next_link.count() == 0:
                break
            next_link.first.click()
            page.wait_for_load_state('networkidle')
            time.sleep(5)
        except Exception:
            break

    return records


def _assign_one(page: Page, record: Record, first_name: str, last_name: str) -> None:
    def _do():
        page.goto(record.link)
        page.locator('#searchPerson').click()
        page.locator('#userFirstName').fill(first_name)
        page.locator('#userLastName').fill(last_name)
        page.locator('#search').click()
        page.locator('xpath=//*[@id="listAssign"]/tbody/tr/td[5]/a/button').click()
        time.sleep(1)

    retry(_do)


def assign_signee(
    page: Page,
    first_name: str,
    last_name: str,
    batch_id: str,
    n_files: int,
    progress: Progress | None = None,
    task_id: TaskID | None = None,
    overall_task_id: TaskID | None = None,
) -> None:
    records = _collect_batch_records(page, batch_id, n_files)

    # Re-target the assign task to the actual record count if the caller passed one in
    if progress is not None and task_id is not None:
        progress.update(task_id, total=len(records))

    for record in records:
        _assign_one(page, record, first_name, last_name)
        if progress is not None and task_id is not None:
            progress.advance(task_id)
        if progress is not None and overall_task_id is not None:
            progress.advance(overall_task_id)
