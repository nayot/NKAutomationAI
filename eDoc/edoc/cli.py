import argparse
import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path

from playwright.async_api import TimeoutError as PlaywrightTimeoutError, async_playwright
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)

from edoc.analyzer import AnalyzerError, analyze, save_history
from edoc.browser import login, navigate_to_inbox, open_page
from edoc.config import Config, ConfigError, load_config
from edoc.docfile import (
    DEFAULT_COMMAND,
    DocFileError,
    queue_has_ready_gate,
    read_queue,
    write_queue,
)
from edoc.inbox import DOCUMENTS_DATA_FILE, load_cached_documents, scrape_documents
from edoc.log import setup_logging
from edoc.signer import SignResult, sign_one

console = Console()


def _make_progress() -> Progress:
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        MofNCompleteColumn(),
        TextColumn("•"),
        TimeElapsedColumn(),
        TextColumn("•"),
        TimeRemainingColumn(),
        console=console,
    )

DEFAULT_DOCFILE = "documents.md"

EXIT_OK = 0
EXIT_RUNTIME = 1
EXIT_USER = 2


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="edoc",
        description="Manage BUU eDoc inbox: fetch documents into a reviewable queue, then sign approved ones.",
    )
    p.add_argument("--sign", action="store_true",
                   help="Sign documents marked for signing in the queue (default: fetch & analyze)")
    p.add_argument("--dry-run", action="store_true",
                   help="With --sign, fill forms but click Cancel instead of OK")

    headless_group = p.add_mutually_exclusive_group()
    headless_group.add_argument("--headless", dest="headless", action="store_const", const=True,
                                help="Run browser headless (override .env HEADLESS)")
    headless_group.add_argument("--headful", dest="headless", action="store_const", const=False,
                                help="Run browser headful (override .env HEADLESS)")

    p.add_argument("--inbox", help="Override INBOX env var")
    p.add_argument("--file", default=DEFAULT_DOCFILE,
                   help=f"Path to queue markdown (default: {DEFAULT_DOCFILE})")
    p.add_argument("--limit", type=int, help="Cap documents processed (testing)")
    p.add_argument("--from-cache", action="store_true",
                   help="(fetch) Skip scrape, re-run AI on existing documents_data.json")
    p.add_argument("--force", action="store_true",
                   help="(fetch) Overwrite documents.md even if its Queue Status is READY")
    p.add_argument("-v", "--verbose", action="store_true", help="Echo log to stderr")
    return p.parse_args(argv)


async def _cmd_fetch(args: argparse.Namespace, config: Config) -> int:
    docfile_path = Path(args.file)
    if docfile_path.exists() and queue_has_ready_gate(args.file) and not args.force:
        print(
            f"Refusing to overwrite {args.file}: Queue Status is READY. "
            f"Sign or reset the queue, or pass --force.",
            file=sys.stderr,
        )
        return EXIT_USER

    if args.from_cache:
        if not Path(DOCUMENTS_DATA_FILE).exists():
            print(f"--from-cache: {DOCUMENTS_DATA_FILE} does not exist.", file=sys.stderr)
            return EXIT_USER
        docs = load_cached_documents()
        console.print(f"Loaded {len(docs)} cached documents from {DOCUMENTS_DATA_FILE}")
    else:
        async with async_playwright() as p:
            browser, _, page = await open_page(p, config.headless)
            try:
                with console.status("[bold]Step 1/4 — Logging in..."):
                    await login(page, config.username, config.password)
                console.print("[green]✓ Logged in successfully[/green]")
                with console.status("[bold]Step 1/4 — Navigating to inbox..."):
                    try:
                        await navigate_to_inbox(page, config.inbox)
                    except PlaywrightTimeoutError:
                        console.print(
                            "[bold green]กล่องรับเอกสารว่างเปล่า — "
                            "ไม่มีเอกสารรอลงนาม ยินดีด้วย![/bold green]"
                        )
                        return EXIT_OK

                with _make_progress() as progress:
                    task = progress.add_task("[cyan]Step 2/4 — Reading documents & attachments", total=None)

                    def update(current: int, total: int, label: str) -> None:
                        if progress.tasks[task].total is None:
                            progress.update(task, total=total)
                        progress.update(task, completed=current, description=f"[cyan]Step 2/4 — {label}")

                    docs = await scrape_documents(page, limit=args.limit, progress=update)
                    progress.update(task, description=f"[cyan]Step 2/4 — Read {len(docs)} documents")
            finally:
                await browser.close()

    if not docs:
        console.print("Inbox is empty. Nothing to analyze.")
        return EXIT_OK

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TextColumn("•"),
        TimeElapsedColumn(),
        console=console,
    ) as ai_progress:
        ai_progress.add_task(
            f"[cyan]Step 3–4/4 — Attachments + ranking ({len(docs)} docs) with {config.ai_model}",
            total=None,
        )
        try:
            ranked = analyze(docs, model=config.ai_model)
        except AnalyzerError as e:
            console.print(f"[red]AI analysis failed:[/red] {e}")
            return EXIT_RUNTIME

    write_queue(ranked, args.file, config.inbox)
    console.print(f"\n[green]✓[/green] Wrote {len(ranked)} documents → [bold]{args.file}[/bold]")
    console.print("Edit the file:")
    console.print("  1. Set Action to 'skip' for any documents you don't want to sign.")
    console.print("  2. Change Queue Status from PROVISIONAL to READY.")
    console.print("Then run: [bold]edoc --sign[/bold]")
    return EXIT_OK


