"""Command-line entry point: ``python -m edgefogsim``."""

import argparse
import sys

from edgefogsim import __version__
from edgefogsim.config import ConfigError, load_settings, parse_value
from edgefogsim.workload import load_tasks

COMMANDS = ("menu", "run")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="edgefogsim",
        description="Simulate placing computing tasks on Edge, Fog and Cloud nodes.",
        epilog="With no command, the interactive menu starts. "
               "Run 'python -m edgefogsim menu --help' to see every option.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument("--config", metavar="FILE", help="JSON file overriding any subset of the default settings")
    shared.add_argument("--nodes", metavar="FILE", help="JSON file with your own node definitions")
    shared.add_argument("--tasks", metavar="N|FILE",
                        help="number of random tasks to generate, or a CSV/JSON task file")
    shared.add_argument("--seed", type=int, help="random seed for generated tasks")
    shared.add_argument("--deadline", metavar="LEVEL=MS", action="append", default=[],
                        help="deadline for a sensitivity level, e.g. high=40 (repeatable)")
    shared.add_argument("--headroom", type=float, help="max node utilisation for Capacity-Aware, e.g. 0.9")
    shared.add_argument("--set", metavar="KEY=VALUE", action="append", default=[], dest="settings",
                        help="change any setting, e.g. generator.count=20 (repeatable)")

    sub = parser.add_subparsers(dest="command", metavar="{menu,run}")
    sub.add_parser("menu", parents=[shared], help="interactive menu (default)")
    run = sub.add_parser("run", parents=[shared], help="run a workload through a policy without the menu")
    run.add_argument(
        "--policy",
        choices=["latency", "cloud", "capacity", "topsis", "qlearn"],
        default="capacity",
        help="placement policy (default: capacity)",
    )
    return parser


def collect_overrides(args: argparse.Namespace) -> dict:
    """Turn command-line flags into dotted setting overrides."""
    overrides = {}
    if args.seed is not None:
        overrides["generator.seed"] = args.seed
    if args.tasks and args.tasks.isdigit():
        overrides["generator.count"] = int(args.tasks)
    if args.headroom is not None:
        overrides["policy.headroom"] = args.headroom
    for item in args.deadline:
        level, _, ms = item.partition("=")
        overrides[f"qos.deadlines_ms.{level.strip()}"] = parse_value(ms)
    for item in args.settings:
        key, sep, value = item.partition("=")
        if not sep:
            raise ConfigError("command line", item, "expected KEY=VALUE")
        overrides[key.strip()] = parse_value(value.strip())
    return overrides


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or (argv[0] not in COMMANDS and argv[0] not in ("-h", "--help", "--version")):
        argv.insert(0, "menu")
    args = build_parser().parse_args(argv)

    try:
        settings = load_settings(config_file=args.config, nodes_file=args.nodes, overrides=collect_overrides(args))
        tasks = load_tasks(args.tasks, settings) if args.tasks and not args.tasks.isdigit() else []
    except ConfigError as exc:
        print(f"Settings error: {exc}", file=sys.stderr)
        return 2

    if args.command == "run":
        # Filled in by Phase 2 (placement engine).
        print("'run' is not implemented yet.")
        return 0

    from edgefogsim.cli import App

    try:
        App(settings, tasks).run()
    except (KeyboardInterrupt, EOFError):
        print("\nBye.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
