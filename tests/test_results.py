"""Results tables and exported files (AC13)."""

import json

import pandas as pd

from edgefogsim.models import Tenant
from edgefogsim.results import export_before_after, export_comparison, export_run, new_export_dir, summary_table
from edgefogsim.simulator import compare_before_after, compare_policies, run_workload
from edgefogsim.workload import generate_tasks, load_tasks
from tests.conftest import ROOT


def sample_run(settings):
    """Capacity-Aware on the 10 sample tasks."""
    return run_workload(settings, load_tasks(ROOT / "examples" / "tasks_sample.csv", settings), "capacity")


def test_exported_counts_add_up(settings, tmp_path):
    """AC13: placed + rejected = total; on time + late = placed; decisions.csv has one row per task."""
    paths = export_run(sample_run(settings), settings, tmp_path / "run")
    summary = json.loads(paths["summary"].read_text())
    assert summary["placed"] + summary["rejected"] == summary["total"] == 10
    assert summary["on_time"] + summary["late"] == summary["placed"]
    decisions = pd.read_csv(paths["decisions"])
    assert len(decisions) == summary["total"]
    assert (decisions["outcome"] == "rejected").sum() == summary["rejected"]


def test_export_writes_every_file_and_reusable_settings(settings, tmp_path):
    """A run export holds decisions, summary, VMs, nodes and a settings file that loads with --config."""
    from edgefogsim.config import load_settings

    paths = export_run(sample_run(settings), settings, tmp_path / "run")
    assert all(p.exists() and p.stat().st_size > 0 for p in paths.values())
    nodes = pd.read_csv(paths["nodes"])
    assert list(nodes["node"]) == ["edge-1", "fog-1", "cloud-1"]
    assert (nodes["cpu_load"] <= nodes["cpu_reserved"]).all()
    assert load_settings(config_file=paths["settings"]).simulation == settings.simulation


def test_tenant_export_contains_only_their_rows(settings, tmp_path):
    """A tenant's export lists only their decisions and VMs; the summary stays cluster-wide."""
    paths = export_run(sample_run(settings), settings, tmp_path / "run", viewer=Tenant("hospital-a", "tenant"))
    assert set(pd.read_csv(paths["decisions"])["tenant"]) == {"hospital-a"}
    assert set(pd.read_csv(paths["vms"])["tenant"]) == {"hospital-a"}
    assert json.loads(paths["summary"].read_text())["total"] == 10


def test_comparison_export_has_one_row_per_policy(settings, tmp_path):
    """comparison.csv and comparison.json have one row per policy."""
    results = compare_policies(settings, generate_tasks(settings))
    paths = export_comparison(results, settings, tmp_path / "cmp")
    assert list(pd.read_csv(paths["comparison_csv"])["policy"]) == [r.label for r in results]
    assert len(json.loads(paths["comparison_json"].read_text())) == 4
    assert list(summary_table(results)["policy"]) == ["Latency-First", "Cloud-Only", "Capacity-Aware", "TOPSIS"]


def test_before_after_export(settings, tmp_path):
    """A before/after export holds the metric diff and both runs' decisions."""
    result = compare_before_after(settings, generate_tasks(settings), "capacity", {"cloud-1": {"base_latency_ms": 150}})
    paths = export_before_after(result, settings, tmp_path / "ba")
    diff = pd.read_csv(paths["diff"])
    assert set(diff["change_made"]) == {"cloud-1 base_latency_ms 80 → 150"}
    assert "on_time" in set(diff["metric"])
    assert len(pd.read_csv(paths["decisions_before"])) == len(pd.read_csv(paths["decisions_after"])) == 12


def test_export_folders_are_unique(settings):
    """Two exports in the same second get different folders under output.dir."""
    first, second = new_export_dir(settings, "x"), new_export_dir(settings, "x")
    assert first != second and first.parent == second.parent
    assert first.parent.name == "results"
