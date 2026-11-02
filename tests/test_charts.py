"""Charts are written as real, non-empty PNG files (AC14)."""

from edgefogsim import charts
from edgefogsim.simulator import compare_before_after, compare_policies
from edgefogsim.workload import generate_tasks

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def assert_png(path):
    """The file exists, is a PNG and has real content."""
    data = path.read_bytes()
    assert data.startswith(PNG_SIGNATURE) and len(data) > 5_000, path


def test_comparison_and_run_charts_are_written(settings, tmp_path):
    """AC14: every comparison and run chart is saved as a non-empty PNG."""
    results = compare_policies(settings, generate_tasks(settings, count=20))
    paths = {**charts.save_comparison_charts(results, tmp_path / "cmp"),
             **charts.save_run_charts(results[2], tmp_path / "run")}
    assert set(paths) == {"outcomes", "tiers", "latency", "node_usage"}
    for path in paths.values():
        assert_png(path)


def test_before_after_chart_is_written(settings, tmp_path):
    """AC14: the before/after chart is saved as a non-empty PNG."""
    result = compare_before_after(settings, generate_tasks(settings), "capacity", {"edge-1": {"cpu_cores": 8}})
    assert_png(charts.save_before_after_chart(result.before, result.after, result.change, tmp_path))


def test_latency_chart_handles_a_run_with_nothing_placed(settings, tmp_path):
    """A run where every task is rejected still draws (an empty box) instead of failing."""
    from edgefogsim.models import Task
    from edgefogsim.simulator import run_workload

    result = run_workload(settings, [Task("T01", "hospital-a", 999, 1, "low", 1)], "capacity")
    assert_png(charts.save_figure(charts.latency_chart([result]), tmp_path / "empty.png"))
