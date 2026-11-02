"""Command-line menu: one of the two user interfaces (the other is the Streamlit app in ``web``).

The menu holds no simulation logic. Each option reads input, calls the engine
modules (``config``, ``workload``, ...) and prints the result with ``rich``
tables. Input goes through an ``ask`` function, so tests can script a whole
session (see ``tests/test_cli.py``).
"""

from pathlib import Path
from typing import Callable

from rich import box
from rich.console import Console
from rich.table import Table

from edgefogsim.config import (
    CONFIG_DIR,
    ConfigError,
    Settings,
    describe_settings,
    parse_value,
    save_settings,
    set_value,
)
from edgefogsim.models import Node, Task, Tenant
from edgefogsim.policies import POLICIES
from edgefogsim.security import AccessDenied, AuditLog, authorize, find_task, find_vm, visible
from edgefogsim.simulator import (
    LATE,
    ON_TIME,
    RunResult,
    compare_policies,
    create_vm,
    empty_cluster,
    run_workload,
    submit,
)
from edgefogsim.vm_manager import CapacityError
from edgefogsim.workload import generate_tasks, load_tasks, make_task

SENSITIVITY_STYLE = {"high": "bold red", "medium": "yellow", "low": "green"}
"""Colour for each sensitivity level in tables."""

TIER_STYLE = {"edge": "cyan", "fog": "magenta", "cloud": "blue"}
"""Colour for each node tier in tables."""

OUTCOME_STYLE = {ON_TIME: "green", LATE: "yellow", "rejected": "red"}
"""Colour for each task outcome in tables."""

SAMPLE_TASKS = CONFIG_DIR.parent / "examples" / "tasks_sample.csv"
"""The sample task file, loaded when the user just presses Enter."""


