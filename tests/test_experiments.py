"""The experiment runner (AC15): four experiments, written up with evidence."""

import json

import pytest

from edgefogsim.__main__ import main
from edgefogsim.config import ConfigError
from edgefogsim.experiments import load_experiments, run_all


@pytest.fixture(scope="module")
def experiment_run(tmp_path_factory):
    """Run E1-E4 once with the default settings and definitions (shared by these tests)."""
    from edgefogsim.config import load_settings

    return run_all(load_settings(), folder=tmp_path_factory.mktemp("experiments"))


def test_all_four_experiments_meet_their_expectations(experiment_run):
    """With the default settings, every experiment's checks hold."""
    assert [e.key for e in experiment_run.experiments] == ["E1", "E2", "E3", "E4"]
    for e in experiment_run.experiments:
        assert e.checks and e.passed, [s for s, held in e.checks if not held]


def test_report_has_all_four_sections_and_parts(experiment_run):
    """AC15: experiments.md has a section per experiment with setup, expected, actual and evidence."""
    text = experiment_run.report.read_text()
    for title in ("E1: Policy comparison", "E2: Overload", "E3: Unauthorised tenant access",
                  "E4: Node capacity and latency change"):
        assert f"## {title}" in text
    for part in ("**Setup**", "**Expected outcome**", "**Actual outcome**", "**Expected vs actual**", "**Evidence**"):
        assert text.count(part) == 4


def test_every_evidence_file_exists(experiment_run):
    """Every file the write-up links to was written and isn't empty."""
    for e in experiment_run.experiments:
        assert e.evidence
        for name in e.evidence:
            path = experiment_run.folder / name
            assert path.exists() and path.stat().st_size > 0, name
    summary = json.loads((experiment_run.folder / "experiments.json").read_text())
    assert [s["passed"] for s in summary] == [True] * 4


def test_unauthorised_access_is_logged(experiment_run):
    """E3's audit log has one DENIED line per refused attempt."""
    lines = (experiment_run.folder / "E3" / "audit.log").read_text().splitlines()
    assert len(lines) == 1 + 3 and all(line.endswith("DENIED") for line in lines[1:])


def test_missing_experiment_is_reported(write_json):
    """A definitions file without E2 fails with the file and key named."""
    path = write_json("mine.json", {"experiments": {"E1": {"workload": {}, "policies": []}}})
    with pytest.raises(ConfigError, match="experiments.E2: is missing"):
        load_experiments(path)


def test_custom_definitions_are_used(settings, tmp_path):
    """Your own definitions change what runs, e.g. E1 from the sample file with two policies."""
    definitions = load_experiments()
    definitions["E1"] = {"title": "Sample comparison", "workload": {"file": "examples/tasks_sample.csv"},
                         "policies": ["latency", "capacity"]}
    run = run_all(settings, definitions, tmp_path / "custom")
    e1 = run.experiments[0]
    assert e1.title == "Sample comparison" and "10 tasks from tasks_sample.csv" in e1.setup[0]


def test_run_experiments_command_exits_zero(capsys):
    """AC15: ``python -m edgefogsim experiments`` (what run_experiments.py calls) exits 0 and prints the write-up path."""
    assert main(["experiments"]) == 0
    out = capsys.readouterr().out
    assert "Write-up: results/" in out and "experiments.md" in out
