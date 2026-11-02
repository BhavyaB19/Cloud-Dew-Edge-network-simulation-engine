"""Phase 0 smoke tests: the project installs, runs and ships valid default config."""

import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"


def test_package_imports():
    import edgefogsim

    assert edgefogsim.__version__


def test_cli_help_runs():
    result = subprocess.run(
        [sys.executable, "-m", "edgefogsim", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "usage: edgefogsim" in result.stdout


@pytest.mark.parametrize(
    "filename, top_key",
    [
        ("nodes.json", "nodes"),
        ("tenants.json", "tenants"),
        ("simulation.json", "generator"),
        ("experiments.json", "experiments"),
    ],
)
def test_config_file_is_valid_json(filename, top_key):
    data = json.loads((CONFIG / filename).read_text())
    assert top_key in data


def test_default_nodes_cover_every_tier():
    nodes = json.loads((CONFIG / "nodes.json").read_text())["nodes"]
    assert sorted(n["tier"] for n in nodes) == ["cloud", "edge", "fog"]


def test_sample_tasks_csv_has_required_columns():
    with open(ROOT / "examples" / "tasks_sample.csv", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    assert reader.fieldnames == [
        "id", "tenant_id", "cpu_cores", "memory_gb", "sensitivity", "work_units",
    ]
    assert len(rows) >= 10
