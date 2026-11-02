"""Shared VMs: create, join, stop and resubmit (AC9-10)."""

import pytest

from edgefogsim.config import load_settings
from edgefogsim.models import Task
from edgefogsim.policies import vm_sizes
from edgefogsim.qos import estimate_latency_ms
from edgefogsim.simulator import create_vm, empty_cluster, fresh_nodes, run_workload, submit
from edgefogsim.vm_manager import CapacityError, VMManager


def task(task_id="T01", tenant="hospital-a", cpu=1, memory=1, sensitivity="high", work=2):
    """Build a task with the given needs."""
    return Task(task_id, tenant, cpu, memory, sensitivity, work)


@pytest.fixture
def vms(settings):
    """A VM manager on fresh default nodes with the default VM sizes (edge 2 CPU / 4 GB)."""
    return VMManager(fresh_nodes(settings), vm_sizes(settings))


def test_new_vm_uses_tier_size_and_task_load(vms):
    """A first task creates a VM of the tier's default size; only the task's own needs count as load."""
    edge = vms.node("edge-1")
    vm, created = vms.assign(task(cpu=1, memory=1), edge)
    assert created and vm.vm_id == "vm-0001"
    assert (vm.cpu_cores, vm.memory_gb, vm.task_ids) == (2, 4, ["T01"])
    assert (edge.cpu_used, edge.memory_used, edge.cpu_load, edge.memory_load) == (2, 4, 1, 1)


def test_same_tenant_tasks_share_a_vm(vms):
    """A second task of the same tenant joins the VM while it has room; nothing new is reserved."""
    edge = vms.node("edge-1")
    first, _ = vms.assign(task("T01"), edge)
    second, created = vms.assign(task("T02"), edge)
    assert second is first and not created
    assert first.task_ids == ["T01", "T02"] and first.free_cpu == 0
    assert edge.cpu_used == 2 and edge.cpu_load == 2


def test_tenants_never_share_a_vm(vms):
    """Another tenant's task gets its own VM even if an existing VM has room."""
    edge = vms.node("edge-1")
    a, _ = vms.assign(task("T01", "hospital-a"), edge)
    b, created = vms.assign(task("T02", "hospital-b"), edge)
    assert created and b is not a and b.tenant_id == "hospital-b"
    assert edge.cpu_used == 4


def test_full_vm_triggers_a_new_vm(vms):
    """When the tenant's VM is full, the next task creates another VM."""
    edge = vms.node("edge-1")
    vms.assign(task("T01", cpu=2), edge)
    vm, created = vms.assign(task("T02", cpu=1), edge)
    assert created and vm.vm_id == "vm-0002" and edge.cpu_used == 4


def test_big_task_gets_a_bigger_vm(vms):
    """A task bigger than the tier's VM size gets a VM sized to the task."""
    vm, _ = vms.assign(task(cpu=10, memory=20), vms.node("fog-1"))
    assert (vm.cpu_cores, vm.memory_gb) == (10, 20)


def test_vm_sizes_come_from_settings():
    """Changing vm.sizes in settings changes the size of new VMs, with no code change."""
    settings = load_settings(overrides={"vm.sizes.edge.cpu_cores": 4, "vm.sizes.edge.memory_gb": 2})
    vms = VMManager(fresh_nodes(settings), vm_sizes(settings))
    vm, _ = vms.assign(task(), vms.node("edge-1"))
    assert (vm.cpu_cores, vm.memory_gb) == (4, 2)


def test_why_cannot_host_explains_missing_room(vms):
    """With no tenant VM to join and too little unreserved CPU, the reason names both numbers."""
    edge = vms.node("edge-1")
    vms.create("hospital-b", edge, 3, 1)
    assert vms.why_cannot_host(task("T01", "hospital-a"), edge) == \
        "edge-1 not enough CPU for a new VM (needs 2, 1 unreserved)"
    with pytest.raises(CapacityError):
        vms.assign(task("T01", "hospital-a"), edge)


