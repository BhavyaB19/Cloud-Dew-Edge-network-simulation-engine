"""Latency and deadline model (F5): how long a task would take on a node, and whether that is in time.

The model, from docs/SPEC.md §3::

    processing_ms = work_units / speed_factor
    congestion    = 1 / (1 - min(cpu_load_after_placement, congestion_cap))
    latency_ms    = base_latency_ms + processing_ms * congestion

Load is the CPU used by running tasks (not what VMs have reserved), so an idle
VM doesn't slow a node down. The congestion factor is a simple queueing
(M/M/1-style) approximation: 1 on an idle node, 2 at half load, 10 at 90% load.
Busy nodes therefore get slow fast, like a queue at a counter. ``congestion_cap`` (default 0.95) stops it reaching
infinity on a completely full node.
"""

from edgefogsim.config import Settings
from edgefogsim.models import Node, Task


def deadline_ms(task: Task, settings: Settings) -> float:
    """The longest delay a task accepts, from ``qos.deadlines_ms`` for its sensitivity.

    Args:
        task: The task.
        settings: Resolved settings.

    Returns:
        The deadline in milliseconds.
    """
    return settings.simulation["qos"]["deadlines_ms"][task.sensitivity]


def utilisation_after(task: Task, node: Node) -> float:
    """CPU load the node would have if the task ran on it.

    Args:
        task: The task to place.
        node: The candidate node, with its current load.

    Returns:
        Fraction of the node's CPU used by tasks after placement (may exceed
        1.0 for a task that could never fit).
    """
    return (node.cpu_load + task.cpu_cores) / node.cpu_cores


def estimate_latency_ms(task: Task, node: Node, settings: Settings) -> float:
    """Simulated latency of a task on a node, counting the task's own load.

    Args:
        task: The task to place.
        node: The candidate node, with its current load (before placement).
        settings: Resolved settings; reads ``qos.congestion_cap``.

    Returns:
        Network delay plus processing time stretched by congestion, in milliseconds.
    """
    cap = settings.simulation["qos"]["congestion_cap"]
    util = min(utilisation_after(task, node), cap)
    processing_ms = task.work_units / node.speed_factor
    return node.base_latency_ms + processing_ms / (1 - util)
