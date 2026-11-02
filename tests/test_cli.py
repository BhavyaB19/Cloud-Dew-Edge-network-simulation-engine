"""Command-line menu and entry point, driven with scripted input (AC1-3 via the UI, AC19 exit code)."""

from rich.console import Console

from edgefogsim.__main__ import main
from edgefogsim.cli import App


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
    out = run_menu(settings, ["admin", "7", "generator.count", "3", "2", "", "", "0"])
    assert "generator.count = 3" in out
    assert "Generated 3 tasks" in out


def test_menu_reports_bad_setting_without_crashing(settings):
    """An invalid menu edit prints the reason and the menu carries on."""
    out = run_menu(settings, ["1", "7", "qos.deadlines_ms.high", "-1", "0"])
    assert "qos.deadlines_ms.high" in out and "must be > 0" in out


def test_menu_add_task_by_hand(settings):
    """A task typed into the menu is added with the next automatic id."""
    out = run_menu(settings, ["1", "4", "", "", "2", "1", "high", "4", "5", "0"])
    assert "Added T01" in out


def test_bad_command_line_value_exits_with_code_2(capsys):
    """A bad --set value prints the setting name and exits with status 2."""
    assert main(["run", "--set", "qos.deadlines_ms.high=abc"]) == 2
    assert "qos.deadlines_ms.high" in capsys.readouterr().err
