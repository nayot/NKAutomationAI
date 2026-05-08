import os
import time
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


def _upload_one(driver, wait, directory: str, filename: str) -> None:
    def _do():
        driver.get(f'{BASE_URL}/addDocument')
        wait.until(EC.visibility_of_element_located((By.NAME, 'DOC_NAME'))).send_keys(filename)
        file_input = driver.find_element(By.CSS_SELECTOR, "input[type='file']")
        file_input.send_keys(os.path.join(directory, filename))
        btn = driver.find_element(By.CLASS_NAME, 'btn-success')
        driver.execute_script("arguments[0].click();", btn)
        time.sleep(1)

    _retry(_do)


def upload_files(driver, wait, directory: str, filenames: list[str]) -> None:
    print(f"\n[Upload] Uploading {len(filenames)} file(s)...")
    for i, filename in enumerate(filenames):
        _upload_one(driver, wait, directory, filename)
        print(f"  Uploaded [{i + 1}/{len(filenames)}] {filename}")
    print("[Upload] Done.")