class App:
    """The interactive menu and the state of one session.

    Attributes:
        settings: Resolved settings; menu edits change them in place.
        tasks: The current workload.
        console: ``rich`` console that all output goes to.
        ask: Function that shows a prompt and returns the user's answer.
        user: Who is logged in, or None before login.
        last_run: The live cluster from the most recent placement run (nodes,
            VMs, decisions), or None. Stopping VMs and placing single tasks act on it.
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
        self.last_run: RunResult | None = None

    @property
    def audit(self) -> AuditLog:
        """The audit log at the current ``security.audit_log`` path."""
        return AuditLog(self.settings.get("security.audit_log"))

    def run(self) -> None:
        """Log in, then show the main menu until the user chooses Exit."""
        self.console.print("[bold]EdgeFogSim[/bold]: Edge / Fog / Cloud placement simulator")
        self.login()
        sections = [
            ("Nodes and workload", [
                ("View nodes", self.show_nodes),
                ("Generate random tasks", self.generate),
                ("Load tasks from a file", self.load),
                ("Add a task by hand", self.add_task),
                ("View tasks", self.show_tasks),
            ]),
            ("Placement", [
                ("Run placement", self.run_placement),
                ("Compare all policies", self.compare),
            ]),
            ("Virtual machines", [
                ("View VMs", self.show_vms),
                ("Create a VM", self.create_vm),
                ("Stop a VM", self.stop_vm),
                ("Place one task now (joins or creates a VM)", self.place_one),
            ]),
            ("Security", [
                ("Look up a task or VM by id", self.lookup),
                ("View audit log", self.show_audit),
            ]),
            ("Settings", [
                ("View settings", self.show_settings),
                ("Change a setting", self.change_setting),
                ("Save settings to a file", self.save),
                ("Switch user", self.login),
            ]),
        ]
        actions = [action for _, items in sections for action in items]
        while True:
            self.console.print()
            mine = len(visible(self.user, self.tasks))
            self.console.print(f"[dim]Logged in as[/dim] [bold]{self.user.tenant_id}[/bold] [dim]({self.user.role})"
                               f" · {len(self.tasks)} tasks loaded, {mine} visible to you[/dim]")
            number = 1
            for title, items in sections:
                self.console.print(f" [bold]{title}[/bold]")
                for label, _ in items:
                    self.console.print(f"  {number:>2}. {label}")
                    number += 1
            self.console.print("   0. Exit")
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
        """Print the nodes: their usage after the last run, or empty if nothing has run yet."""
        if self.last_run:
            print_nodes(self.console, self.last_run.nodes, f"Nodes after the last run ({self.last_run.label})")
        else:
            print_nodes(self.console, self.settings.nodes, "Nodes (nothing placed yet)")

    def run_placement(self) -> None:
        """Ask for a policy, place the whole workload with it and print every decision."""
        if not self._has_tasks():
            return
        key = self._ask_policy()
        self.last_run = run_workload(self.settings, self.tasks, key)
        print_run(self.console, self.last_run, viewer=self.user)

    def compare(self) -> None:
        """Run the workload through every policy on fresh nodes and print the results side by side."""
        if not self._has_tasks():
            return
        print_comparison(self.console, compare_policies(self.settings, self.tasks))

    def show_vms(self) -> None:
        """Print the VMs the user may see (their own; all for an admin)."""
        if not self.last_run or not self.last_run.vms.vms:
            self.console.print("No VMs yet. Run placement (option 6), create a VM (option 9) "
                               "or place one task (option 11).")
            return
        print_vms(self.console, visible(self.user, self.last_run.vms.vms), self.user)

    def create_vm(self) -> None:
        """Create an empty VM on a node, reserving room for a tenant's tasks.

        A tenant creates VMs for themselves; an admin chooses the owner. Size
        defaults to the tier's ``vm.sizes`` entry.
        """
        if self.last_run is None:
            self.last_run = empty_cluster(self.settings)
        node_ids = [n.id for n in self.last_run.nodes]
        node_id = self.ask(f"Node ({', '.join(node_ids)}): ").strip()
        if node_id not in node_ids:
            self.console.print(f"[red]No node '{node_id}'.[/red]")
            return
        owner = self.user.tenant_id
        if self.user.is_admin:
            owners = [t.tenant_id for t in self.settings.tenants if t.role == "tenant"]
            owner = self.ask(f"Owner ({', '.join(owners)}): ").strip()
            if owner not in owners:
                self.console.print(f"[red]No tenant '{owner}'.[/red]")
                return
        size = self.settings.simulation["vm"]["sizes"][self.last_run.vms.node(node_id).tier]
        try:
            cpu = float(self.ask(f"CPU cores [{_fmt(size['cpu_cores'])}]: ").strip() or size["cpu_cores"])
            memory = float(self.ask(f"Memory GB [{_fmt(size['memory_gb'])}]: ").strip() or size["memory_gb"])
            vm = create_vm(self.last_run, owner, node_id, cpu, memory)
        except ValueError as exc:
            self.console.print(f"[red]{exc}[/red]")
            return
        node = self.last_run.vms.node(node_id)
        self.console.print(f"[green]Created {vm.vm_id} for {owner} on {node_id} ({_fmt(cpu)} CPU / {_fmt(memory)} GB); "
                           f"{node_id} now {node.cpu_util:.0%} reserved.[/green]")

    def stop_vm(self) -> None:
        """Ask for a VM id and stop it, freeing its slice of the node; refuse and log another tenant's VM."""
        if not self.last_run:
            self.console.print("No VMs yet. Run placement first (option 6).")
            return
        vm_id = self.ask("VM id to stop (e.g. vm-0001): ").strip()
        try:
            vm = find_vm(self.user, vm_id, self.last_run.vms, self.audit)
        except KeyError as exc:
            self.console.print(f"[red]{exc.args[0]}[/red]")
            return
        except AccessDenied as exc:
            self._denied(exc)
            return
        if not self.last_run.stop_vm(vm.vm_id):
            self.console.print(f"[yellow]{vm.vm_id} was already stopped; nothing freed.[/yellow]")
            return
        node = self.last_run.vms.node(vm.node_id)
        tasks = ", ".join(vm.task_ids) or "no tasks"
        self.console.print(f"[green]Stopped {vm.vm_id} ({tasks}). Freed {_fmt(vm.cpu_cores)} CPU and "
                           f"{_fmt(vm.memory_gb)} GB on {node.id}, now {node.cpu_util:.0%} reserved.[/green]")

    def place_one(self) -> None:
        """Place one of the user's tasks on the current cluster now, e.g. a rejected task after freeing room."""
        if not self._has_tasks():
            return
        task_id = self.ask("Task id to place (e.g. T04): ").strip()
        try:
            task = find_task(self.user, task_id, self.tasks, self.audit)
        except KeyError as exc:
            self.console.print(f"[red]{exc.args[0]}[/red]")
            return
        except AccessDenied as exc:
            self._denied(exc)
            return
        key = self._ask_policy()
        if self.last_run is None:
            self.last_run = empty_cluster(self.settings, key)
        try:
            decision = submit(self.last_run, task, key, self.settings)
        except ValueError as exc:
            self.console.print(f"[yellow]{exc}[/yellow]")
            return
        style = OUTCOME_STYLE[decision.outcome]
        where = f"on {decision.node_id} as {decision.vm_id}" if decision.placed else "nowhere"
        self.console.print(f"[{style}]{task.id}: {decision.outcome}, placed {where}.[/]")
        self.console.print(f"[dim]Why: {decision.reason}[/dim]")

    def lookup(self) -> None:
        """Show one task or VM by id; another tenant's record is refused and logged."""
        record_id = self.ask("Task or VM id (e.g. T05 or vm-0002): ").strip()
        try:
            if record_id.lower().startswith("vm-"):
                if not self.last_run:
                    raise KeyError(f"no VM '{record_id}'")
                print_vms(self.console, [find_vm(self.user, record_id, self.last_run.vms, self.audit)], self.user)
            else:
                task = find_task(self.user, record_id, self.tasks, self.audit)
                self._print_tasks([task], f"Task {task.id}")
        except KeyError as exc:
            self.console.print(f"[red]{exc.args[0]}[/red]")
        except AccessDenied as exc:
            self._denied(exc)

    def show_audit(self) -> None:
        """Print the audit log: every refused attempt for an admin, the user's own attempts otherwise."""
        entries = self.audit.entries(viewer=self.user)
        if not entries:
            self.console.print("The audit log has no refused attempts" +
                               ("." if self.user.is_admin else " by you."))
            return
        table = Table(title=f"Audit log ({self.audit.path})")
        for column in ("Time", "Actor", "Owner", "Resource", "Outcome"):
            table.add_column(column)
        for e in entries:
            table.add_row(e["timestamp"], e["actor"], e["target_tenant"], e["resource"], f"[red]{e['outcome']}[/red]")
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
        path = self.ask("Task file (.csv or .json) [the sample file]: ").strip() or str(SAMPLE_TASKS)
        try:
            self.tasks = load_tasks(path, self.settings)
        except ConfigError as exc:
            self.console.print(f"[red]{exc}[/red]")
            return
        self.console.print(f"[green]Loaded {len(self.tasks)} tasks from {Path(path).name} "
                           "(replaces the previous workload).[/green]")
        self.show_tasks()

    def add_task(self) -> None:
        """Ask for each task field and append the task.

        A tenant owns the task by default and may not add tasks for another
        tenant (refused and logged); an admin may add a task for anyone.
        """
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
            authorize(self.user, raw["tenant_id"], f"new task for {raw['tenant_id']}", self.audit)
            task = make_task(raw, self.settings, existing=self.tasks)
        except AccessDenied as exc:
            self._denied(exc)
            return
        except ConfigError as exc:
            self.console.print(f"[red]{exc}[/red]")
            return
        self.tasks.append(task)
        self.console.print(f"[green]Added {task.id}.[/green]")

    def show_tasks(self) -> None:
        """Print the tasks the user may see: their own, or all of them for an admin."""
        if not self.tasks:
            self.console.print("No tasks yet. Generate, load or add some first.")
            return
        mine = visible(self.user, self.tasks)
        title = (f"Tasks ({len(self.tasks)})" if self.user.is_admin
                 else f"Your tasks ({len(mine)} of {len(self.tasks)}; other tenants' tasks are hidden)")
        self._print_tasks(mine, title)

    def _print_tasks(self, tasks: list[Task], title: str) -> None:
        """Print a table of tasks."""
        table = Table(title=title)
        for column in ("Task", "Tenant", "CPU", "Memory GB", "Sensitivity", "Work units"):
            table.add_column(column, justify="right" if column in ("CPU", "Memory GB", "Work units") else "left")
        for t in tasks:
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
        for path, value, source in describe_settings(self.settings):
            table.add_row(path, str(value), source)
        self.console.print(table)
        self.console.print("[dim]Change any of these with option 15, a --config file, or --set KEY=VALUE.[/dim]")

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

    def _denied(self, exc: AccessDenied) -> None:
        """Show a refused access attempt and where it was logged."""
        self.console.print(f"[bold red]{exc}[/bold red]")
        self.console.print(f"[dim]Recorded in {self.audit.path}.[/dim]")

    def _has_tasks(self) -> bool:
        """True if there is a workload; otherwise say how to make one."""
        if not self.tasks:
            self.console.print("No tasks yet. Generate, load or add some first (options 2-4).")
        return bool(self.tasks)

    def _ask_policy(self) -> str:
        """Ask which policy to use (by number or key); an empty answer picks Capacity-Aware."""
        keys = list(POLICIES)
        for number, key in enumerate(keys, start=1):
            policy = POLICIES[key]
            self.console.print(f"  {number}. {policy.label} [dim]- {policy.summary}[/dim]")
        while True:
            choice = self.ask("Policy [3 = Capacity-Aware]: ").strip() or "3"
            if choice.isdigit() and 1 <= int(choice) <= len(keys):
                return keys[int(choice) - 1]
            if choice in POLICIES:
                return choice
            self.console.print(f"[red]'{choice}' is not a policy.[/red]")

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


