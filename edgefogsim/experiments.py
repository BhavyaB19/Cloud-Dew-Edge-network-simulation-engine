"""The four required experiments (F11), run with one command and written up as evidence.

``python run_experiments.py`` (or ``python -m edgefogsim experiments``) runs:

- **E1 Policy comparison**: the same workload through every policy.
- **E2 Overload**: Edge pre-loaded to 90%, then a burst of urgent tasks: are
  tasks moved to another node, or rejected?
- **E3 Unauthorised access**: one tenant tries to read and stop another
  tenant's records; every attempt must be refused and logged.
- **E4 Node change**: the same workload before and after changing a node's
  capacity, and separately a node's latency.

Each experiment states its setup and expected outcome *before* running, then
checks the expectation against the actual numbers, so "passed" comes from the
data. Everything is written to ``results/<time>-experiments/``: one folder of
evidence (CSV, JSON, PNG, logs) per experiment and ``experiments.md`` with the
setup, expected outcome, actual outcome and evidence for each, ready for the
report. The workloads and changes come from ``config/experiments.json``.
"""

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from edgefogsim import charts
from edgefogsim.config import CONFIG_DIR, ConfigError, Settings, save_settings, set_value
from edgefogsim.models import Task, Tenant
from edgefogsim.policies import POLICIES
from edgefogsim.results import (
    decisions_table,
    export_before_after,
    export_comparison,
    new_export_dir,
)
from edgefogsim.security import AccessDenied, AuditLog, find_task, find_vm
from edgefogsim.simulator import (
    REJECTED,
    RunResult,
    compare_before_after,
    compare_policies,
    fresh_nodes,
    run_workload,
)
from edgefogsim.workload import generate_tasks, load_tasks

EXPERIMENTS_FILE = CONFIG_DIR / "experiments.json"
"""Default experiment definitions."""


@dataclass
class Experiment:
    """One experiment's write-up.

    Attributes:
        key: Short id, e.g. ``"E2"``.
        title: Name, e.g. ``"Overload"``.
        setup: What was run, one line per item.
        expected: The expected outcome, written before running.
        actual: Markdown lines describing what happened (tables, quotes, images).
        checks: ``(statement, held)`` pairs comparing expected with actual.
        evidence: Files produced, relative to the experiments folder.
    """

    key: str
    title: str
    setup: list[str]
    expected: str
    actual: list[str] = field(default_factory=list)
    checks: list[tuple[str, bool]] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """True if every check held."""
        return all(held for _, held in self.checks)


@dataclass
class ExperimentRun:
    """All experiments from one run.

    Attributes:
        folder: Where the evidence and ``experiments.md`` were written.
        experiments: One write-up per experiment, in order.
    """

    folder: Path
    experiments: list[Experiment]

    @property
    def report(self) -> Path:
        """Path of ``experiments.md``."""
        return self.folder / "experiments.md"


def load_experiments(path: Path | str = EXPERIMENTS_FILE) -> dict[str, dict[str, Any]]:
    """Read and check the experiment definitions.

    Args:
        path: A JSON file shaped like ``config/experiments.json``.

    Returns:
        Experiment key -> definition.

    Raises:
        ConfigError: If the file is missing, malformed, or an experiment lacks a required key.
    """
    path = Path(path)
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        raise ConfigError(str(path), "file", "not found") from None
    except json.JSONDecodeError as exc:
        raise ConfigError(str(path), f"line {exc.lineno}", f"invalid JSON: {exc.msg}") from None
    experiments = data.get("experiments") if isinstance(data, dict) else None
    if not isinstance(experiments, dict):
        raise ConfigError(str(path), "experiments", "must be an object of experiments")
    required = {"E1": ("workload", "policies"), "E2": ("workload", "policies", "preload"),
                "E3": ("workload", "policy", "actor", "target_tenant"), "E4": ("workload", "policy", "changes")}
    for key, keys in required.items():
        if key not in experiments:
            raise ConfigError(str(path), f"experiments.{key}", "is missing")
        for name in keys:
            if name not in experiments[key]:
                raise ConfigError(str(path), f"experiments.{key}.{name}", "is missing")
    return experiments


