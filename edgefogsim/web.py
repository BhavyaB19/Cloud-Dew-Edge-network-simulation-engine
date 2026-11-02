"""Streamlit app: the browser interface, alongside the command-line menu in ``cli``.

Start it with ``python -m edgefogsim web`` (it accepts the same options as the
menu, e.g. ``--seed 7``). Like the menu, it holds no simulation logic: every
page reads input, calls the engine modules and shows the result.

Streamlit re-runs this whole script on every click, so everything that must
survive a click (settings, tasks, who is logged in) lives in
``st.session_state``. Widgets have fixed keys so tests can drive them with
Streamlit's ``AppTest`` (see ``tests/test_web.py``).
"""

import json
import os
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

# Project root; added to sys.path because `streamlit run` only adds this file's folder.
# (Constants here use comments, not docstrings: Streamlit would print bare strings on the page.)
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402  (must follow the sys.path fix above)
import streamlit as st  # noqa: E402

from edgefogsim.__main__ import WEB_ARGS_ENV, build_parser, prepare  # noqa: E402
from edgefogsim.config import (  # noqa: E402
    ConfigError,
    Settings,
    describe_settings,
    load_settings,
    parse_value,
    set_value,
    settings_as_json,
)
from edgefogsim.models import SENSITIVITIES, Tenant  # noqa: E402
from edgefogsim.workload import generate_tasks, load_tasks, make_task  # noqa: E402

# Pages in the sidebar, in order. Later phases add Placement, Results, VMs and more.
PAGES = ("Nodes", "Workload", "Settings")

# Sample task file offered on the Workload page.
SAMPLE_TASKS = ROOT / "examples" / "tasks_sample.csv"


def init_state() -> None:
    """Load settings and the starting workload once per browser session.

    Options given to ``python -m edgefogsim web`` arrive as a JSON list in the
    ``EDGEFOGSIM_ARGS`` environment variable and are parsed exactly as the menu
    parses them. A settings error is shown on the page and stops the app.
    """
    if "settings" in st.session_state:
        return
    options = json.loads(os.environ.get(WEB_ARGS_ENV, "[]"))
    try:
        settings, tasks = prepare(build_parser().parse_args(["web", *options]))
    except ConfigError as exc:
        st.error(f"Settings error: {exc}")
        st.stop()
    st.session_state.settings = settings
    st.session_state.tasks = tasks


def sidebar(settings: Settings) -> tuple[Tenant | None, str, "st.delta_generator.DeltaGenerator"]:
    """Draw the login box and page picker.

    Args:
        settings: Current settings; supplies the list of tenants.

    Returns:
        The logged-in tenant (None until one is chosen), the selected page name,
        and an empty sidebar slot for the task count, filled in after the page
        runs so it reflects any change the page just made.
    """
    st.sidebar.title("EdgeFogSim")
    st.sidebar.caption("Edge / Fog / Cloud placement simulator")
    tenant_ids = [t.tenant_id for t in settings.tenants]
    chosen = st.sidebar.selectbox("Log in as", tenant_ids, index=None, placeholder="Choose a tenant", key="login")
    user = settings.tenant(chosen) if chosen else None
    if user:
        st.sidebar.success(f"Logged in as **{user.tenant_id}** ({user.role})")
    page = st.sidebar.radio("Page", PAGES, key="page")
    return user, page, st.sidebar.empty()


def nodes_page(settings: Settings) -> None:
    """Show every node's size, usage, latency, speed and utilisation.

    Args:
        settings: Current settings; supplies the nodes.
    """
    st.header("Nodes")
    rows = [{
        "Node": n.id,
        "Tier": n.tier,
        "CPU used / cores": f"{n.cpu_used:g} / {n.cpu_cores:g}",
        "Memory used / GB": f"{n.memory_used:g} / {n.memory_gb:g}",
        "Latency (ms)": n.base_latency_ms,
        "Speed": n.speed_factor,
        "CPU util": n.cpu_util,
    } for n in settings.nodes]
    st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        width="stretch",
        column_config={"CPU util": st.column_config.ProgressColumn("CPU util", min_value=0, max_value=1, format="percent")},
    )
    st.caption("Edit nodes in config/nodes.json or start with --nodes my_nodes.json. "
               "Node editing in the app arrives with the before/after comparison (Phase 4).")


