"""Placement policies (F3, F4): given a task and the nodes, pick a node or reject.

Every policy implements the same interface, ``choose(task, cluster) -> Choice``,
so the simulator, results and experiments treat them all alike. "Fits" means
the cluster's VM manager can host the task on the node: in one of its tenant's
VMs with room, or in a new VM on unreserved capacity. A ``Choice``
always carries a plain-language reason, including why other nodes were ruled
out, so every decision can be explained in the demo and the viva.

Policies (see docs/SPEC.md §3 for the full rules and the research behind them):

- ``latency``  Latency-First: nearest node with room. Baseline.
- ``cloud``    Cloud-Only: everything to the cloud. Baseline.
- ``capacity`` Capacity-Aware: filter, then score. The required rule-based algorithm.
- ``topsis``   TOPSIS: multi-criteria ranking.

Policies only decide. They never change node usage or VMs; the simulator does that.
"""

import math
from dataclasses import dataclass, field

from edgefogsim.config import Settings
from edgefogsim.models import Node, Task
from edgefogsim.qos import deadline_ms, estimate_latency_ms, utilisation_after
from edgefogsim.vm_manager import VMManager


@dataclass(frozen=True)
class Choice:
    """A policy's decision for one task.

    Attributes:
        node: The chosen node, or None if the task is rejected.
        reason: Why, in plain words, including why other nodes were ruled out.
        offloaded: True if the node is not in the task's first-preference tier.
        scores: Node id -> score or closeness, for policies that rank nodes.
    """

    node: Node | None
    reason: str
    offloaded: bool = False
    scores: dict[str, float] = field(default_factory=dict)


class Policy:
    """Base class for placement policies.

    Subclasses set ``key``, ``label`` and ``summary`` and implement :meth:`_choose`.

    Attributes:
        key: Short name used on the command line, e.g. ``"capacity"``.
        label: Display name, e.g. ``"Capacity-Aware"``.
        summary: One-line description of the rule.
        settings: Resolved settings (deadlines, headroom, weights, tier preference, VM sizes).
        cluster: The VM manager of the decision in progress; answers whether a node can host a task.
    """

    key = ""
    label = ""
    summary = ""

    def __init__(self, settings: Settings):
        """Create the policy.

        Args:
            settings: Resolved settings; read on every decision, so edits apply immediately.
        """
        self.settings = settings
        self.cluster = VMManager([], vm_sizes(settings))

    def choose(self, task: Task, cluster: VMManager | list[Node]) -> Choice:
        """Pick a node for ``task`` or reject it.

        Args:
            task: The task to place.
            cluster: The cluster's VM manager, with current VMs and usage; or a
                plain list of nodes, treated as a cluster with no VMs yet.
                Nothing is modified.

        Returns:
            The decision and its reason.
        """
        if not isinstance(cluster, VMManager):
            cluster = VMManager(cluster, vm_sizes(self.settings))
        self.cluster = cluster
        return self._choose(task, cluster.nodes)

    def _choose(self, task: Task, nodes: list[Node]) -> Choice:
        """The policy's rule; ``self.cluster`` is the cluster being decided on."""
        raise NotImplementedError

    def preferred_tiers(self, task: Task, nodes: list[Node]) -> list[str]:
        """The task's tier preference order, keeping only tiers that have nodes.

        Args:
            task: The task; its sensitivity selects the order from ``policy.tier_preference``.
            nodes: All nodes; tiers with no node are dropped.

        Returns:
            Tier names, most preferred first.
        """
        present = {n.tier for n in nodes}
        order = self.settings.simulation["policy"]["tier_preference"][task.sensitivity]
        return [tier for tier in order if tier in present]

    def is_offload(self, task: Task, node: Node, nodes: list[Node]) -> bool:
        """True if ``node`` is not in the task's first available preferred tier."""
        tiers = self.preferred_tiers(task, nodes)
        return bool(tiers) and node.tier != tiers[0]

    def why_not(self, task: Task, node: Node, headroom: float | None = None,
                check_deadline: bool = True) -> str | None:
        """Explain why a node can't take a task, or return None if it can.

        Args:
            task: The task to place.
            node: The candidate node.
            headroom: Maximum CPU utilisation allowed after placement, or None for no limit.
            check_deadline: Whether the estimated latency must meet the deadline.

        Returns:
            A short reason such as ``"edge-1 would be 100% busy (limit 85%)"``, or None.
        """
        problem = self.cluster.why_cannot_host(task, node)
        if problem:
            return problem
        util = utilisation_after(task, node)
        if headroom is not None and util > headroom + 1e-9:
            return f"{node.id} would be {util:.0%} busy (limit {headroom:.0%})"
        if check_deadline:
            latency, limit = estimate_latency_ms(task, node, self.settings), deadline_ms(task, self.settings)
            if latency > limit:
                return f"{node.id} too slow (est. {latency:.1f} ms > {limit:g} ms deadline)"
        return None

    def placed_reason(self, task: Task, node: Node) -> str:
        """Describe the estimated latency against the deadline for a placement."""
        latency, limit = estimate_latency_ms(task, node, self.settings), deadline_ms(task, self.settings)
        verdict = "≤" if latency <= limit else ">"
        return f"est. {latency:.1f} ms {verdict} {limit:g} ms deadline"


