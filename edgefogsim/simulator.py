"""Run a workload through a placement policy and record every decision.

Tasks are placed one at a time, in order. Each placed task runs in a VM of its
tenant on the chosen node: an existing one with room, or a new one (see
``vm_manager``). Tasks keep running until their VM is stopped, so later tasks
see busier nodes, which is what makes overload and offloading happen.

Each run starts from fresh, empty copies of the configured nodes, so running
several policies on the same workload is a fair comparison. After a run, the
result is a live cluster: VMs can be stopped (:meth:`RunResult.stop_vm`) and
tasks placed again on what's left (:func:`submit`).
"""

import math
from dataclasses import dataclass, replace

from edgefogsim.config import Settings
from edgefogsim.models import Node, Task
from edgefogsim.models import VM
from edgefogsim.policies import POLICIES, Policy, make_policy, vm_sizes
from edgefogsim.qos import deadline_ms, estimate_latency_ms
from edgefogsim.vm_manager import VMManager

ON_TIME, LATE, REJECTED = "on time", "late", "rejected"
"""Possible outcomes of a task: placed and met its deadline, placed but missed it, or not placed."""


@dataclass(frozen=True)
class Decision:
    """What happened to one task.

    Attributes:
        task: The task.
        policy: Key of the policy that decided.
        node_id: Node it was placed on, or None if rejected.
        tier: That node's tier, or None if rejected.
        latency_ms: Simulated latency, or None if rejected.
        deadline_ms: The task's deadline.
        outcome: ``ON_TIME``, ``LATE`` or ``REJECTED``.
        offloaded: True if placed outside its first-preference tier.
        reason: The policy's explanation, plus which VM the task runs in.
        vm_id: The VM it runs in, or None if rejected.
        new_vm: True if that VM was created for this task; False if it joined an existing one.
    """

    task: Task
    policy: str
    node_id: str | None
    tier: str | None
    latency_ms: float | None
    deadline_ms: float
    outcome: str
    offloaded: bool
    reason: str
    vm_id: str | None = None
    new_vm: bool = False

    @property
    def placed(self) -> bool:
        """True if the task got a node (on time or late)."""
        return self.node_id is not None


@dataclass
class RunResult:
    """All decisions from one run, and the cluster it left behind.

    Attributes:
        policy: Key of the policy used.
        label: Display name of the policy.
        decisions: One decision per task, in placement order.
        nodes: The nodes, with current usage.
        vms: The VMs created on those nodes (running and stopped).
    """

    policy: str
    label: str
    decisions: list[Decision]
    nodes: list[Node]
    vms: VMManager | None = None

    def __post_init__(self):
        """Create an empty VM manager for the nodes if none was given (VMs sized to each task)."""
        if self.vms is None:
            self.vms = VMManager(self.nodes)

    def stop_vm(self, vm_id: str) -> bool:
        """Stop a VM in this cluster, freeing its node's CPU and memory.

        Args:
            vm_id: The VM to stop.

        Returns:
            True if it was running; False if it was already stopped (nothing freed twice).

        Raises:
            KeyError: If there is no such VM.
        """
        return self.vms.stop(vm_id)

    def summary(self) -> dict[str, float | int | None]:
        """Headline QoS numbers for the run.

        Returns:
            A dict with ``total``, ``placed``, ``on_time``, ``late``,
            ``rejected``, ``offloaded``, ``running_vms``, ``success_rate`` (on time / total),
            ``avg_latency_ms`` and ``p95_latency_ms`` (over placed tasks; None if
            nothing was placed), and for each node ``<node id> util`` (share of
            CPU reserved by VMs) and ``<node id> load`` (share used by tasks) at the end.
        """
        latencies = sorted(d.latency_ms for d in self.decisions if d.placed)
        total = len(self.decisions)
        on_time = sum(d.outcome == ON_TIME for d in self.decisions)
        result: dict[str, float | int | None] = {
            "total": total,
            "placed": len(latencies),
            "on_time": on_time,
            "late": sum(d.outcome == LATE for d in self.decisions),
            "rejected": sum(d.outcome == REJECTED for d in self.decisions),
            "offloaded": sum(d.offloaded for d in self.decisions),
            "running_vms": len(self.vms.running()),
            "success_rate": on_time / total if total else 0.0,
            "avg_latency_ms": sum(latencies) / len(latencies) if latencies else None,
            "p95_latency_ms": latencies[math.ceil(0.95 * len(latencies)) - 1] if latencies else None,
        }
        for node in self.nodes:
            result[f"{node.id} util"] = node.cpu_util
            result[f"{node.id} load"] = node.load_util
        return result

    def rows(self) -> list[dict[str, object]]:
        """One plain dict per decision, ready for a table or a CSV file.

        Returns:
            Dicts with task fields, ``node``, ``tier``, ``latency_ms``,
            ``deadline_ms``, ``outcome``, ``offloaded``, ``vm``, ``new_vm``, ``vm_status`` and ``reason``.
        """
        return [{
            "task": d.task.id,
            "tenant": d.task.tenant_id,
            "sensitivity": d.task.sensitivity,
            "cpu_cores": d.task.cpu_cores,
            "memory_gb": d.task.memory_gb,
            "work_units": d.task.work_units,
            "node": d.node_id,
            "tier": d.tier,
            "latency_ms": None if d.latency_ms is None else round(d.latency_ms, 1),
            "deadline_ms": d.deadline_ms,
            "outcome": d.outcome,
            "offloaded": d.offloaded,
            "vm": d.vm_id,
            "new_vm": d.new_vm,
            "vm_status": self.vms.get(d.vm_id).status if d.vm_id else None,
            "reason": d.reason,
        } for d in self.decisions]

    @property
    def tasks(self) -> list[Task]:
        """The workload this run placed, in order."""
        return [d.task for d in self.decisions]