async def _cmd_sign(args: argparse.Namespace, config: Config) -> int:
    try:
        queue = read_queue(args.file)
    except DocFileError as e:
        print(f"Cannot read {args.file}: {e}", file=sys.stderr)
        return EXIT_USER

    if queue.queue_status != "READY":
        print(
            f"Queue Status is {queue.queue_status!r}, not READY. "
            f"Open {args.file}, change `**Queue Status:** \\`READY\\``, save, and re-run.",
            file=sys.stderr,
        )
        return EXIT_USER

    to_sign = [d for d in queue.docs if d.action == "signing"]
    skipped = [d for d in queue.docs if d.action == "skip"]
    if not to_sign:
        print(f"All {len(queue.docs)} documents marked skip. Nothing to sign.")
        return EXIT_OK

    mode = "DRY-RUN" if args.dry_run else "LIVE"
    console.print(f"[bold]{mode}[/bold] — signing {len(to_sign)} document(s); skipping {len(skipped)}.")
    if args.dry_run:
        console.print("Dry-run: forms will be filled but cancelled before final submit.")

    results: list[SignResult] = []
    async with async_playwright() as p:
        browser, _, page = await open_page(p, config.headless)
        try:
            with console.status("[bold]Step 1/2 — Logging in & navigating to inbox..."):
                await login(page, config.username, config.password)
                await navigate_to_inbox(page, config.inbox)

            with _make_progress() as progress:
                task = progress.add_task("[cyan]Step 2/2 — Signing", total=len(to_sign))
                for i, doc in enumerate(to_sign, 1):
                    progress.update(task, description=f"[cyan]Step 2/2 — {doc.title[:50]}")
                    result = await sign_one(
                        page,
                        {"data_id": doc.data_id, "title": doc.title, "command": doc.command},
                        config.inbox,
                        dry_run=args.dry_run,
                    )
                    results.append(result)
                    progress.advance(task)
                    if result.error:
                        console.print(f"  [red]✗[/red] [{i}/{len(to_sign)}] {doc.title[:60]} — {result.error}")
                    elif args.dry_run:
                        console.print(f"  [yellow]·[/yellow] [{i}/{len(to_sign)}] {doc.title[:60]} (cancelled)")
                    else:
                        console.print(f"  [green]✓[/green] [{i}/{len(to_sign)}] {doc.title[:60]}")
        finally:
            await browser.close()

    successes = [r for r in results if r.signed]
    failures = [r for r in results if r.error]
    console.print(f"\n[bold]Summary:[/bold] {len(successes)} signed, {len(failures)} failed, {len(skipped)} skipped.")

    if successes and not args.dry_run:
        try:
            cached = load_cached_documents()
            notes_map = {d["data_id"]: d.get("notes", "") for d in cached}
        except FileNotFoundError:
            notes_map = {}
        save_history(
            [{"data_id": r.data_id, "title": r.title, "command": r.command} for r in successes],
            notes_map,
        )

    if not args.dry_run:
        src = Path(args.file)
        if src.exists():
            log_dir = Path("log")
            log_dir.mkdir(exist_ok=True)
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            dest = log_dir / f"{src.stem}_{timestamp}{src.suffix}"
            src.rename(dest)
            console.print(f"Archived queue → [bold]{dest}[/bold]")
            logging.info("Archived queue %s → %s", src, dest)

        tmp_dir = Path("tmp")
        if tmp_dir.exists():
            removed = [f for f in tmp_dir.iterdir() if f.is_file()]
            for f in removed:
                f.unlink()
            if removed:
                console.print(f"Cleaned tmp/ ({len(removed)} file(s) removed)")
                logging.info("Cleaned tmp/: %d files removed", len(removed))

    return EXIT_RUNTIME if failures else EXIT_OK


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    setup_logging(verbose=args.verbose)

    try:
        config = load_config(headless_override=args.headless, inbox_override=args.inbox)
    except ConfigError as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        return EXIT_USER

    logging.info("edoc invoked: sign=%s dry_run=%s headless=%s",
                 args.sign, args.dry_run, config.headless)

    coro = _cmd_sign(args, config) if args.sign else _cmd_fetch(args, config)
    try:
        return asyncio.run(coro)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return EXIT_RUNTIME


if __name__ == "__main__":
    raise SystemExit(main())