def print_nodes(console: Console, nodes: list[Node], title: str) -> None:
    """Print a table of nodes with size, reserved and used capacity, latency and speed.

    Args:
        console: Where to print.
        nodes: The nodes to show.
        title: Table title.
    """
    table = Table(title=title, caption="Reserved = held by VMs. Load = used by tasks (drives latency).")
    for column in ("Node", "Tier", "CPU reserved / cores", "GB reserved / total", "CPU load", "Latency ms",
                   "Speed", "Reserved", "Load"):
        table.add_column(column, justify="left" if column in ("Node", "Tier") else "right")
    for n in nodes:
        style = TIER_STYLE[n.tier]
        table.add_row(n.id, f"[{style}]{n.tier}[/{style}]", f"{_fmt(n.cpu_used)} / {_fmt(n.cpu_cores)}",
                      f"{_fmt(n.memory_used)} / {_fmt(n.memory_gb)}", _fmt(n.cpu_load), _fmt(n.base_latency_ms),
                      _fmt(n.speed_factor), f"{n.cpu_util:.0%}", f"{n.load_util:.0%}")
    console.print(table)


def print_run(console: Console, result: RunResult, viewer: Tenant | None = None) -> None:
    """Print placement decisions, the headline numbers and the nodes afterwards.

    Args:
        console: Where to print.
        result: The run to show.
        viewer: If given and not an admin, only their own tasks' decisions are
            listed. Totals and node usage are cluster-wide and shown to everyone.
    """
    decisions = result.decisions if viewer is None else visible(viewer, result.decisions, lambda d: d.task.tenant_id)
    hidden = len(result.decisions) - len(decisions)
    title = f"Placement decisions: {result.label}" + (f" (your {len(decisions)} tasks)" if hidden else "")
    table = Table(title=title, show_lines=True)
    for column in ("Task", "Tenant", "Sens.", "Node", "VM", "Latency ms", "Deadline", "Outcome", "Why"):
        table.add_column(column, justify="right" if column in ("Latency ms", "Deadline") else "left",
                         overflow="fold", ratio=4 if column == "Why" else None)
    for d in decisions:
        sens, outcome = SENSITIVITY_STYLE[d.task.sensitivity], OUTCOME_STYLE[d.outcome]
        node = "-" if d.node_id is None else f"[{TIER_STYLE[d.tier]}]{d.node_id}[/]" + (" ↪" if d.offloaded else "")
        table.add_row(d.task.id, d.task.tenant_id, f"[{sens}]{d.task.sensitivity}[/]", node, d.vm_id or "-",
                      "-" if d.latency_ms is None else f"{d.latency_ms:.1f}", _fmt(d.deadline_ms),
                      f"[{outcome}]{d.outcome}[/]", d.reason)
    console.print(table)
    console.print("[dim]↪ = offloaded outside the task's first-choice tier[/dim]")
    if hidden:
        console.print(f"[dim]{hidden} decisions for other tenants' tasks are hidden. Totals below are cluster-wide.[/dim]")
    _print_summary_line(console, result)
    print_nodes(console, result.nodes, f"Nodes after {result.label}")


