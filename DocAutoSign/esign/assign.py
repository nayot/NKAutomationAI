import time
from dataclasses import dataclass

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
class Record:
    title: str
    link: str


def _collect_batch_records(driver, wait, batch_id: str, n_files: int) -> list[Record]:
    """Paginate through exactly n_pages of manageDocument and collect unassigned records."""
    driver.get(f'{BASE_URL}/manageDocument')
    time.sleep(2)
    records = []
    n_pages = (n_files + 24) // 25

    for page in range(n_pages):
        soup = BeautifulSoup(driver.page_source, 'lxml')
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
        # Navigate to next page (will fail silently on the last page)
        try:
            driver.find_element(By.XPATH, '//*[@id="manageDocument_next"]/a').click()
            time.sleep(5)
        except Exception:
            break

    return records


def _assign_one(driver, wait, record: Record, first_name: str, last_name: str) -> None:
    def _do():
        driver.get(record.link)
        wait.until(EC.visibility_of_element_located((By.XPATH, '//*[@id="searchPerson"]'))).click()
        wait.until(EC.visibility_of_element_located((By.ID, 'userFirstName'))).send_keys(first_name)
        wait.until(EC.visibility_of_element_located((By.ID, 'userLastName'))).send_keys(last_name)
        wait.until(EC.visibility_of_element_located((By.XPATH, '//*[@id="search"]'))).click()
        wait.until(EC.visibility_of_element_located(
            (By.XPATH, '//*[@id="listAssign"]/tbody/tr/td[5]/a/button')
        )).click()
        time.sleep(1)

    _retry(_do)


def assign_signee(driver, wait, first_name: str, last_name: str, batch_id: str, n_files: int) -> None:
    print(f"\n[Assign] Collecting batch '{batch_id}' documents ({n_files} file(s), "
          f"{(n_files + 24) // 25} page(s))...")
    records = _collect_batch_records(driver, wait, batch_id, n_files)
    print(f"[Assign] Found {len(records)} document(s). Assigning to {first_name} {last_name}...")

    for i, record in enumerate(records):
        _assign_one(driver, wait, record, first_name, last_name)
        print(f"  Assigned [{i + 1}/{len(records)}] {record.title}")

    print("[Assign] Done.")
