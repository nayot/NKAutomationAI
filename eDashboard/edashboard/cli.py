import asyncio

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


@app.command()
def main():
    """Show a summary of all pending tasks and documents."""
    results = asyncio.run(_run_all())
    render_dashboard(results)
    if all(not result.error and result.count == 0 for result in results):
        return
    action_menu(console, results)


if __name__ == "__main__":
    app()
