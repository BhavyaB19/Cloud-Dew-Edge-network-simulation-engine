"""Shared pytest fixtures: default settings and a helper to write JSON files."""

import json
from pathlib import Path

import pytest

from edgefogsim.config import load_settings

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def run_in_temp_folder(tmp_path, monkeypatch):
    """Run every test in its own empty folder, so files like results/audit.log never land in the project."""
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def settings():
    """Settings from the project's default config/ folder."""
    return load_settings()


@pytest.fixture
def write_json(tmp_path):
    """Write a JSON file under tmp_path and return its path."""

    def _write(name, data):
        """Write ``data`` as JSON to ``tmp_path / name`` and return the path."""
        path = tmp_path / name
        path.write_text(json.dumps(data))
        return path

    return _write
