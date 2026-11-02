"""Shared helper for the deliverable scripts: build the evidence pack in ``docs/evidence/``.

The report, slides and submission ZIP all use the same experiment run, so every
number and chart in them agrees. Running this replaces the previous pack.
"""

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from edgefogsim.config import load_settings  # noqa: E402
from edgefogsim.experiments import ExperimentRun, run_all  # noqa: E402

EVIDENCE = ROOT / "docs" / "evidence"
"""Folder for the evidence pack that ships with the submission."""

EXPERIMENTS = EVIDENCE / "experiments"
"""Where the four experiments are written (``experiments.md`` plus E1-E4)."""


def build_experiments() -> ExperimentRun:
    """Run E1-E4 with the default settings into ``docs/evidence/experiments``, replacing any old run.

    Returns:
        The run, with every experiment's tables, figures and checks.
    """
    if EXPERIMENTS.exists():
        shutil.rmtree(EXPERIMENTS)
    return run_all(load_settings(), folder=EXPERIMENTS)


if __name__ == "__main__":
    run = build_experiments()
    print(f"{run.report} ({sum(e.passed for e in run.experiments)}/4 experiments as expected)")
