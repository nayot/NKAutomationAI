import asyncio
import shutil
import subprocess
import threading
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import readchar
from rich.console import Console, Group
from rich.live import Live
from rich.text import Text

from edashboard.config import load_config
from edashboard.models import CheckResult

EDOC_PATH = Path(__file__).parent.parent.parent / "eDoc"
# Unset VIRTUAL_ENV so uv uses eDoc's .venv (not the eDashboard one we're running in),
# and pass --force so edoc doesn't refuse on a READY queue.
EDOC_COMMAND = "unset VIRTUAL_ENV; uv run edoc --force"

GMAIL_URL = "https://mail.google.com"
ESIGN_URL = "https://e-sign.buu.ac.th"
FIORI_URL = (
    "https://buusapwdpap00.buu.ac.th:44301"
    "/sap/bc/ui2/flp?sap-client=900&sap-language=EN#Shell-home"
)

# Terminal emulators tried in order; first one found in PATH wins.
_TERMINALS = [
    ("kitty",          lambda cwd, cmd: ["kitty", "--directory", cwd, "zsh", "-c", f"{cmd}; exec zsh"]),
    ("alacritty",      lambda cwd, cmd: ["alacritty", "--working-directory", cwd, "-e", "zsh", "-c", f"{cmd}; exec zsh"]),
    ("wezterm",        lambda cwd, cmd: ["wezterm", "start", "--cwd", cwd, "--", "zsh", "-c", f"{cmd}; exec zsh"]),
    ("foot",           lambda cwd, cmd: ["foot", "-D", cwd, "zsh", "-c", f"{cmd}; exec zsh"]),
    ("gnome-terminal", lambda cwd, cmd: ["gnome-terminal", f"--working-directory={cwd}", "--", "zsh", "-c", f"{cmd}; exec zsh"]),
    ("konsole",        lambda cwd, cmd: ["konsole", "--workdir", cwd, "-e", "zsh", "-c", cmd]),
    ("xterm",          lambda cwd, cmd: ["xterm", "-e", f"cd '{cwd}' && {cmd}; exec zsh"]),
]


def _open_new_terminal(command: str, cwd: Path) -> str | None:
    for name, build in _TERMINALS:
        if shutil.which(name):
            subprocess.Popen(build(str(cwd), command), start_new_session=True)
            return name
    return None


@dataclass
class MenuItem:
    key: str          # short id, returned on selection
    icon: str
    label: str
    hint: str = ""    # dim suffix


def _render(items: list[MenuItem], cursor: int) -> Group:
    lines: list[Text] = [Text("Actions", style="bold"), Text("")]
    for i, item in enumerate(items):
        selected = i == cursor
        marker = "❯" if selected else " "
        line = Text()
        line.append(f" {marker} ", style="cyan bold" if selected else "")
        line.append(f"{item.icon}  {item.label}", style="reverse" if selected else "")
        if item.hint:
            line.append(f"  {item.hint}", style="dim")
        lines.append(line)
    lines.append(Text(""))
    lines.append(Text("↑/↓ move · Enter select · q quit", style="dim"))
    return Group(*lines)


def _select(console: Console, items: list[MenuItem]) -> str | None:
    """Render `items` and let the user pick one with arrow keys.

    Returns the selected item's `key`, or None if the user quit.
    """
    cursor = 0
    with Live(_render(items, cursor), console=console, auto_refresh=False, screen=False) as live:
        while True:
            key = readchar.readkey()
            if key in (readchar.key.UP, "k"):
                cursor = (cursor - 1) % len(items)
            elif key in (readchar.key.DOWN, "j"):
                cursor = (cursor + 1) % len(items)
            elif key in (readchar.key.HOME, "g"):
                cursor = 0
            elif key in (readchar.key.END, "G"):
                cursor = len(items) - 1
            elif key in (readchar.key.ENTER, "\r", "\n"):
                return items[cursor].key
            elif key in ("q", readchar.key.ESC, readchar.key.CTRL_C):
                return None
            else:
                continue
            live.update(_render(items, cursor), refresh=True)


