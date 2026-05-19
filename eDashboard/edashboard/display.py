from datetime import datetime

from rich import box
from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from edashboard.models import CheckResult

console = Console()

_ICONS = {
    "Gmail": "📧",
    "eDoc": "📄",
    "eSign": "✍️ ",
    "Fiori": "🏢",
}


def _render_result(result: CheckResult) -> Panel:
    icon = _ICONS.get(result.name, "•")

    if result.error:
        body = Text(f"⚠  {result.error}", style="red")
        badge = "[red]error[/red]"
    elif result.count == 0:
        body = Text("✓  Nothing pending", style="green")
        badge = "[green]0 pending[/green]"
    else:
        table = Table(box=None, show_header=False, padding=(0, 1), expand=True)
        table.add_column("item", no_wrap=False, overflow="fold")
        for item in result.items:
            table.add_row(f"  {item}")
        if result.count > len(result.items):
            table.add_row(
                f"  [dim]… and {result.count - len(result.items)} more[/dim]"
            )
        body = table
        badge = f"[yellow]{result.count} pending[/yellow]"

    title = f"{icon} [bold]{result.name}[/bold]  {badge}"
    return Panel(body, title=title, title_align="left", border_style="dim")


def render_dashboard(results: list[CheckResult]) -> None:
    now = datetime.now().strftime("%Y-%m-%d  %H:%M")
    console.print()
    console.rule(f"[bold]eDashboard[/bold]   {now}")
    console.print()
    for result in results:
        console.print(_render_result(result))
    console.print()
