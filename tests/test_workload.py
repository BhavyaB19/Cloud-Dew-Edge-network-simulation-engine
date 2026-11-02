"""Task generation, task files and manual entry (AC2-3)."""

import pytest

from edgefogsim.config import load_settings
from edgefogsim.models import SENSITIVITIES
from edgefogsim.workload import WorkloadError, generate_tasks, load_tasks, make_task
from tests.conftest import ROOT


def test_same_seed_gives_identical_workload(settings):
    """AC2: seed 42, 12 tasks, generated twice -> identical, every field filled."""
    first = generate_tasks(settings, count=12, seed=42)
    second = generate_tasks(settings, count=12, seed=42)
    assert first == second
    assert len(first) == 12
    for task in first:
        assert task.cpu_cores > 0 and task.memory_gb > 0 and task.work_units > 0
        assert task.sensitivity in SENSITIVITIES
        assert task.tenant_id in {"hospital-a", "hospital-b"}


def test_different_seed_gives_different_workload(settings):
    """Changing the seed changes the generated tasks."""
    assert generate_tasks(settings, seed=1) != generate_tasks(settings, seed=2)


def test_generator_respects_configured_ranges_and_mix():
    """Generated tasks stay within configured ranges, sensitivity and tenant shares."""
    custom = load_settings(overrides={
        "generator.cpu_range": [2, 3],
        "generator.memory_range": [1.0, 2.0],
        "generator.sensitivity_mix": {"low": 1},
        "generator.tenant_mix": {"hospital-b": 1},
    })
    tasks = generate_tasks(custom, count=30)
    assert {t.cpu_cores for t in tasks} <= {2, 3}
    assert all(1.0 <= t.memory_gb <= 2.0 for t in tasks)
    assert {t.sensitivity for t in tasks} == {"low"}
    assert {t.tenant_id for t in tasks} == {"hospital-b"}


def test_generated_ids_continue_after_existing(settings):
    """New generated ids continue after the existing ones."""
    first = generate_tasks(settings, count=3)
    more = generate_tasks(settings, count=2, existing=first)
    assert [t.id for t in first + more] == ["T01", "T02", "T03", "T04", "T05"]


def test_sample_csv_loads(settings):
    """The sample CSV loads all 10 tasks with the right values."""
    tasks = load_tasks(ROOT / "examples" / "tasks_sample.csv", settings)
    assert len(tasks) == 10
    assert tasks[3].cpu_cores == 20 and tasks[3].sensitivity == "high"


def test_json_task_file_loads(settings, write_json):
    """A JSON task file loads, numbering blank ids and normalising case."""
    path = write_json("tasks.json", {"tasks": [
        {"tenant_id": "hospital-a", "cpu_cores": 1, "memory_gb": 0.5, "sensitivity": "LOW", "work_units": 3},
    ]})
    tasks = load_tasks(path, settings)
    assert tasks[0].id == "T01"
    assert tasks[0].sensitivity == "low"


@pytest.mark.parametrize(
    "row, expected",
    [
        ("T02,hospital-a,-2,1,high,4", ["row 2", "cpu_cores", "must be > 0"]),
        ("T02,hospital-a,2,1,urgent,4", ["row 2", "sensitivity", "high, medium, low"]),
        ("T02,hospital-z,2,1,high,4", ["row 2", "tenant_id", "unknown tenant"]),
        ("T02,hospital-a,two,1,high,4", ["row 2", "cpu_cores", "must be a number"]),
        ("T01,hospital-a,2,1,high,4", ["row 2", "id", "duplicate"]),
        ("T02,hospital-a,2,,high,4", ["row 2", "memory_gb", "missing"]),
    ],
)
def test_malformed_csv_row_is_named(settings, tmp_path, row, expected):
    """AC3: a bad row raises a validation error naming the file, row and field."""
    path = tmp_path / "bad.csv"
    path.write_text("id,tenant_id,cpu_cores,memory_gb,sensitivity,work_units\n"
                    "T01,hospital-a,2,1,high,4\n" + row + "\n")
    with pytest.raises(WorkloadError) as info:
        load_tasks(path, settings)
    message = str(info.value)
    assert "bad.csv" in message
    for part in expected:
        assert part in message


def test_manual_task_gets_next_id(settings):
    """A typed task with no id gets the next automatic id; string numbers are parsed."""
    existing = generate_tasks(settings, count=2)
    task = make_task({"tenant_id": "hospital-a", "cpu_cores": "2", "memory_gb": "1.5",
                      "sensitivity": "medium", "work_units": "10"}, settings, existing=existing)
    assert task.id == "T03"
    assert task.memory_gb == 1.5


def test_manual_task_rejects_admin_as_owner(settings):
    """The admin account cannot own tasks."""
    with pytest.raises(WorkloadError, match="unknown tenant 'admin'"):
        make_task({"tenant_id": "admin", "cpu_cores": 1, "memory_gb": 1,
                   "sensitivity": "low", "work_units": 1}, settings)
