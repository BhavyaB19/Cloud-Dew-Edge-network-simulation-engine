"""Command-line menu and entry point, driven with scripted input (AC1-3 via the UI, AC19 exit code)."""

from rich.console import Console

from edgefogsim.__main__ import main
from edgefogsim.cli import App
from tests.conftest import ROOT


def run_menu(settings, inputs):
    """Run a whole menu session with scripted answers and return everything printed."""
    answers = iter(inputs)
    console = Console(record=True, width=140)
    App(settings, console=console, ask=lambda prompt: next(answers)).run()
    return console.export_text()


def test_menu_login_view_nodes_generate_and_list(settings):
    """Log in, view nodes, generate the default 12 tasks and list them."""
    out = run_menu(settings, ["1", "1", "2", "", "", "5", "0"])
    assert "Logged in as hospital-a" in out
    assert "edge-1" in out and "fog-1" in out and "cloud-1" in out
    assert "Generated 12 tasks with seed 42" in out
    assert "T12" in out


def test_menu_change_setting_then_generate_uses_it(settings):
    """A setting changed in the menu is used by the next generation."""
    out = run_menu(settings, ["admin", "15", "generator.count", "3", "2", "", "", "0"])
    assert "generator.count = 3" in out
    assert "Generated 3 tasks" in out


def test_menu_reports_bad_setting_without_crashing(settings):
    """An invalid menu edit prints the reason and the menu carries on."""
    out = run_menu(settings, ["1", "15", "qos.deadlines_ms.high", "-1", "0"])
    assert "qos.deadlines_ms.high" in out and "must be > 0" in out


def test_menu_add_task_by_hand(settings):
    """A task typed into the menu is added with the next automatic id."""
    out = run_menu(settings, ["1", "4", "", "", "2", "1", "high", "4", "5", "0"])
    assert "Added T01" in out


def test_bad_command_line_value_exits_with_code_2(capsys):
    """A bad --set value prints the setting name and exits with status 2."""
    assert main(["run", "--set", "qos.deadlines_ms.high=abc"]) == 2
    assert "qos.deadlines_ms.high" in capsys.readouterr().err


def test_menu_run_placement_shows_decisions_and_nodes(settings):
    """Load the sample tasks, run Capacity-Aware (the default), then view nodes after the run."""
    out = run_menu(settings, ["admin", "3", "", "6", "", "1", "0"])
    assert "Placement decisions: Capacity-Aware" in out
    assert "10 tasks: 8 on time, 0 late, 2 rejected, 1 offloaded" in out
    assert "Nodes after the last run (Capacity-Aware)" in out


def test_menu_compare_policies(settings):
    """Generate tasks and compare all four policies in one table."""
    out = run_menu(settings, ["1", "2", "", "", "7", "0"])
    assert "Policy comparison" in out
    for label in ("Latency-First", "Cloud-Only", "Capacity-Aware", "TOPSIS"):
        assert label in out


def test_menu_placement_without_tasks_explains(settings):
    """Running placement with no workload explains how to make one."""
    out = run_menu(settings, ["1", "6", "0"])
    assert "No tasks yet" in out


def test_run_command_compares_all_policies(capsys):
    """``run --policy all`` prints the comparison without the menu."""
    assert main(["run", "--policy", "all", "--tasks", "8"]) == 0
    out = capsys.readouterr().out
    assert "Policy comparison" in out and "TOPSIS" in out


def test_run_command_with_task_file(capsys):
    """``run --tasks FILE`` places that file's tasks and prints each decision."""
    assert main(["run", "--policy", "latency", "--tasks", str(ROOT / "examples" / "tasks_sample.csv")]) == 0
    assert "Placement decisions: Latency-First" in capsys.readouterr().out


def test_menu_tenant_sees_only_own_tasks(settings):
    """A tenant's task list shows only their tasks; the admin sees all of them."""
    out = run_menu(settings, ["hospital-a", "3", "", "5", "0"])
    assert "Your tasks (5 of 10" in out and "hospital-b" not in out.split("Your tasks")[-1]
    out = run_menu(settings, ["admin", "3", "", "5", "0"])
    assert "Tasks (10)" in out


def test_menu_lookup_other_tenant_task_is_denied(settings):
    """AC11 via the menu: looking up another tenant's task shows ACCESS DENIED and it appears in the audit log."""
    out = run_menu(settings, ["hospital-b", "3", "", "12", "T01", "13", "0"])
    assert "ACCESS DENIED: hospital-b may not access task T01 (belongs to hospital-a)" in out
    assert "task T01" in out.split("Audit log")[-1]


def test_menu_tenant_cannot_add_task_for_another_tenant(settings):
    """A tenant typing another tenant as owner is refused and logged."""
    out = run_menu(settings, ["hospital-a", "4", "", "hospital-b", "1", "1", "low", "5", "0"])
    assert "ACCESS DENIED" in out and "new task for hospital-b" in out


def test_menu_stop_vm_and_place_rejected_task(settings):
    """As admin: run placement, stop T01's VM, then place the rejected T08, which now fits on edge."""
    out = run_menu(settings, ["admin", "3", "", "6", "", "10", "vm-0001", "11", "T08", "", "0"])
    assert "Stopped vm-0001 (T01). Freed 2 CPU and 4 GB on edge-1, now 0% reserved." in out
    assert "T08: on time, placed on edge-1" in out


def test_menu_tenant_cannot_stop_another_tenants_vm(settings):
    """Stopping another tenant's VM is refused; the VM keeps running."""
    out = run_menu(settings, ["hospital-b", "3", "", "6", "", "10", "vm-0001", "8", "0"])
    assert "ACCESS DENIED: hospital-b may not access VM vm-0001" in out
    assert "vm-0001" not in out.split("Your VMs")[-1]
