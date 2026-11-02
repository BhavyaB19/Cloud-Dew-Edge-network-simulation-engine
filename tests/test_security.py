"""Tenant access control and the audit log (AC11-12)."""

import pytest

from edgefogsim.models import Task, Tenant
from edgefogsim.security import AccessDenied, AuditLog, authorize, find_task, find_vm, visible
from edgefogsim.simulator import run_workload

HOSPITAL_A = Tenant("hospital-a", "tenant")
HOSPITAL_B = Tenant("hospital-b", "tenant")
ADMIN = Tenant("admin", "admin")
TASKS = [Task("T01", "hospital-a", 1, 1, "high", 2), Task("T02", "hospital-b", 1, 1, "low", 20)]


@pytest.fixture
def audit(tmp_path):
    """An empty audit log in a temporary folder."""
    return AuditLog(tmp_path / "audit.log")


def test_tenant_cannot_read_another_tenants_task(audit):
    """AC11: hospital-b reading hospital-a's task raises AccessDenied and appends one audit line."""
    with pytest.raises(AccessDenied, match="hospital-b may not access task T01"):
        find_task(HOSPITAL_B, "T01", TASKS, audit)
    entries = audit.entries()
    assert len(entries) == 1
    assert {k: entries[0][k] for k in ("actor", "target_tenant", "resource", "outcome")} == \
        {"actor": "hospital-b", "target_tenant": "hospital-a", "resource": "task T01", "outcome": "DENIED"}


def test_tenant_can_read_own_task_without_logging(audit):
    """A tenant reading their own task succeeds and nothing is logged."""
    assert find_task(HOSPITAL_A, "T01", TASKS, audit).id == "T01"
    assert audit.entries() == []


def test_admin_can_read_every_tenants_records(audit, settings):
    """AC12: the admin reads tasks and VMs of every tenant, with nothing logged."""
    assert [find_task(ADMIN, t.id, TASKS, audit).id for t in TASKS] == ["T01", "T02"]
    result = run_workload(settings, TASKS, "capacity")
    assert {find_vm(ADMIN, vm.vm_id, result.vms, audit).tenant_id for vm in result.vms.vms} == \
        {"hospital-a", "hospital-b"}
    assert audit.entries() == []


def test_tenant_cannot_read_another_tenants_vm(audit, settings):
    """VMs are protected the same way as tasks."""
    result = run_workload(settings, TASKS, "capacity")
    vm_a = next(vm for vm in result.vms.vms if vm.tenant_id == "hospital-a")
    with pytest.raises(AccessDenied):
        find_vm(HOSPITAL_B, vm_a.vm_id, result.vms, audit)
    assert audit.entries()[0]["resource"] == f"VM {vm_a.vm_id}"


def test_missing_record_is_not_found_not_denied(audit):
    """An id that doesn't exist raises KeyError and is not logged as a denial."""
    with pytest.raises(KeyError):
        find_task(HOSPITAL_B, "T99", TASKS, audit)
    assert audit.entries() == []


def test_visible_filters_by_owner():
    """Tenants see only their own records in lists; the admin sees all."""
    assert [t.id for t in visible(HOSPITAL_A, TASKS)] == ["T01"]
    assert [t.id for t in visible(ADMIN, TASKS)] == ["T01", "T02"]


def test_tenant_sees_only_own_audit_entries(audit):
    """A tenant reading the log sees only attempts they made; the admin sees every entry."""
    for actor, target in ((HOSPITAL_A, "hospital-b"), (HOSPITAL_B, "hospital-a"), (HOSPITAL_B, "hospital-a")):
        with pytest.raises(AccessDenied):
            authorize(actor, target, "task T0x", audit)
    assert len(audit.entries(viewer=HOSPITAL_B)) == 2
    assert len(audit.entries(viewer=HOSPITAL_A)) == 1
    assert len(audit.entries(viewer=ADMIN)) == 3


def test_audit_log_is_a_csv_with_header(audit):
    """The log file is plain CSV with a header row, readable in Excel."""
    with pytest.raises(AccessDenied):
        authorize(HOSPITAL_A, "hospital-b", "task T02", audit)
    lines = audit.path.read_text().splitlines()
    assert lines[0] == "timestamp,actor,target_tenant,resource,outcome"
    assert lines[1].endswith(",hospital-a,hospital-b,task T02,DENIED")