def print_vms(console: Console, vms: list, viewer: Tenant) -> None:
    """Print a table of VM records.

    Args:
        console: Where to print.
        vms: The VMs to show (already filtered to what ``viewer`` may see).
        viewer: Who is looking; only used for the title.
    """
    title = "VMs" if viewer.is_admin else f"Your VMs ({viewer.tenant_id})"
    table = Table(title=title)
    for column in ("VM", "Tenant", "Node", "CPU used / size", "GB used / size", "Tasks", "Status"):
        table.add_column(column, justify="right" if "/" in column else "left")
    for vm in vms:
        status = "[green]running[/green]" if vm.running else "[dim]stopped[/dim]"
        table.add_row(vm.vm_id, vm.tenant_id, vm.node_id, f"{_fmt(vm.cpu_load)} / {_fmt(vm.cpu_cores)}",
                      f"{_fmt(vm.memory_load)} / {_fmt(vm.memory_gb)}", ", ".join(vm.task_ids) or "-", status)
    console.print(table)
    console.print("[dim]A VM is a slice of its node owned by one tenant; that tenant's tasks run inside it "
                  "while it has room.[/dim]")


def print_comparison(console: Console, results: list[RunResult]) -> None:
    """Print one row of headline numbers per policy, for the same workload.

    Args:
        console: Where to print.
        results: One run per policy.
    """
    node_ids = [n.id for n in results[0].nodes] if results else []
    # Two-line headers and no outer padding keep the table inside an 80-column terminal.
    table = Table(title="Policy comparison (same workload, fresh nodes each)", box=box.SIMPLE_HEAD, show_edge=False, collapse_padding=True,
                  pad_edge=False, caption="Node columns show CPU utilisation at the end of the run.")
    table.add_column("Policy", no_wrap=True, min_width=14)
    for column in ("On\ntime", "Late", "Rej", "Off", "Success", "Avg\nms", "P95\nms", *node_ids):
        table.add_column(column, justify="right")
    best = max(r.summary()["success_rate"] for r in results) if results else 0
    for r in results:
        m = r.summary()
        label = f"[bold green]{r.label}[/]" if m["success_rate"] == best else r.label
        table.add_row(label, str(m["on_time"]), str(m["late"]), str(m["rejected"]), str(m["offloaded"]),
                      f"{m['success_rate']:.0%}", _ms(m["avg_latency_ms"], 0), _ms(m["p95_latency_ms"], 0),
                      *[f"{m[f'{nid} util']:.0%}" for nid in node_ids])
    console.print(table)
    console.print("[dim]Success = tasks placed and on time / all tasks. Latency is over placed tasks.[/dim]")


def _print_summary_line(console: Console, result: RunResult) -> None:
    """Print the run's totals in one line."""
    m = result.summary()
    console.print(f"[bold]{m['total']} tasks[/bold]: [green]{m['on_time']} on time[/green], "
                  f"[yellow]{m['late']} late[/yellow], [red]{m['rejected']} rejected[/red], "
                  f"{m['offloaded']} offloaded · success {m['success_rate']:.0%} · "
                  f"avg {_ms(m['avg_latency_ms'])} ms · p95 {_ms(m['p95_latency_ms'])} ms")


def _ms(value: float | None, decimals: int = 1) -> str:
    """Format milliseconds (one decimal by default), or "-" when there is no value."""
    return "-" if value is None else f"{value:.{decimals}f}"
