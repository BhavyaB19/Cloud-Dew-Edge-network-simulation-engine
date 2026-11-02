"""Create workloads: seeded random generation, task files (CSV/JSON) and manual entry."""

import csv
import json
import random
from pathlib import Path
from typing import Any, Iterable

from edgefogsim.config import ConfigError, Settings
from edgefogsim.models import SENSITIVITIES, Task

TASK_FIELDS = ("id", "tenant_id", "cpu_cores", "memory_gb", "sensitivity", "work_units")


class WorkloadError(ConfigError):
    """A task row is invalid. The message names the file, row and field."""


def generate_tasks(
    settings: Settings,
    count: int | None = None,
    seed: int | None = None,
    existing: Iterable[Task] = (),
) -> list[Task]:
    """Random tasks drawn from the generator settings. The same seed gives the same tasks."""
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
        tasks.append(Task(
            id=next(ids),
            tenant_id=rng.choices(tenant_ids, tenant_weights)[0],
            cpu_cores=_draw(rng, gen["cpu_range"]),
            memory_gb=_draw(rng, gen["memory_range"]),
            sensitivity=rng.choices(levels, level_weights)[0],
            work_units=_draw(rng, gen["work_range"]),
        ))
    return tasks


def load_tasks(path: Path | str, settings: Settings, existing: Iterable[Task] = ()) -> list[Task]:
    """Read tasks from a CSV or JSON file, validating every row."""
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
    """Validate one task typed in by hand. A blank id is numbered automatically."""
    return _build_tasks([("task", raw)], settings, source, existing)[0]


def _build_tasks(rows: list[tuple[str, Any]], settings: Settings, source: str,
                 existing: Iterable[Task]) -> list[Task]:
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
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise WorkloadError(source, where, f"must be a number (got {value!r})") from None
    if number <= 0:
        raise WorkloadError(source, where, f"must be > 0 (got {value})")
    return int(number) if number.is_integer() else number


def _draw(rng: random.Random, bounds: list[float]) -> float:
    """Whole numbers when both bounds are whole, otherwise one decimal place."""
    low, high = bounds
    if isinstance(low, int) and isinstance(high, int):
        return rng.randint(low, high)
    return round(rng.uniform(low, high), 1)


def _id_sequence(existing: Iterable[Task]):
    """Yield T01, T02, ... continuing after the highest existing T-number."""
    highest = 0
    for task in existing:
        if task.id[:1] == "T" and task.id[1:].isdigit():
            highest = max(highest, int(task.id[1:]))
    n = highest
    while True:
        n += 1
        yield f"T{n:02d}"
