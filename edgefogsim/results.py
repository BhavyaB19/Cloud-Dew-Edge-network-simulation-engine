"""Results tables and files (F8): turn runs into pandas tables and save them as CSV and JSON.

Every export goes into its own folder under ``output.dir`` (default ``results/``),
named after the time and what was exported, e.g. ``results/20261102-153012-capacity/``.
Each folder also holds ``settings_used.json``, so any run can be repeated exactly
with ``--config results/<folder>/settings_used.json``.

Files written for one run:

- ``decisions.csv``: one row per task (node, VM, latency, deadline, outcome, reason)
- ``summary.json``: totals, success rate, latency, utilisation per node
- ``vms.csv``: every VM (owner, node, size, use, tasks, status)
- ``nodes.csv``: every node's reserved and used CPU/memory at the end

For a policy comparison: ``comparison.csv`` and ``comparison.json``, one row per policy.
For a before/after node change: ``before_after.csv`` (one row per metric) and both
runs' decisions (``decisions_before.csv``, ``decisions_after.csv``).
A tenant's export contains only their own decisions and VMs; totals stay cluster-wide.
"""

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from edgefogsim.config import Settings, save_settings
from edgefogsim.models import Tenant
from edgefogsim.security import visible
from edgefogsim.simulator import BeforeAfter, RunResult


def decisions_table(result: RunResult, viewer: Tenant | None = None) -> pd.DataFrame:
    """One row per placement decision.

    Args:
        result: The run.
        viewer: If given and not an admin, only their own tasks are included.

    Returns:
        A DataFrame with the columns of :meth:`RunResult.rows`.
    """
    rows = result.rows() if viewer is None else visible(viewer, result.rows(), lambda r: r["tenant"])
    return pd.DataFrame(rows, columns=list(result.rows()[0]) if result.decisions else None)


def summary_table(results: list[RunResult]) -> pd.DataFrame:
    """One row of headline QoS numbers per run, e.g. per policy in a comparison.

    Args:
        results: The runs to summarise.

    Returns:
        A DataFrame with ``policy`` plus every key of :meth:`RunResult.summary`.
    """
    return pd.DataFrame([{"policy": r.label, **r.summary()} for r in results])


def vms_table(result: RunResult, viewer: Tenant | None = None) -> pd.DataFrame:
    """One row per VM: owner, host, size, use, tasks and status.

    Args:
        result: The run whose cluster to describe.
        viewer: If given and not an admin, only their own VMs are included.
    """
    vms = result.vms.vms if viewer is None else visible(viewer, result.vms.vms)
    return pd.DataFrame([{
        "vm": vm.vm_id, "tenant": vm.tenant_id, "node": vm.node_id,
        "cpu_cores": vm.cpu_cores, "memory_gb": vm.memory_gb,
        "cpu_used": vm.cpu_load, "memory_used": vm.memory_load,
        "tasks": " ".join(vm.task_ids), "status": vm.status,
    } for vm in vms], columns=["vm", "tenant", "node", "cpu_cores", "memory_gb", "cpu_used", "memory_used",
                               "tasks", "status"])


def nodes_table(result: RunResult) -> pd.DataFrame:
    """One row per node: size, reserved and used capacity, and utilisation at the end of the run."""
    return pd.DataFrame([{
        "node": n.id, "tier": n.tier, "cpu_cores": n.cpu_cores, "memory_gb": n.memory_gb,
        "cpu_reserved": n.cpu_used, "memory_reserved": n.memory_used,
        "cpu_load": n.cpu_load, "memory_load": n.memory_load,
        "reserved_util": round(n.cpu_util, 4), "load_util": round(n.load_util, 4),
        "base_latency_ms": n.base_latency_ms, "speed_factor": n.speed_factor,
    } for n in result.nodes])


