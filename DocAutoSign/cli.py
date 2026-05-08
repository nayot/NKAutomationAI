import json
import os
import sys
from pathlib import Path
from typing import Optional

import typer
import yaml
from dotenv import load_dotenv
from playwright.sync_api import Error as PlaywrightError
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm

from esign._browser import browser_session
from esign.assign import assign_signee
from esign.download import download_signed
from esign.files import generate_batch_id, rename_files
from esign.preflight import PreflightError, render_summary, validate
from esign.progress import make_progress
from esign.session import login
from esign.sign import sign_all
from esign.upload import upload_files

VERSION = "0.2.0"
ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = ROOT / "config.yaml"
DEFAULT_ENV = ROOT / ".env"
OPENCLI_PATH = ROOT / "opencli.json"

app = typer.Typer(
    no_args_is_help=False,
    add_completion=False,
    help="Automate PDF upload, signing, and download via e-sign.buu.ac.th",
)

console = Console()
err_console = Console(stderr=True)


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"docautosign {VERSION}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def _root(
    ctx: typer.Context,
    version: Optional[bool] = typer.Option(
        None, "--version", callback=_version_callback, is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    if ctx.invoked_subcommand is None:
        # Default subcommand is `run`
        ctx.invoke(run)


def _resolve_headless(cfg: dict, headless: Optional[bool]) -> bool:
    if headless is not None:
        return headless
    return bool((cfg.get('browser') or {}).get('headless', True))


def _print_error(message: str) -> None:
    err_console.print(Panel(message, title="[bold red]Error[/bold red]", border_style="red"))


@app.command()
def run(
    config: Path = typer.Option(
        DEFAULT_CONFIG, "--config", "-c", help="Path to config.yaml.",
    ),
    input_dir: Optional[Path] = typer.Option(
        None, "--input-dir", help="Override input_dir from config.yaml.",
    ),
    download_dir: Optional[Path] = typer.Option(
        None, "--download-dir", help="Override download_dir from config.yaml.",
    ),
    headless: Optional[bool] = typer.Option(
        None, "--headless/--headful", help="Force headless or headful mode.",
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip the pre-flight confirmation prompt.",
    ),
) -> None:
    """Execute the full sign pipeline."""
    # Load config + env
    if not config.exists():
        _print_error(f"Config file not found: {config}")
        raise typer.Exit(code=2)
    with open(config, 'r', encoding='utf-8') as f:
        cfg = yaml.safe_load(f) or {}

    if not DEFAULT_ENV.exists():
        _print_error(
            f"Credentials file not found at {DEFAULT_ENV}\n"
            "Create it with:  cp .env.example .env  then fill in USERNAME and PASSWORD."
        )
        raise typer.Exit(code=2)
    load_dotenv(DEFAULT_ENV, override=True)

    resolved_headless = _resolve_headless(cfg, headless)

    # Preflight
    try:
        result = validate(
            cfg,
            username=os.environ.get('USERNAME'),
            password=os.environ.get('PASSWORD'),
            headless=resolved_headless,
            input_dir_override=str(input_dir) if input_dir else None,
            download_dir_override=str(download_dir) if download_dir else None,
        )
    except PreflightError as e:
        _print_error(str(e))
        raise typer.Exit(code=2)

    batch_id = generate_batch_id()
    render_summary(console, result, batch_id_preview=batch_id)

    if not yes:
        if not Confirm.ask("Proceed?", default=True, console=console):
            console.print("[yellow]Aborted by user.[/yellow]")
            raise typer.Exit(code=0)

    # Phase 1: rename files (in-place)
    filenames = rename_files(result.input_dir, batch_id)
    n = len(filenames)

    # Phase 2-5: browser pipeline
    short_sleep = result.timing['short_sleep']
    long_sleep = result.timing['long_sleep']

    in_login_phase = True
    try:
        with browser_session(
            headless=result.headless,
            viewport=result.viewport,
            user_agent=result.user_agent,
            default_timeout_ms=result.timing['default_timeout_ms'],
            navigation_timeout_ms=result.timing['navigation_timeout_ms'],
        ) as (page, _context):
            login(page, result.username, result.password)
            in_login_phase = False

            # n_docs upload + n_docs assign + n_docs sign + n_docs download = 4n total
            with make_progress(console=console) as progress:
                overall = progress.add_task("Overall", total=n * 4)

                upload_task = progress.add_task("Upload", total=n)
                upload_files(
                    page, result.input_dir, filenames,
                    progress=progress, task_id=upload_task, overall_task_id=overall,
                )

                assign_task = progress.add_task("Assign", total=n)
                assign_signee(
                    page, result.first_name, result.last_name, batch_id, n,
                    progress=progress, task_id=assign_task, overall_task_id=overall,
                )

                sign_task = progress.add_task("Sign", total=n)
                sign_all(
                    page, n, time_sleep=long_sleep,
                    progress=progress, task_id=sign_task, overall_task_id=overall,
                )

                download_task = progress.add_task("Download", total=n)
                download_signed(
                    page, batch_id, result.download_dir,
                    progress=progress, task_id=download_task, overall_task_id=overall,
                )

    except PlaywrightError as e:
        _print_error(f"Browser error: {e}")
        raise typer.Exit(code=3 if in_login_phase else 1)
    except typer.Exit:
        raise
    except Exception as e:
        _print_error(f"{type(e).__name__}: {e}")
        raise typer.Exit(code=1)

    console.print(
        Panel(
            f"All done. Signed documents saved to: [bold]{result.download_dir}[/bold]",
            border_style="green",
        )
    )


@app.command("cli-manifest")
def cli_manifest(
    output: Optional[Path] = typer.Option(
        None, "--output", "-o",
        help="Write the manifest to this path instead of stdout.",
    ),
) -> None:
    """Print or write the OpenCLI manifest."""
    if not OPENCLI_PATH.exists():
        _print_error(f"opencli.json not found at {OPENCLI_PATH}")
        raise typer.Exit(code=1)
    with open(OPENCLI_PATH, 'r', encoding='utf-8') as f:
        manifest = json.load(f)

    text = json.dumps(manifest, indent=2, ensure_ascii=False)
    if output:
        output.write_text(text + "\n", encoding='utf-8')
        console.print(f"Wrote manifest to {output}")
    else:
        # Print raw JSON so it's pipe-friendly
        sys.stdout.write(text + "\n")


if __name__ == "__main__":
    app()
