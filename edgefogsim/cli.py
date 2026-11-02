"""Command-line menu: one of the two user interfaces (the other is the Streamlit app in ``web``).

The menu holds no simulation logic. Each option reads input, calls the engine
modules (``config``, ``workload``, ...) and prints the result with ``rich``
tables. Input goes through an ``ask`` function, so tests can script a whole
session (see ``tests/test_cli.py``).
"""

from pathlib import Path
from typing import Callable

from rich.console import Console
from rich.table import Table

from edgefogsim.config import ConfigError, Settings, origin_of, parse_value, save_settings, set_value
from edgefogsim.models import Task, Tenant
from edgefogsim.workload import generate_tasks, load_tasks, make_task

SENSITIVITY_STYLE = {"high": "bold red", "medium": "yellow", "low": "green"}
"""Colour for each sensitivity level in tables."""

TIER_STYLE = {"edge": "cyan", "fog": "magenta", "cloud": "blue"}
"""Colour for each node tier in tables."""


class App:
    """The interactive menu and the state of one session.

    Attributes:
        settings: Resolved settings; menu edits change them in place.
        tasks: The current workload.
        console: ``rich`` console that all output goes to.
        ask: Function that shows a prompt and returns the user's answer.
        user: Who is logged in, or None before login.
    """

    def __init__(self, settings: Settings, tasks: list[Task] | None = None,
                 console: Console | None = None, ask: Callable[[str], str] | None = None):
        """Set up a session.

        Args:
            settings: Resolved settings from :func:`edgefogsim.config.load_settings`.
            tasks: Optional starting workload, e.g. from ``--tasks FILE``.
            console: Where to print; defaults to the terminal.
            ask: Prompt function; defaults to ``console.input``. Tests pass a
                function that returns scripted answers.
        """
        self.settings = settings
        self.tasks: list[Task] = list(tasks or [])
        self.console = console or Console()
        self.ask = ask or self.console.input
        self.user: Tenant | None = None

    def run(self) -> None:
        """Log in, then show the main menu until the user chooses Exit."""
        self.console.print("[bold]EdgeFogSim[/bold]: Edge / Fog / Cloud placement simulator")
        self.login()
        actions = [
            ("View nodes", self.show_nodes),
            ("Generate random tasks", self.generate),
            ("Load tasks from a file", self.load),
            ("Add a task by hand", self.add_task),
            ("View tasks", self.show_tasks),
            ("View settings", self.show_settings),
            ("Change a setting", self.change_setting),
            ("Save settings to a file", self.save),
            ("Switch user", self.login),
        ]
        while True:
            self.console.print()
            self.console.print(f"[dim]Logged in as[/dim] [bold]{self.user.tenant_id}[/bold] [dim]({self.user.role})[/dim]"
                               f"  [dim]· {len(self.tasks)} tasks loaded[/dim]")
            for number, (label, _) in enumerate(actions, start=1):
                self.console.print(f"  {number}. {label}")
            self.console.print("  0. Exit")
            choice = self.ask("Choose: ").strip()
            if choice in ("0", "q", "exit"):
                self.console.print("Bye.")
                return
            if choice.isdigit() and 1 <= int(choice) <= len(actions):
                actions[int(choice) - 1][1]()
            else:
                self.console.print(f"[red]'{choice}' is not an option.[/red]")

    def login(self) -> None:
        """Ask who the user is (by number or tenant id) until a valid tenant is chosen."""
        tenants = self.settings.tenants
        self.console.print("\nWho are you?")
        for number, tenant in enumerate(tenants, start=1):
            self.console.print(f"  {number}. {tenant.tenant_id} [dim]({tenant.role})[/dim]")
        while True:
            choice = self.ask("Tenant (number or id): ").strip()
            if choice.isdigit() and 1 <= int(choice) <= len(tenants):
                self.user = tenants[int(choice) - 1]
            else:
                self.user = self.settings.tenant(choice)
            if self.user:
                self.console.print(f"[green]Logged in as {self.user.tenant_id}.[/green]")
                return
            self.console.print(f"[red]No tenant '{choice}'.[/red]")

    def show_nodes(self) -> None:
        """Print every node's size, usage, latency, speed and CPU utilisation."""
        table = Table(title="Nodes")
        for column in ("Node", "Tier", "CPU used / cores", "Memory used / GB", "Latency ms", "Speed", "CPU util"):
            table.add_column(column, justify="left" if column in ("Node", "Tier") else "right")
        for n in self.settings.nodes:
            style = TIER_STYLE[n.tier]
            table.add_row(n.id, f"[{style}]{n.tier}[/{style}]", f"{_fmt(n.cpu_used)} / {_fmt(n.cpu_cores)}",
                          f"{_fmt(n.memory_used)} / {_fmt(n.memory_gb)}", _fmt(n.base_latency_ms),
                          _fmt(n.speed_factor), f"{n.cpu_util:.0%}")
        self.console.print(table)

    def generate(self) -> None:
        """Ask for a count and seed, then replace the workload with random tasks."""
        gen = self.settings.simulation["generator"]
        count = self._ask_int("How many tasks", gen["count"], minimum=1)
        seed = self._ask_int("Seed", gen["seed"])
        self.tasks = generate_tasks(self.settings, count=count, seed=seed)
        self.console.print(f"[green]Generated {count} tasks with seed {seed} (replaces the previous workload).[/green]")
        self.show_tasks()

    def load(self) -> None:
        """Ask for a CSV/JSON file and replace the workload with its tasks; print any row error."""
        path = self.ask("Task file (.csv or .json) [examples/tasks_sample.csv]: ").strip() or "examples/tasks_sample.csv"
        try:
            self.tasks = load_tasks(path, self.settings)
        except ConfigError as exc:
            self.console.print(f"[red]{exc}[/red]")
            return
        self.console.print(f"[green]Loaded {len(self.tasks)} tasks from {path} (replaces the previous workload).[/green]")
        self.show_tasks()

    def add_task(self) -> None:
        """Ask for each task field and append the task; a tenant defaults to themselves as owner."""
        default_tenant = self.user.tenant_id if self.user.role == "tenant" else ""
        raw = {
            "id": self.ask("Task id [auto]: ").strip(),
            "tenant_id": self.ask(f"Tenant [{default_tenant}]: ").strip() or default_tenant,
            "cpu_cores": self.ask("CPU cores: ").strip(),
            "memory_gb": self.ask("Memory GB: ").strip(),
            "sensitivity": self.ask("Sensitivity (high / medium / low): ").strip(),
            "work_units": self.ask("Work units: ").strip(),
        }
        try:
            task = make_task(raw, self.settings, existing=self.tasks)
        except ConfigError as exc:
            self.console.print(f"[red]{exc}[/red]")
            return
        self.tasks.append(task)
        self.console.print(f"[green]Added {task.id}.[/green]")

    def show_tasks(self) -> None:
        """Print the current workload as a table."""
        if not self.tasks:
            self.console.print("No tasks yet. Generate, load or add some first.")
            return
        table = Table(title=f"Tasks ({len(self.tasks)})")
        for column in ("Task", "Tenant", "CPU", "Memory GB", "Sensitivity", "Work units"):
            table.add_column(column, justify="right" if column in ("CPU", "Memory GB", "Work units") else "left")
        for t in self.tasks:
            style = SENSITIVITY_STYLE[t.sensitivity]
            table.add_row(t.id, t.tenant_id, _fmt(t.cpu_cores), _fmt(t.memory_gb),
                          f"[{style}]{t.sensitivity}[/{style}]", _fmt(t.work_units))
        self.console.print(table)

    def show_settings(self) -> None:
        """Print every setting, its value and which layer set it."""
        table = Table(title="Settings")
        table.add_column("Setting", no_wrap=True)
        table.add_column("Value")
        table.add_column("From", style="dim")
        for path, value in _flatten(self.settings.simulation):
            table.add_row(path, str(value), _source(self.settings.origins, path))
        self.console.print(table)
        self.console.print("[dim]Change any of these with option 7, a --config file, or --set KEY=VALUE.[/dim]")

    def change_setting(self) -> None:
        """Ask for a dotted setting and a new value, validate and apply it; print any error."""
        path = self.ask("Setting (e.g. generator.seed or qos.deadlines_ms.high): ").strip()
        if not path:
            return
        value = parse_value(self.ask("New value: ").strip())
        try:
            set_value(self.settings, path, value)
        except ConfigError as exc:
            self.console.print(f"[red]{exc}[/red]")
            return
        self.console.print(f"[green]{path} = {value!r}[/green]")

    def save(self) -> None:
        """Save the current settings to a JSON file reusable with ``--config``."""
        path = self.ask("Save to [my_settings.json]: ").strip() or "my_settings.json"
        saved = save_settings(self.settings, path)
        self.console.print(f"[green]Saved to {saved}. Reuse it with --config {saved}.[/green]")

    def _ask_int(self, label: str, default: int, minimum: int | None = None) -> int:
        """Ask for a whole number until one is given; an empty answer returns ``default``."""
        while True:
            text = self.ask(f"{label} [{default}]: ").strip()
            if not text:
                return default
            if text.lstrip("-").isdigit() and (minimum is None or int(text) >= minimum):
                return int(text)
            self.console.print(f"[red]Enter a whole number{'' if minimum is None else f' >= {minimum}'}.[/red]")


def _fmt(value: float) -> str:
    """Format a number compactly: 4.0 -> "4", 0.5 -> "0.5"."""
    return f"{value:g}"


def _flatten(data: dict, prefix: str = ""):
    """Yield ``(dotted path, value)`` for every leaf setting in a nested dict."""
    for key, value in data.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict) and value:
            yield from _flatten(value, f"{path}.")
        else:
            yield path, value


def _source(origins: dict[str, str], path: str) -> str:
    """Where a setting came from, shortening file paths to the file name."""
    source = origin_of(origins, path)
    return Path(source).name if "/" in source else source