def new_export_dir(settings: Settings, label: str) -> Path:
    """Create a fresh, timestamped folder under ``output.dir`` for one export.

    Args:
        settings: Resolved settings; supplies ``output.dir``.
        label: Short name added to the folder, e.g. the policy key.

    Returns:
        The new folder, e.g. ``results/20261102-153012-capacity``. A ``-2``,
        ``-3``... suffix is added if that name already exists.
    """
    base = Path(settings.get("output.dir")) / f"{datetime.now():%Y%m%d-%H%M%S}-{label}"
    folder, n = base, 1
    while folder.exists():
        n += 1
        folder = base.with_name(f"{base.name}-{n}")
    folder.mkdir(parents=True)
    return folder


def export_run(result: RunResult, settings: Settings, folder: Path | str | None = None,
               viewer: Tenant | None = None) -> dict[str, Path]:
    """Save one run's decisions, summary, VMs, nodes and settings.

    Args:
        result: The run to save.
        settings: Resolved settings; saved alongside as ``settings_used.json``.
        folder: Where to write; defaults to a new folder from :func:`new_export_dir`.
        viewer: If given and not an admin, decisions and VMs are limited to theirs.

    Returns:
        File role -> path, for ``decisions``, ``summary``, ``vms``, ``nodes`` and ``settings``.
    """
    folder = Path(folder) if folder else new_export_dir(settings, result.policy)
    folder.mkdir(parents=True, exist_ok=True)
    paths = {
        "decisions": folder / "decisions.csv",
        "summary": folder / "summary.json",
        "vms": folder / "vms.csv",
        "nodes": folder / "nodes.csv",
        "settings": folder / "settings_used.json",
    }
    decisions_table(result, viewer).to_csv(paths["decisions"], index=False)
    summary = {"policy": result.policy, "label": result.label, "exported_at": datetime.now().isoformat(timespec="seconds"),
               "exported_by": viewer.tenant_id if viewer else None, **result.summary()}
    paths["summary"].write_text(json.dumps(summary, indent=2) + "\n")
    vms_table(result, viewer).to_csv(paths["vms"], index=False)
    nodes_table(result).to_csv(paths["nodes"], index=False)
    save_settings(settings, paths["settings"])
    return paths


def export_comparison(results: list[RunResult], settings: Settings,
                      folder: Path | str | None = None) -> dict[str, Path]:
    """Save a policy comparison: one row of headline numbers per policy.

    Args:
        results: One run per policy, on the same workload.
        settings: Resolved settings; saved alongside as ``settings_used.json``.
        folder: Where to write; defaults to a new ``...-comparison`` folder.

    Returns:
        File role -> path, for ``comparison_csv``, ``comparison_json`` and ``settings``.
    """
    folder = Path(folder) if folder else new_export_dir(settings, "comparison")
    folder.mkdir(parents=True, exist_ok=True)
    table = summary_table(results)
    paths = {
        "comparison_csv": folder / "comparison.csv",
        "comparison_json": folder / "comparison.json",
        "settings": folder / "settings_used.json",
    }
    table.to_csv(paths["comparison_csv"], index=False)
    table.to_json(paths["comparison_json"], orient="records", indent=2)
    save_settings(settings, paths["settings"])
    return paths


def export_before_after(comparison: BeforeAfter, settings: Settings,
                        folder: Path | str | None = None) -> dict[str, Path]:
    """Save a before/after node change: the metric diff and both runs' decisions.

    Args:
        comparison: The two runs and the change.
        settings: Settings *before* the change; saved as ``settings_used.json``.
        folder: Where to write; defaults to a new ``...-before-after`` folder.

    Returns:
        File role -> path, for ``diff``, ``decisions_before``, ``decisions_after`` and ``settings``.
    """
    folder = Path(folder) if folder else new_export_dir(settings, "before-after")
    folder.mkdir(parents=True, exist_ok=True)
    paths = {
        "diff": folder / "before_after.csv",
        "decisions_before": folder / "decisions_before.csv",
        "decisions_after": folder / "decisions_after.csv",
        "settings": folder / "settings_used.json",
    }
    frame = pd.DataFrame(comparison.diff())
    frame.insert(0, "change_made", comparison.change)
    frame.to_csv(paths["diff"], index=False)
    decisions_table(comparison.before).to_csv(paths["decisions_before"], index=False)
    decisions_table(comparison.after).to_csv(paths["decisions_after"], index=False)
    save_settings(settings, paths["settings"])
    return paths