class LatencyFirst(Policy):
    """Baseline: the nearest node (lowest network latency) that has room.

    Ignores sensitivity, utilisation and deadlines, so it fills Edge first even
    with tasks that could have gone to the Cloud.
    """

    key = "latency"
    label = "Latency-First"
    summary = "Nearest node with enough free CPU and memory."

    def _choose(self, task: Task, nodes: list[Node]) -> Choice:
        """Try nodes from lowest to highest base latency; take the first that can host the task."""
        skipped = []
        for node in sorted(nodes, key=lambda n: (n.base_latency_ms, n.id)):
            problem = self.why_not(task, node, check_deadline=False)
            if problem is None:
                note = f"; skipped: {'; '.join(skipped)}" if skipped else ""
                return Choice(node, f"nearest node with room ({node.base_latency_ms:g} ms away); "
                                    f"{self.placed_reason(task, node)}{note}")
            skipped.append(problem)
        return Choice(None, f"no node has room: {'; '.join(skipped)}")


class CloudOnly(Policy):
    """Baseline: every task goes to the cloud node with the most free CPU.

    Shows what happens without Edge and Fog: urgent tasks miss their deadlines
    because of the cloud's network delay.
    """

    key = "cloud"
    label = "Cloud-Only"
    summary = "Every task to the least-loaded cloud node."

    def _choose(self, task: Task, nodes: list[Node]) -> Choice:
        """Pick the least-loaded cloud node that can host the task, or reject."""
        clouds = [n for n in nodes if n.tier == "cloud"]
        if not clouds:
            return Choice(None, "there is no cloud node")
        fitting = [n for n in clouds if self.cluster.why_cannot_host(task, n) is None]
        if not fitting:
            problems = [self.why_not(task, n, check_deadline=False) for n in clouds]
            return Choice(None, f"no cloud node has room: {'; '.join(problems)}")
        node = min(fitting, key=lambda n: (n.load_util, n.id))
        return Choice(node, f"cloud only: {node.id} is the least-loaded cloud node; {self.placed_reason(task, node)}",
                      offloaded=self.is_offload(task, node, nodes))


