"""Shared virtual machines (F6): VMs are slices of a node that a tenant's tasks run inside.

How a task gets somewhere to run, once a policy has picked a node:

1. **Join**: if the task's tenant already has a running VM on that node with
   enough free CPU and memory inside it, the task runs in that VM. Nothing new
   is reserved on the node.
2. **Create**: otherwise a new VM is created for the tenant on the node, sized
   to the tier's default (``vm.sizes``) or to the task if the task is bigger.
   The node must have that much CPU and memory not yet reserved by other VMs.

Tenants never share a VM. Stopping a VM gives its whole slice back to the node
and stops every task inside it. VMs can also be created ahead of time (empty),
which reserves room for a tenant.

This module is the only code that changes a node's allocation (``cpu_used``,
``memory_used``) and load (``cpu_load``, ``memory_load``), so both always add
up to the running VMs and the tasks inside them.
"""

from edgefogsim.models import VM, VM_STOPPED, Node, Task

EPSILON = 1e-9
"""Tolerance for floating-point capacity checks (e.g. 0.1 + 0.2 cores)."""


class CapacityError(ValueError):
    """A VM or task doesn't fit: the node or VM lacks the free CPU or memory."""


class VMManager:
    """Creates, fills, stops and lists the VMs on a set of nodes.

    Attributes:
        nodes: The nodes VMs live on; their allocation and load are updated in place.
        sizes: Default VM size per tier, ``{"edge": {"cpu_cores": 2, "memory_gb": 4}, ...}``.
            A tier missing from it gets VMs sized exactly to the task.
        vms: Every VM created, in creation order (stopped ones stay listed as a record).
    """

    def __init__(self, nodes: list[Node], sizes: dict[str, dict[str, float]] | None = None):
        """Manage VMs on ``nodes``.

        Args:
            nodes: The cluster's nodes, with their current usage.
            sizes: Default VM size per tier (from ``vm.sizes`` in the settings).
        """
        self.nodes = nodes
        self.sizes = sizes or {}
        self.vms: list[VM] = []

    def node(self, node_id: str) -> Node:
        """Find a node by id.

        Raises:
            KeyError: If there is no such node.
        """
        for node in self.nodes:
            if node.id == node_id:
                return node
        raise KeyError(f"no node '{node_id}'")

    def get(self, vm_id: str) -> VM:
        """Find a VM by id.

        Raises:
            KeyError: If there is no such VM.
        """
        for vm in self.vms:
            if vm.vm_id == vm_id:
                return vm
        raise KeyError(f"no VM '{vm_id}'")

    def new_vm_size(self, task: Task, node: Node) -> tuple[float, float]:
        """CPU and memory a new VM for ``task`` on ``node`` would reserve.

        Returns:
            ``(cpu_cores, memory_gb)``: the tier's default size, raised to the
            task's needs where the task is bigger.
        """
        default = self.sizes.get(node.tier, {})
        return (max(default.get("cpu_cores", 0), task.cpu_cores),
                max(default.get("memory_gb", 0), task.memory_gb))

    def slot(self, task: Task, node: Node) -> VM | None:
        """A running VM of the task's tenant on ``node`` with room for it, if any.

        When several fit, the one left with the least free CPU is chosen
        (best fit), so VMs fill up before new ones are made.

        Returns:
            The VM to join, or None if a new VM would be needed.
        """
        fitting = [vm for vm in self.vms
                   if vm.running and vm.node_id == node.id and vm.tenant_id == task.tenant_id
                   and task.cpu_cores <= vm.free_cpu + EPSILON and task.memory_gb <= vm.free_memory + EPSILON]
        return min(fitting, key=lambda vm: (vm.free_cpu - task.cpu_cores, vm.vm_id), default=None)

    def why_cannot_host(self, task: Task, node: Node) -> str | None:
        """Explain why ``node`` can't run ``task`` now, or return None if it can.

        Returns:
            None if the task can join one of its tenant's VMs there or a new VM
            fits; otherwise a short reason such as
            ``"edge-1 not enough CPU for a new VM (needs 2, 1 unreserved)"``.
        """
        if self.slot(task, node):
            return None
        cpu, memory = self.new_vm_size(task, node)
        if cpu > node.free_cpu + EPSILON:
            return f"{node.id} not enough CPU for a new VM (needs {cpu:g}, {node.free_cpu:g} unreserved)"
        if memory > node.free_memory + EPSILON:
            return f"{node.id} not enough memory for a new VM (needs {memory:g} GB, {node.free_memory:g} unreserved)"
        return None

    def create(self, tenant_id: str, node: Node, cpu_cores: float, memory_gb: float) -> VM:
        """Create an empty running VM for a tenant, reserving its slice of the node.

        Args:
            tenant_id: Owner of the VM.
            node: Host; must be one of this manager's nodes.
            cpu_cores: Cores to reserve.
            memory_gb: Memory (GB) to reserve.

        Returns:
            The new VM, with the next id (``vm-0001``, ``vm-0002``, ...).

        Raises:
            CapacityError: If the size isn't positive or the node lacks unreserved CPU or memory.
        """
        if cpu_cores <= 0 or memory_gb <= 0:
            raise CapacityError("a VM needs more than 0 CPU and memory")
        if cpu_cores > node.free_cpu + EPSILON or memory_gb > node.free_memory + EPSILON:
            raise CapacityError(f"{node.id} can't fit a {cpu_cores:g} CPU / {memory_gb:g} GB VM: "
                                f"{node.free_cpu:g} CPU / {node.free_memory:g} GB unreserved")
        node.cpu_used += cpu_cores
        node.memory_used += memory_gb
        vm = VM(f"vm-{len(self.vms) + 1:04d}", tenant_id, node.id, cpu_cores, memory_gb)
        self.vms.append(vm)
        return vm

    def assign(self, task: Task, node: Node) -> tuple[VM, bool]:
        """Run ``task`` on ``node``: join one of its tenant's VMs there, or create a new one.

        Args:
            task: The task; its CPU and memory become load on the VM and the node.
            node: The node the policy chose.

        Returns:
            The VM the task runs in, and True if that VM was created for it.

        Raises:
            CapacityError: If the node can't host the task (check :meth:`why_cannot_host` first).
        """
        vm, created = self.slot(task, node), False
        if vm is None:
            problem = self.why_cannot_host(task, node)
            if problem:
                raise CapacityError(problem)
            vm, created = self.create(task.tenant_id, node, *self.new_vm_size(task, node)), True
        vm.task_ids.append(task.id)
        vm.cpu_load += task.cpu_cores
        vm.memory_load += task.memory_gb
        node.cpu_load += task.cpu_cores
        node.memory_load += task.memory_gb
        return vm, created

    def stop(self, vm_id: str) -> bool:
        """Stop a VM: give its whole slice back to the node and stop the tasks inside it.

        Stopping a VM that is already stopped changes nothing, so resources are
        never freed twice.

        Args:
            vm_id: The VM to stop.

        Returns:
            True if the VM was running and is now stopped; False if it was already stopped.

        Raises:
            KeyError: If there is no such VM.
        """
        vm = self.get(vm_id)
        if not vm.running:
            return False
        node = self.node(vm.node_id)
        node.cpu_used = max(0.0, node.cpu_used - vm.cpu_cores)
        node.memory_used = max(0.0, node.memory_used - vm.memory_gb)
        node.cpu_load = max(0.0, node.cpu_load - vm.cpu_load)
        node.memory_load = max(0.0, node.memory_load - vm.memory_load)
        vm.cpu_load = vm.memory_load = 0.0
        vm.status = VM_STOPPED
        return True

    def running(self) -> list[VM]:
        """VMs currently holding a slice of their node."""
        return [vm for vm in self.vms if vm.running]

    def vm_of(self, task_id: str) -> VM | None:
        """The running VM a task is running in, or None if it isn't running."""
        return next((vm for vm in self.vms if vm.running and task_id in vm.task_ids), None)
