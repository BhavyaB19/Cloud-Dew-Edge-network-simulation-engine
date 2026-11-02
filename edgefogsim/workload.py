"""Build workloads (lists of tasks) in three ways.

1. :func:`generate_tasks`: random tasks from the ``generator`` settings. The
   same seed always gives the same tasks, so policy comparisons are fair.
2. :func:`load_tasks`: a CSV or JSON file the user wrote, e.g. in Excel
   (see ``examples/tasks_sample.csv``).
3. :func:`make_task`: one task typed into the menu or the Streamlit form.

Files and typed tasks are validated row by row. A bad value raises
:class:`WorkloadError` naming the file, row and column.
"""

import csv
import json
import random
from pathlib import Path
from typing import Any, Iterable

from edgefogsim.config import ConfigError, Settings
from edgefogsim.models import SENSITIVITIES, Task

TASK_FIELDS = ("id", "tenant_id", "cpu_cores", "memory_gb", "sensitivity", "work_units")
"""Columns of a task file, in order. ``id`` may be left blank for automatic numbering."""


class WorkloadError(ConfigError):
    """A task row is invalid. The message names the file, row and field."""


def generate_tasks(
    settings: Settings,
    count: int | None = None,
    seed: int | None = None,
    existing: Iterable[Task] = (),
) -> list[Task]:
    """Create random tasks from the ``generator`` settings.

    CPU, memory and work units are drawn uniformly from their configured
    ranges (whole numbers when both bounds are whole). Work units have a range
    per sensitivity, because urgent jobs (e.g. a brake-sensor check) are small
    and heavy jobs (e.g. a nightly report) can wait. Tenant and sensitivity
    are drawn using their configured shares; an empty ``tenant_mix`` splits
    tasks evenly across all non-admin tenants.

    Args:
        settings: Resolved settings; reads ``simulation["generator"]`` and the tenants.
        count: Number of tasks; defaults to ``generator.count``.
        seed: Random seed; defaults to ``generator.seed``.
        existing: Tasks already in the workload, so new ids continue after them.

    Returns:
        The new tasks, with ids ``T01``, ``T02``, ... (continuing after ``existing``).
    """
    gen = settings.simulation["generator"]
    count = gen["count"] if count is None else count
    rng = random.Random(gen["seed"] if seed is None else seed)

    tenant_mix = gen["tenant_mix"] or {t.tenant_id: 1 for t in settings.tenants if t.role == "tenant"}
    tenant_ids = [t for t, share in tenant_mix.items() if share > 0]
    tenant_weights = [tenant_mix[t] for t in tenant_ids]
    levels = [s for s in SENSITIVITIES if gen["sensitivity_mix"].get(s, 0) > 0]
    level_weights = [gen["sensitivity_mix"][s] for s in levels]

    ids = _id_sequence(existing)
    tasks = []
    for _ in range(count):
        tenant_id = rng.choices(tenant_ids, tenant_weights)[0]
        sensitivity = rng.choices(levels, level_weights)[0]
        tasks.append(Task(
            id=next(ids),
            tenant_id=tenant_id,
            cpu_cores=_draw(rng, gen["cpu_range"]),
            memory_gb=_draw(rng, gen["memory_range"]),
            sensitivity=sensitivity,
            work_units=_draw(rng, gen["work_range"][sensitivity]),
        ))
    return tasks


def load_tasks(path: Path | str, settings: Settings, existing: Iterable[Task] = ()) -> list[Task]:
    """Read and validate tasks from a CSV or JSON file.

    A CSV needs the header in ``TASK_FIELDS``. A JSON file holds a list of task
    objects, or ``{"tasks": [...]}``. Sensitivity is case-insensitive; blank ids
    are numbered automatically.

    Args:
        path: The ``.csv`` or ``.json`` file.
        settings: Resolved settings; used to check tenant ids.
        existing: Tasks already in the workload, to avoid duplicate ids.

    Returns:
        The tasks in file order.

    Raises:
        WorkloadError: If the file is missing, empty, of another type, or any row
            is invalid. The message names the file, row (and CSV line) and column.
    """
    path = Path(path)
    source = str(path)
    if not path.exists():
        raise WorkloadError(source, "file", "not found")

    if path.suffix.lower() == ".csv":
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            rows = [(f"row {i} (line {reader.line_num})", row) for i, row in enumerate(reader, start=1)]
    elif path.suffix.lower() == ".json":
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            raise WorkloadError(source, f"line {exc.lineno}", f"invalid JSON: {exc.msg}") from None
        if isinstance(data, dict):
            data = data.get("tasks")
        if not isinstance(data, list):
            raise WorkloadError(source, "tasks", "must be a list of tasks (or {\"tasks\": [...]})")
        rows = [(f"tasks[{i}]", row) for i, row in enumerate(data)]
    else:
        raise WorkloadError(source, "file", "must end in .csv or .json")

    if not rows:
        raise WorkloadError(source, "file", "contains no tasks")
    return _build_tasks(rows, settings, source, existing)


