import os
import time
from dataclasses import dataclass
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.sync_api import Page
from rich.progress import Progress, TaskID

from esign._retry import retry

BASE_URL = 'https://e-sign.buu.ac.th'


@dataclass
class SignedDoc:
    title: str
    link: str


def _load_all_records(page: Page, time_sleep: float = 2.0) -> None:
    """Click 'รายการเพิ่มเติม' repeatedly until it disappears (all records loaded)."""
    while True:
        btn = page.locator("xpath=//button[contains(text(), 'รายการเพิ่มเติม')]")
        if btn.count() == 0:
            break
        try:
            btn.first.evaluate("el => el.click()")
            time.sleep(time_sleep)
        except Exception:
            break


def _collect_signed(page: Page, batch_id: str, time_sleep: float = 2.0) -> list[SignedDoc]:
    retry(lambda: page.goto(f'{BASE_URL}/successfullySigned'))
    page.wait_for_load_state('networkidle')
    time.sleep(2)
    _load_all_records(page, time_sleep)

    soup = BeautifulSoup(page.content(), 'html.parser')
    tag = soup.find('table', class_='sign-document table')
    if tag is None:
        return []

    docs: list[SignedDoc] = []
    for row in tag.find_all('tr')[1:]:
        a = row.find('a')
        if a is None:
            continue
        title = a.text.strip()
        if title.endswith('.pdf') and title.startswith(batch_id):
            docs.append(SignedDoc(title=title, link=a['href']))
    return docs


def _cleanup_filenames(download_dir: str, batch_id: str) -> None:
    """Strip batch prefix and collapse duplicate .pdf extension from downloaded files."""
    prefix = f"{batch_id}_"
    for fname in os.listdir(download_dir):
        new_name = fname
        if new_name.startswith(prefix):
            new_name = new_name[len(prefix):]
        if new_name.lower().endswith('.pdf.pdf'):
            new_name = new_name[:-4]
        if new_name != fname:
            os.rename(
                os.path.join(download_dir, fname),
                os.path.join(download_dir, new_name),
            )


def download_signed(
    page: Page,
    batch_id: str,
    download_dir: str,
    progress: Progress | None = None,
    task_id: TaskID | None = None,
    overall_task_id: TaskID | None = None,
) -> None:
    Path(download_dir).mkdir(parents=True, exist_ok=True)
    docs = _collect_signed(page, batch_id)

    if progress is not None and task_id is not None:
        progress.update(task_id, total=len(docs))

    if not docs:
        return

    for doc in docs:
        def _do(d=doc):
            page.goto(d.link)
            with page.expect_download(timeout=60_000) as dl_info:
                page.locator('xpath=//*[@id="toolBar"]/div/a').click()
            download = dl_info.value
            download.save_as(os.path.join(download_dir, download.suggested_filename))

        retry(_do)
        if progress is not None and task_id is not None:
            progress.advance(task_id)
        if progress is not None and overall_task_id is not None:
            progress.advance(overall_task_id)

    _cleanup_filenames(download_dir, batch_id)