class CapacityAware(Policy):
    """The required rule-based algorithm: filter out unsuitable nodes, score the rest.

    Rules (docs/SPEC.md §3, Policy C):

    1. Tier preference by sensitivity (``policy.tier_preference``).
    2. Capacity filter: enough free CPU and memory, and utilisation after
       placement <= ``policy.headroom``.
    3. Deadline filter: estimated latency <= the task's deadline.
    4. Score = w_tier * tier_rank + w_slack * deadline_slack + w_free * free_after
       (weights from ``policy.capacity_weights``).
    5. Highest score wins; ties go to lower latency, then node id.
    6. If nothing passes and ``policy.soft_overload_retry`` is on, retry once
       with headroom 100%.
    7. Still nothing: reject, listing why each node failed.
    """

    key = "capacity"
    label = "Capacity-Aware"
    summary = "Rule out nodes without room or too slow, then score tier preference, deadline slack and free capacity."

    def _choose(self, task: Task, nodes: list[Node]) -> Choice:
        """Apply the filters and scoring; retry once without headroom if allowed."""
        policy = self.settings.simulation["policy"]
        choice = self._choose_with(task, nodes, policy["headroom"])
        if choice.node is None and policy["soft_overload_retry"] and policy["headroom"] < 1:
            retry = self._choose_with(task, nodes, 1.0)
            if retry.node is not None:
                note = f"soft overload: no node stays under {policy['headroom']:.0%}, so up to 100% allowed; "
                return Choice(retry.node, note + retry.reason, retry.offloaded, retry.scores)
        return choice

    def _choose_with(self, task: Task, nodes: list[Node], headroom: float) -> Choice:
        """One pass of filter-and-score with the given headroom."""
        tiers = self.preferred_tiers(task, nodes)
        weights = self.settings.simulation["policy"]["capacity_weights"]
        limit = deadline_ms(task, self.settings)
        scores, latencies, problems = {}, {}, []
        for node in nodes:
            if node.tier not in tiers:
                problems.append(f"{node.id} tier '{node.tier}' not allowed for {task.sensitivity} tasks")
                continue
            problem = self.why_not(task, node, headroom=headroom)
            if problem:
                problems.append(problem)
                continue
            latency = estimate_latency_ms(task, node, self.settings)
            tier_rank = 1.0 if len(tiers) == 1 else 1 - tiers.index(node.tier) / (len(tiers) - 1)
            slack = (limit - latency) / limit
            free_after = 1 - utilisation_after(task, node)
            scores[node.id] = (weights["tier"] * tier_rank + weights["slack"] * slack
                               + weights["free"] * free_after)
            latencies[node.id] = latency
        if not scores:
            return Choice(None, f"no node passes: {'; '.join(problems)}")

        best_id = min(scores, key=lambda nid: (-round(scores[nid], 9), latencies[nid], nid))
        node = next(n for n in nodes if n.id == best_id)
        offloaded = self.is_offload(task, node, nodes)
        ranking = ", ".join(f"{nid} {s:.2f}" for nid, s in sorted(scores.items(), key=lambda kv: -kv[1]))
        reason = (f"best score on {node.id} ({node.tier}, preference {tiers.index(node.tier) + 1} of {len(tiers)}); "
                  f"{self.placed_reason(task, node)}; scores: {ranking}")
        if offloaded:
            first = [p for p in problems if any(p.startswith(n.id) for n in nodes if n.tier == tiers[0])]
            reason = f"offloaded to {node.tier}: " + ("; ".join(first) + "; " if first else "") + reason
        return Choice(node, reason, offloaded, scores)


