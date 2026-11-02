"""Build the single submission ZIP: ``python make_zip.py [--rebuild]``.

Checks that every deliverable the brief lists is present, then packs them into
``EdgeFogSim_submission.zip``. With ``--rebuild`` it first regenerates the
diagram, evidence, report and slides and runs the tests. It refuses to build if
anything required is missing, and lists what to fix.

Packed: source code, requirements.txt, README, docs (spec, architecture diagram,
report, slides, screenshots, evidence pack with experiments and test results),
config, examples, tests and the helper scripts. Left out: the virtual
environment, caches, git data and the local ``results/`` scratch folder.
"""

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "EdgeFogSim_submission.zip"

INCLUDE = ["edgefogsim", "config", "examples", "tests", "tools", "docs", "README.md", "requirements.txt",
           "requirements-docs.txt", "pyproject.toml", "run_experiments.py", "make_zip.py"]
"""Top-level files and folders that go into the ZIP."""

SKIP_PARTS = {"__pycache__", ".pytest_cache", ".DS_Store", ".venv", ".git"}
"""Path parts that are never packed."""

REQUIRED = {
    "Runnable source code": "edgefogsim/__main__.py",
    "requirements.txt": "requirements.txt",
    "README / setup instructions": "README.md",
    "Architecture diagram": "docs/architecture.png",
    "Report (5–8 pages)": "docs/report/EdgeFogSim_Report.docx",
    "Presentation (5–7 slides)": "docs/report/EdgeFogSim_Slides.pptx",
    "Experiment write-up": "docs/evidence/experiments/experiments.md",
    "Experiment evidence (E1 table)": "docs/evidence/experiments/E1/comparison.csv",
    "Results chart": "docs/evidence/experiments/E1/outcomes.png",
    "Overload evidence (E2)": "docs/evidence/experiments/E2/decisions_capacity.csv",
    "Unauthorised-access evidence (E3)": "docs/evidence/experiments/E3/audit.log",
    "Before/after evidence (E4)": "docs/evidence/experiments/E4/a/before_after.png",
    "Test results": "docs/evidence/test_results.txt",
    "Screenshots": "docs/screenshots/web-comparison.png",
}
"""Deliverable -> a file that must exist for it (relative to the project root)."""


def rebuild() -> None:
    """Regenerate the diagram, evidence, report and slides, and save the test results."""
    python = sys.executable
    for script in ("tools/make_diagram.py", "tools/make_report.py", "tools/make_slides.py"):
        print(f"Running {script}...")
        subprocess.run([python, script], cwd=ROOT, check=True)
    export_pdfs()
    print("Running the tests...")
    # -o addopts= drops the project's -q so the file lists every test by name, plus the summary line.
    result = subprocess.run([python, "-m", "pytest", "-p", "no:warnings", "-o", "addopts=", "-v"], cwd=ROOT,
                            capture_output=True, text=True)
    (ROOT / "docs" / "evidence").mkdir(parents=True, exist_ok=True)
    (ROOT / "docs" / "evidence" / "test_results.txt").write_text(result.stdout + result.stderr)
    if result.returncode != 0:
        raise SystemExit("Tests failed; see docs/evidence/test_results.txt")


def export_pdfs() -> None:
    """Save PDF copies of the report and slides next to them, if LibreOffice (``soffice``) is installed."""
    soffice = shutil.which("soffice")
    if not soffice:
        print("LibreOffice not found: skipping PDF copies (install it with `brew install --cask libreoffice`).")
        return
    folder = ROOT / "docs" / "report"
    for name in ("EdgeFogSim_Report.docx", "EdgeFogSim_Slides.pptx"):
        print(f"Exporting {name} to PDF...")
        subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", str(folder), str(folder / name)],
                       check=True, capture_output=True)


def missing_deliverables() -> list[str]:
    """Deliverables whose required file is missing or empty.

    Returns:
        Lines like ``"Report (5–8 pages): docs/report/EdgeFogSim_Report.docx"``.
    """
    return [f"{name}: {path}" for name, path in REQUIRED.items()
            if not (ROOT / path).exists() or (ROOT / path).stat().st_size == 0]


def files_to_pack() -> list[Path]:
    """Every file under ``INCLUDE``, minus caches, environments and git data, in a stable order."""
    files = []
    for name in INCLUDE:
        path = ROOT / name
        candidates = [path] if path.is_file() else sorted(p for p in path.rglob("*") if p.is_file())
        files += [p for p in candidates if not SKIP_PARTS & set(p.relative_to(ROOT).parts)]
    return files


def build(output: Path = OUTPUT) -> Path:
    """Check the deliverables and write the ZIP, with everything inside an ``EdgeFogSim/`` folder.

    Returns:
        The ZIP's path.

    Raises:
        SystemExit: If a required deliverable is missing.
    """
    missing = missing_deliverables()
    if missing:
        raise SystemExit("Missing deliverables:\n  " + "\n  ".join(missing) +
                         "\nRun `python make_zip.py --rebuild` to regenerate them.")
    files = files_to_pack()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, Path("EdgeFogSim") / path.relative_to(ROOT))
    return output


def main(argv: list[str]) -> int:
    """Optionally rebuild, then check and pack; print the checklist and the ZIP's size."""
    if "--rebuild" in argv:
        rebuild()
    path = build()
    for name, required in REQUIRED.items():
        print(f"  ✓ {name}: {required}")
    print(f"{path.name}: {len(files_to_pack())} files, {path.stat().st_size / 1_000_000:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
