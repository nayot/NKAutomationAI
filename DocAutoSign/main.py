import os
import sys

import yaml
from dotenv import load_dotenv

from esign.session import init_driver, login
from esign.files import generate_batch_id, list_pdfs, rename_files
from esign.upload import upload_files
from esign.assign import assign_signee
from esign.sign import sign_all
from esign.download import download_signed

CONFIG_FILE = os.path.join(os.path.dirname(__file__), 'config.yaml')
SECRETS_FILE = os.path.join(os.path.dirname(__file__), '.env')


def load_config() -> dict:
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def main() -> None:
    # Load credentials
    if not os.path.exists(SECRETS_FILE):
        print(f"Error: credentials file not found at {SECRETS_FILE}")
        print("Create it with:\n  cp .env.example .env\nThen fill in USERNAME and PASSWORD.")
        sys.exit(1)
    load_dotenv(SECRETS_FILE, override=True)
    username = os.environ.get('USERNAME')
    password = os.environ.get('PASSWORD')
    if not username or not password:
        print("Error: USERNAME and PASSWORD must be set in .env")
        sys.exit(1)

    # Load config
    config = load_config()
    first_name = config['signee']['first_name']
    last_name = config['signee']['last_name']
    input_dir = os.path.expanduser(config['input_dir'])
    download_dir = os.path.expanduser(config['download_dir'])

    if not os.path.isdir(input_dir):
        print(f"Error: input_dir '{input_dir}' is not a valid directory.")
        sys.exit(1)

    # Step 1: Rename files
    batch_id = generate_batch_id()
    print(f"\n[Files] Batch ID: {batch_id}")
    filenames = rename_files(input_dir, batch_id)
    n = len(filenames)
    print(f"[Files] {n} file(s) ready.")

    # Step 2-5: Browser automation
    print("\nStarting browser...")
    driver, wait = init_driver(download_dir)
    try:
         login(driver, wait, username, password)
#         upload_files(driver, wait, input_dir, filenames)
#         assign_signee(driver, wait, first_name, last_name, batch_id, n)
#         sign_all(driver, wait, n)
         batch_id = "20260501_155512"
         download_signed(driver, wait, batch_id, download_dir)
    finally:
        driver.quit()

    print(f"\nAll done! Signed documents saved to: {download_dir}")


if __name__ == '__main__':
    main()
