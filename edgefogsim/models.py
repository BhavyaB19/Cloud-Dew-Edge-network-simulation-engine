"""Core data objects shared by every part of the simulator: nodes, tasks and tenants.

These are plain dataclasses with no I/O. ``config`` builds nodes and tenants from
settings files, ``workload`` builds tasks, and later phases (placement, VMs,
security) read and update them.
"""

from dataclasses import dataclass, field

TIERS = ("edge", "fog", "cloud")
"""Node tiers, nearest (fastest to reach, smallest) to farthest (slowest, largest)."""

SENSITIVITIES = ("high", "medium", "low")
"""Latency sensitivity levels a task can have, most urgent first."""

ROLES = ("tenant", "admin")
"""Login roles: a tenant sees only its own records; an admin sees everything."""


@dataclass
class Node:
    """A simulated computer in one tier, with its live resource usage.

    Usage has two levels. *Allocated* (``cpu_used``, ``memory_used``) is what
    VMs have reserved; it decides whether a new VM fits. *Load* (``cpu_load``,
    ``memory_load``) is what running tasks actually use inside those VMs; it
    drives latency. Load is never more than allocation.

    Attributes:
        id: Unique name, e.g. ``"edge-1"``.
        tier: One of ``TIERS``.
        cpu_cores: Total CPU cores.
        memory_gb: Total memory in GB.
        base_latency_ms: Network delay to reach the node, in milliseconds.
        speed_factor: Processing speed relative to a Fog node (1.0); higher is faster.
        cpu_used: Cores allocated to running VMs.
        memory_used: Memory (GB) allocated to running VMs.
        cpu_load: Cores used by running tasks.
        memory_load: Memory (GB) used by running tasks.
    """

    id: str
    tier: str
    cpu_cores: float
    memory_gb: float
    base_latency_ms: float
    speed_factor: float
    cpu_used: float = 0.0
    memory_used: float = 0.0
    cpu_load: float = 0.0
    memory_load: float = 0.0

    @property
    def free_cpu(self) -> float:
        """Cores not yet allocated to a VM."""
        return self.cpu_cores - self.cpu_used

    @property
    def free_memory(self) -> float:
        """Memory (GB) not yet allocated."""
        return self.memory_gb - self.memory_used

    @property
    def cpu_util(self) -> float:
        """Fraction of CPU allocated, from 0.0 to 1.0."""
        return self.cpu_used / self.cpu_cores

    @property
    def memory_util(self) -> float:
        """Fraction of memory allocated, from 0.0 to 1.0."""
        return self.memory_used / self.memory_gb

    @property
    def load_util(self) -> float:
        """Fraction of CPU used by running tasks, from 0.0 to 1.0. Drives latency."""
        return self.cpu_load / self.cpu_cores


@dataclass(frozen=True)
class Task:
    """A job submitted by a tenant. Immutable once created.

    Attributes:
        id: Unique name, e.g. ``"T01"``.
        tenant_id: Owner of the task; only they (or an admin) may see it.
        cpu_cores: Cores the task needs.
        memory_gb: Memory (GB) the task needs.
        sensitivity: How urgent it is, one of ``SENSITIVITIES``; sets its deadline.
        work_units: Amount of processing; divided by a node's ``speed_factor``
            to give processing time in milliseconds.
    """

    id: str
    tenant_id: str
    cpu_cores: float
    memory_gb: float
    sensitivity: str
    work_units: float


@dataclass(frozen=True)
class Tenant:
    """Someone who can log in. No password is stored, by design.

    Attributes:
        tenant_id: Login name, e.g. ``"hospital-a"``.
        role: One of ``ROLES``.
    """

    tenant_id: str
    role: str

    @property
    def is_admin(self) -> bool:
        """True if this user may see every tenant's records."""
        return self.role == "admin"


VM_RUNNING, VM_STOPPED = "running", "stopped"
"""VM statuses: running holds its CPU and memory on the host node; stopped has released them."""


@dataclass
class VM:
    """A simulated virtual machine: a slice of one node, owned by one tenant, that runs tasks.

    There is no hypervisor. A VM reserves ``cpu_cores`` and ``memory_gb`` on its
    host node when created and gives them back when stopped. Several tasks of
    the same tenant can run inside one VM while it has room; tenants never
    share a VM.

    Attributes:
        vm_id: Unique id, e.g. ``"vm-0001"``.
        tenant_id: Owner; only they (or an admin) may see, use or stop it.
        node_id: Host node.
        cpu_cores: Cores reserved on the host.
        memory_gb: Memory (GB) reserved on the host.
        status: ``VM_RUNNING`` or ``VM_STOPPED``.
        task_ids: Tasks placed in this VM, in order (kept after the VM stops, as a record).
        cpu_load: Cores used by its running tasks.
        memory_load: Memory (GB) used by its running tasks.
    """

    vm_id: str
    tenant_id: str
    node_id: str
    cpu_cores: float
    memory_gb: float
    status: str = VM_RUNNING
    task_ids: list[str] = field(default_factory=list)
    cpu_load: float = 0.0
    memory_load: float = 0.0

    @property
    def running(self) -> bool:
        """True while the VM holds its slice of the node."""
        return self.status == VM_RUNNING

    @property
    def free_cpu(self) -> float:
        """Cores inside the VM not used by its tasks."""
        return self.cpu_cores - self.cpu_load

    @property
    def free_memory(self) -> float:
        """Memory (GB) inside the VM not used by its tasks."""
        return self.memory_gb - self.memory_load