def fresh_nodes(settings: Settings) -> list[Node]:
    """Empty copies of the configured nodes, so a run never changes the settings.

    Args:
        settings: Resolved settings.

    Returns:
        New Node objects with zero usage.
    """
    return [replace(n, cpu_used=0.0, memory_used=0.0, cpu_load=0.0, memory_load=0.0) for n in settings.nodes]


def place(task: Task, vms: VMManager, policy: Policy) -> Decision:
    """Ask the policy for a node and, if one is chosen, run the task in a VM there.

    The task joins one of its tenant's VMs on the node if one has room,
    otherwise a new VM is created. Latency is estimated before the task is
    added (the estimate already counts its own load), so it matches what the
    policy saw when deciding.

    Args:
        task: The task to place.
        vms: The cluster's VM manager; offered to the policy and updated in place.
        policy: The policy deciding.

    Returns:
        The decision, including the outcome, reason and VM.
    """
    choice = policy.choose(task, vms)
    limit = deadline_ms(task, policy.settings)
    if choice.node is None:
        return Decision(task, policy.key, None, None, None, limit, REJECTED, False, choice.reason)
    node = choice.node
    latency = estimate_latency_ms(task, node, policy.settings)
    vm, created = vms.assign(task, node)
    outcome = ON_TIME if latency <= limit else LATE
    how = (f"new VM {vm.vm_id} ({vm.cpu_cores:g} CPU / {vm.memory_gb:g} GB)" if created
           else f"joined {vm.vm_id}")
    return Decision(task, policy.key, node.id, node.tier, latency, limit, outcome, choice.offloaded,
                    f"{choice.reason}; runs in {how}", vm.vm_id, created)


def run_workload(settings: Settings, tasks: list[Task], policy_key: str,
                 nodes: list[Node] | None = None) -> RunResult:
    """Place every task in order with one policy.

    Args:
        settings: Resolved settings.
        tasks: The workload.
        policy_key: Which policy to use, e.g. ``"capacity"``.
        nodes: Starting nodes (e.g. pre-loaded for an overload test); defaults
            to fresh empty copies. They are updated in place.

    Returns:
        Every decision and the nodes' final usage.

    Raises:
        ValueError: If the policy key is unknown.
    """
    policy = make_policy(policy_key, settings)
    vms = VMManager(fresh_nodes(settings) if nodes is None else nodes, vm_sizes(settings))
    decisions = [place(task, vms, policy) for task in tasks]
    return RunResult(policy.key, policy.label, decisions, vms.nodes, vms)


def empty_cluster(settings: Settings, policy_key: str = "capacity") -> RunResult:
    """A cluster with fresh nodes and no tasks yet, for placing tasks one at a time.

    Args:
        settings: Resolved settings.
        policy_key: Policy recorded as the run's policy.

    Returns:
        A result with no decisions and no VMs.
    """
    nodes = fresh_nodes(settings)
    return RunResult(policy_key, POLICIES[policy_key].label, [], nodes, VMManager(nodes, vm_sizes(settings)))