def run_all(settings: Settings, definitions: dict[str, dict[str, Any]] | None = None,
            folder: Path | str | None = None) -> ExperimentRun:
    """Run E1-E4, save the evidence and write ``experiments.md``.

    Args:
        settings: Resolved settings; experiments never change them.
        definitions: Experiment definitions; defaults to ``config/experiments.json``.
        folder: Where to write; defaults to a new ``results/<time>-experiments`` folder.

    Returns:
        The folder and every experiment's write-up.
    """
    definitions = definitions or load_experiments()
    folder = Path(folder) if folder else new_export_dir(settings, "experiments")
    folder.mkdir(parents=True, exist_ok=True)
    runners = {"E1": policy_comparison, "E2": overload, "E3": unauthorised_access, "E4": node_change}
    experiments = []
    for key, runner in runners.items():
        sub = folder / key
        sub.mkdir(exist_ok=True)
        experiment = runner(settings, definitions[key], sub)
        experiment.evidence = [f"{key}/{name}" for name in experiment.evidence]
        experiments.append(experiment)
    save_settings(settings, folder / "settings_used.json")
    run = ExperimentRun(folder, experiments)
    write_report(run)
    (folder / "experiments.json").write_text(json.dumps([{
        "key": e.key, "title": e.title, "passed": e.passed,
        "checks": [{"statement": s, "held": h} for s, h in e.checks], "evidence": e.evidence,
    } for e in experiments], indent=2) + "\n")
    return run


def policy_comparison(settings: Settings, spec: dict[str, Any], folder: Path) -> Experiment:
    """E1: run the same workload through several policies and compare them."""
    tasks, workload_text = build_workload(settings, spec["workload"])
    keys = spec["policies"]
    smart = [k for k in keys if k in ("capacity", "topsis")]
    baselines = [k for k in keys if k in ("latency", "cloud")]
    exp = Experiment(
        "E1", spec.get("title", "Policy comparison"),
        setup=[workload_text, f"Policies: {', '.join(POLICIES[k].label for k in keys)}",
               "Each policy starts from empty nodes, so the comparison is fair."],
        expected=("The smart policies (Capacity-Aware, TOPSIS) place no task late, and get more tasks "
                  "on time than both baselines (Latency-First, Cloud-Only), which ignore deadlines."),
    )
    results = compare_policies(settings, tasks, keys)
    export_comparison(results, settings, folder)
    exp.evidence += ["comparison.csv", "comparison.json"]
    exp.evidence += [p.name for p in charts.save_comparison_charts(results, folder).values()]
    exp.actual += _summary_markdown(results)
    exp.actual += ["", f"![Task outcomes by policy](E1/outcomes.png)", "",
                   f"![Where each policy placed the tasks](E1/tiers.png)", "",
                   f"![Latency as a share of the deadline](E1/latency.png)"]
    by_key = {r.policy: r.summary() for r in results}
    best_baseline = max((by_key[k]["on_time"] for k in baselines), default=0)
    for key in smart:
        label = POLICIES[key].label
        exp.checks.append((f"{label} places no task late ({by_key[key]['late']} late)", by_key[key]["late"] == 0))
        exp.checks.append((f"{label} gets more tasks on time ({by_key[key]['on_time']}) than the best baseline "
                           f"({best_baseline})", by_key[key]["on_time"] > best_baseline))
    return exp


