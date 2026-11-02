"""Simulator loop: running workloads, outcomes, summaries and policy comparison."""

from edgefogsim.models import Task
from edgefogsim.simulator import compare_policies, fresh_nodes, run_workload
from edgefogsim.workload import generate_tasks


def test_run_never_changes_configured_nodes(settings):
    """Runs use fresh copies, so the settings' nodes stay empty and runs are comparable."""
    run_workload(settings, generate_tasks(settings), "latency")
    assert all(n.cpu_used == 0 for n in settings.nodes)


def test_placed_task_keeps_its_resources(settings):
    """A placed task's VM stays reserved (edge default 2 CPU / 4 GB) and its own needs count as load."""
    tasks = [Task("T01", "hospital-a", 2, 1.5, "high", 4)]
    result = run_workload(settings, tasks, "capacity")
    edge = next(n for n in result.nodes if n.id == "edge-1")
    assert (edge.cpu_used, edge.memory_used) == (2, 4)
    assert (edge.cpu_load, edge.memory_load) == (2, 1.5)


def test_summary_counts_add_up(settings):
    """AC13 (counts): on time + late + rejected = total, and placed = on time + late."""
    result = run_workload(settings, generate_tasks(settings, count=30), "latency")
    m = result.summary()
    assert m["on_time"] + m["late"] + m["rejected"] == m["total"] == 30
    assert m["placed"] == m["on_time"] + m["late"]
    assert m["success_rate"] == m["on_time"] / 30
    assert m["p95_latency_ms"] >= m["avg_latency_ms"] > 0


def test_summary_with_nothing_placed(settings):
    """A run where every task is rejected reports no latency instead of crashing."""
    result = run_workload(settings, [Task("T01", "hospital-a", 999, 1, "low", 1)], "capacity")
    m = result.summary()
    assert (m["placed"], m["avg_latency_ms"], m["p95_latency_ms"]) == (0, None, None)


def test_rows_have_one_entry_per_task(settings):
    """Decision rows (for tables and CSV export) mirror the decisions."""
    tasks = generate_tasks(settings, count=5)
    result = run_workload(settings, tasks, "topsis")
    rows = result.rows()
    assert [r["task"] for r in rows] == [t.id for t in tasks]
    assert {"node", "latency_ms", "outcome", "reason"} <= set(rows[0])
    assert result.tasks == tasks


def test_smart_policies_beat_baselines_on_default_workload(settings):
    """On a mixed 20-task workload, Capacity-Aware and TOPSIS have more tasks on time and none late."""
    results = {r.policy: r.summary() for r in compare_policies(settings, generate_tasks(settings, count=20))}
    for smart in ("capacity", "topsis"):
        assert results[smart]["late"] == 0
        for baseline in ("latency", "cloud"):
            assert results[smart]["on_time"] > results[baseline]["on_time"]


def test_compare_uses_fresh_nodes_per_policy(settings):
    """Each policy in a comparison starts from empty nodes."""
    tasks = generate_tasks(settings, count=10)
    alone = run_workload(settings, tasks, "topsis").summary()
    together = {r.policy: r.summary() for r in compare_policies(settings, tasks)}["topsis"]
    assert alone == together


def test_preloaded_nodes_are_respected(settings):
    """A run can start from pre-loaded nodes (used by the overload experiment)."""
    nodes = fresh_nodes(settings)
    nodes[0].cpu_used = 3.6
    result = run_workload(settings, [Task("T01", "hospital-a", 1, 1, "high", 2)], "capacity", nodes=nodes)
    assert result.decisions[0].node_id == "fog-1" and result.decisions[0].offloaded
