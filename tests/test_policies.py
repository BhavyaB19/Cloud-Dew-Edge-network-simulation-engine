"""Placement policies and the latency model (AC4-8, AC20-23)."""

import math

import pytest

from edgefogsim.config import load_settings
from edgefogsim.models import Node, Task
from edgefogsim.policies import CapacityAware, Topsis, make_policy, topsis_closeness
from edgefogsim.qos import estimate_latency_ms
from edgefogsim.simulator import fresh_nodes, run_workload


def task(sensitivity="high", cpu=2, memory=1, work=4, task_id="T01"):
    """Build a task for hospital-a with the given needs."""
    return Task(task_id, "hospital-a", cpu, memory, sensitivity, work)


def node_by_id(nodes, node_id):
    """Find a node in a list by its id."""
    return next(n for n in nodes if n.id == node_id)


def test_high_task_on_empty_cluster_goes_to_edge(settings):
    """AC4: a high-sensitivity task on empty nodes lands on edge."""
    choice = CapacityAware(settings).choose(task("high"), fresh_nodes(settings))
    assert choice.node.id == "edge-1"
    assert not choice.offloaded


def test_low_task_goes_to_cloud(settings):
    """AC5: a low-sensitivity task lands on cloud."""
    choice = CapacityAware(settings).choose(task("low", work=40), fresh_nodes(settings))
    assert choice.node.id == "cloud-1"


def test_busy_edge_offloads_high_task_to_fog(settings):
    """AC6: with edge at 90% CPU, a high task is offloaded to fog and the reason names edge."""
    nodes = fresh_nodes(settings)
    node_by_id(nodes, "edge-1").cpu_used = 3.6
    choice = CapacityAware(settings).choose(task("high", cpu=1, work=2), nodes)
    assert choice.node.id == "fog-1"
    assert choice.offloaded
    assert "edge-1 not enough CPU for a new VM (needs 2, 0.4 unreserved)" in choice.reason


@pytest.mark.parametrize("policy", ["latency", "cloud", "capacity", "topsis"])
def test_oversized_task_is_rejected_without_allocating(settings, policy):
    """AC7: a task bigger than any free capacity is rejected and no node changes."""
    result = run_workload(settings, [task("low", cpu=500, memory=1)], policy)
    decision = result.decisions[0]
    assert decision.outcome == "rejected" and decision.node_id is None
    assert all(n.cpu_used == 0 and n.memory_used == 0 for n in result.nodes)
    assert "not enough CPU" in decision.reason or "no node" in decision.reason


def test_latency_rises_with_utilisation(settings):
    """AC8: the same task is strictly slower on a busier node."""
    quiet, busy = fresh_nodes(settings)[1], fresh_nodes(settings)[1]
    busy.cpu_used = busy.cpu_load = 8
    t = task("medium", work=10)
    assert estimate_latency_ms(t, busy, settings) > estimate_latency_ms(t, quiet, settings)


def test_latency_formula_matches_spec(settings):
    """latency = base + (work / speed) / (1 - util_after), checked by hand for edge-1."""
    edge = fresh_nodes(settings)[0]
    # util after = 2/4 = 0.5 -> congestion 2; processing 4 / 0.6 = 6.67 ms -> 5 + 13.33 = 18.33 ms
    assert estimate_latency_ms(task(cpu=2, work=4), edge, settings) == pytest.approx(5 + (4 / 0.6) * 2)


def test_explainer_worked_examples(settings):
    """The four worked examples in the explainer doc and spec: place, offload, cloud, reject."""
    tasks = [task("high", 2, 1, 4, "T01"), task("high", 2, 1, 4, "T02"),
             task("low", 8, 16, 40, "T03"), task("high", 20, 8, 4, "T04")]
    d = run_workload(settings, tasks, "capacity").decisions
    assert (d[0].node_id, round(d[0].latency_ms, 1)) == ("edge-1", 18.3)
    assert (d[1].node_id, d[1].offloaded, round(d[1].latency_ms, 1)) == ("fog-1", True, 24.6)
    assert (d[2].node_id, round(d[2].latency_ms, 1)) == ("cloud-1", 101.3)
    assert d[3].outcome == "rejected"