def overload(settings: Settings, spec: dict[str, Any], folder: Path) -> Experiment:
    """E2: pre-load nodes, send a burst of urgent tasks, and show offloads and rejections."""
    tasks, workload_text = build_workload(settings, spec["workload"])
    preload = spec["preload"]
    keys = spec["policies"]
    exp = Experiment(
        "E2", spec.get("title", "Overload"),
        setup=[workload_text,
               "Before the burst: " + ", ".join(f"{node} already {share:.0%} busy" for node, share in preload.items()),
               f"Policies: {', '.join(POLICIES[k].label for k in keys)}"],
        expected=("Capacity-Aware moves tasks that don't fit on the busy Edge node to another node "
                  "(offloaded) and rejects, with a reason, tasks that no node can finish in time. "
                  "It runs nothing late, never allocates more than a node has, and does better than "
                  "Latency-First, which keeps placing tasks where they will be late."),
    )
    results = []
    for key in keys:
        nodes = fresh_nodes(settings)
        for node in nodes:
            if node.id in preload:
                node.cpu_used = node.cpu_load = preload[node.id] * node.cpu_cores
        result = run_workload(settings, tasks, key, nodes=nodes)
        results.append(result)
        decisions_table(result).to_csv(folder / f"decisions_{key}.csv", index=False)
        exp.evidence.append(f"decisions_{key}.csv")
    exp.actual += _summary_markdown(results)
    capacity = next((r for r in results if r.policy == "capacity"), results[-1])
    offload = next((d for d in capacity.decisions if d.offloaded and d.placed), None)
    reject = next((d for d in capacity.decisions if d.outcome == REJECTED), None)
    if offload:
        exp.actual += ["", f"Example offload ({offload.task.id} → {offload.node_id}):", f"> {offload.reason}"]
    if reject:
        exp.actual += ["", f"Example rejection ({reject.task.id}):", f"> {reject.reason}"]
    exp.evidence.append(charts.save_figure(charts.outcomes_chart(results), folder / "outcomes.png").name)
    exp.evidence.append(charts.save_figure(charts.node_usage_chart(capacity), folder / "node_usage.png").name)
    exp.actual += ["", "![Outcomes under overload](E2/outcomes.png)", "",
                   "![Node CPU after the burst](E2/node_usage.png)"]
    m = capacity.summary()
    exp.checks += [
        (f"{capacity.label} offloads at least one task ({m['offloaded']} offloaded)", m["offloaded"] >= 1),
        (f"{capacity.label} rejects tasks no node can serve in time ({m['rejected']} rejected, each with a reason)",
         m["rejected"] >= 1 and all(d.reason for d in capacity.decisions)),
        (f"{capacity.label} places no task late ({m['late']} late)", m["late"] == 0),
        ("No node is ever allocated beyond its capacity",
         all(n.cpu_used <= n.cpu_cores + 1e-9 and n.memory_used <= n.memory_gb + 1e-9
             for r in results for n in r.nodes)),
    ]
    latency_first = next((r for r in results if r.policy == "latency"), None)
    if latency_first:
        lm = latency_first.summary()
        exp.checks.append((f"{capacity.label} gets at least as many tasks on time ({m['on_time']}) as "
                           f"Latency-First ({lm['on_time']}, with {lm['late']} late)", m["on_time"] >= lm["on_time"]))
    return exp


def unauthorised_access(settings: Settings, spec: dict[str, Any], folder: Path) -> Experiment:
    """E3: a tenant tries to read and stop another tenant's task and VM; all attempts must be refused and logged."""
    tasks, workload_text = build_workload(settings, spec["workload"])
    actor = _tenant(settings, spec["actor"])
    admin = next(t for t in settings.tenants if t.is_admin)
    target = spec["target_tenant"]
    result = run_workload(settings, tasks, spec["policy"])
    audit = AuditLog(folder / "audit.log")
    placed = next((d for d in result.decisions if d.placed and d.task.tenant_id == target), None)
    if placed is None:
        raise ConfigError("experiments.json", "E3.workload",
                          f"no task of {target} was placed, so there is no VM to try to access; use a bigger workload")
    task, vm = placed.task, result.vms.get(placed.vm_id)
    exp = Experiment(
        "E3", spec.get("title", "Unauthorised tenant access"),
        setup=[workload_text, f"Placed with {POLICIES[spec['policy']].label}.",
               f"Logged in as {actor.tenant_id}, who tries to read {target}'s task {task.id}, read its VM "
               f"{vm.vm_id}, and stop that VM. Then the admin reads the same records."],
        expected=(f"Every attempt by {actor.tenant_id} is refused with ACCESS DENIED, returns nothing, "
                  f"and adds one line to the audit log. {target}'s VM keeps running. The admin can read both records."),
    )
    lines, denied = [], 0
    attempts = [
        (f"read task {task.id}", lambda: find_task(actor, task.id, tasks, audit)),
        (f"read VM {vm.vm_id}", lambda: find_vm(actor, vm.vm_id, result.vms, audit)),
        (f"stop VM {vm.vm_id}", lambda: result.stop_vm(find_vm(actor, vm.vm_id, result.vms, audit).vm_id)),
    ]
    for action, attempt in attempts:
        try:
            attempt()
            lines.append(f"{actor.tenant_id} → {action}: ALLOWED (unexpected)")
        except AccessDenied as exc:
            denied += 1
            lines.append(f"{actor.tenant_id} → {action}: {exc}")
    admin_ok = True
    try:
        find_task(admin, task.id, tasks, audit)
        find_vm(admin, vm.vm_id, result.vms, audit)
        lines.append(f"{admin.tenant_id} → read task {task.id} and VM {vm.vm_id}: allowed")
    except AccessDenied as exc:
        admin_ok = False
        lines.append(f"{admin.tenant_id} → {exc} (unexpected)")
    (folder / "access_attempts.txt").write_text("\n".join(lines) + "\n")
    exp.evidence += ["access_attempts.txt", "audit.log"]
    entries = audit.entries()
    exp.actual += ["```", *lines, "```", "", "Audit log:", "",
                   *_markdown_table(["timestamp", "actor", "target_tenant", "resource", "outcome"],
                                    [list(e.values()) for e in entries])]
    exp.checks += [
        (f"All {len(attempts)} attempts by {actor.tenant_id} were refused ({denied} refused)", denied == len(attempts)),
        (f"The audit log has one line per refusal ({len(entries)} lines)", len(entries) == len(attempts)),
        (f"{target}'s VM {vm.vm_id} is still running", vm.running),
        ("The admin can read both records", admin_ok),
    ]
    return exp