_HANDLERS: dict[str, Callable[[Console], None]] = {}


def _handler(key: str):
    def deco(fn: Callable[[Console], None]) -> Callable[[Console], None]:
        _HANDLERS[key] = fn
        return fn
    return deco


@_handler("gmail")
def _open_gmail(console: Console) -> None:
    webbrowser.open(GMAIL_URL)
    console.print(f"[dim]→ opened {GMAIL_URL}[/dim]")


@_handler("esign")
def _open_esign(console: Console) -> None:
    webbrowser.open(ESIGN_URL)
    console.print(f"[dim]→ opened {ESIGN_URL}[/dim]")


async def _fiori_login_and_wait(username: str, password: str) -> None:
    from playwright.async_api import async_playwright, TimeoutError as PwTimeout
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            no_viewport=True,
            ignore_https_errors=True,
        )
        page = await context.new_page()
        await page.goto(FIORI_URL, wait_until="domcontentloaded", timeout=60_000)
        await page.fill('[name="sap-user"]', username)
        await page.fill('[name="sap-password"]', password)
        await page.click("#LOGIN_LINK")
        try:
            await page.wait_for_load_state("networkidle", timeout=60_000)
        except PwTimeout:
            pass
        # Keep the browser alive until the user closes it
        closed = asyncio.Event()
        browser.on("disconnected", lambda _: closed.set())
        await closed.wait()


@_handler("fiori")
def _open_fiori(console: Console) -> None:
    cfg = load_config()
    if not cfg.fiori_username or not cfg.fiori_password:
        webbrowser.open(FIORI_URL)
        console.print("[dim]→ opened Fiori in browser (no credentials configured)[/dim]")
        return

    def _run() -> None:
        asyncio.run(_fiori_login_and_wait(cfg.fiori_username, cfg.fiori_password))

    threading.Thread(target=_run, daemon=False).start()
    console.print("[dim]→ launching Fiori and logging in… (close the browser window when done)[/dim]")


@_handler("edoc")
def _open_edoc(console: Console) -> None:
    if not EDOC_PATH.exists():
        console.print(f"[red]eDoc directory not found: {EDOC_PATH}[/red]")
        return
    term = _open_new_terminal(EDOC_COMMAND, EDOC_PATH)
    if term:
        console.print(f"[dim]→ launched {term}: cd {EDOC_PATH} && {EDOC_COMMAND}[/dim]")
    else:
        console.print("[red]No supported terminal emulator found in PATH[/red]")


_CHECK_NAME = {"gmail": "Gmail", "edoc": "eDoc", "esign": "eSign", "fiori": "Fiori"}


def _count_suffix(results: dict[str, CheckResult], key: str) -> str:
    r = results.get(_CHECK_NAME.get(key, ""))
    if r is None:
        return ""
    if r.error:
        return "(✗)"
    return f"({r.count})"


def _build_items(results: list[CheckResult]) -> list[MenuItem]:
    by_name = {r.name: r for r in results}
    specs = [
        ("gmail", "📧", "Open Gmail in browser",        ""),
        ("edoc",  "📄", "Open eDoc in a new terminal", "(uv run edoc)"),
        ("esign", "✍️ ", "Open eSign in browser",       ""),
        ("fiori", "🏢", "Open Fiori (auto-login)",        ""),
    ]
    items: list[MenuItem] = []
    for key, icon, label, hint in specs:
        suffix = _count_suffix(by_name, key)
        labelled = f"{label} {suffix}".rstrip() if suffix else label
        items.append(MenuItem(key, icon, labelled, hint=hint))
    items.append(MenuItem("quit", "⏻ ", "Quit"))
    return items


def action_menu(console: Console, results: list[CheckResult] | None = None) -> None:
    items = _build_items(results or [])
    while True:
        choice = _select(console, items)
        if choice is None or choice == "quit":
            break
        _HANDLERS[choice](console)
        console.print()
