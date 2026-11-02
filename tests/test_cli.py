from rich.console import Console

from edgefogsim.__main__ import main
from edgefogsim.cli import App


def run_menu(settings, inputs):
    answers = iter(inputs)
    console = Console(record=True, width=140)
    App(settings, console=console, ask=lambda prompt: next(answers)).run()
    return console.export_text()


def test_menu_login_view_nodes_generate_and_list(settings):
    out = run_menu(settings, ["1", "1", "2", "", "", "5", "0"])
    assert "Logged in as hospital-a" in out
    assert "edge-1" in out and "fog-1" in out and "cloud-1" in out
    assert "Generated 12 tasks with seed 42" in out
    assert "T12" in out


def test_menu_change_setting_then_generate_uses_it(settings):
    out = run_menu(settings, ["admin", "7", "generator.count", "3", "2", "", "", "0"])
    assert "generator.count = 3" in out
    assert "Generated 3 tasks" in out


def test_menu_reports_bad_setting_without_crashing(settings):
    out = run_menu(settings, ["1", "7", "qos.deadlines_ms.high", "-1", "0"])
    assert "qos.deadlines_ms.high" in out and "must be > 0" in out


def test_menu_add_task_by_hand(settings):
    out = run_menu(settings, ["1", "4", "", "", "2", "1", "high", "4", "5", "0"])
    assert "Added T01" in out


def test_bad_command_line_value_exits_with_code_2(capsys):
    assert main(["run", "--set", "qos.deadlines_ms.high=abc"]) == 2
    assert "qos.deadlines_ms.high" in capsys.readouterr().err