def node_change(settings: Settings, spec: dict[str, Any], folder: Path) -> Experiment:
    """E4: re-run the same workload after each node change (capacity, then latency) and compare."""
    tasks, workload_text = build_workload(settings, spec["workload"])
    exp = Experiment(
        "E4", spec.get("title", "Node capacity and latency change"),
        setup=[workload_text, f"Policy: {POLICIES[spec['policy']].label}",
               "Each change is compared with the original nodes, one at a time."],
        expected=("More CPU on a node lets it take more tasks, so at least as many finish on time and no more "
                  "are rejected. More network latency on a node makes every task placed there slower; tasks "
                  "whose deadline no longer allows that node move elsewhere or are rejected, while "
                  "low-sensitivity tasks still finish on time."),
    )
    for i, change in enumerate(spec["changes"]):
        sub = folder / "abcdefgh"[i]
        sub.mkdir(exist_ok=True)
        result = compare_before_after(settings, tasks, spec["policy"], change)
        export_before_after(result, settings, sub)
        charts.save_before_after_chart(result.before, result.after, result.change, sub)
        tag = f"{sub.name}/"
        exp.evidence += [tag + "before_after.csv", tag + "before_after.png",
                         tag + "decisions_before.csv", tag + "decisions_after.csv"]
        exp.actual += ["" if exp.actual else None, f"**Change {sub.name}: {result.change}**", "",
                       *_markdown_table(["Metric", "Before", "After"], _before_after_rows(result)),
                       "", f"![Before and after {result.change}](E4/{sub.name}/before_after.png)"]
        exp.checks += _node_change_checks(result, change)
    return exp


def write_report(run: ExperimentRun) -> Path:
    """Write ``experiments.md``: a summary table, then setup, expected, actual and evidence per experiment.

    Args:
        run: The experiments and their folder.

    Returns:
        The report's path.
    """
    lines = ["# EdgeFogSim experiments", "",
             f"Generated in `{run.folder.name}/`. Re-run with `python run_experiments.py`; the exact settings are in "
             "[settings_used.json](settings_used.json).", "",
             *_markdown_table(["Experiment", "Result", "Checks held"],
                              [[f"{e.key} {e.title}", "✅ as expected" if e.passed else "❌ differs from expected",
                                f"{sum(h for _, h in e.checks)} / {len(e.checks)}"] for e in run.experiments])]
    for e in run.experiments:
        lines += ["", f"## {e.key}: {e.title}", "", "**Setup**", "", *[f"- {s}" for s in e.setup],
                  "", "**Expected outcome**", "", e.expected, "", "**Actual outcome**", "",
                  *[line for line in e.actual if line is not None],
                  "", "**Expected vs actual**", "", *[f"- {'✅' if held else '❌'} {s}" for s, held in e.checks],
                  "", "**Evidence**", "", *[f"- [{p}]({p})" for p in e.evidence]]
    run.report.write_text("\n".join(lines) + "\n")
    return run.report


def build_workload(settings: Settings, spec: dict[str, Any]) -> tuple[list[Task], str]:
    """Create an experiment's tasks from its ``workload`` definition.

    Args:
        settings: Resolved settings (not modified).
        spec: Either ``{"file": "examples/tasks_sample.csv"}`` or ``{"generate": N, "seed": S}``
            with an optional ``sensitivity_mix``.

    Returns:
        The tasks, and one line describing them for the write-up.
    """
    if "file" in spec:
        path = Path(spec["file"])
        path = path if path.is_absolute() else CONFIG_DIR.parent / path
        tasks = load_tasks(path, settings)
        return tasks, f"Workload: {len(tasks)} tasks from {path.name}."
    trial = copy.deepcopy(settings)
    if "sensitivity_mix" in spec:
        set_value(trial, "generator.sensitivity_mix", spec["sensitivity_mix"], source="experiments.json")
    tasks = generate_tasks(trial, count=spec["generate"], seed=spec["seed"])
    mix = {level: sum(t.sensitivity == level for t in tasks) for level in ("high", "medium", "low")}
    mix_text = ", ".join(f"{n} {level}" for level, n in mix.items() if n)
    return tasks, f"Workload: {len(tasks)} generated tasks, seed {spec['seed']} ({mix_text} sensitivity)."