def test_latency_first_overloads_edge(settings):
    """The baseline keeps using the nearest node even when it makes tasks late."""
    d = run_workload(settings, [task(task_id="T01"), task(task_id="T02")], "latency").decisions
    assert [x.node_id for x in d] == ["edge-1", "edge-1"]
    assert d[1].outcome == "late"


def test_cloud_only_puts_everything_on_cloud_and_misses_high_deadlines(settings):
    """AC20: Cloud-Only places every fitting task on cloud; high tasks miss the 25 ms deadline."""
    tasks = [task("high", task_id="T01"), task("medium", work=10, task_id="T02"), task("low", task_id="T03")]
    d = run_workload(settings, tasks, "cloud").decisions
    assert {x.node_id for x in d} == {"cloud-1"}
    assert d[0].outcome == "late"


def test_capacity_aware_prefers_freer_node_in_same_tier(write_json):
    """AC21: with two feasible edge nodes, the one with more free capacity wins and both scores are shown."""
    settings = load_settings(nodes_file=write_json("two_edges.json", [
        {"id": "edge-a", "tier": "edge", "cpu_cores": 4, "memory_gb": 8, "base_latency_ms": 5, "speed_factor": 0.6},
        {"id": "edge-b", "tier": "edge", "cpu_cores": 4, "memory_gb": 8, "base_latency_ms": 5, "speed_factor": 0.6},
    ]))
    nodes = fresh_nodes(settings)
    edge_a = node_by_id(nodes, "edge-a")
    edge_a.cpu_used = edge_a.cpu_load = 1
    choice = CapacityAware(settings).choose(task("high", cpu=1, work=2), nodes)
    assert choice.node.id == "edge-b"
    assert "edge-a" in choice.reason and "edge-b" in choice.reason
    assert choice.scores["edge-b"] > choice.scores["edge-a"]


def test_topsis_closeness_matches_hand_calculation():
    """AC22: TOPSIS closeness for a 3-node matrix equals a step-by-step hand calculation."""
    rows = [(10.0, 0.5, 0.5), (20.0, 0.9, 0.8), (30.0, 0.2, 0.9)]
    weights = (0.5, 0.3, 0.2)
    # Hand calculation: normalise columns by their vector length, weight, find ideal/anti-ideal.
    norm = [math.sqrt(10**2 + 20**2 + 30**2), math.sqrt(.5**2 + .9**2 + .2**2), math.sqrt(.5**2 + .8**2 + .9**2)]
    v = [[r[j] / norm[j] * weights[j] for j in range(3)] for r in rows]
    ideal = [v[0][0], v[1][1], v[2][2]]   # lowest latency, highest CPU, highest memory
    anti = [v[2][0], v[2][1], v[0][2]]    # highest latency, lowest CPU, lowest memory
    expected = []
    for row in v:
        d_best = math.dist(row, ideal)
        d_worst = math.dist(row, anti)
        expected.append(d_worst / (d_best + d_worst))
    result = topsis_closeness(rows, weights, benefit=(False, True, True))
    assert [round(x, 3) for x in result] == [round(x, 3) for x in expected] == [0.684, 0.646, 0.155]


def test_topsis_identical_options_all_score_one():
    """When every option is identical, TOPSIS gives each a closeness of 1."""
    assert topsis_closeness([(1.0, 1.0), (1.0, 1.0)], (0.5, 0.5), (False, True)) == [1.0, 1.0]


def test_topsis_respects_deadline(settings):
    """TOPSIS never picks a node that would miss the deadline."""
    choice = Topsis(settings).choose(task("high", cpu=1, work=2), fresh_nodes(settings))
    assert choice.node.id in {"edge-1", "fog-1"}
    assert "cloud-1 too slow" in choice.reason


def test_weights_in_config_change_the_choice():
    """AC23: changing capacity_weights in settings changes the pick, with no code change."""
    t = task("medium", cpu=1, work=5)
    default = load_settings()
    by_tier = CapacityAware(default).choose(t, fresh_nodes(default))
    free_only = load_settings(overrides={
        "policy.capacity_weights.tier": 0, "policy.capacity_weights.slack": 0, "policy.capacity_weights.free": 1})
    by_free = CapacityAware(free_only).choose(t, fresh_nodes(free_only))
    assert by_tier.node.id == "fog-1"
    assert by_free.node.id == "cloud-1"


