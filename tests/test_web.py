"""Streamlit app, driven headlessly with Streamlit's AppTest (AC25-26)."""

import json

import pytest
from streamlit.testing.v1 import AppTest

from edgefogsim.__main__ import WEB_ARGS_ENV, _without_port
from edgefogsim.cli import App
from edgefogsim.workload import generate_tasks
from tests.conftest import ROOT

APP = str(ROOT / "edgefogsim" / "web.py")


def open_app(monkeypatch, *options: str, user: str | None = "hospital-a", page: str | None = None) -> AppTest:
    """Start the app with command-line ``options``, optionally log in and open a page."""
    monkeypatch.setenv(WEB_ARGS_ENV, json.dumps(list(options)))
    at = AppTest.from_file(APP, default_timeout=30).run()
    if user:
        at.sidebar.selectbox(key="login").set_value(user).run()
    if page:
        at.sidebar.radio(key="page").set_value(page).run()
    return at


def click(at: AppTest, label: str) -> AppTest:
    """Click the (form or normal) button with this label and re-run the app."""
    next(b for b in at.button if b.label == label).click()
    return at.run()


def test_welcome_screen_before_login(monkeypatch):
    """Before anyone logs in, only the welcome screen shows."""
    at = open_app(monkeypatch, user=None)
    assert not at.exception
    assert "Choose who you are" in at.info[0].value


@pytest.mark.parametrize("user", ["hospital-a", "admin"])
def test_every_page_loads_for_tenant_and_admin(monkeypatch, user):
    """AC25: every page renders without an exception for a tenant and for the admin."""
    at = open_app(monkeypatch, user=user)
    for page in ("Nodes", "Workload", "Settings"):
        at.sidebar.radio(key="page").set_value(page).run()
        assert not at.exception, f"{page} page failed for {user}"
        assert at.header[0].value == page


def test_generate_matches_menu_and_engine(monkeypatch, settings):
    """AC26: the same settings and seed give the same tasks in the app, the menu and the engine."""
    at = open_app(monkeypatch, page="Workload")
    at = click(at, "Generate (replaces the workload)")
    web_tasks = at.session_state.tasks

    answers = iter(["1", "2", "", "", "0"])
    menu = App(settings, ask=lambda prompt: next(answers))
    menu.console.quiet = True
    menu.run()

    assert web_tasks == menu.tasks == generate_tasks(settings, count=12, seed=42)


def test_command_line_options_reach_the_app(monkeypatch, settings):
    """Options given to ``web`` (here --seed 7) are applied to the app's settings."""
    at = open_app(monkeypatch, "--seed", "7", page="Workload")
    assert at.session_state.settings.get("generator.seed") == 7
    at = click(at, "Generate (replaces the workload)")
    assert at.session_state.tasks == generate_tasks(settings, seed=7)


def test_bad_option_shows_error_instead_of_crashing(monkeypatch):
    """An invalid option is shown on the page and the app stops cleanly."""
    at = open_app(monkeypatch, "--set", "policy.headroom=5", user=None)
    assert not at.exception
    assert "policy.headroom" in at.error[0].value


def test_load_sample_file(monkeypatch):
    """The sample-file button loads the 10 sample tasks."""
    at = open_app(monkeypatch, page="Workload")
    at = click(at, "Load the sample file")
    assert len(at.session_state.tasks) == 10
    assert "Loaded 10 tasks" in at.success[0].value


def test_add_task_form(monkeypatch):
    """A task added with the form gets the next id and the logged-in tenant as owner."""
    at = open_app(monkeypatch, user="hospital-b", page="Workload")
    at.selectbox(key="add_sensitivity").set_value("high")
    at.number_input(key="add_cpu").set_value(2.0)
    at = click(at, "Add task")
    task = at.session_state.tasks[-1]
    assert (task.id, task.tenant_id, task.cpu_cores, task.sensitivity) == ("T01", "hospital-b", 2, "high")


def test_change_setting_valid_and_invalid(monkeypatch):
    """A valid edit is applied with source "web app"; an invalid one shows an error and changes nothing."""
    at = open_app(monkeypatch, page="Settings")
    at.selectbox(key="setting_path").set_value("qos.deadlines_ms.high")
    at.text_input(key="setting_value").set_value("40")
    at = click(at, "Apply")
    settings = at.session_state.settings
    assert settings.get("qos.deadlines_ms.high") == 40
    assert settings.origins["qos.deadlines_ms.high"] == "web app"

    at.selectbox(key="setting_path").set_value("qos.deadlines_ms.high")
    at.text_input(key="setting_value").set_value("-1")
    at = click(at, "Apply")
    assert "must be > 0" in at.error[0].value
    assert at.session_state.settings.get("qos.deadlines_ms.high") == 40


def test_without_port_strips_only_the_port_option():
    """``--port`` is removed before options are handed to the app; other options are kept."""
    assert _without_port(["--seed", "7", "--port", "9000", "--port=1", "--deadline", "high=40"]) == \
        ["--seed", "7", "--deadline", "high=40"]