def _node_change_checks(result, change: dict[str, dict[str, float]]) -> list[tuple[str, bool]]:
    """Checks for one E4 change, depending on whether it raised CPU or latency."""
    b, a = result.before.summary(), result.after.summary()
    checks = []
    for node_id, fields in change.items():
        old = next(n for n in result.before.nodes if n.id == node_id)
        if fields.get("cpu_cores", old.cpu_cores) > old.cpu_cores:
            on_node = [sum(d.node_id == node_id for d in r.decisions) for r in (result.before, result.after)]
            checks += [
                (f"{node_id} takes at least as many tasks ({on_node[0]} → {on_node[1]})", on_node[1] >= on_node[0]),
                (f"At least as many tasks on time ({b['on_time']} → {a['on_time']})", a["on_time"] >= b["on_time"]),
                (f"No more tasks rejected ({b['rejected']} → {a['rejected']})", a["rejected"] <= b["rejected"]),
            ]
        if fields.get("base_latency_ms", old.base_latency_ms) > old.base_latency_ms:
            avg = [_avg([d.latency_ms for d in r.decisions if d.node_id == node_id])
                   for r in (result.before, result.after)]
            low = [d for d in result.after.decisions if d.task.sensitivity == "low"]
            checks += [
                (f"Tasks on {node_id} are slower on average ({avg[0]:.0f} → {avg[1]:.0f} ms)", avg[1] > avg[0]),
                (f"Low-sensitivity tasks all still finish on time ({sum(d.outcome == 'on time' for d in low)} / "
                 f"{len(low)})", all(d.outcome == "on time" for d in low)),
                (f"No task runs late (late {b['late']} → {a['late']})", a["late"] == 0),
            ]
    return checks


def _before_after_rows(result) -> list[list[str]]:
    """Table rows for the E4 write-up: headline counts, latency and tasks per tier."""
    rows = []
    for row in result.diff():
        if row["metric"] in ("on_time", "late", "rejected", "offloaded", "avg_latency_ms", "p95_latency_ms"):
            fmt = (lambda v: "-" if v is None else f"{v:.1f}") if "latency" in row["metric"] else str
            rows.append([row["metric"].replace("_", " "), fmt(row["before"]), fmt(row["after"])])
    for tier in ("edge", "fog", "cloud"):
        rows.append([f"tasks on {tier}", *[str(sum(d.tier == tier for d in r.decisions))
                                            for r in (result.before, result.after)]])
    return rows


def _summary_markdown(results: list[RunResult]) -> list[str]:
    """A markdown table of headline numbers, one row per policy."""
    rows = []
    for r in results:
        m = r.summary()
        rows.append([r.label, m["on_time"], m["late"], m["rejected"], m["offloaded"], f"{m['success_rate']:.0%}",
                     "-" if m["avg_latency_ms"] is None else f"{m['avg_latency_ms']:.1f}",
                     "-" if m["p95_latency_ms"] is None else f"{m['p95_latency_ms']:.1f}"])
    return _markdown_table(["Policy", "On time", "Late", "Rejected", "Offloaded", "Success", "Avg ms", "P95 ms"], rows)


def _markdown_table(headers: list[str], rows: list[list[Any]]) -> list[str]:
    """Lines of a markdown table."""
    return ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers),
            *["| " + " | ".join(str(cell) for cell in row) + " |" for row in rows]]


def _tenant(settings: Settings, tenant_id: str) -> Tenant:
    """Find a tenant by id or raise ConfigError naming the experiments file."""
    tenant = settings.tenant(tenant_id)
    if tenant is None:
        raise ConfigError("experiments.json", "actor", f"unknown tenant '{tenant_id}'")
    return tenant


def _avg(values: list[float]) -> float:
    """Average, or 0 for an empty list."""
    return sum(values) / len(values) if values else 0.0


def summary_frame(run: ExperimentRun) -> pd.DataFrame:
    """One row per experiment: key, title, result and checks held (for the menu and app)."""
    return pd.DataFrame([{"experiment": f"{e.key} {e.title}", "result": "as expected" if e.passed else "differs",
                          "checks held": f"{sum(h for _, h in e.checks)} / {len(e.checks)}"} for e in run.experiments])