def make_task(raw: dict[str, Any], settings: Settings, existing: Iterable[Task] = (),
              source: str = "manual entry") -> Task:
    """Validate and build one task typed in by hand.

    Args:
        raw: Field name -> value, as typed (strings are fine, e.g. ``"2"``).
            A blank or missing ``id`` is numbered automatically.
        settings: Resolved settings; used to check the tenant id.
        existing: Tasks already in the workload, to avoid duplicate ids.
        source: Label used in error messages.

    Returns:
        The new task.

    Raises:
        WorkloadError: If any field is missing or invalid.
    """
    return _build_tasks([("task", raw)], settings, source, existing)[0]


def _build_tasks(rows: list[tuple[str, Any]], settings: Settings, source: str,
                 existing: Iterable[Task]) -> list[Task]:
    """Validate rows and turn them into tasks; shared by file loading and manual entry.

    Args:
        rows: ``(location label, raw dict)`` pairs, e.g. ``("row 4 (line 5)", {...})``.
        settings: Resolved settings; used to check tenant ids.
        source: File name or label used in error messages.
        existing: Tasks already in the workload, to avoid duplicate ids.

    Returns:
        One task per row.

    Raises:
        WorkloadError: On the first invalid row, naming its location and column.
    """
    existing = list(existing)
    used = {t.id for t in existing}
    ids = _id_sequence(existing)
    allowed_tenants = [t.tenant_id for t in settings.tenants if t.role == "tenant"]
    tasks = []
    for where, raw in rows:
        if not isinstance(raw, dict):
            raise WorkloadError(source, where, "must be an object with task fields")
        for key in raw:
            if key not in TASK_FIELDS:
                raise WorkloadError(source, f"{where}, {key}", f"unknown column; expected {', '.join(TASK_FIELDS)}")
        for key in TASK_FIELDS[1:]:
            if raw.get(key) in (None, ""):
                raise WorkloadError(source, f"{where}, {key}", "is missing")

        task_id = str(raw.get("id") or "").strip()
        if not task_id:
            task_id = next(i for i in ids if i not in used)
        if task_id in used:
            raise WorkloadError(source, f"{where}, id", f"duplicate task id '{task_id}'")
        used.add(task_id)

        tenant_id = str(raw["tenant_id"]).strip()
        if tenant_id not in allowed_tenants:
            raise WorkloadError(source, f"{where}, tenant_id",
                                f"unknown tenant '{tenant_id}'; expected one of {', '.join(allowed_tenants)}")
        sensitivity = str(raw["sensitivity"]).strip().lower()
        if sensitivity not in SENSITIVITIES:
            raise WorkloadError(source, f"{where}, sensitivity",
                                f"must be one of {', '.join(SENSITIVITIES)} (got {raw['sensitivity']!r})")

        tasks.append(Task(
            id=task_id,
            tenant_id=tenant_id,
            cpu_cores=_positive(raw["cpu_cores"], source, f"{where}, cpu_cores"),
            memory_gb=_positive(raw["memory_gb"], source, f"{where}, memory_gb"),
            sensitivity=sensitivity,
            work_units=_positive(raw["work_units"], source, f"{where}, work_units"),
        ))
    return tasks


def _positive(value: Any, source: str, where: str) -> float:
    """Parse a positive number from a cell, as an int when it is whole.

    Raises:
        WorkloadError: If the value is not a number or is <= 0.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise WorkloadError(source, where, f"must be a number (got {value!r})") from None
    if number <= 0:
        raise WorkloadError(source, where, f"must be > 0 (got {value})")
    return int(number) if number.is_integer() else number


def _draw(rng: random.Random, bounds: list[float]) -> float:
    """Draw a value in ``[low, high]``: a whole number when both bounds are whole, else rounded to 0.1."""
    low, high = bounds
    if isinstance(low, int) and isinstance(high, int):
        return rng.randint(low, high)
    return round(rng.uniform(low, high), 1)


def _id_sequence(existing: Iterable[Task]):
    """Yield ``T01``, ``T02``, ... starting after the highest ``T<number>`` id in ``existing``."""
    highest = 0
    for task in existing:
        if task.id[:1] == "T" and task.id[1:].isdigit():
            highest = max(highest, int(task.id[1:]))
    n = highest
    while True:
        n += 1
        yield f"T{n:02d}"
