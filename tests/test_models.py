from edgefogsim.models import Node


def test_default_nodes_one_per_tier_and_idle(settings):
    """AC1: exactly one edge, fog and cloud node, all at 0% utilisation."""
    assert sorted(n.tier for n in settings.nodes) == ["cloud", "edge", "fog"]
    assert all(n.cpu_util == 0 and n.memory_util == 0 for n in settings.nodes)


def test_node_free_capacity_and_utilisation():
    node = Node("edge-1", "edge", cpu_cores=4, memory_gb=8, base_latency_ms=5, speed_factor=0.6,
                cpu_used=3, memory_used=2)
    assert node.free_cpu == 1
    assert node.free_memory == 6
    assert node.cpu_util == 0.75
    assert node.memory_util == 0.25
