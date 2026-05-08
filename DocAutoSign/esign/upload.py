import os
import time

from playwright.sync_api import Page
from rich.progress import Progress, TaskID

from esign._retry import retry

BASE_URL = 'https://e-sign.buu.ac.th'


def _upload_one(page: Page, directory: str, filename: str) -> None:
    def _do():
        page.goto(f'{BASE_URL}/addDocument')
        page.locator('[name="DOC_NAME"]').fill(filename)
        page.locator("input[type='file']").set_input_files(os.path.join(directory, filename))
        page.locator('.btn-success').click()
        page.wait_for_load_state('networkidle')
        time.sleep(1)

    retry(_do)


def upload_files(
    page: Page,
    directory: str,
    filenames: list[str],
    progress: Progress | None = None,
    task_id: TaskID | None = None,
    overall_task_id: TaskID | None = None,
) -> None:
    for filename in filenames:
        _upload_one(page, directory, filename)
        if progress is not None and task_id is not None:
            progress.advance(task_id)
        if progress is not None and overall_task_id is not None:
            progress.advance(overall_task_id)