class Topsis(Policy):
    """Multi-criteria ranking with TOPSIS.

    Among nodes that fit and meet the deadline, rank by closeness to an ideal
    node on three criteria: estimated latency (lower is better), CPU free after
    placement and memory free after placement (higher is better), weighted by
    ``policy.topsis_weights``. No headroom limit.
    """

    key = "topsis"
    label = "TOPSIS"
    summary = "Rank feasible nodes by closeness to the ideal on latency, free CPU and free memory."

    def _choose(self, task: Task, nodes: list[Node]) -> Choice:
        """Filter by capacity and deadline, then pick the highest TOPSIS closeness."""
        feasible, problems = [], []
        for node in nodes:
            problem = self.why_not(task, node)
            if problem:
                problems.append(problem)
            else:
                feasible.append(node)
        if not feasible:
            return Choice(None, f"no node fits and meets the deadline: {'; '.join(problems)}")

        rows = [self.criteria(task, n) for n in feasible]
        closeness = topsis_closeness(rows, self.weight_vector(), benefit=(False, True, True))
        scores = {n.id: c for n, c in zip(feasible, closeness)}
        latency = {n.id: r[0] for n, r in zip(feasible, rows)}
        best_id = min(scores, key=lambda nid: (-round(scores[nid], 9), latency[nid], nid))
        node = next(n for n in feasible if n.id == best_id)
        ranking = ", ".join(f"{nid} {c:.2f}" for nid, c in sorted(scores.items(), key=lambda kv: -kv[1]))
        reason = f"closest to ideal: {node.id}; {self.placed_reason(task, node)}; closeness: {ranking}"
        if problems:
            reason += f"; ruled out: {'; '.join(problems)}"
        return Choice(node, reason, self.is_offload(task, node, nodes), scores)

    def criteria(self, task: Task, node: Node) -> tuple[float, float, float]:
        """The decision-matrix row for a node: (latency ms, CPU free after, memory free after) as load fractions."""
        return (
            estimate_latency_ms(task, node, self.settings),
            1 - utilisation_after(task, node),
            1 - (node.memory_load + task.memory_gb) / node.memory_gb,
        )

    def weight_vector(self) -> tuple[float, float, float]:
        """Weights in criteria order: latency, CPU, memory."""
        w = self.settings.simulation["policy"]["topsis_weights"]
        return (w["latency"], w["cpu"], w["memory"])


def topsis_closeness(rows: list[tuple[float, ...]], weights: tuple[float, ...],
                     benefit: tuple[bool, ...]) -> list[float]:
    """Compute TOPSIS closeness for each option.

    Steps: vector-normalise each column, multiply by its weight, find the ideal
    (best per column) and anti-ideal (worst per column), then
    closeness = distance to anti-ideal / (distance to ideal + distance to anti-ideal).

    Args:
        rows: One row per option, one value per criterion.
        weights: Weight per criterion.
        benefit: Per criterion, True if higher is better, False if lower is better.

    Returns:
        Closeness per option, from 0 (worst) to 1 (best). If all options are
        identical, every option gets 1.0.
    """
    columns = list(zip(*rows))
    norms = [math.sqrt(sum(v * v for v in col)) for col in columns]
    weighted = [[(v / norms[j] if norms[j] else 0.0) * weights[j] for j, v in enumerate(row)] for row in rows]
    cols = list(zip(*weighted))
    ideal = [max(c) if benefit[j] else min(c) for j, c in enumerate(cols)]
    anti = [min(c) if benefit[j] else max(c) for j, c in enumerate(cols)]
    result = []
    for row in weighted:
        d_best = math.sqrt(sum((v - ideal[j]) ** 2 for j, v in enumerate(row)))
        d_worst = math.sqrt(sum((v - anti[j]) ** 2 for j, v in enumerate(row)))
        result.append(1.0 if d_best + d_worst == 0 else d_worst / (d_best + d_worst))
    return result


POLICIES: dict[str, type[Policy]] = {p.key: p for p in (LatencyFirst, CloudOnly, CapacityAware, Topsis)}
"""Available policies by key, in display order."""


def vm_sizes(settings: Settings) -> dict[str, dict[str, float]]:
    """Default VM size per tier from ``vm.sizes`` in the settings."""
    return settings.simulation["vm"]["sizes"]


def make_policy(key: str, settings: Settings) -> Policy:
    """Create a policy by its key.

    Args:
        key: One of ``POLICIES`` (``latency``, ``cloud``, ``capacity``, ``topsis``).
        settings: Resolved settings.

    Returns:
        The policy.

    Raises:
        ValueError: For an unknown key, or ``qlearn`` before Phase 7 adds it.
    """
    if key == "qlearn":
        raise ValueError("Q-Learning is an optional stretch goal (Phase 7) and is not built yet")
    if key not in POLICIES:
        raise ValueError(f"unknown policy '{key}'; choose from {', '.join(POLICIES)}")
    return POLICIES[key](settings)
