import os
import time
from dataclasses import dataclass
from pathlib import Path

from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC

BASE_URL = 'https://e-sign.buu.ac.th'


def _retry(fn, max_attempts: int = 3, delay: float = 2.0):
    for attempt in range(max_attempts):
        try:
            return fn()
        except Exception as e:
            if attempt == max_attempts - 1:
                raise
            print(f"    Retrying ({attempt + 1}/{max_attempts - 1})... ({e})")
            time.sleep(delay * (attempt + 1))


@dataclass
class SignedDoc:
    title: str
    link: str


def _load_all_records(driver, time_sleep: float = 2.0) -> None:
    """Click 'รายการเพิ่มเติม' repeatedly until it disappears (all records loaded)."""
    while True:
        try:
            btn = driver.find_element(
                By.XPATH, "//button[contains(text(), 'รายการเพิ่มเติม')]"
            )
            driver.execute_script("arguments[0].click();", btn)
            time.sleep(time_sleep)
        except Exception:
            break


def _collect_signed(driver, batch_id: str, time_sleep: float = 2.0) -> list[SignedDoc]:
    driver.get(f'{BASE_URL}/successfullySigned')
    time.sleep(2)
    _load_all_records(driver, time_sleep)

    soup = BeautifulSoup(driver.page_source, 'html.parser')
    tag = soup.find('table', class_='sign-document table')
    if tag is None:
        return []

    docs = []
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
            print(f"  Renamed: {fname} → {new_name}")


def _wait_for_download(download_dir: str, count_before: int, timeout: int = 30) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        current = len([f for f in os.listdir(download_dir) if not f.endswith('.crdownload')])
        if current > count_before:
            return
        time.sleep(0.5)


def download_signed(driver, wait, batch_id: str, download_dir: str) -> None:
    Path(download_dir).mkdir(parents=True, exist_ok=True)
    print(f"\n[Download] Loading all signed documents (batch '{batch_id}')...")
    docs = _collect_signed(driver, batch_id)

    if not docs:
        print("[Download] No signed documents found for this batch.")
        return

    print(f"[Download] Downloading {len(docs)} document(s) to {download_dir}...")
    for i, doc in enumerate(docs):
        def _do(d=doc):
            driver.get(d.link)
            count_before = len([f for f in os.listdir(download_dir) if not f.endswith('.crdownload')])
            wait.until(EC.visibility_of_element_located(
                (By.XPATH, '//*[@id="toolBar"]/div/a')
            )).click()
            _wait_for_download(download_dir, count_before)

        _retry(_do)
        print(f"  Downloaded [{i + 1}/{len(docs)}] {doc.title}")

    print("[Download] Cleaning up filenames...")
    _cleanup_filenames(download_dir, batch_id)
    print("[Download] Done.")
