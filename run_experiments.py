"""Run the four required experiments: ``python run_experiments.py [options]``.

Same as ``python -m edgefogsim experiments``. Writes the evidence and
``experiments.md`` to ``results/<time>-experiments/``. Accepts the usual
settings options (``--config``, ``--nodes``, ``--set KEY=VALUE``, ...) and
``--experiments FILE`` for your own experiment definitions.
"""

import sys

from edgefogsim.__main__ import main

if __name__ == "__main__":
    sys.exit(main(["experiments", *sys.argv[1:]]))
