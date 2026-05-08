import time
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

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


def _get_tags(driver) -> list:
    soup = BeautifulSoup(driver.page_source, 'html.parser')
    return soup.find_all('a', class_='btn btn-outline-success')


def _reload_dashboard(driver, time_sleep: float) -> list:
    """Double-load the dashboard to force a fresh pending-docs list."""
    driver.get(BASE_URL)
    time.sleep(time_sleep)
    driver.get(BASE_URL)
    time.sleep(time_sleep)
    return _get_tags(driver)


def _confirm(driver, time_sleep: float) -> None:
    def _do():
        WebDriverWait(driver, 15).until(
            EC.visibility_of_element_located((By.ID, 'confirmDocument'))
        ).click()
        time.sleep(time_sleep)
        WebDriverWait(driver, 15).until(
            EC.visibility_of_element_located(
                (By.XPATH, '/html/body/div[3]/div[2]/div/div/div/div/div/div/div/div[4]/button[1]')
            )
        ).click()
        time.sleep(time_sleep)

    _retry(_do, delay=time_sleep)


def sign_all(driver, wait, n_docs: int, time_sleep: float = 2.0) -> None:
    print(f"\n[Sign] Signing {n_docs} document(s)...")
    tags = _reload_dashboard(driver, time_sleep)

    counter = 0
    for i in range(n_docs):
        driver.get(tags[counter]['href'])
        time.sleep(time_sleep)
        _confirm(driver, time_sleep)

        if counter == 9:
            # Page shows 10 docs at a time — reload to get the next batch
            tags = _reload_dashboard(driver, time_sleep)
            counter = 0
            continue

        print(f'  Signing cert #{i + 1}')
        counter += 1

    # Handle any docs that remain after the main loop
    tags = _reload_dashboard(driver, time_sleep)
    if tags:
        print(f"[Sign] Signing {len(tags)} remaining document(s)...")
        for i, tag in enumerate(tags):
            driver.get(tag['href'])
            time.sleep(time_sleep)
            _confirm(driver, time_sleep)
            print(f'  Signing remaining cert #{i + 1}')

    print("[Sign] Done.")