def test_stop_frees_the_whole_slice_and_its_tasks(vms):
    """AC9: stopping a VM frees exactly its reserved size and its tasks' load, and marks it stopped."""
    edge = vms.node("edge-1")
    other, _ = vms.assign(task("T00", "hospital-b"), edge)
    vm, _ = vms.assign(task("T01"), edge)
    vms.assign(task("T02"), edge)
    assert vms.stop(vm.vm_id) is True
    assert (edge.cpu_used, edge.memory_used, edge.cpu_load) == (2, 4, 1)
    assert vm.status == "stopped" and vm.task_ids == ["T01", "T02"]
    assert vms.vm_of("T01") is None and vms.vm_of("T00") is other


def test_stopping_twice_is_a_no_op(vms):
    """AC10: stopping an already-stopped VM returns False and frees nothing twice."""
    edge = vms.node("edge-1")
    vms.assign(task("T00", "hospital-b"), edge)
    vm, _ = vms.assign(task("T01"), edge)
    vms.stop(vm.vm_id)
    assert vms.stop(vm.vm_id) is False
    assert edge.cpu_used == 2


def test_unknown_vm_raises_key_error(vms):
    """Stopping or finding a VM that doesn't exist raises KeyError."""
    with pytest.raises(KeyError):
        vms.stop("vm-9999")


def test_explicit_vm_reserves_room_that_tasks_then_use(settings):
    """A VM created ahead of time reserves room; the tenant's next task joins it instead of creating one."""
    cluster = empty_cluster(settings)
    vm = create_vm(cluster, "hospital-a", "edge-1")
    assert (vm.cpu_cores, vm.memory_gb, vm.task_ids) == (2, 4, [])
    decision = submit(cluster, task("T01"), "capacity", settings)
    assert decision.vm_id == vm.vm_id and not decision.new_vm
    assert "joined vm-0001" in decision.reason


def test_explicit_vm_that_does_not_fit_is_refused(settings):
    """Creating a VM bigger than the node's unreserved capacity fails with a clear reason."""
    with pytest.raises(CapacityError, match="edge-1 can't fit a 8 CPU / 4 GB VM"):
        create_vm(empty_cluster(settings), "hospital-a", "edge-1", 8, 4)


def test_idle_vm_does_not_slow_the_node(settings):
    """Latency depends on task load, not reservations: an empty VM leaves latency unchanged."""
    cluster = empty_cluster(settings)
    edge = cluster.vms.node("edge-1")
    before = estimate_latency_ms(task(), edge, settings)
    create_vm(cluster, "hospital-b", "edge-1")
    assert estimate_latency_ms(task(), edge, settings) == before


def test_every_placed_task_gets_a_vm(settings):
    """Each placed decision names its VM; rejected tasks have none; reservations equal running VMs."""
    tasks = [task("T01", cpu=2, work=4), task("T02", cpu=2, work=4), task("T03", cpu=500)]
    result = run_workload(settings, tasks, "capacity")
    assert [d.vm_id for d in result.decisions] == ["vm-0001", "vm-0002", None]
    for node in result.nodes:
        assert node.cpu_used == sum(vm.cpu_cores for vm in result.vms.running() if vm.node_id == node.id)
        assert node.cpu_load == sum(vm.cpu_load for vm in result.vms.running() if vm.node_id == node.id)
    assert result.summary()["running_vms"] == 2


def test_stop_then_resubmit_places_a_rejected_task(settings):
    """Stopping a VM frees room, and a task rejected earlier is then placed on time."""
    tasks = [task("T01", cpu=2, work=4), task("T02", cpu=2, work=4),
             task("T03", tenant="hospital-b", cpu=2, memory=2, work=6)]
    nodes = fresh_nodes(settings)
    next(n for n in nodes if n.id == "fog-1").cpu_used = 15  # fog nearly fully reserved
    result = run_workload(settings, tasks, "capacity", nodes=nodes)
    assert result.decisions[2].outcome == "rejected"

    result.stop_vm(result.decisions[0].vm_id)
    decision = submit(result, tasks[2], "capacity", settings)
    assert decision.outcome == "on time" and decision.node_id == "edge-1"
    assert [d.task.id for d in result.decisions] == ["T01", "T02", "T03"]
    assert result.summary()["rejected"] == 1  # only T02 now: edge and fog had no room for it either


def test_resubmitting_a_running_task_is_refused(settings):
    """A task that is already running can't be placed again until its VM is stopped."""
    result = run_workload(settings, [task("T01")], "capacity")
    with pytest.raises(ValueError, match="already running on vm-0001"):
        submit(result, task("T01"), "capacity", settings)
