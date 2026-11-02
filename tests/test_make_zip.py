"""The submission ZIP builder: it checks every deliverable and packs only project files."""

import zipfile

import pytest

import make_zip


def test_missing_deliverable_stops_the_build(monkeypatch, tmp_path):
    """If a required file is missing, the build stops and names it."""
    monkeypatch.setitem(make_zip.REQUIRED, "Imaginary deliverable", "docs/does-not-exist.txt")
    with pytest.raises(SystemExit, match="Imaginary deliverable: docs/does-not-exist.txt"):
        make_zip.build(tmp_path / "out.zip")


def test_pack_list_skips_caches_and_environments():
    """No virtualenv, cache or git files are packed; the main code is."""
    names = {str(p.relative_to(make_zip.ROOT)) for p in make_zip.files_to_pack()}
    assert "edgefogsim/__main__.py" in names and "requirements.txt" in names
    assert not any(part in name for name in names for part in ("__pycache__", ".venv/", ".git/", ".pytest_cache"))


def test_build_writes_zip_inside_a_project_folder(monkeypatch, tmp_path):
    """With deliverables present, the ZIP holds every file under EdgeFogSim/."""
    monkeypatch.setattr(make_zip, "missing_deliverables", lambda: [])
    path = make_zip.build(tmp_path / "out.zip")
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
    assert "EdgeFogSim/edgefogsim/__main__.py" in names
    assert all(name.startswith("EdgeFogSim/") for name in names)