def test_topsis_weights_change_the_choice():
    """AC23: TOPSIS weights from settings change its pick, with no code change."""
    t = task("medium", cpu=1, work=5)
    latency_heavy = load_settings(overrides={"policy.topsis_weights.latency": 1, "policy.topsis_weights.cpu": 0,
                                             "policy.topsis_weights.memory": 0})
    cpu_heavy = load_settings(overrides={"policy.topsis_weights.latency": 0, "policy.topsis_weights.cpu": 1,
                                         "policy.topsis_weights.memory": 0})
    assert Topsis(latency_heavy).choose(t, fresh_nodes(latency_heavy)).node.id == "edge-1"
    assert Topsis(cpu_heavy).choose(t, fresh_nodes(cpu_heavy)).node.id == "cloud-1"


def test_soft_overload_retry_uses_full_node(write_json):
    """When nothing stays under the headroom, Capacity-Aware retries allowing up to 100%."""
    settings = load_settings(nodes_file=write_json("one_edge.json", [
        {"id": "edge-1", "tier": "edge", "cpu_cores": 4, "memory_gb": 8, "base_latency_ms": 1, "speed_factor": 10},
    ]))
    choice = CapacityAware(settings).choose(task("high", cpu=4, work=1), fresh_nodes(settings))
    assert choice.node.id == "edge-1"
    assert choice.reason.startswith("soft overload")


def test_soft_overload_retry_can_be_turned_off(write_json):
    """With soft_overload_retry false, the same task is rejected."""
    settings = load_settings(
        nodes_file=write_json("one_edge.json", [
            {"id": "edge-1", "tier": "edge", "cpu_cores": 4, "memory_gb": 8, "base_latency_ms": 1, "speed_factor": 10},
        ]),
        overrides={"policy.soft_overload_retry": False},
    )
    assert CapacityAware(settings).choose(task("high", cpu=4, work=1), fresh_nodes(settings)).node is None


def test_missing_fog_tier_is_skipped(write_json):
    """AC18 (placement part): with no fog node, a busy edge offloads a high task straight to the next tier."""
    settings = load_settings(nodes_file=write_json("no_fog.json", [
        {"id": "edge-1", "tier": "edge", "cpu_cores": 4, "memory_gb": 8, "base_latency_ms": 5, "speed_factor": 0.6},
        {"id": "cloud-1", "tier": "cloud", "cpu_cores": 64, "memory_gb": 64, "base_latency_ms": 10,
         "speed_factor": 2},
    ]))
    nodes = fresh_nodes(settings)
    node_by_id(nodes, "edge-1").cpu_used = 4
    choice = CapacityAware(settings).choose(task("high", cpu=1, work=2), nodes)
    assert choice.node.id == "cloud-1" and choice.offloaded


def test_unknown_and_future_policies_raise(settings):
    """Unknown keys and the not-yet-built Q-learning policy give clear errors."""
    with pytest.raises(ValueError, match="unknown policy"):
        make_policy("random", settings)
    with pytest.raises(ValueError, match="Phase 7"):
        make_policy("qlearn", settings)


def test_node_never_over_allocated(settings):
    """Across a large workload, no policy ever allocates more than a node's capacity."""
    from edgefogsim.workload import generate_tasks

    tasks = generate_tasks(settings, count=200, seed=3)
    for key in ("latency", "cloud", "capacity", "topsis"):
        for n in run_workload(settings, tasks, key).nodes:
            assert n.cpu_used <= n.cpu_cores + 1e-9 and n.memory_used <= n.memory_gb + 1e-9
            assert n.cpu_load <= n.cpu_used + 1e-9 and n.memory_load <= n.memory_used + 1e-9


def test_choosing_does_not_change_nodes(settings):
    """Policies only decide; choosing never changes node usage."""
    nodes = fresh_nodes(settings)
    for key in ("latency", "cloud", "capacity", "topsis"):
        make_policy(key, settings).choose(task(), nodes)
    assert all(isinstance(n, Node) and n.cpu_used == 0 for n in nodes)