def submit(result: RunResult, task: Task, policy_key: str, settings: Settings) -> Decision:
    """Place one task now on the cluster a run left behind (e.g. after stopping a VM).

    If the task was already in the run, its old decision is replaced by the new
    one, so the summary still counts each task once.

    Args:
        result: The cluster to place on; updated in place.
        task: The task to place.
        policy_key: Policy deciding this placement.
        settings: Resolved settings.

    Returns:
        The new decision.

    Raises:
        ValueError: If the task already has a running VM (stop it first), or the policy is unknown.
    """
    running = result.vms.vm_of(task.id)
    if running:
        raise ValueError(f"{task.id} is already running on {running.vm_id}; stop that VM first")
    decision = place(task, result.vms, make_policy(policy_key, settings))
    for i, old in enumerate(result.decisions):
        if old.task.id == task.id:
            result.decisions[i] = decision
            break
    else:
        result.decisions.append(decision)
    return decision


def compare_policies(settings: Settings, tasks: list[Task], keys: list[str] | None = None) -> list[RunResult]:
    """Run the same workload through several policies, each on fresh nodes.

    Args:
        settings: Resolved settings.
        tasks: The workload.
        keys: Policy keys to compare; defaults to every available policy.

    Returns:
        One result per policy, in the order given.
    """
    return [run_workload(settings, tasks, key) for key in (keys or list(POLICIES))]


def create_vm(result: RunResult, tenant_id: str, node_id: str,
              cpu_cores: float | None = None, memory_gb: float | None = None) -> VM:
    """Create an empty VM ahead of time, reserving room on a node for a tenant's tasks.

    Args:
        result: The cluster to create it in; updated in place.
        tenant_id: Owner of the VM.
        node_id: Host node.
        cpu_cores: Cores to reserve; defaults to the tier's VM size.
        memory_gb: Memory (GB) to reserve; defaults to the tier's VM size.

    Returns:
        The new running VM, with no tasks yet.

    Raises:
        KeyError: If the node doesn't exist.
        CapacityError: If the node doesn't have that much unreserved CPU or memory.
    """
    node = result.vms.node(node_id)
    default = result.vms.sizes.get(node.tier, {})
    return result.vms.create(tenant_id, node,
                             cpu_cores if cpu_cores is not None else default.get("cpu_cores", 1),
                             memory_gb if memory_gb is not None else default.get("memory_gb", 1))


@dataclass
class BeforeAfter:
    """The same workload and policy run before and after a node change.

    Attributes:
        change: What changed, in words, e.g. ``"edge-1 cpu_cores 4 → 8"``.
        before: The run with the original nodes.
        after: The run with the changed nodes.
    """

    change: str
    before: RunResult
    after: RunResult

    def diff(self) -> list[dict[str, object]]:
        """Headline numbers side by side.

        Returns:
            One dict per metric with ``metric``, ``before``, ``after`` and
            ``change`` (after minus before; None where either is missing).
        """
        b, a = self.before.summary(), self.after.summary()
        rows = []
        for key in b:
            if key in a and key != "total":
                change = None if b[key] is None or a[key] is None else a[key] - b[key]
                rows.append({"metric": key, "before": b[key], "after": a[key], "change": change})
        return rows


def compare_before_after(settings: Settings, tasks: list[Task], policy_key: str,
                         changes: dict[str, dict[str, float]]) -> BeforeAfter:
    """Run a workload with the current nodes and again with some nodes changed.

    Args:
        settings: Current settings (not modified).
        tasks: The workload.
        policy_key: Policy used for both runs.
        changes: Node id -> {field: new value}, e.g. ``{"cloud-1": {"base_latency_ms": 150}}``.

    Returns:
        Both runs and a description of the change.

    Raises:
        ConfigError: For an unknown node or field, or an invalid value.
    """
    from edgefogsim.config import with_node_changes

    changed = with_node_changes(settings, changes)
    old = {n.id: n for n in settings.nodes}
    words = ", ".join(f"{node_id} {key} {getattr(old[node_id], key):g} → {value:g}"
                      for node_id, fields in changes.items() for key, value in fields.items())
    return BeforeAfter(words, run_workload(settings, tasks, policy_key), run_workload(changed, tasks, policy_key))
