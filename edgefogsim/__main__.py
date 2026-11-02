"""Command-line entry point: ``python -m edgefogsim``."""

import argparse
import sys

from edgefogsim import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="edgefogsim",
        description="Simulate placing computing tasks on Edge, Fog and Cloud nodes.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--config",
        metavar="FILE",
        help="JSON file overriding any subset of the default settings",
    )
    parser.add_argument("--nodes", metavar="FILE", help="JSON file with your own node definitions")

    sub = parser.add_subparsers(dest="command")

    sub.add_parser("menu", help="interactive menu (default when no command is given)")

    run = sub.add_parser("run", help="run a workload through a policy without the menu")
    run.add_argument(
        "--policy",
        choices=["latency", "cloud", "capacity", "topsis", "qlearn"],
        default="capacity",
        help="placement policy (default: capacity)",
    )
    run.add_argument(
        "--tasks",
        metavar="N|FILE",
        help="number of random tasks to generate, or a CSV/JSON task file",
    )
    run.add_argument("--seed", type=int, help="random seed for generated tasks")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    command = args.command or "menu"
    # Filled in by later phases: menu (Phase 1), run (Phase 2).
    print(f"'{command}' is not implemented yet.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
