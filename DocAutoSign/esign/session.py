import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

BASE_URL = 'https://e-sign.buu.ac.th'


def init_driver(download_dir: str) -> tuple[webdriver.Chrome, WebDriverWait]:
    options = Options()
    options.add_experimental_option('prefs', {
        'download.default_directory': download_dir,
        'download.prompt_for_download': False,
        'plugins.always_open_pdf_externally': True,
    })
    driver = webdriver.Chrome(options=options)
    wait = WebDriverWait(driver, 15)
    return driver, wait


def login(driver: webdriver.Chrome, wait: WebDriverWait, username: str, password: str) -> None:
    driver.get(BASE_URL)
    wait.until(EC.visibility_of_element_located((By.NAME, 'username'))).send_keys(username)
    wait.until(EC.visibility_of_element_located((By.NAME, 'password'))).send_keys(password)
    btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button[type='submit']")))
    driver.execute_script("arguments[0].click();", btn)
    # Wait until the login page navigates away (button goes stale)
    wait.until(EC.staleness_of(btn))
    time.sleep(1)
    # Click the Authorize button if present (only appears on first SSO visit)
    try:
        short_wait = WebDriverWait(driver, 5)
        authorize_btn = short_wait.until(EC.element_to_be_clickable(
            (By.XPATH, "//button[contains(text(), 'Authorize')] | //a[contains(text(), 'Authorize')]")
        ))
        driver.execute_script("arguments[0].click();", authorize_btn)
        wait.until(EC.staleness_of(authorize_btn))
        time.sleep(1)
    except TimeoutException:
        pass
    print('Logged in successfully.')
