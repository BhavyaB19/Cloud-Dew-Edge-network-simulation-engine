"""Core data objects shared by every part of the simulator: nodes, tasks and tenants.

These are plain dataclasses with no I/O. ``config`` builds nodes and tenants from
settings files, ``workload`` builds tasks, and later phases (placement, VMs,
security) read and update them.
"""

from dataclasses import dataclass

TIERS = ("edge", "fog", "cloud")
"""Node tiers, nearest (fastest to reach, smallest) to farthest (slowest, largest)."""

SENSITIVITIES = ("high", "medium", "low")
"""Latency sensitivity levels a task can have, most urgent first."""

ROLES = ("tenant", "admin")
"""Login roles: a tenant sees only its own records; an admin sees everything."""


@dataclass
class Node:
    """A simulated computer in one tier, with its live resource usage.

    Attributes:
        id: Unique name, e.g. ``"edge-1"``.
        tier: One of ``TIERS``.
        cpu_cores: Total CPU cores.
        memory_gb: Total memory in GB.
        base_latency_ms: Network delay to reach the node, in milliseconds.
        speed_factor: Processing speed relative to a Fog node (1.0); higher is faster.
        cpu_used: Cores currently allocated to VMs.
        memory_used: Memory (GB) currently allocated to VMs.
    """

    id: str
    tier: str
    cpu_cores: float
    memory_gb: float
    base_latency_ms: float
    speed_factor: float
    cpu_used: float = 0.0
    memory_used: float = 0.0

    @property
    def free_cpu(self) -> float:
        """Cores not yet allocated."""
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
