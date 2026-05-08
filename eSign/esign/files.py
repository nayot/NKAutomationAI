import os
import re
from datetime import datetime
from pathlib import Path

# Matches any previously applied batch prefix: YYYYMMDD_ or YYYYMMDD_HHMMSS_
_BATCH_PREFIX_RE = re.compile(r'^\d{8}(_\d{6})?_')


def generate_batch_id() -> str:
    return datetime.today().strftime('%Y%m%d_%H%M%S')


def list_pdfs(directory: str) -> list[str]:
    files = sorted(f for f in os.listdir(directory) if f.lower().endswith('.pdf'))
    if not files:
        raise FileNotFoundError(f"No PDF files found in '{directory}'")
    return files


def rename_files(directory: str, batch_id: str) -> list[str]:
    """Rename each PDF in-place, prepending batch_id. Returns new filenames."""
    path = Path(directory)
    original_files = list_pdfs(directory)
    renamed = []
    for fname in original_files:
        if _BATCH_PREFIX_RE.match(fname):
            renamed.append(fname)
            continue
        new_name = f"{batch_id}_{fname}"
        (path / fname).rename(path / new_name)
        renamed.append(new_name)
        print(f"  Renamed: {fname} → {new_name}")
    return renamed
