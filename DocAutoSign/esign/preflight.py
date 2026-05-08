import os
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table


class PreflightError(Exception):
    """Raised when a preflight check fails. CLI maps this to exit code 2."""


@dataclass
class PreflightResult:
    username: str
    password: str
    first_name: str
    last_name: str
    input_dir: str
    download_dir: str
    pdf_filenames: list[str]
    headless: bool
    viewport: dict
    user_agent: str
    timing: dict


def _list_pdfs(directory: str) -> list[str]:
    return sorted(f for f in os.listdir(directory) if f.lower().endswith('.pdf'))


def validate(
    cfg: dict,
    username: str | None,
    password: str | None,
    headless: bool,
    input_dir_override: str | None = None,
    download_dir_override: str | None = None,
) -> PreflightResult:
    """Validate config + env. Returns a populated PreflightResult or raises PreflightError."""
    if not username or not password:
        raise PreflightError(
            "USERNAME and PASSWORD must be set in .env "
            "(copy .env.example to .env and fill them in)."
        )

    try:
        first_name = cfg['signee']['first_name']
        last_name = cfg['signee']['last_name']
    except (KeyError, TypeError):
        raise PreflightError("config.yaml must define signee.first_name and signee.last_name")

    input_dir = os.path.expanduser(
        input_dir_override if input_dir_override else cfg.get('input_dir', '')
    )
    download_dir = os.path.expanduser(
        download_dir_override if download_dir_override else cfg.get('download_dir', '')
    )
    if not input_dir or not download_dir:
        raise PreflightError("config.yaml must define input_dir and download_dir")

    if not os.path.isdir(input_dir):
        raise PreflightError(f"input_dir '{input_dir}' does not exist or is not a directory.")

    pdfs = _list_pdfs(input_dir)
    if not pdfs:
        raise PreflightError(f"input_dir '{input_dir}' contains no PDF files.")

    Path(download_dir).mkdir(parents=True, exist_ok=True)
    existing = _list_pdfs(download_dir)
    if existing:
        raise PreflightError(
            f"download_dir '{download_dir}' already contains {len(existing)} PDF "
            f"file(s). Move or delete them before running a new batch."
        )

    browser_cfg = cfg.get('browser', {}) or {}
    viewport = browser_cfg.get('viewport', {'width': 1920, 'height': 1080})
    user_agent = browser_cfg.get(
        'user_agent',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    )
    timing = cfg.get('timing', {}) or {}

    return PreflightResult(
        username=username,
        password=password,
        first_name=first_name,
        last_name=last_name,
        input_dir=input_dir,
        download_dir=download_dir,
        pdf_filenames=pdfs,
        headless=headless,
        viewport=viewport,
        user_agent=user_agent,
        timing={
            'default_timeout_ms': int(timing.get('default_timeout_ms', 30000)),
            'navigation_timeout_ms': int(
                timing.get('navigation_timeout_ms', timing.get('default_timeout_ms', 30000) * 2)
            ),
            'short_sleep': float(timing.get('short_sleep', 1.0)),
            'long_sleep': float(timing.get('long_sleep', 2.0)),
        },
    )


def render_summary(console: Console, result: PreflightResult, batch_id_preview: str) -> None:
    """Print a Rich panel summarising what the run is about to do."""
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold cyan", justify="right")
    table.add_column()

    table.add_row("Batch ID", batch_id_preview)
    table.add_row("Signee", f"{result.first_name} {result.last_name}")
    table.add_row("Input dir", result.input_dir)
    table.add_row("Download dir", result.download_dir)
    table.add_row("PDFs to process", str(len(result.pdf_filenames)))
    table.add_row("Browser mode", "headless" if result.headless else "headful")
    table.add_row(
        "Viewport",
        f"{result.viewport.get('width')}x{result.viewport.get('height')}",
    )

    console.print(
        Panel(
            table,
            title="[bold]DocAutoSign — pre-flight summary[/bold]",
            subtitle="upload → assign → sign → download",
            border_style="cyan",
        )
    )
