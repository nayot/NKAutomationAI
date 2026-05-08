import time
from typing import Callable, TypeVar

T = TypeVar('T')


def retry(fn: Callable[[], T], max_attempts: int = 3, delay: float = 2.0) -> T:
    """Run fn() with linear backoff. Re-raises the final exception."""
    for attempt in range(max_attempts):
        try:
            return fn()
        except Exception as e:
            if attempt == max_attempts - 1:
                raise
            print(f"    Retrying ({attempt + 1}/{max_attempts - 1})... ({e})")
            time.sleep(delay * (attempt + 1))
