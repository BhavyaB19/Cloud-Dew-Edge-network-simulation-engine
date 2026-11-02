"""Tenant access control (F7): who may see or change which records, with an audit log of refusals.

The rule is simple and lives in one place, :func:`authorize`:

- a **tenant** may see and act on records (tasks, VMs, decisions) whose
  ``tenant_id`` is their own;
- an **admin** may see and act on every record.

Any other attempt raises :class:`AccessDenied` and is appended to the audit
log (``security.audit_log``, default ``results/audit.log``) as a CSV row:
``timestamp,actor,target_tenant,resource,outcome``. No passwords or other
secrets exist anywhere; logging in means choosing a tenant id.
"""

import csv
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, TypeVar

from edgefogsim.models import VM, Task, Tenant
from edgefogsim.vm_manager import VMManager

T = TypeVar("T")

AUDIT_FIELDS = ("timestamp", "actor", "target_tenant", "resource", "outcome")
"""Columns of the audit log, in order."""


class AccessDenied(PermissionError):
    """A user tried to see or change another tenant's record.

    Attributes:
        actor: Who tried.
        target_tenant: Whose record it was.
        resource: What it was, e.g. ``"task T05"``.
    """

    def __init__(self, actor: str, target_tenant: str, resource: str):
        """Build the error with a message suitable for showing to the user."""
        super().__init__(f"ACCESS DENIED: {actor} may not access {resource} (belongs to {target_tenant})")
        self.actor = actor
        self.target_tenant = target_tenant
        self.resource = resource


class AuditLog:
    """Append-only CSV log of denied access attempts.

    Attributes:
        path: The log file; created with a header row on first write.
    """

    def __init__(self, path: Path | str):
        """Use the log at ``path`` (relative paths are relative to the current folder)."""
        self.path = Path(path)

    def record(self, actor: str, target_tenant: str, resource: str, outcome: str = "DENIED") -> dict[str, str]:
        """Append one entry.

        Args:
            actor: Who made the attempt.
            target_tenant: Owner of the record.
            resource: What was requested, e.g. ``"task T05"``.
            outcome: ``"DENIED"`` for refusals.

        Returns:
            The entry written, as a dict keyed by ``AUDIT_FIELDS``.
        """
        entry = dict(zip(AUDIT_FIELDS, (datetime.now().isoformat(timespec="seconds"),
                                        actor, target_tenant, resource, outcome)))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        new_file = not self.path.exists()
        with open(self.path, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=AUDIT_FIELDS)
            if new_file:
                writer.writeheader()
            writer.writerow(entry)
        return entry

    def entries(self, viewer: Tenant | None = None) -> list[dict[str, str]]:
        """Read the log, oldest first.

        Args:
            viewer: If given and not an admin, only entries where they were the
                actor are returned (a tenant sees their own refused attempts).

        Returns:
            One dict per entry; empty if the log doesn't exist yet.
        """
        if not self.path.exists():
            return []
        with open(self.path, newline="") as f:
            rows = list(csv.DictReader(f))
        if viewer is not None and not viewer.is_admin:
            rows = [r for r in rows if r["actor"] == viewer.tenant_id]
        return rows


def can_access(user: Tenant, tenant_id: str) -> bool:
    """True if ``user`` may see or act on a record owned by ``tenant_id``."""
    return user.is_admin or user.tenant_id == tenant_id


def authorize(user: Tenant, tenant_id: str, resource: str, audit: AuditLog) -> None:
    """Allow the access, or log the attempt and refuse it.

    Args:
        user: Who is asking.
        tenant_id: Owner of the record.
        resource: What is being accessed, for the message and the log, e.g. ``"VM vm-0003"``.
        audit: Where refusals are recorded.

    Raises:
        AccessDenied: If ``user`` is not the owner and not an admin.
    """
    if not can_access(user, tenant_id):
        audit.record(user.tenant_id, tenant_id, resource)
        raise AccessDenied(user.tenant_id, tenant_id, resource)


def visible(user: Tenant, records: Iterable[T], owner: Callable[[T], str] = lambda r: r.tenant_id) -> list[T]:
    """Filter records down to those ``user`` may see (no logging: nothing was asked for by id).

    Args:
        user: Who is viewing.
        records: Tasks, VMs, decisions, ...
        owner: Function returning a record's tenant id; defaults to ``record.tenant_id``.

    Returns:
        The visible records, in their original order.
    """
    return [r for r in records if can_access(user, owner(r))]


def find_task(user: Tenant, task_id: str, tasks: Iterable[Task], audit: AuditLog) -> Task:
    """Look up a task by id, enforcing ownership.

    Args:
        user: Who is asking.
        task_id: The task id, e.g. ``"T05"``.
        tasks: The workload to search.
        audit: Where a refusal is recorded.

    Returns:
        The task.

    Raises:
        KeyError: If no task has that id.
        AccessDenied: If it belongs to another tenant and ``user`` is not an admin.
    """
    task = next((t for t in tasks if t.id == task_id), None)
    if task is None:
        raise KeyError(f"no task '{task_id}'")
    authorize(user, task.tenant_id, f"task {task_id}", audit)
    return task


def find_vm(user: Tenant, vm_id: str, vms: VMManager, audit: AuditLog) -> VM:
    """Look up a VM by id, enforcing ownership.

    Args:
        user: Who is asking.
        vm_id: The VM id, e.g. ``"vm-0003"``.
        vms: The cluster's VM manager.
        audit: Where a refusal is recorded.

    Returns:
        The VM.

    Raises:
        KeyError: If no VM has that id.
        AccessDenied: If it belongs to another tenant and ``user`` is not an admin.
    """
    vm = vms.get(vm_id)
    authorize(user, vm.tenant_id, f"VM {vm_id}", audit)
    return vm