def workload_page(settings: Settings, user: Tenant) -> None:
    """Build the workload (generate, upload or add by hand) and show it.

    Args:
        settings: Current settings; supplies generator defaults and tenants.
        user: Who is logged in; a tenant adding a task owns it by default.
    """
    st.header("Workload")
    generate_tab, upload_tab, add_tab = st.tabs(["Generate", "Upload a file", "Add a task"])
    gen = settings.simulation["generator"]

    with generate_tab:
        col1, col2 = st.columns(2)
        count = col1.number_input("How many tasks", min_value=1, value=gen["count"], step=1, key="gen_count")
        seed = col2.number_input("Seed", value=gen["seed"], step=1, key="gen_seed")
        if st.button("Generate (replaces the workload)", key="generate", type="primary"):
            st.session_state.tasks = generate_tasks(settings, count=int(count), seed=int(seed))
            st.success(f"Generated {int(count)} tasks with seed {int(seed)}.")

    with upload_tab:
        uploaded = st.file_uploader("CSV or JSON task file", type=["csv", "json"], key="task_file")
        col1, col2 = st.columns(2)
        if col1.button("Load uploaded file", key="load_upload", disabled=uploaded is None):
            _load_task_file(_save_upload(uploaded), settings)
        if col2.button("Load the sample file", key="load_sample"):
            _load_task_file(SAMPLE_TASKS, settings)
        st.caption("Columns: id, tenant_id, cpu_cores, memory_gb, sensitivity, work_units. Leave id blank to number automatically.")

    with add_tab:
        owners = [t.tenant_id for t in settings.tenants if t.role == "tenant"]
        with st.form("add_task", clear_on_submit=True):
            task_id = st.text_input("Task id (blank = automatic)", key="add_id")
            owner = st.selectbox("Tenant", owners, index=owners.index(user.tenant_id) if user.tenant_id in owners else 0,
                                 key="add_tenant")
            col1, col2, col3 = st.columns(3)
            cpu = col1.number_input("CPU cores", min_value=0.1, value=1.0, step=0.5, key="add_cpu")
            memory = col2.number_input("Memory (GB)", min_value=0.1, value=1.0, step=0.5, key="add_memory")
            work = col3.number_input("Work units", min_value=0.1, value=5.0, step=1.0, key="add_work")
            sensitivity = st.selectbox("Sensitivity", SENSITIVITIES, key="add_sensitivity")
            if st.form_submit_button("Add task"):
                raw = {"id": task_id, "tenant_id": owner, "cpu_cores": cpu, "memory_gb": memory,
                       "sensitivity": sensitivity, "work_units": work}
                try:
                    task = make_task(raw, settings, existing=st.session_state.tasks)
                except ConfigError as exc:
                    st.error(str(exc))
                else:
                    st.session_state.tasks = [*st.session_state.tasks, task]
                    st.success(f"Added {task.id}.")

    tasks = st.session_state.tasks
    st.subheader(f"Tasks ({len(tasks)})")
    if not tasks:
        st.info("No tasks yet. Generate, upload or add some above.")
        return
    st.dataframe(pd.DataFrame([asdict(t) for t in tasks]), hide_index=True, width="stretch")
    if st.button("Clear all tasks", key="clear_tasks"):
        st.session_state.tasks = []
        st.rerun()


def settings_page(settings: Settings) -> None:
    """Show every setting with its source; change one, download all, or apply a settings file.

    Args:
        settings: Current settings; changed in place by edits.
    """
    st.header("Settings")
    rows = describe_settings(settings)
    st.dataframe(
        pd.DataFrame([{"Setting": p, "Value": json.dumps(v), "From": s} for p, v, s in rows]),
        hide_index=True,
        width="stretch",
    )

    st.subheader("Change a setting")
    with st.form("change_setting"):
        path = st.selectbox("Setting", [p for p, _, _ in rows], key="setting_path")
        value = st.text_input("New value (JSON, e.g. 40, true, [1, 4])", key="setting_value")
        if st.form_submit_button("Apply"):
            try:
                set_value(settings, path, parse_value(value.strip()), source="web app")
            except ConfigError as exc:
                st.error(str(exc))
            else:
                st.success(f"{path} = {parse_value(value.strip())!r}")
                st.rerun()

    st.subheader("Save or load")
    st.download_button("Download settings (JSON)", settings_as_json(settings), file_name="my_settings.json",
                       mime="application/json", key="download_settings")
    uploaded = st.file_uploader("Apply a settings file (same format as --config)", type=["json"], key="settings_file")
    if uploaded is not None and st.button("Apply settings file", key="apply_settings"):
        path = _save_upload(uploaded)
        try:
            st.session_state.settings = load_settings(config_file=path)
        except ConfigError as exc:
            st.error(_tidy(str(exc), path))
        else:
            st.success(f"Applied {uploaded.name} on top of the defaults.")
            st.rerun()


def main() -> None:
    """Render the app: sidebar, then the selected page (login required)."""
    st.set_page_config(page_title="EdgeFogSim", layout="wide")
    init_state()
    settings = st.session_state.settings
    user, page, task_count = sidebar(settings)
    if user is None:
        st.title("EdgeFogSim")
        st.write("Simulate placing computing tasks on Edge, Fog and Cloud nodes.")
        st.info("Choose who you are in the sidebar to start.")
    elif page == "Nodes":
        nodes_page(settings)
    elif page == "Workload":
        workload_page(settings, user)
    else:
        settings_page(st.session_state.settings)
    task_count.caption(f"{len(st.session_state.tasks)} tasks loaded")


def _save_upload(uploaded) -> Path:
    """Write an uploaded file to a temporary folder under its original name and return the path."""
    path = Path(tempfile.mkdtemp(prefix="edgefogsim-")) / uploaded.name
    path.write_bytes(uploaded.getvalue())
    return path


def _load_task_file(path: Path, settings: Settings) -> None:
    """Replace the workload with a task file's tasks, showing the result or the row error."""
    try:
        st.session_state.tasks = load_tasks(path, settings)
    except ConfigError as exc:
        st.error(_tidy(str(exc), path))
    else:
        st.success(f"Loaded {len(st.session_state.tasks)} tasks from {path.name}.")


def _tidy(message: str, path: Path) -> str:
    """Show just the file name instead of its full (often temporary) path in an error message."""
    return message.replace(str(path), path.name)


main()
