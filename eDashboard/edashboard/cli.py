import asyncio
import json
from datetime import datetime
from typing import Annotated

import typer
from rich.console import Console
from rich.progress import SpinnerColumn, TextColumn, TimeElapsedColumn, Progress

from edashboard.actions import action_menu
from edashboard.config import load_config
from edashboard.display import render_dashboard
from edashboard.edoc_checker import check_edoc
from edashboard.esign_checker import check_esign
from edashboard.fiori_checker import check_fiori
from edashboard.gmail_checker import check_gmail

app = typer.Typer(help="Check pending tasks across Gmail, eDoc, eSign, and Fiori.")
console = Console()

_ICONS = {"Gmail": "📧", "eDoc": "📄", "eSign": "✍️ ", "Fiori": "🏢"}


async def _gather_results(cfg):
    """Run all four checkers concurrently with no UI side effects."""
    return list(await asyncio.gather(
        check_gmail(cfg.google_client_id, cfg.google_client_secret),
        check_edoc(cfg.edoc_username, cfg.edoc_password, cfg.edoc_inbox),
        check_esign(cfg.esign_username, cfg.esign_password),
        check_fiori(cfg.fiori_username, cfg.fiori_password),
    ))


async def _run_all():
    cfg = load_config()

    with Progress(
        SpinnerColumn(),
        TextColumn("{task.description}"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        task_ids = {
            name: progress.add_task(f"{_ICONS[name]} {name}", total=1)
            for name in ("Gmail", "eDoc", "eSign", "Fiori")
        }

        async def run(coro, name):
            result = await coro
            icon = _ICONS[name]
            if result.error:
                desc = f"[red]{icon} {name}  ✗[/red]"
            else:
                desc = f"[green]{icon} {name}  ✓  {result.count} pending[/green]"
            progress.update(task_ids[name], description=desc, completed=1)
            return result

        results = await asyncio.gather(
            run(check_gmail(cfg.google_client_id, cfg.google_client_secret), "Gmail"),
            run(check_edoc(cfg.edoc_username, cfg.edoc_password, cfg.edoc_inbox), "eDoc"),
            run(check_esign(cfg.esign_username, cfg.esign_password), "eSign"),
            run(check_fiori(cfg.fiori_username, cfg.fiori_password), "Fiori"),
        )

    return list(results)


def _parse_items(result) -> list[dict]:
    if result.name == "Gmail":
        out = []
        for item in result.items:
            if "  ·  " in item:
                subject, sender = item.split("  ·  ", 1)
                out.append({"subject": subject.strip(), "from": sender.strip()})
            else:
                out.append({"subject": item.strip(), "from": None})
        return out
    if result.name == "Fiori":
        out = []
        for item in result.items:
            if "  (" in item and item.endswith(")"):
                category, rest = item.rsplit("  (", 1)
                try:
                    count = int(rest.rstrip(")"))
                except ValueError:
                    count = None
                out.append({"category": category.strip(), "count": count})
            else:
                out.append({"category": item.strip(), "count": None})
        return out
    return [{"title": item.strip()} for item in result.items]


def _to_json_payload(results: list) -> dict:
    systems = []
    for r in results:
        entry = {
            "name": r.name,
            "pending": r.count if not r.error else 0,
            "error": r.error,
            "items": _parse_items(r) if not r.error else [],
        }
        if not r.error and r.count > len(r.items):
            entry["items_truncated"] = True
            entry["items_shown"] = len(r.items)
        systems.append(entry)
    return {
        "ok": not all(r.error for r in results),
        "total_pending": sum(s["pending"] for s in systems),
        "checked_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "systems": systems,
    }


@app.command()
def main(
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable JSON and exit.")] = False,
):
    """Show a summary of all pending tasks and documents."""
    if json_output:
        cfg = load_config()
        results = asyncio.run(_gather_results(cfg))
        print(json.dumps(_to_json_payload(results)))
        raise typer.Exit(code=1 if all(r.error for r in results) else 0)

    results = asyncio.run(_run_all())
    render_dashboard(results)
    if all(not result.error and result.count == 0 for result in results):
        return
    action_menu(console, results)


if __name__ == "__main__":
    app()
