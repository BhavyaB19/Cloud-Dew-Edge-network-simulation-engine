"""Core data objects: nodes, tasks and tenants."""

from dataclasses import dataclass

TIERS = ("edge", "fog", "cloud")
SENSITIVITIES = ("high", "medium", "low")
ROLES = ("tenant", "admin")


@dataclass
class Node:
    """A simulated computer in one tier, with its live resource usage."""

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
        return self.cpu_cores - self.cpu_used

    @property
    def free_memory(self) -> float:
        return self.memory_gb - self.memory_used

    @property
    def cpu_util(self) -> float:
        return self.cpu_used / self.cpu_cores

    @property
    def memory_util(self) -> float:
        return self.memory_used / self.memory_gb


@dataclass(frozen=True)
class Task:
    """A job submitted by a tenant."""

    id: str
    tenant_id: str
    cpu_cores: float
    memory_gb: float
    sensitivity: str
    work_units: float


@dataclass(frozen=True)
class Tenant:
    tenant_id: str
    role: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"
