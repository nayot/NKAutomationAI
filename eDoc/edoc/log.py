import logging
from pathlib import Path

LOG_FILE = "edoc_automation.log"


def setup_logging(verbose: bool = False) -> None:
    Path("screenshots").mkdir(exist_ok=True)
    handlers: list[logging.Handler] = [logging.FileHandler(LOG_FILE, encoding="utf-8")]
    if verbose:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=handlers,
        force=True,
    )
